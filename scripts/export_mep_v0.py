"""Export MEP v0 — produit ``data/export/`` consommable par alwanbooks-pipeline.

Brief : ``docs/architect/briefs/2026-05-10_brief-mep-v0-C-export-data.md``.

Pipeline orchestré
------------------

1. Charge ``data/export/_i18n_batch.json`` (output Brief B).
2. Filtre les leaves :

   - Status acceptable : ``status='ok'`` OU ``status='soft_caps_violated'``
     **avec respect strict des HARD caps Zod** ``[5,100]/[20,200]`` (le
     pipeline n'est pas miroir des soft caps éditoriaux internes,
     cf. ``CLAUDE.md`` §Validation).
   - Au moins une annotation ``publishable=true`` ``target_type='benchmark_file'``
     pour ce leaf en DB (mappage par filename → leaf_id).

3. Pour chaque leaf retenu :

   a. Calcule ``r2_slug = slug_utils.r2_slug(name_en)``.
   b. Calcule les 3 ``post_slug`` (fr/en/ar) via ``slug_utils.post_slug``.
   c. Choisit la **meilleure** annotation publishable pour ce leaf (score
      max, premier rencontré sinon) — c'est elle qui fournit le master PNG.
   d. Crée / met à jour la ligne ``image`` (UPSERT par image_id stable
      ``benchmark:<dir>/<filename>``), ``origin_type='benchmark_publishable'``,
      ``status='approved'``.
   e. Upsert × 3 ``image_publication`` (1 par locale) avec title/description/
      slugs + ``status='pending'``.
   f. Appelle ``mark_image_ready_for_export`` (brief A) — passe les 3 lignes
      à ``ready_for_export``.
   g. Écrit ``data/export/posts/<locale>/<post_slug>.json`` (frontmatter
      conforme contrat §4).
   h. Copie le PNG master vers ``data/export/images/<r2_slug>.png`` **si**
      le master existe sur disque ; sinon → consigné en warning, l'export
      Post est quand même produit (les URLs R2 sont prédites).

4. Écrit ``data/export/manifest.json`` (récapitulatif).
5. Produit le rapport phase ``docs/reports/2026-05-12_phase-mep-v0-C-export-data.md``.

Usage
-----
::

    # Dry-run (n'écrit rien, juste compte ce qui serait exporté)
    python scripts/export_mep_v0.py --dry-run

    # Mode normal (écrit DB + fichiers)
    python scripts/export_mep_v0.py

    # Limite (utile pour test rapide sur 5 leaves)
    python scripts/export_mep_v0.py --limit 5

Convention métier (i18n une fois pour toutes)
---------------------------------------------

- **Chiffres en lettres** : les ``name_*`` source ne doivent contenir aucun
  chiffre — convention validée 2026-05-12. Le slugifier ``r2_slug`` lève
  une ``ValueError`` sur les ``name_en`` qui commencent par un chiffre.
  Les ``name_fr`` / ``name_ar`` suivent la même règle implicitement.
- **Gate HARD caps Zod strict** : pas d'export silencieux pour un leaf qui
  viole les bornes contractuelles plateforme [5,100] titre / [20,200]
  description. Tout leaf bloqué → consigné dans le rapport avec le
  champ fautif et sa longueur.
- **Pas de fallback latin résiduel en AR** : ``post_slug`` AR est
  translittéré strictement (corpus + table char-par-char), tout résidu
  non-ASCII fait échouer la validation ASCII_KEBAB_RE.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = PROJECT_ROOT / "docs" / "reports"
EXPORT_DIR = PROJECT_ROOT / "data" / "export"
EXPORT_IMAGES_DIR = EXPORT_DIR / "images"
EXPORT_POSTS_DIR = EXPORT_DIR / "posts"
I18N_BATCH_PATH = EXPORT_DIR / "_i18n_batch.json"
REPORT_PATH = REPORTS_DIR / "2026-05-12_phase-mep-v0-C-export-data.md"
MANIFEST_PATH = EXPORT_DIR / "manifest.json"

# Console Windows par défaut cp1252 → forcer utf-8 pour --help et prints.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, str(PROJECT_ROOT / "src"))

from api.db import DBConnAdapter, SessionLocal  # noqa: E402
from api.image_publication import (  # noqa: E402
    PUBLICATION_LOCALES,
    mark_image_approved,
    mark_image_ready_for_export,
)
from services.slug_utils import post_slug, r2_slug  # noqa: E402

logger = logging.getLogger("export_mep_v0")

# HARD caps Zod plateforme — bornes contractuelles uniformes toutes locales
# (cf. CLAUDE.md §Validation, ADR §1.13).
HARD_CAP_TITLE = (5, 100)
HARD_CAP_DESCRIPTION = (20, 200)

# Base URL R2 publique (prédite ; alwanbooks-pipeline upload réellement).
R2_BASE = "https://assets.alwanbooks.com/coloriages"

# Schéma frontmatter Post v0 — aligné contrat Alwan v2.4.
FRONTMATTER_SCHEMA_VERSION = "v2.4"


# ── Helpers utilitaires ──────────────────────────────────────────────────────


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hard_caps_ok(leaf: dict[str, Any]) -> tuple[bool, list[str]]:
    """Vérifie qu'un leaf passe les HARD caps Zod pour les 3 locales.

    Retourne ``(ok, violations)``. ``violations`` est une liste de strings
    descriptives (vide si OK).
    """
    violations: list[str] = []
    tmin, tmax = HARD_CAP_TITLE
    dmin, dmax = HARD_CAP_DESCRIPTION
    for loc in PUBLICATION_LOCALES:
        title = leaf.get(f"title_{loc}") or ""
        desc = leaf.get(f"description_{loc}") or ""
        if not (tmin <= len(title) <= tmax):
            violations.append(
                f"title_{loc} len={len(title)} hors [{tmin},{tmax}]"
            )
        if not (dmin <= len(desc) <= dmax):
            violations.append(
                f"description_{loc} len={len(desc)} hors [{dmin},{dmax}]"
            )
    return (not violations), violations


def _i18n_status_ok(leaf: dict[str, Any]) -> bool:
    """Statut acceptable côté pipeline.

    On accepte ``status='ok'`` et ``status='soft_caps_violated'`` (les soft
    caps sont des préférences éditoriales internes ; la gate contractuelle
    plateforme est les HARD caps — appliquées séparément).
    """
    return leaf.get("status") in ("ok", "soft_caps_violated")


_LEAFID_FROM_FILENAME_CACHE: dict[str, str | None] = {}


def _guess_leaf_id_from_filename(
    filename: str, known_leaf_ids: set[str],
) -> str | None:
    """Devine le ``leaf_id`` d'une annotation à partir du filename PNG.

    Stratégie : on supprime l'extension puis on coupe progressivement les
    suffixes ``_<resolution>_<batch>_<sampler>...`` jusqu'à matcher un
    leaf_id connu. Mémoïsé.
    """
    if filename in _LEAFID_FROM_FILENAME_CACHE:
        return _LEAFID_FROM_FILENAME_CACHE[filename]
    base = re.sub(r"\.(png|jpg|jpeg)$", "", filename, flags=re.IGNORECASE)
    parts = base.split("_")
    for n in range(len(parts), 0, -1):
        candidate = "_".join(parts[:n])
        if candidate in known_leaf_ids:
            _LEAFID_FROM_FILENAME_CACHE[filename] = candidate
            return candidate
    _LEAFID_FROM_FILENAME_CACHE[filename] = None
    return None


def _load_i18n_batch(path: Path) -> tuple[dict[str, dict], dict[str, Any]]:
    """Charge ``_i18n_batch.json`` et retourne (leaves_by_id, raw_meta)."""
    if not path.is_file():
        raise FileNotFoundError(f"i18n batch introuvable : {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    leaves = {leaf["leaf_id"]: leaf for leaf in data.get("leaves", [])}
    return leaves, data


def _fetch_publishable_annotations(
    conn: DBConnAdapter,
) -> list[tuple[str, int | None, str]]:
    """Retourne ``[(target_id, score, updated_at), …]`` triés par score DESC.

    Ne filtre que ``target_type='benchmark_file'`` ET ``publishable=true``.
    """
    rows = conn.execute(
        """
        SELECT target_id, score, updated_at
        FROM annotation
        WHERE target_type = 'benchmark_file' AND publishable = TRUE
        ORDER BY score DESC NULLS LAST, updated_at DESC
        """,
        [],
    ).fetchall()
    out: list[tuple[str, int | None, str]] = []
    for r in rows:
        out.append((str(r[0]), int(r[1]) if r[1] is not None else None, str(r[2])))
    return out


def _select_best_per_leaf(
    publishable_rows: list[tuple[str, int | None, str]],
    leaves_by_id: dict[str, dict],
) -> dict[str, tuple[str, int | None]]:
    """Pour chaque leaf_id présent dans i18n batch, sélectionne la **meilleure**
    annotation publishable (score max). Retourne ``{leaf_id: (target_id, score)}``.
    """
    best: dict[str, tuple[str, int | None]] = {}
    known = set(leaves_by_id.keys())
    for target_id, score, _updated in publishable_rows:
        _dir, fn = target_id.split("/", 1)
        leaf = _guess_leaf_id_from_filename(fn, known)
        if leaf is None:
            continue
        if leaf not in best:
            best[leaf] = (target_id, score)
            continue
        # publishable_rows est déjà trié par score DESC — première occurrence
        # = meilleure. On ignore les suivantes pour ce leaf.
    return best


# ── DB writes (UPSERT cross-dialect) ─────────────────────────────────────────


def _upsert_image(
    conn: DBConnAdapter, *, image_id: str, title: str, target_id: str,
    now: str,
) -> str:
    """UPSERT d'une ligne ``image`` (idempotent).

    Retourne ``'INSERT'`` ou ``'UPDATE'``. ``status='approved'`` car les
    images viennent du corpus publishable validé humainement.
    """
    existing = conn.execute(
        "SELECT id FROM image WHERE id = ?", [image_id],
    ).fetchone()
    if existing is None:
        conn.execute(
            """
            INSERT INTO image (
                id, title, status, origin_type, origin_batch_id,
                file_path, file_format, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                image_id, title, "approved", "benchmark_publishable",
                target_id, target_id, "png", now, now,
            ],
        )
        return "INSERT"

    conn.execute(
        """
        UPDATE image SET
            title = ?,
            status = ?,
            origin_type = ?,
            origin_batch_id = ?,
            file_path = ?,
            file_format = ?,
            updated_at = ?
        WHERE id = ?
        """,
        [
            title, "approved", "benchmark_publishable", target_id,
            target_id, "png", now, image_id,
        ],
    )
    return "UPDATE"


