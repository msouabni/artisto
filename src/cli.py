from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

import httpx
import typer

from api.routes.images import BULK_CREATE_GENERATION_JOBS_MAX, IMAGE_STATUSES
from taxonomy import get_taxonomy, get_terms_for_branch

app = typer.Typer(help="CLI Artiste Coloriage : taxonomie locale + client HTTP jobs / file d'attente IA")

jobs_app = typer.Typer(help="File d'attente : POST /api/jobs/enqueue, diff, validate (ARTISTE_API_BASE)")

images_jobs_app = typer.Typer(help="Concepts image : export d'identifiants via l'API")
ai_jobs_app = typer.Typer(help="Appels IA directs (HTTP), sans enfiler de job")
wizard_jobs_app = typer.Typer(help="Assistants interactifs (filtres, chemins, confirmation)")

# Aligné sur ``BULK_CREATE_PROMPTS_MAX_ITEMS`` dans ``api.routes.ai``.
CREATE_PROMPTS_BULK_MAX = 10

def _api_base() -> str:
    return os.environ.get("ARTISTE_API_BASE", "http://127.0.0.1:8000").rstrip("/")


def _post_enqueue(payload: dict) -> None:
    url = f"{_api_base()}/api/jobs/enqueue"
    r = httpx.post(url, json=payload, timeout=120.0)
    if r.is_error:
        detail: Any = r.text
        try:
            body = r.json()
            if isinstance(body, dict) and body.get("detail") is not None:
                detail = body["detail"]
        except Exception:
            pass
        typer.echo(f"POST {url} -> HTTP {r.status_code}\n{detail}", err=True)
        raise typer.Exit(code=1)
    typer.echo(json.dumps(r.json(), indent=2, ensure_ascii=False))


def _theme_from_term_label(term_json: dict[str, Any], *, term_id: str) -> str:
    """Même règle que ``images_editor.html`` : name_en, sinon name_fr, sinon id du terme."""
    name_en = str(term_json.get("name_en") or "").strip()
    name_fr = str(term_json.get("name_fr") or "").strip()
    tid = str(term_json.get("id") or term_id or "").strip()
    return name_en or name_fr or tid or "Theme"


def _fetch_term_for_cli(vocabulary_id: str, term_id: str) -> dict[str, Any]:
    vid = quote(vocabulary_id, safe="")
    tid = quote(term_id, safe="")
    url = f"{_api_base()}/api/taxonomy/vocabularies/{vid}/terms/{tid}"
    r = httpx.get(url, timeout=60.0)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict):
        typer.echo("Réponse API terme invalide.", err=True)
        raise typer.Exit(code=1)
    return data


def _ensure_job_type_enabled(job_type: str) -> None:
    """Active le type de job côté API si nécessaire.

    Idempotent: la route PUT force simplement ``enabled=true``.
    """
    encoded = quote(job_type, safe="")
    url = f"{_api_base()}/api/jobs/types/{encoded}"
    r = httpx.put(url, json={"enabled": True}, timeout=60.0)
    if r.is_error:
        detail: Any = r.text
        try:
            body = r.json()
            if isinstance(body, dict) and body.get("detail") is not None:
                detail = body["detail"]
        except Exception:
            pass
        typer.echo(f"PUT {url} -> HTTP {r.status_code}\n{detail}", err=True)
        raise typer.Exit(code=1)


def _http_json_or_exit(method: str, url: str, **kwargs: Any) -> Any:
    try:
        r = httpx.request(method, url, **kwargs)
    except httpx.HTTPError as e:
        typer.echo(f"{method} {url} -> erreur reseau : {e!s}", err=True)
        raise typer.Exit(code=1) from e
    if r.is_error:
        detail: Any = r.text
        try:
            body = r.json()
            if isinstance(body, dict) and body.get("detail") is not None:
                detail = body["detail"]
        except Exception:
            pass
        typer.echo(f"{method} {url} -> HTTP {r.status_code}\n{detail}", err=True)
        raise typer.Exit(code=1)
    try:
        return r.json()
    except Exception:
        return None


