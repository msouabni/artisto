"""POC MEP-v0/B — Batch i18n des leaves publishable.

Génère pour chaque leaf publishable (annotations.flags.publishable=true sur les
dirs POC) trois versions linguistiques (FR/EN/AR) du `title` et `description`,
validées par les SOFT caps actées 2026-05-05 :

- title_fr_en        : [40, 60] chars
- title_ar           : [25, 55] chars
- description_fr_en  : [80, 130] chars
- description_ar     : [40, 115] chars

Pipeline par leaf :
1. Récupère ``name_en``/``name_fr``/``name_ar`` depuis
   ``data/prompt_generator/coloring_taxonomy_full.json``.
2. Appelle ``services.content_generator.generate_content`` (qwen3.5:4b par défaut).
3. Validate les SOFT caps. Si dépassement borne haute → retry (max 3 essais).
4. Strip harakat post-process sur les outputs AR (regex codepoints explicites).
5. Checkpoint atomique après chaque leaf (tempfile + rename).

Mode ``--resume`` reprend depuis le checkpoint.
Mode ``--dry-run`` liste les leaves cibles sans appel Ollama.

Output principal : ``data/export/_i18n_batch.json``.
Checkpoint        : ``data/export/_i18n_batch_progress.json``.

Convention rapport : voir ``CLAUDE.md`` §Reporting convention.

Note technique — bug import contourné en surface :
    ``services.content_generator`` importe ``HARAKAT_RE`` et ``strip_harakat``
    depuis ``services.ollama_json`` mais ces symboles n'y existent pas (voir
    ``docs/architect/MEMORY.md``). Pour ne pas patcher hors-scope (brief
    MEP-v0/B interdit ``content_generator.py`` et ``ollama_json.py``), ce
    script injecte les deux symboles dans le module ``services.ollama_json``
    AVANT que ``content_generator`` soit importé. C'est un shim run-time,
    pas une modification de fichier. À nettoyer par un brief séparé.

Note technique — patch ``think: false`` natif (2026-05-10) :
    ``services.ollama_json.call_ollama_sync`` ne propage pas le paramètre natif
    Ollama ``"think": false`` dans le payload, ce qui faisait timeout
    ``qwen3.5:4b`` (modèle thinking-by-default) — le modèle consommait tous ses
    tokens en thinking et renvoyait ``response: ""``. Pour rester hors-scope
    (zone gelée), ce script monkey-patch ``call_ollama_sync`` avec un wrapper
    qui injecte ``"think": false`` au niveau ``httpx.post`` pour les modèles
    ``qwen3.X`` (X ≥ 3, ie. ``qwen3.5``, ``qwen3.6``, …). Pour les modèles
    ``qwen3:`` strict (sans ``.``), le tag ``/no_think`` est déjà injecté côté
    ``apply_no_think_system`` (pas de re-injection ici).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ─── Setup paths ─────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# ─── Shim ``services.ollama_json`` AVANT d'importer content_generator ───────
# Codepoints explicites — RTL trap résolu (cf. CLAUDE.md §Routing LLM).
HARAKAT_RE = re.compile("[ؐ-ًؚ-ٟ]")


def strip_harakat(text: str) -> str:
    """Retire tous les harakat (signes diacritiques arabes) d'une chaîne."""
    if not text:
        return text
    return HARAKAT_RE.sub("", text)


def _ensure_ollama_json_shim() -> None:
    """Injecte HARAKAT_RE et strip_harakat dans services.ollama_json.

    Cela permet à ``content_generator`` de s'importer sans erreur sans modifier
    le fichier source (gelé par le brief MEP-v0/B).
    """
    import services.ollama_json as oj

    if not hasattr(oj, "HARAKAT_RE"):
        oj.HARAKAT_RE = HARAKAT_RE
    if not hasattr(oj, "strip_harakat"):
        oj.strip_harakat = strip_harakat


_ensure_ollama_json_shim()


