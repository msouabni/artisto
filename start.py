#!/usr/bin/env python3
"""Démarrage unifié : API Uvicorn, workers, ComfyUI (optionnel), Ollama uniquement avec --with-ollama."""
from __future__ import annotations

import argparse
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from shutil import which
from urllib.parse import urlparse

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"

_children: list[tuple[str, subprocess.Popen]] = []
_singleton_lock_fh = None
_singleton_lock_path: Path | None = None


def _load_env() -> None:
    load_dotenv(PROJECT_ROOT / ".env")


def _resolve_log_dir() -> Path:
    raw = os.environ.get("ARTISTE_LOG_DIR", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return PROJECT_ROOT / "logs"


def _acquire_singleton_lock(lock_path: Path) -> bool:
    """Empêche de lancer plusieurs instances concurrentes de start.py.

    Implémente un lock fichier inter-processus :
    - Windows : msvcrt.locking (verrou 1 byte, non bloquant)
    - POSIX : fcntl.flock (LOCK_EX | LOCK_NB)
    """
    global _singleton_lock_fh, _singleton_lock_path
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock_path, "a+", encoding="utf-8")
    try:
        if sys.platform == "win32":
            import msvcrt

            fh.seek(0)
            try:
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                fh.close()
                return False
        else:
            import fcntl  # type: ignore

            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                fh.close()
                return False

        # Écrire un diagnostic utile (PID, commande) ; le lock reste tenu par le handle.
        fh.seek(0)
        fh.truncate(0)
        fh.write(f"pid={os.getpid()}\n")
        fh.write(f"argv={' '.join(sys.argv)}\n")
        fh.flush()
        _singleton_lock_fh = fh
        _singleton_lock_path = lock_path
        return True
    except Exception:
        try:
            fh.close()
        except Exception:
            pass
        raise


def _release_singleton_lock() -> None:
    global _singleton_lock_fh, _singleton_lock_path
    fh = _singleton_lock_fh
    _singleton_lock_fh = None
    _singleton_lock_path = None
    if not fh:
        return
    try:
        if sys.platform == "win32":
            import msvcrt

            try:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            except Exception:
                pass
        else:
            import fcntl  # type: ignore

            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
    finally:
        try:
            fh.close()
        except Exception:
            pass


def _comfy_root_valid(path: Path) -> bool:
    return (path / "main.py").is_file()


def _resolve_comfyui_home() -> tuple[Path | None, str]:
    """Renvoie (chemin ComfyUI, source) ou (None, raison)."""
    env_errors: list[str] = []
    for key in ("COMFYUI_HOME", "COMFYUI_ROOT"):
        raw = os.environ.get(key, "").strip()
        if not raw:
            continue
        p = Path(raw).expanduser().resolve()
        if _comfy_root_valid(p):
            return p, key
        env_errors.append(f"{key}={raw!r} invalide (pas de main.py)")

    parent = PROJECT_ROOT.parent
    for label, candidate in (
        ("voisin ../comfy/ComfyUI", parent / "comfy" / "ComfyUI"),
        ("voisin ../ComfyUI", parent / "ComfyUI"),
    ):
        p = candidate.resolve()
        if _comfy_root_valid(p):
            return p, label

    hint = "aucun dossier ComfyUI (définir COMFYUI_HOME / COMFYUI_ROOT ou placer le clone en ../comfy/ComfyUI ou ../ComfyUI)"
    if env_errors:
        return None, hint + " — " + " ; ".join(env_errors)
    return None, hint