def _enqueue_and_poll(
    job_type: str,
    config: dict[str, Any],
    *,
    poll_interval: float = 3.0,
    timeout: float = 300.0,
    verbose: bool = False,
) -> dict[str, Any]:
    """Enfile un job et poll jusqu'à sa completion.

    - Active le type si désactivé.
    - Poll GET /api/jobs (filtre par type + status running/pending) jusqu'à terminal.
    - Retourne job.result parsé ou le dict job complet.
    - Lève typer.Exit en cas d'échec ou timeout.
    """
    import time

    _ensure_job_type_enabled(job_type)

    url_enqueue = f"{_api_base()}/api/jobs/enqueue"
    payload: dict[str, Any] = {"type": job_type, "config": config}
    r = httpx.post(url_enqueue, json=payload, timeout=60.0)
    if r.is_error:
        detail: Any = r.text
        try:
            body = r.json()
            if isinstance(body, dict) and body.get("detail") is not None:
                detail = body["detail"]
        except Exception:
            pass
        typer.echo(f"POST /api/jobs/enqueue -> HTTP {r.status_code}\n{detail}", err=True)
        raise typer.Exit(code=1)
    enq = r.json()
    job_id: str = enq.get("id") or enq.get("job_id") or ""
    if not job_id:
        typer.echo("Réponse enqueue sans job_id.", err=True)
        raise typer.Exit(code=1)
    if verbose:
        typer.echo(f"[enqueue] job_id={job_id} type={job_type}")

    _TERMINAL_DONE = {"awaiting_validation", "completed", "applied", "rejected"}
    _TERMINAL_ERR = {"failed", "cancelled"}

    url_list = f"{_api_base()}/api/jobs"
    started = time.time()
    while True:
        elapsed = time.time() - started
        if elapsed > timeout:
            typer.echo(f"Timeout : job {job_id} non terminé après {timeout:.0f}s.", err=True)
            raise typer.Exit(code=1)
        time.sleep(poll_interval)
        try:
            resp = httpx.get(url_list, params={"page_size": 100, "sort": "created_at", "order": "desc"}, timeout=30.0)
        except httpx.HTTPError as e:
            if verbose:
                typer.echo(f"[poll] erreur réseau: {e}", err=True)
            continue
        if resp.is_error:
            if verbose:
                typer.echo(f"[poll] HTTP {resp.status_code}", err=True)
            continue
        try:
            data = resp.json()
        except Exception:
            continue
        jobs = data.get("jobs") or []
        job = next((j for j in jobs if j.get("id") == job_id), None)
        if job is None:
            if verbose:
                typer.echo(f"[poll] job {job_id} non trouvé (page 1).", err=True)
            continue
        status = job.get("status", "")
        if verbose:
            typer.echo(f"[poll] job {job_id} status={status} progress={job.get('progress', 0)}")
        if status in _TERMINAL_DONE:
            result_raw = job.get("result")
            if result_raw:
                try:
                    artifact = json.loads(result_raw) if isinstance(result_raw, str) else result_raw
                    proposal = artifact.get("proposal")
                    if proposal is not None:
                        return proposal
                    return artifact
                except Exception:
                    pass
            return job
        if status in _TERMINAL_ERR:
            typer.echo(f"Job {job_id} terminé en erreur (status={status}): {job.get('error_message', '')}", err=True)
            raise typer.Exit(code=1)


def _list_images_page(
    *,
    status: str | None,
    status_in: str | None,
    origin_term_id: str | None,
    origin_batch_id: str | None,
    origin_type: str | None,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if status:
        params["status"] = status
    if status_in:
        params["status_in"] = status_in
    if origin_term_id:
        params["origin_term_id"] = origin_term_id
    if origin_batch_id:
        params["origin_batch_id"] = origin_batch_id
    if origin_type:
        params["origin_type"] = origin_type
    url = f"{_api_base()}/api/images"
    data = _http_json_or_exit("GET", url, params=params, timeout=120.0)
    if not isinstance(data, list):
        typer.echo("Réponse inattendue pour GET /api/images (liste attendue).", err=True)
        raise typer.Exit(code=1)
    return data


def _fetch_all_image_ids(
    *,
    status: str | None,
    status_in: str | None,
    origin_term_id: str | None,
    origin_batch_id: str | None,
    origin_type: str | None,
    page_size: int,
) -> list[str]:
    out: list[str] = []
    offset = 0
    while True:
        page = _list_images_page(
            status=status,
            status_in=status_in,
            origin_term_id=origin_term_id,
            origin_batch_id=origin_batch_id,
            origin_type=origin_type,
            limit=page_size,
            offset=offset,
        )
        if not page:
            break
        for row in page:
            iid = str((row or {}).get("id") or "").strip()
            if iid:
                out.append(iid)
        if len(page) < page_size:
            break
        offset += page_size
    return out


def _read_image_id_file(path: Path) -> list[str]:
    raw_full = path.read_text(encoding="utf-8")
    raw = raw_full.strip()
    if not raw:
        return []
    if raw.startswith("{"):
        data = json.loads(raw)
        if not isinstance(data, dict):
            typer.echo("JSON : objet attendu avec la clé image_ids (export jobs images).", err=True)
            raise typer.Exit(code=1)
        arr = data.get("image_ids")
        if not isinstance(arr, list):
            typer.echo("JSON : image_ids doit être un tableau de chaînes.", err=True)
            raise typer.Exit(code=1)
        return [str(x).strip() for x in arr if str(x).strip()]
    if raw.startswith("["):
        data = json.loads(raw)
        if not isinstance(data, list):
            typer.echo("JSON : attendu un tableau de chaînes (ids).", err=True)
            raise typer.Exit(code=1)
        return [str(x).strip() for x in data if str(x).strip()]
    ids: list[str] = []
    for line in raw_full.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        ids.append(s)
    return ids


def _iter_chunks(xs: list[str], n: int) -> Iterable[list[str]]:
    for i in range(0, len(xs), n):
        yield xs[i : i + n]


def _read_checkpoint_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()}


def _apply_resume_filter(
    ids: list[str],
    *,
    checkpoint: Path | None,
    resume: bool,
) -> list[str]:
    if not resume or checkpoint is None or not checkpoint.exists():
        return ids
    done = _read_checkpoint_ids(checkpoint)
    out = [i for i in ids if i not in done]
    typer.echo(f"Reprise : {len(done)} id(s) déjà au checkpoint, {len(out)} restante(s).")
    return out


def _append_checkpoint_image_ids(checkpoint: Path | None, image_ids: Iterable[str]) -> None:
    if checkpoint is None:
        return
    mode = "a" if checkpoint.exists() else "w"
    with checkpoint.open(mode, encoding="utf-8") as cf:
        for iid in image_ids:
            s = str(iid).strip()
            if s:
                cf.write(s + "\n")


def _ok_image_ids_from_bulk_rows(results: list[Any]) -> list[str]:
    out: list[str] = []
    for row in results:
        if isinstance(row, dict) and row.get("ok"):
            iid = str(row.get("image_id") or "").strip()
            if iid:
                out.append(iid)
    return out