# ─── Helpers think: false (patch 2026-05-10) ────────────────────────────────
def _supports_native_think_disable(model: str | None) -> bool:
    """True si le modèle supporte le paramètre natif Ollama ``"think": false``.

    Cible : ``qwen3.X`` avec X >= 3 (qwen3.5, qwen3.6, …).
    Exclut : ``qwen3:8b``, ``qwen3:4b`` (qwen3 strict — utiliser ``/no_think``).
    """
    name = (model or "").lower()
    return name.startswith("qwen3.")


def _is_qwen3_strict(model: str | None) -> bool:
    """True si le modèle est ``qwen3:`` strict (qwen3:8b, qwen3:4b, etc.).

    Ces modèles ne supportent pas le param natif ``"think": false`` ; le tag
    ``/no_think`` doit être injecté dans le system prompt (déjà fait par
    ``apply_no_think_system`` dans ``services.ollama_json``).
    """
    name = (model or "").lower()
    return name.startswith("qwen3:")


def _patch_ollama_call_for_native_think_disable() -> None:
    """Wrap ``services.ollama_json.call_ollama_sync`` pour injecter ``"think": false``.

    Le wrapper ré-implémente la même logique que l'original mais ajoute
    ``"think": false`` au payload Ollama pour les modèles ``qwen3.X``. Les
    autres branches (qwen3 strict via ``/no_think``) sont laissées intactes.

    NB : on ne modifie PAS le module source ``services/ollama_json.py``
    (zone gelée par le brief). Ce wrapper est un shim runtime.
    """
    import httpx

    import services.ollama_json as oj

    original = oj.call_ollama_sync

    def patched_call_ollama_sync(
        prompt: str,
        system: str = "",
        model: str | None = None,
        temperature: float = 0.3,
        timeout: int | None = None,
    ) -> str:
        m = model or oj.OLLAMA_MODEL
        # Pas de patch nécessaire si le modèle ne supporte pas le param natif
        # → on laisse l'original gérer (apply_no_think_system pour qwen3 strict).
        if not _supports_native_think_disable(m):
            return original(
                prompt,
                system=system,
                model=model,
                temperature=temperature,
                timeout=timeout,
            )

        # Reconstruction du payload avec "think": false injecté (logique
        # alignée sur ``oj.call_ollama_sync`` ligne par ligne pour rester
        # iso-fonctionnel hors injection).
        url = f"{oj.OLLAMA_BASE_URL}/api/generate"
        sys_p = oj.apply_no_think_system(m, system)  # no-op pour qwen3.X
        payload = {
            "model": m,
            "prompt": prompt,
            "system": sys_p,
            "stream": False,
            "think": False,  # ← patch natif qwen3.X (2026-05-10)
            "options": {"temperature": temperature},
        }
        eff_timeout = float(timeout or oj.OLLAMA_TIMEOUT)
        try:
            with httpx.Client(timeout=eff_timeout) as client:
                res = client.post(url, json=payload)
                res.raise_for_status()
                data = res.json()
                if "error" in data and "response" not in data:
                    raise RuntimeError(f"Ollama erreur modele : {data['error']}")
                return data.get("response", "")
        except httpx.TimeoutException as exc:
            logger.warning(
                "Ollama timeout (sync, patched think=false) model=%s timeout=%ss url=%s prompt_chars=%d",
                m,
                eff_timeout,
                url,
                len(prompt),
            )
            raise RuntimeError(
                f"Ollama timeout apres {eff_timeout}s sur {m}"
            ) from exc

    # Marquer pour pouvoir détecter le patch (utile aux tests)
    patched_call_ollama_sync._patched_for_native_think_disable = True  # type: ignore[attr-defined]
    oj.call_ollama_sync = patched_call_ollama_sync


_patch_ollama_call_for_native_think_disable()

# Maintenant content_generator peut s'importer
from services import content_generator as cg  # noqa: E402

