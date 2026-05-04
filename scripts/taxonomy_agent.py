#!/usr/bin/env python
"""
Taxonomy Agent CLI — enrichissement automatique de la taxonomie via Ollama.

Les commandes passent désormais par la file d'attente de jobs (POST /api/jobs/enqueue)
et attendent la completion via polling, afin de tracer les performances et la qualité.

Usage :
  python scripts/taxonomy_agent.py enrich-term animaux --fields name_ar,description_ar
  python scripts/taxonomy_agent.py suggest-children animaux --count 5
  python scripts/taxonomy_agent.py generate-vocabulary --theme sports --root-count 5
  python scripts/taxonomy_agent.py enrich-keywords animaux --min-kw 8 --max-kw 20
  python scripts/taxonomy_agent.py status

Flags communs :
  --vocabulary-id : vocabulaire cible (défaut : themes)
  --model         : modèle Ollama (défaut : qwen3:8b ou OLLAMA_MODEL)
  --temperature   : température (défaut selon le template YAML)
  --dry-run       : affiche les suggestions sans les appliquer
  --apply         : applique directement les suggestions sans confirmation
  --api-base      : URL de l'API FastAPI (défaut : http://localhost:8000)
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Optional

import httpx
import typer
from rich import print as rprint
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

app = typer.Typer(
    name="taxonomy-agent",
    help="Enrichissement de la taxonomie via la file de jobs (Qwen3:8B).",
    add_completion=False,
)
console = Console()

DEFAULT_API_BASE = "http://localhost:8000"
SUGGESTIONS_FILE = Path(__file__).resolve().parents[1] / "data" / "ai_suggestions.json"

_TERMINAL_DONE = {"awaiting_validation", "completed", "applied", "rejected"}
_TERMINAL_ERR = {"failed", "cancelled"}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _enable_job_type(api_base: str, job_type: str) -> None:
    """Active le type de job si nécessaire (idempotent)."""
    url = f"{api_base.rstrip('/')}/api/jobs/types/{job_type}"
    try:
        res = httpx.put(url, json={"enabled": True}, timeout=10.0)
        if res.is_error:
            rprint(f"[yellow]⚠ Impossible d'activer le type {job_type}: HTTP {res.status_code}[/yellow]")
    except Exception as e:
        rprint(f"[yellow]⚠ Enable job type {job_type}: {e}[/yellow]")


def _enqueue_and_poll(
    api_base: str,
    job_type: str,
    config: dict,
    *,
    poll_interval: float = 3.0,
    timeout: float = 180.0,
) -> dict:
    """Enfile un job, attend sa completion et retourne le résultat (proposal ou artefact).

    Lève typer.Exit en cas d'erreur.
    """
    _enable_job_type(api_base, job_type)

    url_enqueue = f"{api_base.rstrip('/')}/api/jobs/enqueue"
    try:
        res = httpx.post(url_enqueue, json={"type": job_type, "config": config}, timeout=30.0)
    except httpx.ConnectError:
        rprint(f"[red]✗ API non disponible sur {api_base}.[/red]")
        raise typer.Exit(code=1)
    if res.status_code == 400:
        detail = res.json().get("detail", res.text)
        rprint(f"[red]✗ Enqueue échoué : {detail}[/red]")
        raise typer.Exit(code=1)
    if res.is_error:
        rprint(f"[red]✗ Enqueue HTTP {res.status_code} : {res.text[:300]}[/red]")
        raise typer.Exit(code=1)
    enq = res.json()
    job_id = enq.get("id") or enq.get("job_id") or ""
    if not job_id:
        rprint("[red]✗ Réponse enqueue sans job_id.[/red]")
        raise typer.Exit(code=1)

    rprint(f"  [dim]→ job_id={job_id} (type={job_type}, polling…)[/dim]")

    url_list = f"{api_base.rstrip('/')}/api/jobs"
    started = time.time()
    while True:
        elapsed = time.time() - started
        if elapsed > timeout:
            rprint(f"[red]✗ Timeout : job {job_id} non terminé après {timeout:.0f}s.[/red]")
            raise typer.Exit(code=1)
        time.sleep(poll_interval)
        try:
            resp = httpx.get(url_list, params={"page_size": 100, "sort": "created_at", "order": "desc"}, timeout=15.0)
        except httpx.HTTPError as e:
            if elapsed < timeout - poll_interval:
                continue
            rprint(f"[red]✗ Erreur réseau polling : {e}[/red]")
            raise typer.Exit(code=1)
        if resp.is_error:
            continue
        try:
            data = resp.json()
        except Exception:
            continue
        jobs = data.get("jobs") or []
        job = next((j for j in jobs if j.get("id") == job_id), None)
        if job is None:
            continue
        status = job.get("status", "")
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
            rprint(f"[red]✗ Job {job_id} échoué (status={status}) : {job.get('error_message', '')}[/red]")
            raise typer.Exit(code=1)


def _call_api(
    api_base: str,
    endpoint: str,
    payload: dict,
    timeout: int = 90,
) -> dict:
    """[Legacy / mode sync] Appelle l'API FastAPI /api/ai/* et retourne la réponse JSON.

    Utilisé uniquement si AI_ROUTES_MODE=sync est actif. En mode async (défaut),
    les routes renvoient HTTP 202 et ce helper ne fonctionne plus directement.
    Préférez _enqueue_and_poll() pour toutes les nouvelles opérations.
    """
    url = f"{api_base.rstrip('/')}{endpoint}"
    try:
        res = httpx.post(url, json=payload, timeout=float(timeout))
        if res.status_code == 503:
            rprint("[red]✗ Ollama non disponible.[/red] Vérifiez qu'Ollama est démarré (`ollama serve`).")
            raise typer.Exit(code=1)
        if res.status_code == 404:
            rprint("[red]✗ Terme non trouvé (404).[/red]")
            raise typer.Exit(code=1)
        if res.status_code == 202:
            data = res.json()
            job_id = data.get("job_id") or data.get("id") or ""
            if job_id:
                # Mode async : basculer sur le polling
                return _enqueue_and_poll.__wrapped__ if hasattr(_enqueue_and_poll, "__wrapped__") else {}
        res.raise_for_status()
        return res.json()
    except httpx.ConnectError:
        rprint(f"[red]✗ API FastAPI non disponible sur {api_base}.[/red] Lancez le serveur : uvicorn src.api.main:app --reload")
        raise typer.Exit(code=1)
    except httpx.HTTPStatusError as exc:
        rprint(f"[red]✗ Erreur HTTP {exc.response.status_code} :[/red] {exc.response.text[:300]}")
        raise typer.Exit(code=1)


def _confirm_or_apply(data: dict, apply: bool, dry_run: bool, description: str) -> bool:
    """Demande confirmation si ni --apply ni --dry-run. Retourne True si on doit appliquer."""
    if dry_run:
        return False
    if apply:
        return True
    return typer.confirm(f"\nAppliquer {description} ?", default=True)


def _save_to_staging(suggestions_data: dict, label: str) -> None:
    """Sauvegarde les suggestions dans data/ai_suggestions.json pour revue ultérieure."""
    existing = []
    if SUGGESTIONS_FILE.exists():
        try:
            existing = json.loads(SUGGESTIONS_FILE.read_text(encoding="utf-8"))
            if not isinstance(existing, list):
                existing = []
        except (json.JSONDecodeError, OSError):
            existing = []
    existing.append({"label": label, "data": suggestions_data})
    SUGGESTIONS_FILE.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    rprint(f"[dim]→ Suggestions sauvegardées dans {SUGGESTIONS_FILE}[/dim]")


def _apply_term_update(api_base: str, vocabulary_id: str, term_id: str, fields: dict) -> None:
    """Applique une mise à jour partielle d'un terme via PUT /api/taxonomy."""
    get_url = f"{api_base.rstrip('/')}/api/taxonomy/vocabularies/{vocabulary_id}/terms/{term_id}"
    try:
        res = httpx.get(get_url, timeout=10.0)
        res.raise_for_status()
        current = res.json()
    except Exception as exc:
        rprint(f"[red]✗ Impossible de récupérer le terme {term_id} : {exc}[/red]")
        return

    updated = {**current, **fields}
    put_url = f"{api_base.rstrip('/')}/api/taxonomy/vocabularies/{vocabulary_id}/terms/{term_id}"
    try:
        res = httpx.put(put_url, json=updated, timeout=10.0)
        res.raise_for_status()
        rprint(f"  [green]✓[/green] Terme [bold]{term_id}[/bold] mis à jour ({', '.join(fields.keys())})")
    except Exception as exc:
        rprint(f"  [red]✗ PUT {term_id} : {exc}[/red]")