def _image_put_payload_from_get(row: dict[str, Any], *, prompt: str, negative_prompt: str) -> dict[str, Any]:
    """Corps PUT /api/images/{id} compatible avec ``ImagePayload``."""
    return {
        "id": row.get("id"),
        "title": row.get("title") or "",
        "status": row.get("status") or "draft",
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "origin_type": row.get("origin_type") or "manual",
        "origin_batch_id": row.get("origin_batch_id"),
        "origin_term_id": row.get("origin_term_id"),
        "origin_taxonomy_id": row.get("origin_taxonomy_id"),
        "selected_output_id": row.get("selected_output_id"),
        "current_job_id": row.get("current_job_id"),
    }


@images_jobs_app.command("export-ids")
def jobs_images_export_ids(
    out: Path = typer.Option(..., "--out", "-o", help="Fichier de sortie (txt : une id par ligne ; json si extension .json)"),
    status: str | None = typer.Option(None, "--status", "-s", help="Filtre statut unique (ex. draft)"),
    status_in: str | None = typer.Option(
        None,
        "--status-in",
        help="Plusieurs statuts séparés par des virgules (ex. draft,prompt_ready). Ignoré si --status est défini.",
    ),
    origin_term_id: str | None = typer.Option(None, "--origin-term-id"),
    origin_batch_id: str | None = typer.Option(None, "--origin-batch-id"),
    origin_type: str | None = typer.Option(None, "--origin-type"),
    page_size: int = typer.Option(200, "--page-size", min=1, max=2000),
) -> None:
    """Exporte les identifiants de concepts image via GET /api/images (pagination automatique)."""
    if status and status not in IMAGE_STATUSES:
        typer.echo(f"--status invalide. Valeurs : {', '.join(IMAGE_STATUSES)}", err=True)
        raise typer.Exit(code=1)
    if status_in and not status:
        for part in status_in.split(","):
            p = part.strip()
            if p and p not in IMAGE_STATUSES:
                typer.echo(f"statut invalide dans --status-in : {p!r}", err=True)
                raise typer.Exit(code=1)
    ids = _fetch_all_image_ids(
        status=status.strip() if status else None,
        status_in=status_in.strip() if status_in else None,
        origin_term_id=origin_term_id.strip() if origin_term_id else None,
        origin_batch_id=origin_batch_id.strip() if origin_batch_id else None,
        origin_type=origin_type.strip() if origin_type else None,
        page_size=page_size,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.suffix.lower() == ".json":
        payload = {
            "image_ids": ids,
            "filters": {
                "status": status,
                "status_in": status_in,
                "origin_term_id": origin_term_id,
                "origin_batch_id": origin_batch_id,
                "origin_type": origin_type,
            },
            "count": len(ids),
        }
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    else:
        out.write_text("\n".join(ids) + ("\n" if ids else ""), encoding="utf-8")
    typer.echo(f"{len(ids)} id(s) écrites dans {out}")


@images_jobs_app.command("bulk-create-generation-jobs")
def jobs_images_bulk_create_generation_jobs(
    id_file: Path = typer.Argument(
        ...,
        help="Fichier d'ids (une par ligne, JSON tableau, ou export .json avec image_ids)",
    ),
    workflow_template: str | None = typer.Option(
        None,
        "--workflow-template",
        "-w",
        help="Template workflow (ex. z_image_turbo_v1). Sans flag : défaut worker API.",
    ),
    steps: int | None = typer.Option(None, "--steps"),
    cfg: float | None = typer.Option(None, "--cfg"),
    sampler_name: str | None = typer.Option(None, "--sampler-name"),
    scheduler: str | None = typer.Option(None, "--scheduler"),
    denoise: float | None = typer.Option(None, "--denoise"),
    shift: float | None = typer.Option(None, "--shift"),
    seed: int | None = typer.Option(None, "--seed"),
    chunk_size: int = typer.Option(
        BULK_CREATE_GENERATION_JOBS_MAX,
        "--chunk-size",
        min=1,
        max=BULK_CREATE_GENERATION_JOBS_MAX,
        help=f"Taille des lots POST (max {BULK_CREATE_GENERATION_JOBS_MAX}, limite API).",
    ),
    resume: bool = typer.Option(
        False,
        "--resume",
        help="Ignore les ids déjà présents dans le fichier --checkpoint (une id par ligne).",
    ),
    checkpoint: Path | None = typer.Option(
        None,
        "--checkpoint",
        help="Avec --resume : ids à sauter ; sinon : append des ids pour lesquels ok=true.",
    ),
    results_out: Path | None = typer.Option(
        None,
        "--results-out",
        help="Fichier NDJSON : une ligne JSON par chunk (résumé + results).",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Affiche les lots sans appeler l'API."),
) -> None:
    """Appelle POST /api/images/bulk-create-generation-jobs par paquets (images ``prompt_ready``)."""
    if chunk_size > BULK_CREATE_GENERATION_JOBS_MAX:
        typer.echo(f"--chunk-size ne peut pas dépasser {BULK_CREATE_GENERATION_JOBS_MAX}.", err=True)
        raise typer.Exit(code=1)
    ids = _read_image_id_file(id_file)
    if not ids:
        typer.echo("Aucun identifiant dans le fichier.", err=True)
        raise typer.Exit(code=1)
    ids = _apply_resume_filter(ids, checkpoint=checkpoint, resume=resume)
    if not ids:
        typer.echo("Rien à traiter.", err=True)
        raise typer.Exit(code=0)

    url_bulk = f"{_api_base()}/api/images/bulk-create-generation-jobs"
    ndjson_f = results_out.open("a", encoding="utf-8") if results_out else None
    total_ok = 0
    total_fail = 0
    try:
        for batch in _iter_chunks(ids, chunk_size):
            body: dict[str, Any] = {"image_ids": batch}
            if workflow_template and str(workflow_template).strip():
                body["workflow_template"] = str(workflow_template).strip()
            if steps is not None:
                body["steps"] = steps
            if cfg is not None:
                body["cfg"] = cfg
            if sampler_name and str(sampler_name).strip():
                body["sampler_name"] = str(sampler_name).strip()
            if scheduler and str(scheduler).strip():
                body["scheduler"] = str(scheduler).strip()
            if denoise is not None:
                body["denoise"] = denoise
            if shift is not None:
                body["shift"] = shift
            if seed is not None:
                body["seed"] = seed
            if dry_run:
                typer.echo(f"[dry-run] lot de {len(batch)} -> {batch[:3]}{'...' if len(batch) > 3 else ''}")
                continue
            resp = _http_json_or_exit("POST", url_bulk, json=body, timeout=600.0)
            if not isinstance(resp, dict):
                typer.echo("Réponse bulk invalide.", err=True)
                raise typer.Exit(code=1)
            results = resp.get("results") or []
            summary = resp.get("summary") or {}
            total_ok += int(summary.get("success") or 0)
            total_fail += int(summary.get("failed") or 0)
            if ndjson_f is not None:
                ndjson_f.write(json.dumps({"batch": batch, "summary": summary, "results": results}, ensure_ascii=False))
                ndjson_f.write("\n")
                ndjson_f.flush()
            _append_checkpoint_image_ids(checkpoint, _ok_image_ids_from_bulk_rows(results))
    finally:
        if ndjson_f is not None:
            ndjson_f.close()

    if dry_run:
        n_chunks = (len(ids) + chunk_size - 1) // chunk_size
        typer.echo(f"[dry-run] terminé ({len(ids)} id(s) en {n_chunks} lot(s)).")
        return
    typer.echo(
        json.dumps(
            {
                "success": total_ok,
                "failed": total_fail,
                "chunks": (len(ids) + chunk_size - 1) // chunk_size,
            },
            ensure_ascii=False,
        )
    )


@ai_jobs_app.command("bulk-create-prompts")
def jobs_ai_bulk_create_prompts(
    id_file: Path = typer.Argument(
        ...,
        help="Fichier d'ids (une par ligne, JSON tableau, ou export .json avec image_ids)",
    ),
    profile: str = typer.Option("kids_coloring_lineart_v1", "--profile", "-p"),
    workflow_template: str | None = typer.Option(
        None,
        "--workflow-template",
        "-w",
        help="Override explicite (ex. z_image_turbo_v1). Sans flag : défaut API (Ernie).",
    ),
    validate_prompts: bool = typer.Option(False, "--validate", "-V", help="Score de validation par ligne (plus lent)"),
    model: str | None = typer.Option(None, "--model"),
    temperature: float | None = typer.Option(None, "--temperature"),
    chunk_size: int = typer.Option(
        CREATE_PROMPTS_BULK_MAX,
        "--chunk-size",
        min=1,
        max=CREATE_PROMPTS_BULK_MAX,
        help=f"Taille des lots POST (max {CREATE_PROMPTS_BULK_MAX}, limite API).",
    ),
    persist: bool = typer.Option(
        False,
        "--persist",
        help="Écrit prompt + negative_prompt sur chaque concept (PUT /api/images/{id}) pour les lignes ok.",
    ),
    resume: bool = typer.Option(
        False,
        "--resume",
        help="Ignore les ids déjà présents dans le fichier --checkpoint (une id par ligne).",
    ),
    checkpoint: Path | None = typer.Option(
        None,
        "--checkpoint",
        help="Avec --resume : ids à sauter ; sinon : append des ids traités avec succès (persist ou bulk ok).",
    ),
    results_out: Path | None = typer.Option(
        None,
        "--results-out",
        help="Fichier NDJSON : une ligne JSON par chunk (résumé + results).",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Affiche les lots sans appeler l'API."),
) -> None:
    """Appelle POST /api/ai/create-prompts-bulk par paquets (ids → items avec image_id seul)."""
    if chunk_size > CREATE_PROMPTS_BULK_MAX:
        typer.echo(f"--chunk-size ne peut pas dépasser {CREATE_PROMPTS_BULK_MAX}.", err=True)
        raise typer.Exit(code=1)
    ids = _read_image_id_file(id_file)
    if not ids:
        typer.echo("Aucun identifiant dans le fichier.", err=True)
        raise typer.Exit(code=1)
    ids = _apply_resume_filter(ids, checkpoint=checkpoint, resume=resume)
    if not ids:
        typer.echo("Rien à traiter.", err=True)
        raise typer.Exit(code=0)

    ndjson_f = results_out.open("a", encoding="utf-8") if results_out else None

    total_ok = 0
    total_fail = 0
    try:
        for batch in _iter_chunks(ids, chunk_size):
            items = [{"image_id": x, "profile": profile} for x in batch]
            config: dict[str, Any] = {"items": items, "validate_prompts": validate_prompts}
            if workflow_template and str(workflow_template).strip():
                config["workflow_template"] = str(workflow_template).strip()
            if model and str(model).strip():
                config["model"] = str(model).strip()
            if temperature is not None:
                config["temperature"] = temperature
            if dry_run:
                typer.echo(f"[dry-run] lot de {len(batch)} -> {batch[:3]}{'...' if len(batch) > 3 else ''}")
                continue
            typer.echo(f"[bulk] enqueue image_prompts_bulk ({len(batch)} item(s))…")
            resp = _enqueue_and_poll("image_prompts_bulk", config, timeout=600.0, poll_interval=3.0, verbose=False)
            if not isinstance(resp, dict):
                typer.echo("Résultat bulk invalide.", err=True)
                raise typer.Exit(code=1)
            results = resp.get("results") or []
            summary = resp.get("summary") or {}
            total_ok += int(summary.get("success") or 0)
            total_fail += int(summary.get("failed") or 0)
            if ndjson_f is not None:
                ndjson_f.write(json.dumps({"batch": batch, "summary": summary, "results": results}, ensure_ascii=False))
                ndjson_f.write("\n")
                ndjson_f.flush()

            if persist:
                base = _api_base()
                for row in results:
                    if not isinstance(row, dict) or not row.get("ok"):
                        continue
                    iid = str(row.get("image_id") or "").strip()
                    if not iid:
                        continue
                    prompt = str(row.get("prompt") or "")
                    neg = str(row.get("negative_prompt") or "")
                    cur = _http_json_or_exit("GET", f"{base}/api/images/{quote(iid, safe='')}", timeout=60.0)
                    if not isinstance(cur, dict):
                        continue
                    for noise in ("current_job", "current_job_output"):
                        cur.pop(noise, None)
                    put_body = _image_put_payload_from_get(cur, prompt=prompt, negative_prompt=neg)
                    _http_json_or_exit(
                        "PUT",
                        f"{base}/api/images/{quote(iid, safe='')}",
                        json=put_body,
                        timeout=60.0,
                    )

            _append_checkpoint_image_ids(checkpoint, _ok_image_ids_from_bulk_rows(results))
    finally:
        if ndjson_f is not None:
            ndjson_f.close()

    if dry_run:
        typer.echo(f"[dry-run] terminé ({len(ids)} id(s) en {((len(ids) + chunk_size - 1) // chunk_size)} lot(s)).")
        return
    typer.echo(json.dumps({"success": total_ok, "failed": total_fail, "chunks": (len(ids) + chunk_size - 1) // chunk_size}, ensure_ascii=False))


@ai_jobs_app.command("bulk-image-prompt-create")
def jobs_ai_bulk_image_prompt_create(
    id_file: Path = typer.Argument(
        ...,
        help="Fichier d'ids (une par ligne, JSON tableau, ou export .json avec image_ids)",
    ),
    keywords: str = typer.Option(
        "",
        "--keywords",
        "-k",
        help="Mots-clés pour chaque image. Si omis avec --title, titre/prompt lus via GET /api/images/{id}.",
    ),
    title: str = typer.Option(
        "",
        "--title",
        "-t",
        help="Titre pour chaque image. Peut être combiné avec --keywords.",
    ),
    profile: str = typer.Option("kids_coloring_lineart_v1", "--profile", "-p"),
    workflow_template: str | None = typer.Option(
        None,
        "--workflow-template",
        "-w",
        help="Override explicite (ex. z_image_turbo_v1). Sans flag : défaut Ernie.",
    ),
    chunk_size: int = typer.Option(
        25,
        "--chunk-size",
        min=1,
        max=500,
        help="Taille de lot logique (écriture checkpoint / ligne --results-out).",
    ),
    resume: bool = typer.Option(
        False,
        "--resume",
        help="Ignore les ids déjà présents dans le fichier --checkpoint (une id par ligne).",
    ),
    checkpoint: Path | None = typer.Option(
        None,
        "--checkpoint",
        help="Avec --resume : ids à sauter ; sinon : append des ids pour lesquels l'enqueue a réussi.",
    ),
    results_out: Path | None = typer.Option(
        None,
        "--results-out",
        help="Fichier NDJSON : une ligne JSON par chunk (résumé + results par image).",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Sans HTTP ; exiger --keywords et/ou --title."),
) -> None:
    """Enfile un job ``image_prompt_create`` par image (POST /api/jobs/enqueue), par lots logiques."""
    gkw = keywords.strip()
    gti = title.strip()
    if dry_run and not gkw and not gti:
        typer.echo(
            "Avec --dry-run, fournissez --keywords et/ou --title (aucun GET vers l'API).",
            err=True,
        )
        raise typer.Exit(code=1)

    ids = _read_image_id_file(id_file)
    if not ids:
        typer.echo("Aucun identifiant dans le fichier.", err=True)
        raise typer.Exit(code=1)
    ids = _apply_resume_filter(ids, checkpoint=checkpoint, resume=resume)
    if not ids:
        typer.echo("Rien à traiter.", err=True)
        raise typer.Exit(code=0)

    if not dry_run:
        _ensure_job_type_enabled("image_prompt_create")

    base = _api_base()
    url_enqueue = f"{base}/api/jobs/enqueue"
    ndjson_f = results_out.open("a", encoding="utf-8") if results_out else None
    total_ok = 0
    total_fail = 0
    n_chunks = 0

    def _detail_from_response(r: httpx.Response) -> str:
        detail: Any = r.text
        try:
            body = r.json()
            if isinstance(body, dict) and body.get("detail") is not None:
                detail = body["detail"]
        except Exception:
            pass
        return str(detail)

    try:
        for batch in _iter_chunks(ids, chunk_size):
            n_chunks += 1
            chunk_results: list[dict[str, Any]] = []
            ok_ids: list[str] = []
            for iid in batch:
                kw, tt = gkw, gti
                if not kw and not tt:
                    if dry_run:
                        chunk_results.append({"image_id": iid, "ok": True, "job_id": None, "note": "dry-run"})
                        total_ok += 1
                        ok_ids.append(iid)
                        continue
                    cur = _http_json_or_exit("GET", f"{base}/api/images/{quote(iid, safe='')}", timeout=60.0)
                    if not isinstance(cur, dict):
                        chunk_results.append({"image_id": iid, "ok": False, "error": "Réponse image invalide."})
                        total_fail += 1
                        continue
                    tt = str(cur.get("title") or "").strip()
                    kw = str(cur.get("prompt") or "").strip()
                    if len(kw) > 4000:
                        kw = kw[:4000]
                if not kw and not tt:
                    chunk_results.append(
                        {
                            "image_id": iid,
                            "ok": False,
                            "error": "Ni mots-clés ni titre (--keywords/--title ou image avec title/prompt).",
                        }
                    )
                    total_fail += 1
                    continue
                cfg: dict[str, str] = {
                    "image_id": iid,
                    "keywords": kw,
                    "title": tt,
                    "profile": profile,
                }
                if workflow_template and str(workflow_template).strip():
                    cfg["workflow_template"] = str(workflow_template).strip()
                payload = {
                    "type": "image_prompt_create",
                    "entity_type": "image",
                    "entity_id": iid,
                    "config": cfg,
                }
                if dry_run:
                    chunk_results.append({"image_id": iid, "ok": True, "job_id": None})
                    total_ok += 1
                    ok_ids.append(iid)
                    continue
                r = httpx.post(url_enqueue, json=payload, timeout=120.0)
                if r.is_error:
                    chunk_results.append({"image_id": iid, "ok": False, "error": _detail_from_response(r)})
                    total_fail += 1
                    continue
                try:
                    data = r.json()
                except Exception:
                    chunk_results.append({"image_id": iid, "ok": False, "error": "Réponse JSON invalide."})
                    total_fail += 1
                    continue
                jid = str((data or {}).get("id") or "").strip()
                chunk_results.append({"image_id": iid, "ok": True, "job_id": jid or None})
                total_ok += 1
                ok_ids.append(iid)

            summary = {
                "total": len(batch),
                "success": sum(1 for row in chunk_results if row.get("ok")),
                "failed": sum(1 for row in chunk_results if not row.get("ok")),
            }
            if ndjson_f is not None:
                ndjson_f.write(json.dumps({"batch": batch, "summary": summary, "results": chunk_results}, ensure_ascii=False))
                ndjson_f.write("\n")
                ndjson_f.flush()
            _append_checkpoint_image_ids(checkpoint, ok_ids)
    finally:
        if ndjson_f is not None:
            ndjson_f.close()

    if dry_run:
        typer.echo(f"[dry-run] terminé ({len(ids)} id(s) en {n_chunks} lot(s)).")
        return
    typer.echo(json.dumps({"success": total_ok, "failed": total_fail, "chunks": n_chunks}, ensure_ascii=False))


@wizard_jobs_app.command("bulk-prompts")
def jobs_wizard_bulk_prompts() -> None:
    """Assistant : export d'ids (filtre statut) puis lancement optionnel du bulk create-prompts."""
    typer.echo(f"API : {_api_base()}")
    typer.echo("Statuts possibles : " + ", ".join(IMAGE_STATUSES))
    st = typer.prompt("Filtre --status (Entrée = aucun, liste toutes les images)", default="").strip()
    if st and st not in IMAGE_STATUSES:
        typer.echo(f"Statut inconnu : {st!r}", err=True)
        raise typer.Exit(code=1)
    st_in = ""
    if not st:
        st_in = typer.prompt(
            "Ou --status-in (virgules, ex. draft,prompt_ready ; Entrée = aucun)",
            default="",
        ).strip()
        if st_in:
            for part in st_in.split(","):
                p = part.strip()
                if p and p not in IMAGE_STATUSES:
                    typer.echo(f"Statut inconnu dans la liste : {p!r}", err=True)
                    raise typer.Exit(code=1)
    default_export = Path("data") / "exported_image_ids.txt"
    out_s = typer.prompt("Fichier export ids", default=str(default_export)).strip()
    out_path = Path(out_s)
    ids = _fetch_all_image_ids(
        status=st or None,
        status_in=st_in or None,
        origin_term_id=None,
        origin_batch_id=None,
        origin_type=None,
        page_size=200,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(ids) + ("\n" if ids else ""), encoding="utf-8")
    typer.echo(f"Export : {len(ids)} id(s) -> {out_path.resolve()}")
    if not ids:
        return
    if not typer.confirm("Lancer la génération bulk de prompts maintenant ?", default=False):
        return
    prof = typer.prompt("Profil", default="kids_coloring_lineart_v1").strip()
    wt = typer.prompt("workflow_template (Entrée = défaut API / Ernie)", default="").strip() or None
    do_val = typer.confirm("Activer la validation (--validate) ?", default=False)
    do_persist = typer.confirm("Persister les prompts en base (--persist) ?", default=False)
    ck_default = str(out_path) + ".checkpoint.txt"
    ck_s = typer.prompt("Fichier checkpoint (append ids ok)", default=ck_default).strip()
    ck_path = Path(ck_s)
    ndone: set[str] = set()
    if ck_path.exists():
        ndone = {ln.strip() for ln in ck_path.read_text(encoding="utf-8").splitlines() if ln.strip()}
    todo = [i for i in ids if i not in ndone]
    typer.echo(f"Traitement de {len(todo)} id(s) ({len(ndone)} déjà au checkpoint).")
    total_ok = total_fail = 0
    for i in range(0, len(todo), CREATE_PROMPTS_BULK_MAX):
        batch = todo[i : i + CREATE_PROMPTS_BULK_MAX]
        config: dict[str, Any] = {
            "items": [{"image_id": x, "profile": prof} for x in batch],
            "validate_prompts": do_val,
        }
        if wt:
            config["workflow_template"] = wt
        typer.echo(f"[wizard] enqueue image_prompts_bulk ({len(batch)} item(s))…")
        resp = _enqueue_and_poll("image_prompts_bulk", config, timeout=600.0, poll_interval=3.0, verbose=False)
        if not isinstance(resp, dict):
            typer.echo("Résultat invalide.", err=True)
            raise typer.Exit(code=1)
        results = resp.get("results") or []
        summary = resp.get("summary") or {}
        total_ok += int(summary.get("success") or 0)
        total_fail += int(summary.get("failed") or 0)
        if do_persist:
            base = _api_base()
            for row in results:
                if not isinstance(row, dict) or not row.get("ok"):
                    continue
                iid = str(row.get("image_id") or "").strip()
                if not iid:
                    continue
                cur = _http_json_or_exit("GET", f"{base}/api/images/{quote(iid, safe='')}", timeout=60.0)
                if not isinstance(cur, dict):
                    continue
                for noise in ("current_job", "current_job_output"):
                    cur.pop(noise, None)
                put_body = _image_put_payload_from_get(
                    cur,
                    prompt=str(row.get("prompt") or ""),
                    negative_prompt=str(row.get("negative_prompt") or ""),
                )
                _http_json_or_exit("PUT", f"{base}/api/images/{quote(iid, safe='')}", json=put_body, timeout=60.0)
        with ck_path.open("a", encoding="utf-8") as cf:
            for row in results:
                if isinstance(row, dict) and row.get("ok"):
                    iid = str(row.get("image_id") or "").strip()
                    if iid:
                        cf.write(iid + "\n")
    typer.echo(json.dumps({"success": total_ok, "failed": total_fail}, ensure_ascii=False))


@jobs_app.command("enqueue-text")
def jobs_enqueue_text(
    prompt: str = typer.Argument(..., help="Prompt utilisateur pour Ollama"),
    entity_id: str = typer.Option("", "--entity-id", "-e", help="ID entité cible (ex. terme)"),
    vocabulary_id: str = typer.Option("themes", "--vocabulary-id", "-v"),
    system: str = typer.Option("", "--system", "-s", help="Message système optionnel"),
) -> None:
    """Enfile un job ``text_enrichment`` (worker Ollama + artefact de revue v1)."""
    payload: dict = {
        "type": "text_enrichment",
        "entity_type": "term",
        "config": {"prompt": prompt, "system": system},
        "vocabulary_id": vocabulary_id,
    }
    if entity_id.strip():
        payload["entity_id"] = entity_id.strip()
    _post_enqueue(payload)


@jobs_app.command("generate-concepts")
def jobs_generate_concepts(
    theme: str | None = typer.Argument(
        None,
        help="Thème libre. Omis si --term-id : thème = name_en | name_fr du terme (comme l'UI images).",
    ),
    vocabulary_id: str = typer.Option(
        "",
        "--vocabulary-id",
        "-v",
        help="Vocabulaire pour l'ancrage (défaut : themes si --term-id)",
    ),
    term_id: str = typer.Option(
        "",
        "--term-id",
        "-t",
        help="Terme d'ancrage : contexte taxonomique ; thème dérivé du libellé si THEME est omis",
    ),
    count: int = typer.Option(5, "--count", "-n", help="Nombre de concepts (1–15)"),
    model: str = typer.Option("", "--model"),
    temperature: float | None = typer.Option(None, "--temperature"),
) -> None:
    """Enfile un job ``image_generate_concepts`` (revue puis persistance des concepts en base)."""
    if count < 1 or count > 15:
        typer.echo("--count doit être entre 1 et 15.", err=True)
        raise typer.Exit(code=1)
    tid = term_id.strip()
    theme_str = (theme or "").strip()
    vocab_raw = vocabulary_id.strip()
    vocab = vocab_raw or "themes"

    if tid:
        try:
            term_row = _fetch_term_for_cli(vocab, tid)
        except httpx.HTTPStatusError as e:
            typer.echo(f"Impossible de charger le terme ({e.response.status_code}) : {e!s}", err=True)
            raise typer.Exit(code=1) from e
        except httpx.HTTPError as e:
            typer.echo(f"Erreur HTTP vers l'API : {e!s}", err=True)
            raise typer.Exit(code=1) from e
        derived = _theme_from_term_label(term_row, term_id=tid)
        final_theme = theme_str if theme_str else derived
        cfg: dict[str, Any] = {
            "theme": final_theme,
            "count": count,
            "term_id": tid,
            "vocabulary_id": vocab,
        }
    else:
        if not theme_str:
            typer.echo(
                "Fournissez un THEME en argument ou bien --term-id (vocabulaire via -v, défaut themes).",
                err=True,
            )
            raise typer.Exit(code=1)
        cfg = {"theme": theme_str, "count": count}
        if vocab_raw:
            cfg["vocabulary_id"] = vocab_raw
    if model.strip():
        cfg["model"] = model.strip()
    if temperature is not None:
        cfg["temperature"] = temperature
    _ensure_job_type_enabled("image_generate_concepts")
    _post_enqueue(
        {
            "type": "image_generate_concepts",
            "config": cfg,
        }
    )


@jobs_app.command("enqueue-json")
def jobs_enqueue_json(
    path: Path | None = typer.Option(
        None,
        "--file",
        "-f",
        help="Fichier JSON (corps POST /api/jobs/enqueue). Sinon lecture depuis stdin.",
    ),
) -> None:
    """Enfile un job à partir du corps JSON complet (type, config, entity_*, …)."""
    raw = path.read_text(encoding="utf-8") if path else sys.stdin.read()
    body = json.loads(raw)
    if not isinstance(body, dict):
        typer.echo("Le JSON doit être un objet.", err=True)
        raise typer.Exit(code=1)
    _post_enqueue(body)


@jobs_app.command("taxonomy-enrich-term")
def jobs_taxonomy_enrich_term(
    term_id: str = typer.Argument(...),
    vocabulary_id: str = typer.Option("themes", "--vocabulary-id", "-v"),
    model: str = typer.Option("", "--model"),
    temperature: float | None = typer.Option(None, "--temperature"),
) -> None:
    """Job ``taxonomy_enrich_term`` : suggestions de champs pour un terme."""
    cfg: dict = {"vocabulary_id": vocabulary_id, "term_id": term_id}
    if model.strip():
        cfg["model"] = model.strip()
    if temperature is not None:
        cfg["temperature"] = temperature
    _post_enqueue(
        {
            "type": "taxonomy_enrich_term",
            "config": cfg,
            "vocabulary_id": vocabulary_id,
            "entity_id": term_id,
        }
    )


@jobs_app.command("taxonomy-enrich-batch")
def jobs_taxonomy_enrich_batch(
    term_ids: str = typer.Argument(..., help="IDs séparés par des virgules"),
    vocabulary_id: str = typer.Option("themes", "--vocabulary-id", "-v"),
) -> None:
    """Job ``taxonomy_enrich_terms_batch``."""
    ids = [x.strip() for x in term_ids.split(",") if x.strip()]
    if not ids:
        typer.echo("Au moins un term_id requis.", err=True)
        raise typer.Exit(code=1)
    _post_enqueue(
        {
            "type": "taxonomy_enrich_terms_batch",
            "config": {"vocabulary_id": vocabulary_id, "term_ids": ids},
            "vocabulary_id": vocabulary_id,
        }
    )


@jobs_app.command("image-prompt-create")
def jobs_image_prompt_create(
    image_id: str = typer.Option(..., "--image-id", "-i"),
    keywords: str = typer.Option("", "--keywords", "-k"),
    title: str = typer.Option("", "--title", "-t"),
    profile: str = typer.Option("kids_coloring_lineart_v1", "--profile", "-p"),
    workflow_template: str | None = typer.Option(
        None,
        "--workflow-template",
        "-w",
        help="Override explicite (ex. z_image_turbo_v1 pour writer Z-Image). Sans flag : défaut Ernie.",
    ),
) -> None:
    """Job ``image_prompt_create`` (planner + writer ; défaut Ernie, opt-in Z-Image via --workflow-template)."""
    if not keywords.strip() and not title.strip():
        typer.echo("Fournir --keywords et/ou --title.", err=True)
        raise typer.Exit(code=1)
    cfg: dict[str, str] = {
        "image_id": image_id,
        "keywords": keywords,
        "title": title,
        "profile": profile,
    }
    if workflow_template and str(workflow_template).strip():
        cfg["workflow_template"] = str(workflow_template).strip()
    _post_enqueue(
        {
            "type": "image_prompt_create",
            "entity_type": "image",
            "entity_id": image_id,
            "config": cfg,
        }
    )


@jobs_app.command("diff")
def jobs_diff(job_id: str = typer.Argument(..., help="ID du job")) -> None:
    """Affiche le diff JSON (job awaiting_validation)."""
    r = httpx.get(f"{_api_base()}/api/jobs/{job_id}/diff", timeout=60.0)
    r.raise_for_status()
    typer.echo(json.dumps(r.json(), indent=2, ensure_ascii=False))


@jobs_app.command("validate")
def jobs_validate(
    job_id: str = typer.Argument(..., help="ID du job"),
    action: str = typer.Argument(..., help="apply ou reject"),
) -> None:
    """Applique ou rejette le résultat d'un job en awaiting_validation."""
    act = action.lower().strip()
    if act not in ("apply", "reject"):
        typer.echo("action doit être apply ou reject", err=True)
        raise typer.Exit(code=1)
    r = httpx.post(
        f"{_api_base()}/api/jobs/{job_id}/validate",
        json={"action": act},
        timeout=120.0,
    )
    r.raise_for_status()
    typer.echo(json.dumps(r.json(), indent=2, ensure_ascii=False))


jobs_app.add_typer(images_jobs_app, name="images")
jobs_app.add_typer(ai_jobs_app, name="ai")
jobs_app.add_typer(wizard_jobs_app, name="wizard")

app.add_typer(jobs_app, name="jobs")


@app.command()
def list_themes() -> None:
    """Lister les principaux thèmes (racine de la taxonomie universelle)."""
    taxonomy = get_taxonomy()
    for vocab in taxonomy.vocabularies:
        typer.echo(f"Vocabulaire: {vocab.id}")
        for term in vocab.terms:
            typer.echo(f"- {term.id}: {term.name_fr} / {term.name_en}")


@app.command()
def show_branch(term_id: str) -> None:
    """Afficher une branche de la taxonomie (terme + descendants)."""
    taxonomy = get_taxonomy()
    terms = get_terms_for_branch(taxonomy, term_id=term_id)
    if not terms:
        typer.echo(f"Aucun terme trouvé pour id='{term_id}'")
        raise typer.Exit(code=1)
    for term in terms:
        depth = 0
        current_parent = term.parent_id
        while current_parent:
            parent = taxonomy.find_term(current_parent)
            if parent is None:
                break
            depth += 1
            current_parent = parent.parent_id
        indent = "  " * depth
        typer.echo(f"{indent}- {term.id}: {term.name_fr} / {term.name_en}")


@app.command()
def input_theme() -> None:
    """Saisie interactive d'un thème libre, avec rappel de quelques exemples."""
    taxonomy = get_taxonomy()
    typer.echo("Quelques thèmes existants dans la taxonomie :")
    for vocab in taxonomy.vocabularies:
        for term in vocab.terms:
            typer.echo(f"- {term.name_fr} / {term.name_en} (id={term.id})")
    theme = typer.prompt("Saisis un thème général (texte libre)")
    typer.echo(f"Thème saisi: {theme}")


if __name__ == "__main__":
    app()