def _resolve_comfyui_python(home: Path) -> tuple[str, str]:
    """(exécutable, source)."""
    explicit = os.environ.get("COMFYUI_PYTHON", "").strip()
    if explicit:
        return explicit, "COMFYUI_PYTHON"
    if sys.platform == "win32":
        for rel, lbl in (
            (Path("venv") / "Scripts" / "python.exe", "venv\\Scripts\\python.exe"),
            (Path(".venv") / "Scripts" / "python.exe", ".venv\\Scripts\\python.exe"),
            (Path("python_embeded") / "python.exe", "python_embeded\\python.exe"),
        ):
            cand = home / rel
            if cand.is_file():
                return str(cand), lbl
    else:
        for rel, lbl in (
            (Path("venv") / "bin" / "python", "venv/bin/python"),
            (Path(".venv") / "bin" / "python", ".venv/bin/python"),
        ):
            cand = home / rel
            if cand.is_file():
                return str(cand), lbl
    return sys.executable, "sys.executable (Comfy peut échouer sans son venv — définir COMFYUI_PYTHON)"


def _parse_http_url(url: str) -> tuple[str, int]:
    p = urlparse(url.strip())
    host = p.hostname or "127.0.0.1"
    if p.port is not None:
        return host, p.port
    if p.scheme == "https":
        return host, 443
    return host, 80


def _parse_postgres_url(url: str) -> tuple[str, int]:
    """Extrait host/port depuis DATABASE_URL PostgreSQL.

    Accepte des formes comme:
    - postgresql+psycopg://user:pass@host:5432/db
    - postgresql://user:pass@host/db
    """
    raw = (url or "").strip()
    if not raw:
        return "127.0.0.1", 5432
    p = urlparse(raw)
    if p.scheme.startswith("postgresql"):
        return (p.hostname or "127.0.0.1"), (p.port or 5432)
    return "127.0.0.1", 5432


