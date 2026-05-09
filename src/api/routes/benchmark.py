"""Routes API pour l'annotation des benchmarks visuels.

Sert :
- la liste des images d'un sous-dossier de ``docs/reports/`` avec leurs
  métriques QC (depuis le JSON d'index si présent) et annotations existantes ;
- les bytes PNG d'une image (FileResponse) ;
- l'écriture incrémentale de ``annotations.json`` dans ce même sous-dossier.

Pas de DB. Tout est sur disque sous ``docs/reports/<dir>/``.

Convention :
- index métriques : ``docs/reports/<dir>/<dir>.json`` (clé ``results``
  indexée par filename, comme produit par ``poc_sampler_benchmark.py``).
- annotations : ``docs/reports/<dir>/annotations.json``
  (clé ``annotations`` indexée par filename).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

# Vocabulaires fermés (axes IMAGE / PROMPT) : source de vérité unique
# partagée avec le routeur ``review`` (mode prod). Toute clé non listée
# ici est rejetée côté API si soumise dans ``image_tags`` ou
# ``prompt_tags``. Les ``custom_tags`` restent libres.
from api.annotation_vocab import (
    IMAGE_AXIS,
    IMAGE_TAGS_VOCAB,
    PROMPT_AXIS,
    PROMPT_TAGS_VOCAB,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/benchmark", tags=["benchmark"])

PROJECT_ROOT = Path(__file__).resolve().parents[3]
REPORTS_DIR = PROJECT_ROOT / "docs" / "reports"

_DIR_RE = re.compile(r"^[a-zA-Z0-9._-]+$")
_NAME_RE = re.compile(r"^[a-zA-Z0-9._-]+\.png$")


def _safe_dir(dir_name: str) -> Path:
    if not dir_name or not _DIR_RE.match(dir_name):
        raise HTTPException(status_code=400, detail=f"invalid dir name: {dir_name!r}")
    p = (REPORTS_DIR / dir_name).resolve()
    # garde-fou : doit rester sous REPORTS_DIR
    try:
        p.relative_to(REPORTS_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="dir escapes reports root")
    if not p.is_dir():
        raise HTTPException(status_code=404, detail=f"dir not found: {dir_name}")
    return p


def _safe_name(name: str) -> str:
    if not name or not _NAME_RE.match(name):
        raise HTTPException(status_code=400, detail=f"invalid filename: {name!r}")
    return name


def _decompose_filename(filename: str) -> dict[str, Any]:
    """Décompose un nom de fichier benchmark en tags lisibles.

    Patterns supportés :
      {concept}_{NN}s_{scheduler}_{sampler}_cfg{N}_{seed_short}.png
      {concept_with_underscores}_{NN}s_{scheduler}_{sampler_with_underscores}_cfg{N}_{seed_short}.png

    Stratégie : on cherche le token ``NNs`` (steps) → tout avant = concept ;
    le 2ᵉ avant la fin = ``cfgN`` ; le dernier = ``seed_short`` ;
    entre les deux : scheduler (1 token) + sampler (peut contenir ``_``).
    """
    base = filename.removesuffix(".png")
    parts = base.split("_")
    if len(parts) < 5:
        return {"concept": base, "steps": None, "scheduler": None,
                "sampler": None, "cfg": None, "seed_short": None}
    seed_short = parts[-1]
    cfg_token = parts[-2]
    try:
        cfg = int(cfg_token.removeprefix("cfg")) / 10.0
    except Exception:
        cfg = None
    steps_idx = None
    for i, p in enumerate(parts):
        if len(p) >= 2 and p[-1] == "s" and p[:-1].isdigit():
            steps_idx = i
            break
    if steps_idx is None or steps_idx + 2 > len(parts) - 2:
        return {"concept": base, "steps": None, "scheduler": None,
                "sampler": None, "cfg": cfg, "seed_short": seed_short}
    concept = "_".join(parts[:steps_idx])
    steps = int(parts[steps_idx][:-1])
    scheduler = parts[steps_idx + 1]
    sampler = "_".join(parts[steps_idx + 2:-2]) or None
    return {
        "concept": concept,
        "steps": steps,
        "scheduler": scheduler,
        "sampler": sampler,
        "cfg": cfg,
        "seed_short": seed_short,
    }


def _read_index(dir_path: Path) -> dict[str, Any]:
    """Lit ``<dir>/<dir>.json`` (index métriques)."""
    candidate = dir_path / f"{dir_path.name}.json"
    if not candidate.is_file():
        return {}
    try:
        return json.loads(candidate.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("benchmark: index JSON illisible (%s) : %s", candidate, exc)
        return {}


_PROMPT_INDEX_GLOBS = ("poc-*.json", "*-index.json", "index-*.json", "index.json")


def _result_entry_to_subject(key: Any, entry: dict) -> dict | None:
    """Convertit une entrée ``results`` (typiquement keyed par ``leaf_id`` avec
    un champ ``filename`` à l'intérieur) en entrée de schéma ``subjects``.

    Schémas supportés en entrée :
    - ``results: {leaf_id: {filename, leaf_name_en, positive, negative, ...}}`` (poc-generator)
    - ``results: {filename.png: {...}}`` (legacy keyed par filename)

    Retourne ``None`` si l'entrée ne permet pas de déduire un ``filename``.
    """
    fname = entry.get("filename")
    if not fname and isinstance(key, str) and key.lower().endswith(".png"):
        fname = key
    if not fname:
        return None
    return {
        "filename": fname,
        "name_en": entry.get("leaf_name_en") or entry.get("name_en") or entry.get("title"),
        "positive_prompt": entry.get("positive") or entry.get("positive_prompt") or entry.get("prompt"),
        "negative_prompt": entry.get("negative") or entry.get("negative_prompt"),
        "tier": entry.get("tier"),
        "workflow_class": entry.get("workflow_class"),
        "technique": entry.get("technique"),
        "pipeline": entry.get("pipeline"),
        "confidence": entry.get("confidence"),
        "pitfalls": entry.get("pitfalls"),
        "leaf_id": entry.get("leaf_id"),
    }


def _find_prompt_index(dir_path: Path) -> dict | None:
    """Fusionne TOUS les fichiers d'index prompts du dossier en un index virtuel.

    Patterns testés : ``poc-*.json``, ``*-index.json``, ``index.json``.
    Le fichier de métriques canonique ``<dir>/<dir>.json`` (lu par
    ``_read_index``) est exclu pour éviter la double-lecture.

    Pour chaque fichier matché qui parse en dict :
    - ``subjects`` (liste) → concaténée dans la liste fusionnée
    - ``items`` (liste) → concaténée
    - ``prompts_used`` (dict) → fusionné (premier vu gagne par clé)
    - ``results`` (dict, typiquement keyed par ``leaf_id`` avec ``filename``
      inline) → chaque entrée convertie au schéma ``subjects`` et ajoutée

    Retourne ``None`` si aucun fichier n'apporte de prompts.
    """
    metrics_filename = f"{dir_path.name}.json"
    seen: set[Path] = set()
    candidates: list[Path] = []
    for pat in _PROMPT_INDEX_GLOBS:
        for p in sorted(dir_path.glob(pat)):
            if p in seen:
                continue
            if p.name == metrics_filename:
                # Fichier métriques canonique : géré par _read_index, pas ici.
                continue
            seen.add(p)
            candidates.append(p)

    merged_subjects: list[dict] = []
    merged_items: list[dict] = []
    merged_prompts_used: dict[str, Any] = {}
    found_any = False

    for c in candidates:
        try:
            data = json.loads(c.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("benchmark: index JSON illisible (%s)", c)
            continue
        if not isinstance(data, dict):
            continue

        subjects = data.get("subjects")
        if isinstance(subjects, list):
            for s in subjects:
                if isinstance(s, dict):
                    merged_subjects.append(s)
            found_any = True

        items = data.get("items")
        if isinstance(items, list):
            for i in items:
                if isinstance(i, dict):
                    merged_items.append(i)
            found_any = True

        prompts_used = data.get("prompts_used")
        if isinstance(prompts_used, dict):
            for k, v in prompts_used.items():
                merged_prompts_used.setdefault(k, v)
            found_any = True

        results = data.get("results")
        if isinstance(results, dict):
            for k, entry in results.items():
                if not isinstance(entry, dict):
                    continue
                conv = _result_entry_to_subject(k, entry)
                if conv is not None:
                    merged_subjects.append(conv)
                    found_any = True

    if not found_any:
        return None

    return {
        "subjects": merged_subjects,
        "items": merged_items,
        "prompts_used": merged_prompts_used,
    }


_EXTRA_META_KEYS = ("workflow_class", "technique", "pipeline", "confidence", "pitfalls")


def _extract_extra_meta(src: dict) -> dict:
    """Récupère les champs supplémentaires (workflow_class, technique, pipeline,
    confidence, pitfalls) si présents dans ``src``. Champs absents → None / []."""
    out: dict = {}
    for k in _EXTRA_META_KEYS:
        out[k] = src.get(k)
    if out["pitfalls"] is None:
        out["pitfalls"] = []
    elif not isinstance(out["pitfalls"], list):
        out["pitfalls"] = [str(out["pitfalls"])]
    return out


def _empty_meta() -> dict:
    return {
        "title": None, "prompt": None, "negative": None, "tier": None,
        "workflow_class": None, "technique": None, "pipeline": None,
        "confidence": None, "pitfalls": [],
    }


def _resolve_prompt_meta(filename: str, index: dict | None) -> dict:
    """Cherche title / prompt / negative / tier + champs étendus pour un filename.

    Schémas supportés :
    - ``subjects: [{filename, name_en, positive_prompt, negative_prompt, tier, ...}]``
      → match par filename exact, sinon par name_en présent dans le filename.
    - ``items: [{filename, concept}]`` + ``prompts_used: {concept: ...}``
      → match par filename exact, ``title = concept``, ``prompt = prompts_used[concept]``
      (peut être string ou dict avec positive_prompt/negative_prompt/tier).
    Champs étendus pris en compte si présents : workflow_class, technique,
    pipeline, confidence, pitfalls. Aucun match → tous les champs à None / [].
    """
    if not index:
        return _empty_meta()

    base = filename.removesuffix(".png").lower()

    # subjects format
    subjects = index.get("subjects")
    if isinstance(subjects, list):
        for s in subjects:
            if isinstance(s, dict) and s.get("filename") == filename:
                return {
                    "title": s.get("name_en") or s.get("title"),
                    "prompt": s.get("positive_prompt") or s.get("prompt"),
                    "negative": s.get("negative_prompt") or s.get("negative"),
                    "tier": s.get("tier"),
                    **_extract_extra_meta(s),
                }
        for s in subjects:
            if not isinstance(s, dict):
                continue
            name_en = (s.get("name_en") or "").lower()
            if not name_en:
                continue
            slug = name_en.replace(" ", "_").replace("-", "_")
            if slug and slug in base:
                return {
                    "title": s.get("name_en"),
                    "prompt": s.get("positive_prompt") or s.get("prompt"),
                    "negative": s.get("negative_prompt") or s.get("negative"),
                    "tier": s.get("tier"),
                    **_extract_extra_meta(s),
                }

    # items + prompts_used format
    items = index.get("items")
    prompts_used = index.get("prompts_used") or {}
    if isinstance(items, list):
        for it in items:
            if not isinstance(it, dict):
                continue
            if it.get("filename") != filename:
                continue
            concept = it.get("concept")
            entry = prompts_used.get(concept) if concept else None
            # Item-level extra meta wins over prompts_used entry
            item_extra = _extract_extra_meta(it)
            if isinstance(entry, dict):
                entry_extra = _extract_extra_meta(entry)
                merged_extra = {
                    k: (item_extra[k] if item_extra[k] not in (None, []) else entry_extra[k])
                    for k in _EXTRA_META_KEYS
                }
                return {
                    "title": entry.get("name_en") or entry.get("title") or concept,
                    "prompt": entry.get("positive_prompt") or entry.get("prompt"),
                    "negative": entry.get("negative_prompt") or entry.get("negative"),
                    "tier": entry.get("tier"),
                    **merged_extra,
                }
            return {
                "title": concept,
                "prompt": entry if isinstance(entry, str) else None,
                "negative": None,
                "tier": None,
                **item_extra,
            }

    return _empty_meta()


def _normalize_results_index(raw_results: Any) -> tuple[dict[str, dict], dict[str, dict]]:
    """Sépare un mapping ``results`` en (metrics_par_filename, meta_par_filename).

    Deux schémas supportés :
    - legacy : ``results`` keyed par filename .png → metrics direct.
    - poc-generator : ``results`` keyed par leaf_id ; chaque entrée contient
      un champ ``filename`` + métriques + prompts/extra_meta inline.

    Les deux mappings sont indexés par filename. ``meta_par_filename`` ne
    contient que les filenames pour lesquels au moins un champ prompt/title
    /extra_meta est présent dans l'entrée. Les entrées sans ``filename`` sont
    ignorées (ex. ``status: skip_unknown_leaf``).
    """
    metrics_by_fn: dict[str, dict] = {}
    meta_by_fn: dict[str, dict] = {}
    if not isinstance(raw_results, dict):
        return metrics_by_fn, meta_by_fn
    for key, entry in raw_results.items():
        if not isinstance(entry, dict):
            # legacy: scalaire ou autre — ignore
            continue
        # Détermine le filename canonique pour cette entrée.
        fname = entry.get("filename")
        if not fname:
            # legacy : la clé est elle-même le filename
            fname = key if isinstance(key, str) and key.lower().endswith(".png") else None
        if not fname:
            continue
        # Synthèse rétrocompat de la forme nested {histogram, vision_qc} attendue par
        # l'overlay frontend. Le nouveau schéma poc-generator-benchmark expose ces
        # champs à plat sur l'entrée (color_ratio, ink_ratio, flags, vision_verdict),
        # alors que les legacy POCs (poc-seed-variance, poc-sampler-benchmark…) ont
        # déjà les sous-objets imbriqués. On préserve les nested existants quand
        # présents et on synthétise sinon — les valeurs absentes restent ``None``,
        # le frontend affichera "—".
        entry_out = dict(entry)
        if not isinstance(entry_out.get("histogram"), dict):
            entry_out["histogram"] = {
                "color_ratio": entry.get("color_ratio"),
                "ink_ratio":   entry.get("ink_ratio"),
                "white_ratio": entry.get("white_ratio"),
                "flags":       entry.get("flags", []),
            }
        if not isinstance(entry_out.get("vision_qc"), dict):
            entry_out["vision_qc"] = {
                "verdict": entry.get("vision_verdict") or entry.get("verdict"),
            }
        metrics_by_fn[fname] = entry_out
        # Si l'entrée porte du contenu prompt/title/extra_meta, on l'expose comme meta.
        title = entry.get("leaf_name_en") or entry.get("name_en") or entry.get("title")
        prompt_pos = (
            entry.get("positive")
            or entry.get("positive_prompt")
            or entry.get("prompt")
        )
        prompt_neg = entry.get("negative") or entry.get("negative_prompt")
        extra = _extract_extra_meta(entry)
        has_extra = any(extra.get(k) not in (None, []) for k in _EXTRA_META_KEYS)
        if title or prompt_pos or has_extra:
            meta_by_fn[fname] = {
                "title": title,
                "prompt": prompt_pos,
                "negative": prompt_neg,
                "tier": entry.get("tier"),
                **extra,
            }
    return metrics_by_fn, meta_by_fn


def _read_annotations(dir_path: Path) -> dict[str, Any]:
    p = dir_path / "annotations.json"
    if not p.is_file():
        return {"dir": dir_path.name, "annotations": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"dir": dir_path.name, "annotations": {}}
        data.setdefault("dir", dir_path.name)
        data.setdefault("annotations", {})
        return data
    except Exception as exc:
        logger.warning("benchmark: annotations.json illisible (%s) : %s", p, exc)
        return {"dir": dir_path.name, "annotations": {}}


def _write_annotations(dir_path: Path, data: dict) -> None:
    p = dir_path / "annotations.json"
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/images")
def list_images(dir: str = Query(..., description="sous-dossier de docs/reports/")):
    """Liste les PNG du sous-dossier avec métriques QC + annotations + prompts (si index trouvé)."""
    dir_path = _safe_dir(dir)
    index = _read_index(dir_path)
    raw_results = (index.get("results") or {}) if isinstance(index, dict) else {}
    metrics_by_fn, embedded_meta_by_fn = _normalize_results_index(raw_results)
    annot = _read_annotations(dir_path)
    annotations = annot.get("annotations") or {}
    prompt_index = _find_prompt_index(dir_path)

    pngs = sorted(p.name for p in dir_path.glob("*.png"))
    items = []
    for name in pngs:
        # Embedded meta = ce que le fichier métriques canonique <dir>/<dir>.json
        # apporte directement (poc-generator schema). External meta = ce que les
        # autres index *-index.json apportent via _resolve_prompt_meta.
        # On fusionne : embedded gagne sur les valeurs non-vides, sinon fallback
        # sur external. Cas d'usage : un metrics file qui contient title +
        # workflow_class mais pas de positive_prompt, et un index-<class>.json
        # voisin qui contient le prompt — l'utilisateur veut voir les deux.
        embedded = embedded_meta_by_fn.get(name)
        external = _resolve_prompt_meta(name, prompt_index)
        if embedded is None:
            meta = external
        else:
            meta = {**_empty_meta(), **embedded}
            for k, v in list(meta.items()):
                if v in (None, "", []) and external.get(k) not in (None, "", []):
                    meta[k] = external[k]
        items.append({
            "filename": name,
            "tags": _decompose_filename(name),
            "metrics": metrics_by_fn.get(name),
            "annotation": annotations.get(name),
            "title": meta["title"],
            "prompt": meta["prompt"],
            "negative": meta["negative"],
            "tier": meta["tier"],
            "workflow_class": meta.get("workflow_class"),
            "technique": meta.get("technique"),
            "pipeline": meta.get("pipeline"),
            "confidence": meta.get("confidence"),
            "pitfalls": meta.get("pitfalls") or [],
        })

    return JSONResponse({
        "dir": dir,
        "image_url_template": f"/api/benchmark/file?dir={dir}&name={{name}}",
        "count": len(items),
        "items": items,
        "index_present": bool(index),
        "prompt_index_present": bool(prompt_index),
    })


@router.get("/file")
def serve_image(dir: str = Query(...), name: str = Query(...)):
    """Sert les bytes PNG d'une image du sous-dossier."""
    dir_path = _safe_dir(dir)
    fname = _safe_name(name)
    p = dir_path / fname
    if not p.is_file():
        raise HTTPException(status_code=404, detail=f"image not found: {fname}")
    return FileResponse(p, media_type="image/png")


class FlagsPayload(BaseModel):
    pattern: bool | None = False
    pattern_note: str | None = ""
    sample: bool | None = False
    publishable: bool | None = None


class AnnotatePayload(BaseModel):
    """Payload v2 (grille 3 axes + flags).

    Compatible v1 lecture seule : si un client legacy envoie ``defects`` /
    ``notes`` / ``publishable`` au top-level, on les accepte mais on
    privilégie les champs v2 (image_tags / prompt_tags / flags). Lors de
    l'écriture on **persiste toujours en v2**.
    """

    dir: str
    filename: str
    score: int | None = None  # v2 : 1..6
    score_legacy: int | None = None  # v1 : 1..10 conservé après migration
    image_tags: list[str] = Field(default_factory=list)
    prompt_tags: list[str] = Field(default_factory=list)
    custom_tags: list[str] = Field(default_factory=list)
    flags: FlagsPayload | None = None
    # Champs v1 tolérés pour rétro-compat client (rarement utilisés en v2)
    defects: list[str] | None = None
    notes: str | None = None
    publishable: bool | None = None


@router.get("/vocabularies")
def get_vocabularies():
    """Expose les vocabulaires fermés (axes IMAGE / PROMPT) + score range.

    Endpoint de découverte consommé par le front au boot
    (``data/benchmark-annotator.html``) pour construire les pills et la
    numérotation chord. Source unique : ``src/api/annotation_vocab.py``.

    Pas de query params, idempotent, cacheable côté client (1 fetch par
    session — le HTML stocke en mémoire et ne re-fetch pas).

    Réponse :
        {
          "image_axis":  [{"key", "label", "polarity"}, ...],   # 18 entrées
          "prompt_axis": [{"key", "label", "polarity"}, ...],   # 8 entrées
          "score_range": {"min": 1, "max": 6},
          "schema_version": 2
        }

    L'ordre des listes détermine la numérotation chord (touche ``D``
    pour image_axis, ``T`` pour prompt_axis ; k-ième entrée → touche k+1).
    """
    return JSONResponse({
        "image_axis": [dict(t) for t in IMAGE_AXIS],
        "prompt_axis": [dict(t) for t in PROMPT_AXIS],
        "score_range": {"min": 1, "max": 6},
        "schema_version": 2,
    })


@router.get("/dirs")
def list_dirs():
    """Liste les sous-dossiers de ``docs/reports/`` contenant ≥1 PNG.

    Triés par mtime descendant (le plus récent en premier).
    """
    if not REPORTS_DIR.is_dir():
        return JSONResponse({"dirs": []})
    entries: list[tuple[float, str, int]] = []
    for sub in REPORTS_DIR.iterdir():
        if not sub.is_dir():
            continue
        if not _DIR_RE.match(sub.name):
            continue
        # Compter les PNG (lazy : on s'arrête dès qu'on en trouve un, mais on
        # remonte le compte total pour info — utile si l'UI veut afficher
        # "(N images)" dans le datalist).
        pngs = list(sub.glob("*.png"))
        if not pngs:
            continue
        try:
            mtime = sub.stat().st_mtime
        except OSError:
            mtime = 0.0
        entries.append((mtime, sub.name, len(pngs)))
    entries.sort(key=lambda t: t[0], reverse=True)
    return JSONResponse({
        "dirs": [
            {"name": name, "png_count": count, "mtime": mtime}
            for mtime, name, count in entries
        ]
    })


@router.get("/custom-tags")
def list_custom_tags():
    """Union des ``custom_tags`` connus (parcourt tous les annotations.json).

    Inclut aussi les tags issus du champ legacy ``notes`` quand il contient
    un JSON array — le front legacy y stockait des tags type pills.
    """
    seen: set[str] = set()
    if not REPORTS_DIR.is_dir():
        return JSONResponse({"tags": []})
    for sub in REPORTS_DIR.iterdir():
        if not sub.is_dir():
            continue
        if not _DIR_RE.match(sub.name):
            continue
        ap = sub / "annotations.json"
        if not ap.is_file():
            continue
        try:
            data = json.loads(ap.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        annotations = data.get("annotations") or {}
        if not isinstance(annotations, dict):
            continue
        for entry in annotations.values():
            if not isinstance(entry, dict):
                continue
            tags = entry.get("custom_tags")
            if isinstance(tags, list):
                for t in tags:
                    if isinstance(t, str) and t.strip():
                        seen.add(t.strip())
            # Legacy : champ "notes" contenant un JSON array → tags
            notes = entry.get("notes")
            if isinstance(notes, str) and notes.strip().startswith("["):
                try:
                    parsed = json.loads(notes)
                except Exception:
                    parsed = None
                if isinstance(parsed, list):
                    for t in parsed:
                        if isinstance(t, str) and t.strip():
                            seen.add(t.strip())
    return JSONResponse({"tags": sorted(seen)})


@router.post("/annotate")
def annotate(payload: AnnotatePayload = Body(...)):
    """Sauvegarde l'annotation d'une image au format v2.

    Validation v2 :
    - ``score`` (si fourni) ∈ [1, 6]
    - ``score_legacy`` (si fourni) ∈ [1, 10]
    - ``image_tags`` ⊂ IMAGE_TAGS_VOCAB
    - ``prompt_tags`` ⊂ PROMPT_TAGS_VOCAB
    - ``custom_tags`` libres
    """
    dir_path = _safe_dir(payload.dir)
    fname = _safe_name(payload.filename)
    if not (dir_path / fname).is_file():
        raise HTTPException(status_code=404, detail=f"image not found: {fname}")

    if payload.score is not None and not (1 <= payload.score <= 6):
        raise HTTPException(status_code=400, detail="score must be between 1 and 6")
    if payload.score_legacy is not None and not (1 <= payload.score_legacy <= 10):
        raise HTTPException(
            status_code=400, detail="score_legacy must be between 1 and 10"
        )

    image_tags = list(payload.image_tags or [])
    unknown_image = [t for t in image_tags if t not in IMAGE_TAGS_VOCAB]
    if unknown_image:
        raise HTTPException(
            status_code=400,
            detail=f"unknown image_tags: {sorted(set(unknown_image))}",
        )
    prompt_tags = list(payload.prompt_tags or [])
    unknown_prompt = [t for t in prompt_tags if t not in PROMPT_TAGS_VOCAB]
    if unknown_prompt:
        raise HTTPException(
            status_code=400,
            detail=f"unknown prompt_tags: {sorted(set(unknown_prompt))}",
        )

    # Custom tags : strip + dédup, garde l'ordre
    custom_tags: list[str] = []
    seen_custom: set[str] = set()
    for t in payload.custom_tags or []:
        if not isinstance(t, str):
            continue
        s = t.strip()
        if not s or s in seen_custom:
            continue
        seen_custom.add(s)
        custom_tags.append(s)

    # Flags
    flags_in = payload.flags or FlagsPayload()
    flags = {
        "pattern": bool(flags_in.pattern),
        "pattern_note": (flags_in.pattern_note or "").strip(),
        "sample": bool(flags_in.sample),
        # `publishable` peut venir soit du flag soit du champ top-level legacy
        "publishable": (
            flags_in.publishable
            if flags_in.publishable is not None
            else payload.publishable
        ),
    }

    data = _read_annotations(dir_path)
    annotations: dict[str, Any] = data.get("annotations") or {}
    annotations[fname] = {
        "score": payload.score,
        "score_legacy": payload.score_legacy,
        "image_tags": image_tags,
        "prompt_tags": prompt_tags,
        "custom_tags": custom_tags,
        "flags": flags,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    data["annotations"] = annotations
    data["dir"] = payload.dir
    _write_annotations(dir_path, data)
    return JSONResponse({"ok": True, "filename": fname, "annotation": annotations[fname]})