def _apply_post_term(api_base: str, vocabulary_id: str, term: dict) -> None:
    """Crée un nouveau terme via POST /api/taxonomy."""
    post_url = f"{api_base.rstrip('/')}/api/taxonomy/vocabularies/{vocabulary_id}/terms"
    try:
        res = httpx.post(post_url, json=term, timeout=10.0)
        res.raise_for_status()
        rprint(f"  [green]✓[/green] Terme créé : [bold]{term.get('id')}[/bold] — {term.get('name_fr', '')}")
    except Exception as exc:
        rprint(f"  [red]✗ POST {term.get('id')} : {exc}[/red]")


# ─── Commandes ────────────────────────────────────────────────────────────────

@app.command("status")
def cmd_status(
    api_base: str = typer.Option(DEFAULT_API_BASE, "--api-base", help="URL de l'API FastAPI"),
) -> None:
    """Vérifie la disponibilité d'Ollama et de l'API FastAPI."""
    try:
        res = httpx.get(f"{api_base.rstrip('/')}/api/ai/status", timeout=5.0)
        data = res.json()
        if data.get("available"):
            rprint(f"[green]✓ Ollama disponible[/green] sur {data['base_url']}")
            rprint(f"  Modèle configuré : [bold]{data['configured_model']}[/bold]")
            models = data.get("models", [])
            if models:
                rprint(f"  Modèles installés : {', '.join(models)}")
        else:
            rprint(f"[yellow]⚠ Ollama non disponible[/yellow] : {data.get('error')}")
            rprint(f"  URL testée : {data['base_url']}")
    except httpx.ConnectError:
        rprint(f"[red]✗ API FastAPI non disponible sur {api_base}[/red]")
        raise typer.Exit(code=1)