def _tcp_open(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _http_get_status(url: str, timeout: float = 2.0) -> int | None:
    try:
        req = urllib.request.Request(url, method="GET", headers={"User-Agent": "artiste-coloriage-start"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return None


def _run_short_command(args: list[str], cwd: Path) -> tuple[int, str]:
    """Exécute une commande courte et retourne (exit_code, stderr+stdout)."""
    try:
        cp = subprocess.run(
            args,
            cwd=str(cwd),
            check=False,
            capture_output=True,
            text=True,
        )
        out = "\n".join(x for x in [cp.stdout, cp.stderr] if x).strip()
        return cp.returncode, out
    except Exception as e:  # pragma: no cover - garde-fou runtime
        return 1, str(e)


def _ensure_postgres_ready(db_url: str, timeout: int = 60) -> bool:
    """Vérifie PostgreSQL, sinon lance docker compose et attend."""
    pg_host, pg_port = _parse_postgres_url(db_url)
    if _tcp_open(pg_host, pg_port):
        print(f"[postgres] Déjà joignable ({pg_host}:{pg_port}).", flush=True)
        return True

    print(f"[postgres] Non joignable ({pg_host}:{pg_port}), lancement docker compose…", flush=True)
    docker_bin = which("docker")
    if not docker_bin:
        print("[postgres] ERREUR: `docker` introuvable dans le PATH.", flush=True)
        return False

    code, out = _run_short_command([docker_bin, "compose", "up", "-d", "postgres"], cwd=PROJECT_ROOT)
    if code != 0:
        print("[postgres] ERREUR: impossible de démarrer postgres via docker compose.", flush=True)
        if out:
            print(out, flush=True)
        return False

    print(f"[postgres] Démarrage demandé, attente de disponibilité (timeout {timeout}s)…", flush=True)
    for _ in range(timeout):
        if _tcp_open(pg_host, pg_port):
            print(f"[postgres] OK : {pg_host}:{pg_port}", flush=True)
            return True
        time.sleep(1)
    print(f"[postgres] TIMEOUT: PostgreSQL non joignable après {timeout}s ({pg_host}:{pg_port}).", flush=True)
    return False


def _ensure_schema_migrated(db_url: str) -> bool:
    """Applique les migrations Alembic (idempotent) avant de lancer API/workers."""
    py = sys.executable
    env = {**os.environ, "DATABASE_URL": db_url, "PYTHONPATH": str(SRC_DIR)}
    try:
        cp = subprocess.run(
            [py, "-m", "alembic", "-c", str(PROJECT_ROOT / "alembic.ini"), "upgrade", "head"],
            cwd=str(PROJECT_ROOT),
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        if cp.returncode == 0:
            print("[db] Migrations Alembic OK.", flush=True)
            return True
        out = "\n".join(x for x in [cp.stdout, cp.stderr] if x).strip()
        print("[db] ERREUR: alembic upgrade head a échoué.", flush=True)
        if out:
            print(out, flush=True)
        return False
    except Exception as e:  # pragma: no cover
        print(f"[db] ERREUR: impossible d'exécuter Alembic: {e}", flush=True)
        return False


def _is_artiste_api(base: str) -> bool:
    url = base.rstrip("/") + "/"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "artiste-coloriage-start"})
        with urllib.request.urlopen(req, timeout=3.0) as r:
            body = r.read(800).decode("utf-8", errors="replace")
        return "Artiste Coloriage" in body or '"docs"' in body or "/docs" in body
    except Exception:
        return False


def _worker_running(script_name: str) -> bool | None:
    """True si un process semble lancer ce script ; None si indétectable (pas psutil)."""
    try:
        import psutil  # type: ignore[import-untyped]
    except ImportError:
        return None
    needle = script_name
    for proc in psutil.process_iter(["cmdline"]):
        try:
            cmd = proc.info.get("cmdline") or []
            flat = " ".join(cmd)
            if needle in flat and "start.py" not in flat:
                return True
        except (psutil.Error, TypeError):
            continue
    return False


def _register(name: str, proc: subprocess.Popen) -> None:
    _children.append((name, proc))


def _shutdown(_sig=None, _frame=None) -> None:
    print("\n[stop] Arrêt des processus lancés par ce script…", flush=True)
    for name, proc in reversed(_children):
        if proc.poll() is not None:
            continue
        try:
            proc.terminate()
        except Exception:
            pass
    for name, proc in reversed(_children):
        if proc.poll() is not None:
            continue
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except Exception:
                pass
    print("[stop] Terminé.", flush=True)
    _release_singleton_lock()
    sys.exit(0)


def _popen(
    name: str,
    args: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.Popen:
    print(f"[start] {name}: {' '.join(args)}", flush=True)
    merged = {**os.environ, **(env or {})}
    proc = subprocess.Popen(
        args,
        cwd=str(cwd) if cwd else None,
        env=merged,
    )
    _register(name, proc)
    return proc


def _wait_api_ready(base: str, timeout: int = 45) -> bool:
    for _ in range(timeout):
        if _is_artiste_api(base):
            return True
        time.sleep(1)
    return False


def main() -> int:
    _load_env()
    log_dir = _resolve_log_dir()
    lock_path = log_dir / "start.lock"
    if not _acquire_singleton_lock(lock_path):
        print(f"[start] Une autre instance est déjà active (lock: {lock_path}).", flush=True)
        return 2

    try:
        parser = argparse.ArgumentParser(description="Démarrage stack Artiste Coloriage")
        parser.add_argument("--with-ollama", action="store_true", help="Lancer `ollama serve` si Ollama n'est pas déjà joignable")
        parser.add_argument("--no-reload", action="store_true", help="Uvicorn sans --reload")
        parser.add_argument("--no-image-worker", action="store_true")
        parser.add_argument("--no-text-worker", action="store_true")
        parser.add_argument("--no-comfy", action="store_true", help="Ne pas lancer ComfyUI (vérifie seulement COMFY_URL)")
        parser.add_argument("--api-port", type=int, default=int(os.environ.get("ARTISTE_API_PORT", "8000")))
        args = parser.parse_args()

        # Bind host : ARTISTE_API_HOST (défaut 0.0.0.0) pour exposer l'API à
        # d'autres machines (Tailscale, LAN…). Les health checks et
        # probes locaux ciblent 127.0.0.1 indépendamment, car connect(0.0.0.0)
        # n'est pas portable.
        api_host = os.environ.get("ARTISTE_API_HOST", "0.0.0.0").strip() or "0.0.0.0"
        api_port = args.api_port
        api_probe_host = "127.0.0.1"
        api_base = f"http://{api_probe_host}:{api_port}"

        ollama_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
        comfy_url = os.environ.get("COMFY_URL", "http://127.0.0.1:8188").rstrip("/")
        database_url = os.environ.get(
            "DATABASE_URL",
            "postgresql+psycopg://artiste:artiste@127.0.0.1:5432/artiste_coloriage",
        ).strip()

        ollama_host, ollama_port = _parse_http_url(ollama_url + "/")
        comfy_host, comfy_port = _parse_http_url(comfy_url + "/")
        pg_host, pg_port = _parse_postgres_url(database_url)

        comfy_home, comfy_home_reason = _resolve_comfyui_home()

        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)

        print("=" * 64)
        print("  Artiste Coloriage — démarrage")
        print("=" * 64)

        # --- Ollama (optionnel) ---
        ollama_reachable = _http_get_status(ollama_url + "/", timeout=2.0) is not None or _http_get_status(
            ollama_url + "/api/tags", timeout=2.0
        ) is not None
        if args.with_ollama:
            if ollama_reachable:
                print(f"[ollama] Déjà joignable ({ollama_url}), pas de `ollama serve` lancé.", flush=True)
            else:
                ollama_bin = which("ollama")
                if not ollama_bin:
                    print("[ollama] ERREUR: `ollama` introuvable dans le PATH.", flush=True)
                else:
                    _popen("ollama serve", [ollama_bin, "serve"], cwd=PROJECT_ROOT)
                    time.sleep(1.5)
        else:
            if not ollama_reachable:
                print(
                    f"[ollama] Non démarré par ce script (utiliser --with-ollama). "
                    f"Non joignable pour l'instant : {ollama_url}",
                    flush=True,
                )
            else:
                print(f"[ollama] Joignable : {ollama_url} (inchangé).", flush=True)

        # --- PostgreSQL (précondition API/workers) ---
        if not _ensure_postgres_ready(database_url, timeout=60):
            print("[postgres] Arrêt du démarrage global: PostgreSQL indisponible.", flush=True)
            return 1
        if not _ensure_schema_migrated(database_url):
            print("[db] Arrêt du démarrage global: migrations DB non appliquées.", flush=True)
            return 1

        # --- ComfyUI ---
        comfy_reachable = _tcp_open(comfy_host, comfy_port)
        if args.no_comfy:
            print(f"[comfy] Ignoré (--no-comfy). URL attendue : {comfy_url}", flush=True)
        elif comfy_reachable:
            print(f"[comfy] Déjà actif ({comfy_url}).", flush=True)
        elif comfy_home is None:
            print(
                f"[comfy] Non lancé : {comfy_home_reason}. URL attendue : {comfy_url}",
                flush=True,
            )
        else:
            home = comfy_home
            comfy_exe, comfy_py_src = _resolve_comfyui_python(home)
            print(f"[comfy] Dossier : {home} (détecté via {comfy_home_reason})", flush=True)
            print(f"[comfy] Python : {comfy_exe} ({comfy_py_src})", flush=True)
            # Bind host ComfyUI : COMFYUI_HOST (défaut 0.0.0.0) pour Tailscale/LAN.
            # ComfyUI accepte --listen <ip>. Sans flag, il bind 127.0.0.1.
            comfy_bind_host = os.environ.get("COMFYUI_HOST", "0.0.0.0").strip() or "0.0.0.0"
            comfy_args = [comfy_exe, str(home / "main.py"), "--listen", comfy_bind_host]
            print(f"[comfy] Bind  : --listen {comfy_bind_host} (env COMFYUI_HOST)", flush=True)
            proc = _popen("ComfyUI", comfy_args, cwd=home)
            time.sleep(2.5)
            if proc.poll() is not None:
                print(
                    f"[comfy] ERREUR: le processus ComfyUI s'est arrêté tout de suite (code {proc.returncode}). "
                    f"Vérifiez COMFYUI_PYTHON et les dépendances dans le dossier ci-dessus.",
                    flush=True,
                )
            else:
                print("[comfy] Démarrage en cours… (le port peut prendre quelques secondes)", flush=True)

        # --- API ---
        if _tcp_open(api_probe_host, api_port):
            if _is_artiste_api(api_base):
                print(f"[api] Déjà actif : {api_base}", flush=True)
            else:
                print(
                    f"[api] ATTENTION: le port {api_port} est occupé mais ne répond pas comme l'API Artiste Coloriage. "
                    f"Uvicorn non lancé.",
                    flush=True,
                )
        else:
            uvicorn_args = [
                sys.executable,
                "-m",
                "uvicorn",
                "api.main:app",
                "--host",
                api_host,
                "--port",
                str(api_port),
            ]
            if not args.no_reload:
                uvicorn_args.append("--reload")
            _popen("uvicorn", uvicorn_args, cwd=SRC_DIR)
            print("[api] Attente de disponibilité…", flush=True)
            if not _wait_api_ready(api_base, timeout=60):
                print("[api] TIMEOUT: l'API ne répond pas comme attendu.", flush=True)
            else:
                print(f"[api] OK : {api_base}", flush=True)

        # --- Workers ---
        for label, script, skip_flag in (
            ("image_worker", "run_image_worker.py", args.no_image_worker),
            ("text_worker", "run_text_worker.py", args.no_text_worker),
        ):
            if skip_flag:
                print(f"[{label}] Ignoré (flag --no-…).", flush=True)
                continue
            running = _worker_running(script)
            if running is True:
                print(f"[{label}] Processus existant détecté, pas de nouveau lancement.", flush=True)
                continue
            if running is None:
                print(
                    f"[{label}] psutil absent : impossible de détecter un doublon. "
                    f"Installez psutil pour une détection fiable.",
                    flush=True,
                )
            script_path = PROJECT_ROOT / "scripts" / script
            _popen(label, [sys.executable, str(script_path)], cwd=PROJECT_ROOT)

        # --- Récap ---
        print("\n" + "=" * 64)
        print("  Ports et URLs")
        print("=" * 64)
        rows = [
            ("PostgreSQL", pg_port, f"{pg_host}:{pg_port}"),
            ("API", api_port, api_base),
            ("Swagger", api_port, f"{api_base}/docs"),
            ("ComfyUI", comfy_port, comfy_url),
            ("Ollama", ollama_port, ollama_url),
        ]
        w = max(len(r[0]) for r in rows)
        for name, port, url in rows:
            print(f"  {name:<{w}}  port {port:<5}  {url}")
        print("\n  Éditeurs (API) :")
        for path in (
            "/data/admin.html",
            "/data/images_editor.html",
            "/data/jobs_editor.html",
            "/data/taxonomy_editor.html",
            "/data/sites_editor.html",
        ):
            print(f"    {api_base}{path}")

        print("\n" + "=" * 64)
        print("  Fichiers de logs (voir README section « Logs »)")
        print("=" * 64)
        for name in ("api.log", "image_worker.log", "text_worker.log"):
            p = log_dir / name
            print(f"  {p}")
        print("\n  PowerShell (suivi) :")
        print(f'    Get-Content -Path "{log_dir / "api.log"}" -Wait -Tail 80')
        print("  Git Bash / WSL :")
        print(f"    tail -f {log_dir.as_posix()}/api.log")

        print("\n" + "=" * 64)
        print("  Ctrl+C pour arrêter les processus lancés par ce script.")
        print("=" * 64 + "\n")

        try:
            while True:
                for name, proc in list(_children):
                    code = proc.poll()
                    if code is not None:
                        print(f"[warn] {name} s'est terminé (code {code}). Arrêt global.", flush=True)
                        _shutdown()
                time.sleep(2)
        except KeyboardInterrupt:
            _shutdown()
        return 0
    finally:
        _release_singleton_lock()


if __name__ == "__main__":
    raise SystemExit(main())