# ─── Constants ───────────────────────────────────────────────────────────────
DEFAULT_TAXONOMY = PROJECT_ROOT / "data" / "prompt_generator" / "coloring_taxonomy_full.json"
DEFAULT_ANNOTATIONS_GLOB = "docs/reports/poc-*/annotations.json"
DEFAULT_OUT = PROJECT_ROOT / "data" / "export" / "_i18n_batch.json"
DEFAULT_CHECKPOINT = PROJECT_ROOT / "data" / "export" / "_i18n_batch_progress.json"

SCHEMA_VERSION = 1

SOFT_CAPS = {
    "title_fr_en": (40, 60),
    "title_ar": (25, 55),
    "description_fr_en": (80, 130),
    "description_ar": (40, 115),
}

MAX_RETRIES = 3
RETRY_DELAYS_S = [60, 300, 900]  # Pour erreurs Ollama dures
DEFAULT_MODEL = "qwen3.5:4b"

logger = logging.getLogger(__name__)


# ─── Data discovery ──────────────────────────────────────────────────────────
def collect_taxonomy_leaves(taxonomy_path: Path) -> dict[str, dict]:
    """Charge la taxonomie et retourne un dict ``leaf_id -> node`` pour les feuilles."""
    with taxonomy_path.open(encoding="utf-8") as f:
        tax = json.load(f)

    leaves: dict[str, dict] = {}

    def walk(node: dict) -> None:
        children = node.get("children") or []
        if not children:
            lid = node.get("id")
            if lid:
                leaves[lid] = node
        else:
            for ch in children:
                walk(ch)

    if isinstance(tax, list):
        for n in tax:
            walk(n)
    elif isinstance(tax, dict):
        if "categories" in tax:
            for n in tax["categories"]:
                walk(n)
        else:
            walk(tax)
    return leaves


def collect_publishable_leaves(
    annotations_glob: str, taxonomy_leaves: dict[str, dict]
) -> tuple[list[str], list[str]]:
    """Parcourt les ``annotations.json`` et retourne (leaves_matchées, filenames_orphelins).

    Filtre ``flags.publishable=true``. Matching: longest prefix sur ``leaf_id`` de
    la taxonomie. Les filenames orphelins (concepts non présents dans la
    taxonomie) sont retournés à part pour reporting.
    """
    import glob

    leaf_ids_sorted = sorted(taxonomy_leaves.keys(), key=len, reverse=True)

    matched: set[str] = set()
    orphan_filenames: list[str] = []
    files = sorted(glob.glob(annotations_glob))
    for path in files:
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to load %s", path)
            continue

        annotations = data.get("annotations", {})
        if not isinstance(annotations, dict):
            continue

        for fname, entry in annotations.items():
            if not isinstance(entry, dict):
                continue
            flags = entry.get("flags") or {}
            if not flags.get("publishable"):
                continue

            stem = fname.rsplit(".", 1)[0]
            found = None
            for lid in leaf_ids_sorted:
                if stem.startswith(lid + "_") or stem == lid:
                    found = lid
                    break
            if found:
                matched.add(found)
            else:
                orphan_filenames.append(fname)

    return (sorted(matched), orphan_filenames)


# ─── Validation ──────────────────────────────────────────────────────────────
@dataclass
class FieldViolation:
    field: str
    value_len: int
    expected_min: int
    expected_max: int
    kind: str  # "too_short" | "too_long"


def check_soft_caps(
    title_en: str,
    title_fr: str,
    title_ar: str,
    desc_en: str,
    desc_fr: str,
    desc_ar: str,
) -> list[FieldViolation]:
    """Retourne la liste des violations SOFT caps."""
    out: list[FieldViolation] = []
    tmin_fe, tmax_fe = SOFT_CAPS["title_fr_en"]
    tmin_ar, tmax_ar = SOFT_CAPS["title_ar"]
    dmin_fe, dmax_fe = SOFT_CAPS["description_fr_en"]
    dmin_ar, dmax_ar = SOFT_CAPS["description_ar"]

    def _check(field: str, value: str, lo: int, hi: int) -> None:
        n = len(value or "")
        if n < lo:
            out.append(FieldViolation(field, n, lo, hi, "too_short"))
        elif n > hi:
            out.append(FieldViolation(field, n, lo, hi, "too_long"))

    _check("title_en", title_en, tmin_fe, tmax_fe)
    _check("title_fr", title_fr, tmin_fe, tmax_fe)
    _check("title_ar", title_ar, tmin_ar, tmax_ar)
    _check("description_en", desc_en, dmin_fe, dmax_fe)
    _check("description_fr", desc_fr, dmin_fe, dmax_fe)
    _check("description_ar", desc_ar, dmin_ar, dmax_ar)
    return out