@app.command("enrich-term")
def cmd_enrich_term(
    term_id: str = typer.Argument(..., help="ID du terme à enrichir"),
    vocabulary_id: str = typer.Option("themes", "--vocabulary-id", "-v", help="ID du vocabulaire"),
    fields: str = typer.Option("", "--fields", "-f", help="Champs à générer séparés par virgule (vide = tous les champs vides)"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Modèle Ollama"),
    temperature: Optional[float] = typer.Option(None, "--temperature", "-t", help="Température (0.0–1.0)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Affiche les suggestions sans appliquer"),
    apply: bool = typer.Option(False, "--apply", help="Applique sans confirmation"),
    api_base: str = typer.Option(DEFAULT_API_BASE, "--api-base", help="URL de l'API"),
) -> None:
    """Enrichit les champs manquants d'un terme via Ollama."""
    fields_list = [f.strip() for f in fields.split(",") if f.strip()] if fields else []

    rprint(f"\n[bold blue]Enrichissement du terme[/bold blue] [bold]{term_id}[/bold] (vocabulaire: {vocabulary_id})")
    if fields_list:
        rprint(f"  Champs demandés : {', '.join(fields_list)}")
    else:
        rprint("  Champs : détection automatique des champs vides")

    config: dict = {
        "term_id": term_id,
        "vocabulary_id": vocabulary_id,
        "fields": fields_list,
    }
    if model:
        config["model"] = model
    if temperature is not None:
        config["temperature"] = temperature
    with console.status("Enqueue + poll job taxonomy_enrich_term…"):
        result = _enqueue_and_poll(api_base, "taxonomy_enrich_term", config)

    # Le résultat peut être une proposal directe (champs textuels) ou {suggestions: {...}}
    suggestions = result.get("suggestions") or {k: v for k, v in result.items() if k not in ("model", "temperature", "raw_response", "fields_requested", "term_id", "vocabulary_id", "skipped", "message", "status")}
    if not suggestions:
        rprint(f"[yellow]Aucune suggestion générée.[/yellow] {result.get('message', '')}")
        return

    rprint(f"\n[bold green]Suggestions :[/bold green]")
    table = Table(show_header=True, header_style="bold")
    table.add_column("Champ", style="cyan", width=20)
    table.add_column("Valeur suggérée")
    for field, value in suggestions.items():
        table.add_row(field, str(value)[:100])
    console.print(table)

    _save_to_staging(result, f"enrich-term:{term_id}")

    if _confirm_or_apply(result, apply, dry_run, f"les {len(suggestions)} champ(s) au terme {term_id}"):
        rprint("\nApplication…")
        _apply_term_update(api_base, vocabulary_id, term_id, suggestions)


@app.command("suggest-children")
def cmd_suggest_children(
    term_id: str = typer.Argument(..., help="ID du terme parent"),
    vocabulary_id: str = typer.Option("themes", "--vocabulary-id", "-v", help="ID du vocabulaire"),
    count: int = typer.Option(5, "--count", "-n", help="Nombre de sous-termes à suggérer"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Modèle Ollama"),
    temperature: Optional[float] = typer.Option(None, "--temperature", "-t", help="Température"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Affiche sans appliquer"),
    apply: bool = typer.Option(False, "--apply", help="Applique sans confirmation"),
    api_base: str = typer.Option(DEFAULT_API_BASE, "--api-base", help="URL de l'API"),
) -> None:
    """Suggère de nouveaux termes enfants pour un terme parent via Ollama."""
    rprint(f"\n[bold blue]Suggestions d'enfants pour[/bold blue] [bold]{term_id}[/bold] (x{count})")

    sc_config: dict = {"term_id": term_id, "vocabulary_id": vocabulary_id, "count": count}
    if model:
        sc_config["model"] = model
    if temperature is not None:
        sc_config["temperature"] = temperature
    with console.status("Enqueue + poll job taxonomy_suggest_children…"):
        result = _enqueue_and_poll(api_base, "taxonomy_suggest_children", sc_config)

    # Le résultat peut être une liste d'operations (artefact v1) ou {suggestions: [...]}
    operations = result.get("operations") or []
    suggestions_raw = result.get("suggestions") or []
    if operations:
        suggestions_raw = [op.get("value") for op in operations if isinstance(op, dict) and op.get("op") == "add"]
    if not suggestions_raw:
        rprint("[yellow]Aucune suggestion générée.[/yellow]")
        return

    rprint(f"\n[bold green]{len(suggestions_raw)} termes enfants suggérés :[/bold green]")
    table = Table(show_header=True, header_style="bold")
    table.add_column("ID", style="cyan", width=25)
    table.add_column("FR", width=22)
    table.add_column("EN", width=22)
    table.add_column("AR", width=20)
    for child in suggestions_raw:
        if not isinstance(child, dict):
            continue
        table.add_row(
            child.get("id", ""), child.get("name_fr", ""),
            child.get("name_en", ""), child.get("name_ar", ""),
        )
    console.print(table)

    _save_to_staging(result, f"suggest-children:{term_id}")

    if _confirm_or_apply(result, apply, dry_run, f"{len(suggestions_raw)} terme(s) enfant(s)"):
        rprint("\nCréation des termes…")
        for child in suggestions_raw:
            if isinstance(child, dict):
                _apply_post_term(api_base, vocabulary_id, child)


@app.command("generate-vocabulary")
def cmd_generate_vocabulary(
    theme: str = typer.Option(..., "--theme", help="Thème du vocabulaire (ex: sports, nature, fêtes)"),
    root_count: int = typer.Option(5, "--root-count", help="Nombre de termes racines"),
    children_per_root: int = typer.Option(3, "--children-per-root", help="Nombre d'enfants par racine"),
    vocabulary_id: str = typer.Option("themes", "--vocabulary-id", "-v", help="Vocabulaire cible pour l'application"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Modèle Ollama"),
    temperature: Optional[float] = typer.Option(None, "--temperature", "-t", help="Température"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Affiche sans appliquer"),
    apply: bool = typer.Option(False, "--apply", help="Applique sans confirmation"),
    api_base: str = typer.Option(DEFAULT_API_BASE, "--api-base", help="URL de l'API"),
) -> None:
    """Génère un ensemble de termes racines (avec enfants) pour un thème donné."""
    rprint(f"\n[bold blue]Génération de vocabulaire[/bold blue] — thème : [bold]{theme}[/bold] "
           f"({root_count} racines × {children_per_root} enfants)")

    gv_config: dict = {
        "theme": theme,
        "root_count": root_count,
        "children_per_root": children_per_root,
        "target_vocabulary_id": vocabulary_id,
    }
    if model:
        gv_config["model"] = model
    if temperature is not None:
        gv_config["temperature"] = temperature
    with console.status("Enqueue + poll job taxonomy_generate_vocabulary…"):
        result = _enqueue_and_poll(api_base, "taxonomy_generate_vocabulary", gv_config, timeout=300.0)

    # Le résultat peut venir de l'artefact (proposal.operations) ou du dict brut
    operations = result.get("operations") or result.get("suggestions_flat") or result.get("suggestions") or []
    root_terms = [op.get("value") for op in operations if isinstance(op, dict) and op.get("op") == "add" and not (op.get("value") or {}).get("parent_id")]
    if not root_terms and not operations:
        rprint("[yellow]Aucune suggestion générée.[/yellow]")
        return

    total = len(operations)
    rprint(f"\n[bold green]{total} terme(s) générés ({len(root_terms)} racine(s)) :[/bold green]")
    for op in operations[:20]:
        v = op.get("value") or {}
        indent = "  " if v.get("parent_id") else ""
        prefix = "└─ " if v.get("parent_id") else ""
        rprint(f"  {indent}[cyan]{prefix}{v.get('id', '')}[/cyan] — {v.get('name_fr', '')} / {v.get('name_en', '')}")
    if total > 20:
        rprint(f"  ... ({total - 20} termes supplémentaires)")

    _save_to_staging(result, f"generate-vocabulary:{theme}")

    if _confirm_or_apply(result, apply, dry_run, f"{total} terme(s) dans '{vocabulary_id}'"):
        rprint("\nCréation des termes…")
        for op in operations:
            v = op.get("value") if isinstance(op, dict) else op
            if isinstance(v, dict):
                _apply_post_term(api_base, vocabulary_id, v)


@app.command("enrich-keywords")
def cmd_enrich_keywords(
    term_id: str = typer.Argument(..., help="ID du terme à enrichir"),
    vocabulary_id: str = typer.Option("themes", "--vocabulary-id", "-v", help="ID du vocabulaire"),
    min_kw: int = typer.Option(5, "--min-kw", help="Nombre minimum de mots-clés"),
    max_kw: int = typer.Option(15, "--max-kw", help="Nombre maximum de mots-clés"),
    merge: bool = typer.Option(True, "--merge/--replace", help="Fusionner avec les mots-clés existants"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Modèle Ollama"),
    temperature: Optional[float] = typer.Option(None, "--temperature", "-t", help="Température"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Affiche sans appliquer"),
    apply: bool = typer.Option(False, "--apply", help="Applique sans confirmation"),
    api_base: str = typer.Option(DEFAULT_API_BASE, "--api-base", help="URL de l'API"),
) -> None:
    """Génère des mots-clés SEO multilingues pour un terme via Ollama."""
    rprint(f"\n[bold blue]Enrichissement keywords[/bold blue] — terme : [bold]{term_id}[/bold]")

    ek_config: dict = {
        "term_id": term_id,
        "vocabulary_id": vocabulary_id,
        "min_keywords": min_kw,
        "max_keywords": max_kw,
    }
    if model:
        ek_config["model"] = model
    if temperature is not None:
        ek_config["temperature"] = temperature
    with console.status("Enqueue + poll job taxonomy_enrich_keywords…"):
        result = _enqueue_and_poll(api_base, "taxonomy_enrich_keywords", ek_config)

    # Le résultat peut être une proposal {keywords: "..."} ou une liste directe
    kw_raw = result.get("keywords") or result.get("suggestions_keywords") or result.get("suggestions") or []
    if isinstance(kw_raw, str):
        kw_raw = [k.strip() for k in kw_raw.split(",") if k.strip()]
    existing = result.get("existing_keywords", [])
    suggestions = kw_raw if isinstance(kw_raw, list) else []

    if not suggestions:
        rprint("[yellow]Aucun mot-clé généré.[/yellow]")
        return

    rprint(f"\n[bold green]{len(suggestions)} mots-clés suggérés[/bold green] :")
    rprint("  " + " · ".join(f"[cyan]{k}[/cyan]" for k in suggestions))

    if existing:
        rprint(f"\n  Existants ({len(existing)}) : {', '.join(existing)}")

    final_keywords = list(dict.fromkeys(existing + suggestions)) if merge else suggestions
    rprint(f"\n  Total après fusion : [bold]{len(final_keywords)}[/bold] mots-clés")

    _save_to_staging(result, f"enrich-keywords:{term_id}")

    if _confirm_or_apply(result, apply, dry_run, f"les {len(final_keywords)} mots-clés au terme {term_id}"):
        rprint("\nApplication…")
        _apply_term_update(api_base, vocabulary_id, term_id, {"keywords": final_keywords})


if __name__ == "__main__":
    app()