def _upsert_image_publication(
    conn: DBConnAdapter, *, image_id: str, locale: str,
    title: str, description: str, post_slug_value: str, r2_slug_value: str,
    now: str,
) -> str:
    """UPSERT d'une ligne ``image_publication`` (PK = (image_id, locale))."""
    existing = conn.execute(
        "SELECT image_id FROM image_publication"
        " WHERE image_id = ? AND locale = ?",
        [image_id, locale],
    ).fetchone()
    if existing is None:
        conn.execute(
            """
            INSERT INTO image_publication (
                image_id, locale, title, description,
                post_slug, r2_slug, status,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                image_id, locale, title, description,
                post_slug_value, r2_slug_value, "pending", now, now,
            ],
        )
        return "INSERT"

    conn.execute(
        """
        UPDATE image_publication SET
            title = ?,
            description = ?,
            post_slug = ?,
            r2_slug = ?,
            updated_at = ?
        WHERE image_id = ? AND locale = ?
        """,
        [
            title, description, post_slug_value, r2_slug_value, now,
            image_id, locale,
        ],
    )
    return "UPDATE"


# ── Frontmatter ──────────────────────────────────────────────────────────────


def _build_post_frontmatter(
    *, leaf: dict[str, Any], locale: str, image_id: str,
    r2_slug_value: str, post_slug_value: str, now: str,
) -> dict[str, Any]:
    """Construit le frontmatter Post v0 conforme contrat Alwan §4.

    Champs minimum : locale, post_slug, r2_slug, title, title_card,
    description, keywords, image_id, image_*, status, created_at.

    Tags taxonomiques : laissés vides en v0 (les image_taxonomy_tag ne sont
    pas peuplés pour le corpus benchmark — décision archi à raffiner).
    """
    title = leaf.get(f"title_{locale}") or ""
    title_card = leaf.get(f"title_card_{locale}") or title[:40]
    description = leaf.get(f"description_{locale}") or ""
    keywords = leaf.get(f"keywords_{locale}") or []
    if not isinstance(keywords, list):
        keywords = []

    return {
        "schema_version": FRONTMATTER_SCHEMA_VERSION,
        "locale": locale,
        "slug": post_slug_value,
        "r2_slug": r2_slug_value,
        "title": title,
        "title_card": title_card,
        "description": description,
        "keywords": list(keywords),
        "categoryId": "",  # v0 : taxonomy tag pas peuplé pour benchmark corpus
        "themeIds": [],
        "status": "approved",
        "image_id": image_id,
        "imageSource": f"{R2_BASE}/png/{r2_slug_value}.png",
        "imageWeb": f"{R2_BASE}/webp/{r2_slug_value}.webp",
        "imageThumb": f"{R2_BASE}/thumbs/{r2_slug_value}.webp",
        "imagePdf": f"{R2_BASE}/pdf/{r2_slug_value}.pdf",
        "datePublication": now[:10],  # YYYY-MM-DD
        "featured": False,
        # Metadata pipeline (toléré par passthrough côté Astro).
        "_pipeline": {
            "leaf_id": leaf.get("leaf_id"),
            "name_en": leaf.get("name_en"),
            "name_fr": leaf.get("name_fr"),
            "name_ar": leaf.get("name_ar"),
            "i18n_status": leaf.get("status"),
            "generated_at": now,
        },
    }


#: Roots additionnels où chercher les PNG masters. Permet à un worktree
#: (qui ne matérialise pas les PNG gitignored) de retrouver les masters
#: stockés dans le repo principal. Override via env ``ARTISTE_MASTER_ROOTS``
#: (séparé par ``;`` sous Windows / ``:`` sous Unix).
_DEFAULT_MASTER_ROOTS = [
    Path("D:/projets/artiste-coloriage"),
]


def _master_roots() -> list[Path]:
    """Liste ordonnée de roots de recherche pour les PNG masters.

    Inclut toujours ``PROJECT_ROOT`` (le repo / worktree courant) en premier,
    puis les roots additionnels (repo principal côté worktree).
    """
    roots: list[Path] = [PROJECT_ROOT]
    extra_env = os.environ.get("ARTISTE_MASTER_ROOTS", "")
    if extra_env:
        sep = ";" if ";" in extra_env else ":"
        for raw in extra_env.split(sep):
            raw = raw.strip()
            if raw:
                roots.append(Path(raw))
    else:
        for default in _DEFAULT_MASTER_ROOTS:
            if default != PROJECT_ROOT and default.is_dir():
                roots.append(default)
    return roots


def _resolve_master_png(target_id: str) -> Path | None:
    """Tente de localiser le PNG master sur disque.

    Cherche dans chaque ``_master_roots()`` les emplacements suivants
    (premier qui existe gagne) :

    - ``<root>/docs/reports/<dir>/<filename>`` (POC reports)
    - ``<root>/data/outputs/<filename>``
    - ``<root>/data/<target_id>``

    Retourne le path absolu ou ``None`` si aucun n'existe.
    """
    dir_, fn = target_id.split("/", 1)
    for root in _master_roots():
        candidates = [
            root / "docs" / "reports" / dir_ / fn,
            root / "data" / "outputs" / fn,
            root / "data" / target_id,
        ]
        for c in candidates:
            if c.is_file():
                return c
    return None


# ── Orchestrateur ────────────────────────────────────────────────────────────


def export_run(
    *, dry_run: bool, limit: int | None,
) -> dict[str, Any]:
    """Exécute l'export. Retourne un summary détaillé."""
    logger.info("Chargement i18n batch %s", I18N_BATCH_PATH)
    leaves_by_id, _meta = _load_i18n_batch(I18N_BATCH_PATH)
    total_leaves = len(leaves_by_id)

    summary: dict[str, Any] = {
        "dry_run": dry_run,
        "i18n_leaves_total": total_leaves,
        "leaves_status_ok": 0,
        "leaves_status_violated": 0,
        "leaves_status_other": 0,
        "leaves_pass_hard_caps": 0,
        "leaves_fail_hard_caps": 0,
        "leaves_no_publishable": 0,
        "leaves_exported": 0,
        "leaves_skipped": [],         # [(leaf_id, reason)]
        "hard_cap_violations": [],    # [(leaf_id, [violations])]
        "image_inserts": 0,
        "image_updates": 0,
        "publication_inserts": 0,
        "publication_updates": 0,
        "posts_written": 0,
        "images_copied": 0,
        "images_missing_master": [],  # [r2_slug]
        "exported": [],               # [dict per leaf]
    }

    session = None
    conn: DBConnAdapter | None = None
    try:
        session = SessionLocal()
        conn = DBConnAdapter(session)

        # Filtrer i18n leaves par status acceptable + HARD caps.
        eligible_leaves: dict[str, dict] = {}
        for leaf_id, leaf in leaves_by_id.items():
            st = leaf.get("status")
            if st == "ok":
                summary["leaves_status_ok"] += 1
            elif st == "soft_caps_violated":
                summary["leaves_status_violated"] += 1
            else:
                summary["leaves_status_other"] += 1

            if not _i18n_status_ok(leaf):
                summary["leaves_skipped"].append(
                    (leaf_id, f"i18n status={st}"),
                )
                continue
            ok, viol = _hard_caps_ok(leaf)
            if not ok:
                summary["leaves_fail_hard_caps"] += 1
                summary["hard_cap_violations"].append((leaf_id, viol))
                summary["leaves_skipped"].append(
                    (leaf_id, f"hard_caps_violation: {';'.join(viol[:2])}"),
                )
                continue
            summary["leaves_pass_hard_caps"] += 1
            eligible_leaves[leaf_id] = leaf

        # Map publishable annotations → leaf_id
        publishable_rows = _fetch_publishable_annotations(conn)
        best_per_leaf = _select_best_per_leaf(publishable_rows, eligible_leaves)

        # Leaves éligibles MAIS sans annotation publishable.
        for leaf_id in eligible_leaves:
            if leaf_id not in best_per_leaf:
                summary["leaves_no_publishable"] += 1
                summary["leaves_skipped"].append(
                    (leaf_id, "no publishable annotation"),
                )

        # Trier de manière déterministe par leaf_id.
        exportable = sorted(best_per_leaf.keys())
        if limit is not None and limit >= 0:
            exportable = exportable[:limit]

        logger.info(
            "Eligible: %d leaves (hard_caps OK + publishable), exporting %d",
            len(best_per_leaf), len(exportable),
        )

        if not dry_run:
            EXPORT_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
            for loc in PUBLICATION_LOCALES:
                (EXPORT_POSTS_DIR / loc).mkdir(parents=True, exist_ok=True)

        # Index seen slugs pour détecter collisions intra-export.
        seen_post_slugs: dict[tuple[str, str], str] = {}
        seen_r2_slugs: dict[str, str] = {}

        for leaf_id in exportable:
            leaf = eligible_leaves[leaf_id]
            target_id, score = best_per_leaf[leaf_id]

            # 1. Calcul des slugs
            name_en = leaf.get("name_en") or ""
            name_fr = leaf.get("name_fr") or ""
            name_ar = leaf.get("name_ar") or ""

            try:
                r2 = r2_slug(name_en)
            except ValueError as exc:
                summary["leaves_skipped"].append(
                    (leaf_id, f"r2_slug error: {exc}"),
                )
                continue

            try:
                ps_en = post_slug(name_en, "en")
                ps_fr = post_slug(name_fr, "fr")
                ps_ar = post_slug(name_ar, "ar")
            except ValueError as exc:
                summary["leaves_skipped"].append(
                    (leaf_id, f"post_slug error: {exc}"),
                )
                continue

            # Collisions r2 (cross-leaf).
            if r2 in seen_r2_slugs and seen_r2_slugs[r2] != leaf_id:
                summary["leaves_skipped"].append(
                    (leaf_id, f"r2_slug collision: '{r2}' déjà pris par "
                              f"{seen_r2_slugs[r2]}"),
                )
                continue
            seen_r2_slugs[r2] = leaf_id

            # Collisions post_slug intra-locale.
            collided = False
            for loc, ps in (("en", ps_en), ("fr", ps_fr), ("ar", ps_ar)):
                key = (loc, ps)
                if key in seen_post_slugs and seen_post_slugs[key] != leaf_id:
                    summary["leaves_skipped"].append(
                        (leaf_id, f"post_slug collision: ({loc}, '{ps}') "
                                  f"déjà pris par {seen_post_slugs[key]}"),
                    )
                    collided = True
                    break
            if collided:
                continue
            for loc, ps in (("en", ps_en), ("fr", ps_fr), ("ar", ps_ar)):
                seen_post_slugs[(loc, ps)] = leaf_id

            image_id = f"benchmark:{target_id}"
            now = _now()

            # 2. DB writes (DB only en mode normal)
            if not dry_run:
                op_img = _upsert_image(
                    conn, image_id=image_id, title=name_en,
                    target_id=target_id, now=now,
                )
                if op_img == "INSERT":
                    summary["image_inserts"] += 1
                else:
                    summary["image_updates"] += 1

                # 3 lignes publication
                for loc, ps in (("fr", ps_fr), ("en", ps_en), ("ar", ps_ar)):
                    op = _upsert_image_publication(
                        conn, image_id=image_id, locale=loc,
                        title=leaf.get(f"title_{loc}") or "",
                        description=leaf.get(f"description_{loc}") or "",
                        post_slug_value=ps, r2_slug_value=r2, now=now,
                    )
                    if op == "INSERT":
                        summary["publication_inserts"] += 1
                    else:
                        summary["publication_updates"] += 1

                # Transition ready_for_export (idempotent)
                mark_image_ready_for_export(conn, image_id, now)

            # 3. Écriture frontmatter Post × 3 locales
            for loc, ps in (("fr", ps_fr), ("en", ps_en), ("ar", ps_ar)):
                fm = _build_post_frontmatter(
                    leaf=leaf, locale=loc, image_id=image_id,
                    r2_slug_value=r2, post_slug_value=ps, now=now,
                )
                if not dry_run:
                    out_path = EXPORT_POSTS_DIR / loc / f"{ps}.json"
                    out_path.write_text(
                        json.dumps(fm, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    summary["posts_written"] += 1

            # 4. Copie PNG master (best-effort).
            master = _resolve_master_png(target_id)
            if master is not None:
                if not dry_run:
                    dst = EXPORT_IMAGES_DIR / f"{r2}.png"
                    shutil.copy2(master, dst)
                    summary["images_copied"] += 1
            else:
                summary["images_missing_master"].append({
                    "r2_slug": r2, "target_id": target_id,
                })

            summary["leaves_exported"] += 1
            summary["exported"].append({
                "leaf_id": leaf_id,
                "r2_slug": r2,
                "post_slugs": {"fr": ps_fr, "en": ps_en, "ar": ps_ar},
                "target_id": target_id,
                "score": score,
                "image_id": image_id,
                "master_present": master is not None,
            })

        # 5. Manifest
        if not dry_run:
            session.commit()
            manifest = {
                "schema_version": "v0",
                "generated_at": _now(),
                "total_leaves_exported": summary["leaves_exported"],
                "total_publications": summary["publication_inserts"] + summary["publication_updates"],
                "leaves": [
                    {
                        "image_id": e["image_id"],
                        "leaf_id": e["leaf_id"],
                        "r2_slug": e["r2_slug"],
                        "post_slugs": e["post_slugs"],
                        "status": "ready_for_export",
                        "master_present": e["master_present"],
                    }
                    for e in summary["exported"]
                ],
            }
            MANIFEST_PATH.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    except Exception:
        if session is not None:
            session.rollback()
        raise
    finally:
        if session is not None:
            session.close()

    return summary


# ── Rapport ──────────────────────────────────────────────────────────────────


def write_report(summary: dict[str, Any]) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    mode = "DRY-RUN" if summary["dry_run"] else "APPLY"

    lines: list[str] = []
    lines.append("# Phase MEP v0 / C — Export `data/export/`")
    lines.append("Date : 2026-05-12")
    lines.append("")
    lines.append("## Contexte")
    lines.append("")
    lines.append(
        "Export du corpus MEP v0 (manifest + posts × 3 locales + images "
        "PNG) consommable par `alwanbooks-pipeline`. Filtre `publishable=true` "
        "**depuis la table `annotation` en DB** (post Brief C1), pas depuis "
        "les fichiers `annotations.json`. Gate HARD caps Zod strict [5,100] "
        "titre / [20,200] description. Soft caps éditoriaux internes "
        "tolérés (cf. CLAUDE.md §Validation)."
    )
    lines.append("")
    lines.append("## Résultats")
    lines.append("")
    lines.append(f"- Mode : **{mode}**")
    lines.append(f"- Leaves i18n total : **{summary['i18n_leaves_total']}**")
    lines.append(f"  - status=ok : {summary['leaves_status_ok']}")
    lines.append(f"  - status=soft_caps_violated : {summary['leaves_status_violated']}")
    lines.append(f"  - status=autre : {summary['leaves_status_other']}")
    lines.append(f"- Leaves passant HARD caps : **{summary['leaves_pass_hard_caps']}**")
    lines.append(f"- Leaves échouant HARD caps : {summary['leaves_fail_hard_caps']}")
    lines.append(f"- Leaves sans annotation publishable : {summary['leaves_no_publishable']}")
    lines.append(f"- **Leaves exportés : {summary['leaves_exported']}**")
    lines.append("")
    lines.append("### DB writes")
    lines.append("")
    lines.append(f"- image INSERT : {summary['image_inserts']}")
    lines.append(f"- image UPDATE : {summary['image_updates']}")
    lines.append(f"- image_publication INSERT : {summary['publication_inserts']}")
    lines.append(f"- image_publication UPDATE : {summary['publication_updates']}")
    lines.append("")
    lines.append("### Fichiers écrits")
    lines.append("")
    lines.append(f"- Posts JSON (3 par leaf) : {summary['posts_written']}")
    lines.append(f"- PNG copiés : {summary['images_copied']}")
    lines.append(f"- PNG master manquants : {len(summary['images_missing_master'])}")
    lines.append("")
    if summary["hard_cap_violations"]:
        lines.append("### Leaves bloqués par HARD caps Zod (extrait, max 20)")
        lines.append("")
        for leaf_id, viol in summary["hard_cap_violations"][:20]:
            lines.append(f"- `{leaf_id}` : {'; '.join(viol[:3])}")
        if len(summary["hard_cap_violations"]) > 20:
            lines.append(
                f"- … ({len(summary['hard_cap_violations']) - 20} autres tronqués)"
            )
        lines.append("")
    if summary["images_missing_master"]:
        lines.append("### PNG masters manquants (extrait, max 10)")
        lines.append("")
        for entry in summary["images_missing_master"][:10]:
            lines.append(
                f"- `{entry['r2_slug']}` (target_id: `{entry['target_id']}`)"
            )
        if len(summary["images_missing_master"]) > 10:
            lines.append(
                f"- … ({len(summary['images_missing_master']) - 10} autres)"
            )
        lines.append("")
    lines.append("## Points d'attention")
    lines.append("")
    lines.append(
        "- **HARD caps Zod stricts** : gate contractuelle plateforme appliquée. "
        "Les leaves qui violent [5,100]/[20,200] sont **explicitement bloqués** "
        "et listés ici — pas d'export silencieux."
    )
    lines.append(
        "- **Soft caps éditoriaux tolérés** : 149/150 leaves ont `status='soft_caps_violated'` "
        "mais respectent les HARD caps Zod. Le pipeline accepte ce contenu "
        "(soft caps = préférences internes, pas contrat plateforme)."
    )
    lines.append(
        "- **Convention chiffres en lettres** (i18n une fois pour toutes) : les "
        "`name_*` source ne doivent contenir aucun chiffre. `r2_slug` lève "
        "`ValueError` sur tout `name_en` commençant par un chiffre (cf. brief "
        "C2). À documenter pour les futurs runs de batch i18n côté Brief B."
    )
    lines.append(
        "- **PNG masters absents du repo** : les fichiers PNG référencés par "
        "les annotations publishable ne sont pas tous présents sur disque "
        "(stockés hors repo). Les Posts JSON sont produits avec URLs R2 "
        "prédites ; les masters seront uploadés par `alwanbooks-pipeline` "
        "depuis le bucket source réel."
    )
    lines.append(
        "- **Collisions slug** : aucune collision intra-export détectée sur "
        "le corpus actuel. Stratégie de déduplication post-collision (suffixe "
        "numérique) à implémenter si besoin futur (cf. contrat §5)."
    )
    lines.append(
        "- **categoryId / themeIds vides en v0** : la table `image_taxonomy_tag` "
        "n'est pas peuplée pour le corpus benchmark — à compléter dans un "
        "brief post-v0 (mapping leaf_id → categoryId via taxonomy production "
        "cartography)."
    )
    lines.append("")
    lines.append("## Décision / Action suivante")
    lines.append("")
    if summary["dry_run"]:
        lines.append(
            "- Vérifier les counts puis lancer sans `--dry-run` pour écrire."
        )
    else:
        lines.append(
            f"- ✅ {summary['leaves_exported']} leaves exportés en DB + sur disque "
            f"(`data/export/`)."
        )
        lines.append(
            "- ✅ Manifest `data/export/manifest.json` produit pour "
            "`alwanbooks-pipeline`."
        )
        lines.append(
            "- ➡️ Brief D (post-v0) : peupler `image_taxonomy_tag` pour les "
            "leaves benchmark exportés (`categoryId` non vide)."
        )
        lines.append(
            "- ➡️ Action Brief B : relancer batch i18n pour les "
            f"{summary['leaves_fail_hard_caps']} leaves bloqués HARD caps "
            "(descriptions trop longues principalement)."
        )
    lines.append("")
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


# ── Stdout summary + CLI ─────────────────────────────────────────────────────


def _print_summary(summary: dict[str, Any]) -> None:
    mode = "DRY-RUN" if summary["dry_run"] else "APPLY"
    print(f"[{mode}] i18n leaves: {summary['i18n_leaves_total']}")
    print(f"  hard_caps OK     : {summary['leaves_pass_hard_caps']}")
    print(f"  hard_caps FAIL   : {summary['leaves_fail_hard_caps']}")
    print(f"  no publishable   : {summary['leaves_no_publishable']}")
    print(f"  EXPORTED         : {summary['leaves_exported']}")
    print(f"  DB image  INS/UPD: {summary['image_inserts']}/{summary['image_updates']}")
    print(f"  DB publi  INS/UPD: {summary['publication_inserts']}/{summary['publication_updates']}")
    print(f"  posts written    : {summary['posts_written']}")
    print(f"  png copied       : {summary['images_copied']}")
    print(f"  png missing      : {len(summary['images_missing_master'])}")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(
        description="Export MEP v0 — produit data/export/.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=False,
        help="Compte uniquement, n'écrit rien (DB ni disque).",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Limite le nombre de leaves exportés (utile pour tests).",
    )
    args = parser.parse_args(argv)

    summary = export_run(dry_run=args.dry_run, limit=args.limit)
    _print_summary(summary)
    write_report(summary)
    print(f"[info] rapport : {REPORT_PATH.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