def has_too_long(violations: list[FieldViolation]) -> bool:
    """Au moins une violation de borne haute → regen utile (le LLM doit raccourcir)."""
    return any(v.kind == "too_long" for v in violations)


# ─── Atomic write ────────────────────────────────────────────────────────────
def atomic_write_json(path: Path, payload: dict) -> None:
    """Écrit ``payload`` dans ``path`` de manière atomique via tempfile + os.replace.

    fsync + replace garantissent qu'on ne se retrouve jamais avec un fichier
    JSON corrompu après SIGINT/SIGKILL.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ─── Generation per leaf ─────────────────────────────────────────────────────
@dataclass
class LeafResult:
    leaf_id: str
    name_en: str
    name_fr: str
    name_ar: str
    title_en: str = ""
    title_fr: str = ""
    title_ar: str = ""
    description_en: str = ""
    description_fr: str = ""
    description_ar: str = ""
    title_card_en: str = ""
    title_card_fr: str = ""
    title_card_ar: str = ""
    keywords_en: list[str] | None = None
    keywords_fr: list[str] | None = None
    keywords_ar: list[str] | None = None
    status: str = "pending"  # ok | failed | soft_caps_violated
    generation_attempts: dict[str, int] | None = None
    soft_cap_violations: list[dict] | None = None
    review_flags: list[str] | None = None
    error: str | None = None
    latency_ms: int = 0

    def to_dict(self) -> dict:
        return {
            "leaf_id": self.leaf_id,
            "name_en": self.name_en,
            "name_fr": self.name_fr,
            "name_ar": self.name_ar,
            "title_en": self.title_en,
            "title_fr": self.title_fr,
            "title_ar": self.title_ar,
            "title_card_en": self.title_card_en,
            "title_card_fr": self.title_card_fr,
            "title_card_ar": self.title_card_ar,
            "description_en": self.description_en,
            "description_fr": self.description_fr,
            "description_ar": self.description_ar,
            "keywords_en": self.keywords_en or [],
            "keywords_fr": self.keywords_fr or [],
            "keywords_ar": self.keywords_ar or [],
            "status": self.status,
            "generation_attempts": self.generation_attempts or {},
            "soft_cap_violations": self.soft_cap_violations or [],
            "review_flags": self.review_flags or [],
            "error": self.error,
            "latency_ms": self.latency_ms,
        }


def generate_leaf(
    leaf_id: str,
    name_en: str,
    name_fr: str,
    name_ar: str,
    model: str = DEFAULT_MODEL,
    max_retries: int = MAX_RETRIES,
) -> LeafResult:
    """Génère un leaf, avec retry sur dépassement borne haute SOFT caps.

    Stratégie :
    - Appelle ``content_generator.generate_content`` (qui fait déjà 3 retries
      AR en interne pour les bornes / latin).
    - Si la longueur des champs (titre/description) dépasse la borne haute SOFT
      sur EN/FR/AR, on relance jusqu'à ``max_retries`` fois la génération
      complète (parce que content_generator ne fait pas de regen sur EN/FR
      isolément).
    - On rejette uniquement sur les SOFT caps (cf. CLAUDE.md §Validation).
    - Erreurs Ollama hard (timeout/HTTP error) : backoff `RETRY_DELAYS_S`.
    """
    result = LeafResult(
        leaf_id=leaf_id,
        name_en=name_en,
        name_fr=name_fr,
        name_ar=name_ar,
        generation_attempts={"content_generator": 0, "regen_for_caps": 0},
    )

    t0 = time.time()

    last_violations: list[FieldViolation] = []
    last_content = None
    review_flags: list[str] = []

    for attempt in range(max_retries):
        result.generation_attempts["content_generator"] += 1
        try:
            content = cg.generate_content(
                concept_name_en=name_en,
                concept_name_fr=name_fr,
                term_name_ar=name_ar,
                model=model,
            )
        except RuntimeError as exc:
            # Erreur Ollama dure : backoff puis retry
            msg = str(exc)
            logger.warning("Ollama error on %s attempt=%d: %s", leaf_id, attempt + 1, msg)
            if attempt < max_retries - 1:
                delay = RETRY_DELAYS_S[min(attempt, len(RETRY_DELAYS_S) - 1)]
                logger.info("Backing off %ds before retry…", delay)
                time.sleep(delay)
                continue
            result.status = "failed"
            result.error = f"ollama_error: {msg}"
            result.latency_ms = int((time.time() - t0) * 1000)
            return result
        except Exception as exc:  # noqa: BLE001
            result.status = "failed"
            result.error = f"unexpected_error: {type(exc).__name__}: {exc}"
            result.latency_ms = int((time.time() - t0) * 1000)
            return result

        last_content = content
        review_flags = list(content.review_flags or [])

        # Strip harakat redondant côté script (content_generator le fait déjà mais
        # on le ré-applique en filet de sécurité) — voir CLAUDE.md.
        ar_title = strip_harakat(content.ar.title)
        ar_card = strip_harakat(content.ar.title_card)
        ar_desc = strip_harakat(content.ar.description)
        ar_kw = [strip_harakat(k) for k in (content.ar.keywords or [])]

        violations = check_soft_caps(
            title_en=content.en.title,
            title_fr=content.fr.title,
            title_ar=ar_title,
            desc_en=content.en.description,
            desc_fr=content.fr.description,
            desc_ar=ar_desc,
        )
        last_violations = violations

        # On stocke le dernier essai
        result.title_en = content.en.title
        result.title_fr = content.fr.title
        result.title_ar = ar_title
        result.title_card_en = content.en.title_card
        result.title_card_fr = content.fr.title_card
        result.title_card_ar = ar_card
        result.description_en = content.en.description
        result.description_fr = content.fr.description
        result.description_ar = ar_desc
        result.keywords_en = list(content.en.keywords or [])
        result.keywords_fr = list(content.fr.keywords or [])
        result.keywords_ar = ar_kw

        if not violations:
            # Tout SOFT cap respecté
            result.status = "ok"
            break

        # Si seules les bornes basses sont violées on garde (trop court → moins
        # bloquant — on accepte mais on flag).
        if not has_too_long(violations):
            result.status = "soft_caps_violated"
            break

        # Sinon (au moins une borne haute violée) : relance
        result.generation_attempts["regen_for_caps"] += 1
        if attempt < max_retries - 1:
            logger.info(
                "Soft cap too_long on %s — retry %d/%d (violations=%d)",
                leaf_id,
                attempt + 2,
                max_retries,
                len(violations),
            )
        else:
            result.status = "soft_caps_violated"

    # Sérialiser les violations finales
    result.soft_cap_violations = [
        {
            "field": v.field,
            "len": v.value_len,
            "expected_min": v.expected_min,
            "expected_max": v.expected_max,
            "kind": v.kind,
        }
        for v in last_violations
    ]
    if last_content is not None:
        result.review_flags = review_flags
        result.latency_ms = last_content.latency_ms
    else:
        result.latency_ms = int((time.time() - t0) * 1000)
    return result


# ─── Checkpoint & resume ─────────────────────────────────────────────────────
def load_checkpoint(checkpoint_path: Path) -> dict | None:
    if not checkpoint_path.exists():
        return None
    try:
        with checkpoint_path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Checkpoint %s unreadable (%s) — starting fresh.", checkpoint_path, exc)
        return None


def build_payload(
    leaves_results: list[LeafResult],
    *,
    schema_version: int = SCHEMA_VERSION,
) -> dict:
    total = len(leaves_results)
    ok = sum(1 for r in leaves_results if r.status == "ok")
    failed = sum(1 for r in leaves_results if r.status == "failed")
    soft = sum(1 for r in leaves_results if r.status == "soft_caps_violated")
    # avg attempts AR description (regen_for_caps + content_generator)
    ar_attempts = []
    for r in leaves_results:
        att = r.generation_attempts or {}
        n = att.get("content_generator", 0) + att.get("regen_for_caps", 0)
        if n:
            ar_attempts.append(n)
    avg_ar = (sum(ar_attempts) / len(ar_attempts)) if ar_attempts else 0.0

    return {
        "schema_version": schema_version,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "soft_caps": {
            k: list(v) for k, v in SOFT_CAPS.items()
        },
        "leaves": [r.to_dict() for r in leaves_results],
        "stats": {
            "total_leaves": total,
            "ok": ok,
            "failed": failed,
            "soft_caps_violated": soft,
            "avg_attempts_ar_desc": round(avg_ar, 2),
        },
    }


def results_from_checkpoint(payload: dict) -> dict[str, LeafResult]:
    """Reconstruit les ``LeafResult`` depuis le payload checkpoint (best-effort)."""
    out: dict[str, LeafResult] = {}
    for d in payload.get("leaves", []):
        lid = d.get("leaf_id")
        if not lid:
            continue
        r = LeafResult(
            leaf_id=lid,
            name_en=d.get("name_en", ""),
            name_fr=d.get("name_fr", ""),
            name_ar=d.get("name_ar", ""),
            title_en=d.get("title_en", ""),
            title_fr=d.get("title_fr", ""),
            title_ar=d.get("title_ar", ""),
            description_en=d.get("description_en", ""),
            description_fr=d.get("description_fr", ""),
            description_ar=d.get("description_ar", ""),
            title_card_en=d.get("title_card_en", ""),
            title_card_fr=d.get("title_card_fr", ""),
            title_card_ar=d.get("title_card_ar", ""),
            keywords_en=d.get("keywords_en") or [],
            keywords_fr=d.get("keywords_fr") or [],
            keywords_ar=d.get("keywords_ar") or [],
            status=d.get("status", "pending"),
            generation_attempts=d.get("generation_attempts") or {},
            soft_cap_violations=d.get("soft_cap_violations") or [],
            review_flags=d.get("review_flags") or [],
            error=d.get("error"),
            latency_ms=d.get("latency_ms", 0),
        )
        out[lid] = r
    return out


# ─── Main batch ──────────────────────────────────────────────────────────────
def run_batch(
    leaves_to_process: list[tuple[str, dict]],
    *,
    out_path: Path,
    checkpoint_path: Path,
    resume: bool,
    model: str,
    max_retries: int,
) -> dict:
    """Exécute le batch et écrit ``out_path`` + ``checkpoint_path`` après chaque leaf.

    Retourne le payload final.
    """
    results_by_id: dict[str, LeafResult] = {}
    if resume:
        ck = load_checkpoint(checkpoint_path)
        if ck:
            results_by_id = results_from_checkpoint(ck)
            logger.info("Resumed from checkpoint: %d leaves already in checkpoint", len(results_by_id))

    total = len(leaves_to_process)
    n_skipped = 0
    n_done = 0
    for idx, (leaf_id, node) in enumerate(leaves_to_process, start=1):
        prev = results_by_id.get(leaf_id)
        if resume and prev is not None and prev.status == "ok":
            n_skipped += 1
            continue

        logger.info(
            "[%d/%d] generating leaf_id=%s (model=%s)",
            idx,
            total,
            leaf_id,
            model,
        )
        result = generate_leaf(
            leaf_id=leaf_id,
            name_en=node.get("name_en") or leaf_id,
            name_fr=node.get("name_fr") or leaf_id,
            name_ar=node.get("name_ar") or "",
            model=model,
            max_retries=max_retries,
        )
        results_by_id[leaf_id] = result
        n_done += 1
        logger.info(
            "  → status=%s attempts=%s latency_ms=%d",
            result.status,
            result.generation_attempts,
            result.latency_ms,
        )

        # Checkpoint atomique après chaque leaf
        payload = build_payload(list(results_by_id.values()))
        atomic_write_json(checkpoint_path, payload)

    final_payload = build_payload(list(results_by_id.values()))
    atomic_write_json(out_path, final_payload)

    logger.info(
        "Batch done: total=%d skipped=%d processed=%d stats=%s",
        total,
        n_skipped,
        n_done,
        final_payload["stats"],
    )
    return final_payload


# ─── CLI ─────────────────────────────────────────────────────────────────────
def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--source",
        default=DEFAULT_ANNOTATIONS_GLOB,
        help="Glob pour les annotations.json (défaut: %(default)s)",
    )
    p.add_argument(
        "--taxonomy",
        type=Path,
        default=DEFAULT_TAXONOMY,
        help="Chemin du fichier taxonomy (défaut: %(default)s)",
    )
    p.add_argument(
        "--leaves",
        nargs="*",
        default=None,
        help="Liste explicite de leaf_id (override pour test/re-run)",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help="Output JSON final (défaut: %(default)s)",
    )
    p.add_argument(
        "--checkpoint",
        type=Path,
        default=DEFAULT_CHECKPOINT,
        help="Checkpoint JSON (défaut: %(default)s)",
    )
    p.add_argument(
        "--resume",
        action="store_true",
        help="Reprend depuis le checkpoint, skip les leaves status=ok",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Liste les leaves cibles sans appel Ollama",
    )
    p.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="Modèle Ollama (défaut: %(default)s)",
    )
    p.add_argument(
        "--max-retries",
        type=int,
        default=MAX_RETRIES,
        help="Max retries par leaf (défaut: %(default)d)",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limite le nombre de leaves à traiter (utile pour tests rapides)",
    )
    p.add_argument(
        "--log-level",
        default="INFO",
        help="Log level (défaut: INFO)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_argparser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # 1. Charge la taxonomie
    if not args.taxonomy.exists():
        logger.error("Taxonomy file not found: %s", args.taxonomy)
        return 2
    taxonomy_leaves = collect_taxonomy_leaves(args.taxonomy)
    logger.info("Loaded taxonomy: %d leaves", len(taxonomy_leaves))

    # 2. Détermine la liste des leaves
    if args.leaves:
        target_ids = [lid for lid in args.leaves if lid in taxonomy_leaves]
        missing = [lid for lid in args.leaves if lid not in taxonomy_leaves]
        if missing:
            logger.warning("Leaves not in taxonomy (skipped): %s", missing)
        orphan_filenames: list[str] = []
    else:
        target_ids, orphan_filenames = collect_publishable_leaves(
            args.source, taxonomy_leaves
        )

    logger.info(
        "Target leaves: %d (orphans: %d)",
        len(target_ids),
        len(orphan_filenames),
    )

    leaves_to_process: list[tuple[str, dict]] = [
        (lid, taxonomy_leaves[lid]) for lid in target_ids
    ]
    if args.limit:
        leaves_to_process = leaves_to_process[: args.limit]
        logger.info("Limited to %d leaves", len(leaves_to_process))

    if args.dry_run:
        print(f"# Dry run — {len(leaves_to_process)} leaves cibles")
        print(f"# Orphan filenames (non matched in taxonomy): {len(orphan_filenames)}")
        for lid, node in leaves_to_process:
            print(
                f"  {lid}\tEN={node.get('name_en','')}\tFR={node.get('name_fr','')}\tAR={node.get('name_ar','')}"
            )
        if orphan_filenames:
            print("\n# Sample orphan filenames (first 20):")
            for fn in orphan_filenames[:20]:
                print(f"  {fn}")
        return 0

    # 3. Run batch
    payload = run_batch(
        leaves_to_process,
        out_path=args.out,
        checkpoint_path=args.checkpoint,
        resume=args.resume,
        model=args.model,
        max_retries=args.max_retries,
    )

    # 4. Print stats
    print(json.dumps(payload["stats"], indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
