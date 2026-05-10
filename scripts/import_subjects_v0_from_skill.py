#!/usr/bin/env python3
"""Import subjects v0 depuis la taxonomie de référence skill v0.

Source canonique : ``data/prompt_generator/coloring_taxonomy_full.json`` (1376 leaves).

Pour chaque leaf de la taxonomie :
  - Vérifie qu'un term correspondant existe en BD (table ``term``).
  - Vérifie qu'aucun subject ``(term_id=<leaf>, source='skill_v0')`` n'existe déjà.
  - Insère un subject minimal (status='draft', tags=[], prompt_positive=NULL).

Idempotent : 2 runs consécutifs n'insèrent rien la 2e fois.

CLI :
    python scripts/import_subjects_v0_from_skill.py --dry-run
    python scripts/import_subjects_v0_from_skill.py --limit 10
    python scripts/import_subjects_v0_from_skill.py --source skill_v0
    python scripts/import_subjects_v0_from_skill.py --rapport-dir data/import

Dépendance : V1.2 (modèle ``Subject`` + migration ``0007_subject_table.py``)
doit être livré avant l'exécution réelle. Le script est utilisable
techniquement dès que ``api.models.Subject`` existe.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

DEFAULT_TAXONOMY_PATH = (
    PROJECT_ROOT / "data" / "prompt_generator" / "coloring_taxonomy_full.json"
)
DEFAULT_RAPPORT_DIR = PROJECT_ROOT / "data" / "import"
DEFAULT_REPORT_MD = PROJECT_ROOT / "docs" / "reports" / "2026-05-10_import-subjects-v0-skill.md"

LOGGER = logging.getLogger("import_subjects_v0")


# ---------------------------------------------------------------------------
# Taxonomie : aplatissement
# ---------------------------------------------------------------------------

def load_taxonomy(path: Path) -> list[dict[str, Any]]:
    """Charge le JSON taxonomie (liste de roots)."""
    if not path.exists():
        raise FileNotFoundError(f"Taxonomy JSON not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def flatten_leaves(roots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aplatit l'arbre en liste de leaves.

    Une leaf = noeud sans ``children`` (ou avec ``children`` vide).
    Renvoie : ``[{leaf_id, name_en, root, path}]``.
    """
    leaves: list[dict[str, Any]] = []

    def walk(node: dict[str, Any], path: list[str], root: str) -> None:
        children = node.get("children") or []
        if children:
            for c in children:
                walk(c, path + [node["id"]], root)
        else:
            leaves.append(
                {
                    "leaf_id": node["id"],
                    "name_en": node.get("name_en") or node["id"],
                    "name_fr": node.get("name_fr"),
                    "name_ar": node.get("name_ar"),
                    "root": root,
                    "path": path + [node["id"]],
                }
            )

    for root_node in roots:
        walk(root_node, [], root_node["id"])

    return leaves


# ---------------------------------------------------------------------------
# Import : insertion idempotente
# ---------------------------------------------------------------------------

def _make_subject_id(leaf_id: str) -> str:
    """Convention id stable et traçable humainement."""
    return f"sub_{leaf_id}"


def _term_exists(session, term_id: str) -> bool:
    """Vérifie qu'un term existe (compte robuste).

    Note: ``term`` a une PK composite ``(id, vocabulary_id)`` dans le schéma
    actuel mais ``id`` reste unique en pratique pour les leaves taxonomie.
    """
    from sqlalchemy import text as sql_text

    row = session.execute(
        sql_text("SELECT 1 FROM term WHERE id = :tid LIMIT 1"),
        {"tid": term_id},
    ).first()
    return row is not None


def _subject_already_imported(session, term_id: str, source: str) -> bool:
    from sqlalchemy import text as sql_text

    row = session.execute(
        sql_text(
            "SELECT 1 FROM subject WHERE term_id = :tid AND source = :src LIMIT 1"
        ),
        {"tid": term_id, "src": source},
    ).first()
    return row is not None


def import_subjects(
    session,
    leaves: list[dict[str, Any]],
    *,
    source: str = "skill_v0",
    dry_run: bool = False,
    limit: int | None = None,
    import_run_ts: str | None = None,
) -> dict[str, Any]:
    """Insère un subject par leaf, idempotent.

    Renvoie un dict de stats : ``inserted``, ``already_present``, ``orphans``,
    ``per_root``, ``samples``, ``total_leaves``.
    """
    # Import lazy de Subject : laisse les tests injecter leur propre modèle
    # dans Base.metadata avant l'appel à ce script.
    try:
        from api.models import Subject  # type: ignore
    except ImportError as exc:  # pragma: no cover - branche post-V1.2
        raise RuntimeError(
            "Le modèle Subject n'est pas disponible. "
            "V1.2 (brief modele-subject) doit être mergé avant l'import réel."
        ) from exc

    if import_run_ts is None:
        import_run_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    stats: dict[str, Any] = {
        "total_leaves": len(leaves),
        "considered": 0,
        "inserted": 0,
        "already_present": 0,
        "orphans": [],          # leaves dont term_id n'existe pas en BD
        "per_root": {},         # root -> count inséré
        "samples": [],          # 10 derniers insérés (id, term_id, name)
        "source": source,
        "dry_run": dry_run,
        "import_run": import_run_ts,
    }

    # Tri stable pour reproductibilité (NULL-safe : leaf_id est non-null par construction)
    leaves_sorted = sorted(leaves, key=lambda x: x["leaf_id"] or "")

    if limit is not None and limit >= 0:
        leaves_sorted = leaves_sorted[:limit]

    for leaf in leaves_sorted:
        stats["considered"] += 1
        leaf_id = leaf["leaf_id"]
        name_en = leaf["name_en"]
        root = leaf["root"]

        if not _term_exists(session, leaf_id):
            stats["orphans"].append(
                {"leaf_id": leaf_id, "root": root, "reason": "no term row"}
            )
            continue

        if _subject_already_imported(session, leaf_id, source):
            stats["already_present"] += 1
            continue

        subject_id = _make_subject_id(leaf_id)

        if dry_run:
            stats["inserted"] += 1
            stats["per_root"][root] = stats["per_root"].get(root, 0) + 1
            if len(stats["samples"]) < 10:
                stats["samples"].append(
                    {"id": subject_id, "term_id": leaf_id, "name": name_en}
                )
            continue

        subject = Subject(
            id=subject_id,
            term_id=leaf_id,
            name=name_en,
            source=source,
            tags=[],
            note=None,
            status="draft",
            enrichment=None,
            prompt_positive=None,
            metadata_={
                "imported_from": "coloring_taxonomy_full.json",
                "import_run": import_run_ts,
                "root": root,
                "path": leaf["path"],
            },
        )
        session.add(subject)
        # Flush pour détecter les violations d'unicité tôt et avancer le compteur réel.
        session.flush()
        stats["inserted"] += 1
        stats["per_root"][root] = stats["per_root"].get(root, 0) + 1
        if len(stats["samples"]) < 10:
            stats["samples"].append(
                {"id": subject_id, "term_id": leaf_id, "name": name_en}
            )

    if not dry_run:
        session.commit()

    return stats


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def write_json_report(stats: dict[str, Any], rapport_dir: Path) -> Path:
    rapport_dir.mkdir(parents=True, exist_ok=True)
    ts = stats.get("import_run") or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = rapport_dir / f"subjects_v0_{ts}.json"
    out.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def render_markdown_report(stats: dict[str, Any], json_path: Path | None) -> str:
    lines: list[str] = []
    lines.append("# Import — subjects v0 (skill)")
    lines.append(f"Date : 2026-05-10")
    lines.append("")
    lines.append("## Contexte")
    lines.append(
        "Import idempotent des leaves de `coloring_taxonomy_full.json` "
        "vers la table `subject` (source='skill_v0', status='draft'). "
        "Source : skill `prompt-taxonomy-ecosystem` v0."
    )
    lines.append("")
    lines.append("## Compteurs")
    lines.append("")
    lines.append("| Mesure | Valeur |")
    lines.append("|---|---|")
    lines.append(f"| Total leaves taxonomie | {stats['total_leaves']} |")
    lines.append(f"| Leaves considérés (limit appliqué) | {stats['considered']} |")
    lines.append(f"| Subjects insérés | {stats['inserted']} |")
    lines.append(f"| Subjects déjà présents (idempotence) | {stats['already_present']} |")
    lines.append(f"| Leaves orphelins (sans term en BD) | {len(stats['orphans'])} |")
    lines.append(f"| Source | `{stats['source']}` |")
    lines.append(f"| Dry-run | {stats['dry_run']} |")
    lines.append(f"| Import run id | `{stats['import_run']}` |")
    lines.append("")

    lines.append("## Distribution par root")
    lines.append("")
    if stats["per_root"]:
        lines.append("| Root | Subjects insérés |")
        lines.append("|---|---|")
        for root, count in sorted(
            stats["per_root"].items(), key=lambda x: -(x[1] or 0)
        ):
            lines.append(f"| {root} | {count} |")
    else:
        lines.append("_Aucun subject inséré ce run._")
    lines.append("")

    lines.append("## Échantillon (10 premiers)")
    lines.append("")
    if stats["samples"]:
        lines.append("| id | term_id | name |")
        lines.append("|---|---|---|")
        for s in stats["samples"]:
            lines.append(f"| `{s['id']}` | `{s['term_id']}` | {s['name']} |")
    else:
        lines.append("_Aucun échantillon (rien inséré)._")
    lines.append("")

    lines.append("## Liste orphelins")
    lines.append("")
    if stats["orphans"]:
        lines.append(
            "Leaves de la taxonomie pour lesquels aucune ligne `term` n'existe "
            "en BD. À régler avant import définitif (seed `term` complet)."
        )
        lines.append("")
        lines.append("| leaf_id | root | raison |")
        lines.append("|---|---|---|")
        # Afficher max 50 pour lisibilité
        for o in stats["orphans"][:50]:
            lines.append(f"| `{o['leaf_id']}` | {o['root']} | {o['reason']} |")
        if len(stats["orphans"]) > 50:
            lines.append(
                f"| _... {len(stats['orphans']) - 50} autres tronqués (voir JSON)_ | | |"
            )
    else:
        lines.append("_Aucun orphelin — tous les leaves ont un term en BD._")
    lines.append("")

    lines.append("## Décision / Action suivante")
    lines.append("")
    inserted = stats["inserted"]
    already = stats["already_present"]
    orphans = len(stats["orphans"])
    if stats["dry_run"]:
        lines.append(
            f"**Dry-run** — aucun écrit. {inserted} subjects seraient insérés, "
            f"{already} déjà présents, {orphans} orphelins."
        )
    elif inserted == 0 and already > 0 and orphans == 0:
        lines.append(
            "**Idempotence vérifiée** — aucun nouveau subject (tous déjà présents). "
            "OK pour itérer sur l'aval (annotation, enrichment, prompt_positive)."
        )
    elif orphans > 0:
        lines.append(
            f"**À régler** — {orphans} leaves sans `term` en BD. "
            "Re-seeder la taxonomie (`scripts/import_taxonomy_json_to_db.py`) "
            "ou enquêter sur les divergences leaf_id avant nouveau run."
        )
    else:
        lines.append(
            f"**Go** — {inserted} subjects insérés, {already} déjà présents. "
            "Prochaine étape : annotation manuelle (Vague 2) puis "
            "génération de `prompt_positive` (job `subject_prompt_generation`)."
        )

    if json_path is not None:
        lines.append("")
        lines.append(f"Rapport JSON brut : `{json_path.relative_to(PROJECT_ROOT)}`")

    return "\n".join(lines) + "\n"


def write_markdown_report(stats: dict[str, Any], md_path: Path, json_path: Path | None) -> Path:
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_markdown_report(stats, json_path), encoding="utf-8")
    return md_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import idempotent subjects v0 depuis taxonomie skill."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="N'écrit rien en BD — affiche/produit le résumé attendu.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limite à N leaves (utile pour tests).",
    )
    parser.add_argument(
        "--source",
        type=str,
        default="skill_v0",
        help="Override de la valeur 'source' (default: skill_v0).",
    )
    parser.add_argument(
        "--rapport-dir",
        type=Path,
        default=DEFAULT_RAPPORT_DIR,
        help="Dossier de sortie pour le rapport JSON.",
    )
    parser.add_argument(
        "--md-report",
        type=Path,
        default=DEFAULT_REPORT_MD,
        help="Chemin de sortie du rapport Markdown.",
    )
    parser.add_argument(
        "--taxonomy-path",
        type=Path,
        default=DEFAULT_TAXONOMY_PATH,
        help="Chemin du JSON taxonomie source.",
    )
    parser.add_argument(
        "--no-md",
        action="store_true",
        help="N'écrit pas le rapport Markdown (utile en CI).",
    )
    return parser


def run_cli(argv: list[str] | None = None) -> dict[str, Any]:
    """Entrée CLI testable. Retourne les stats."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)

    LOGGER.info("Loading taxonomy from %s", args.taxonomy_path)
    roots = load_taxonomy(args.taxonomy_path)
    leaves = flatten_leaves(roots)
    LOGGER.info("Found %d leaves", len(leaves))

    from api.db import SessionLocal  # type: ignore

    session = SessionLocal()
    try:
        stats = import_subjects(
            session,
            leaves,
            source=args.source,
            dry_run=args.dry_run,
            limit=args.limit,
        )
    finally:
        session.close()

    json_path = write_json_report(stats, args.rapport_dir)
    LOGGER.info("JSON report: %s", json_path)

    if not args.no_md:
        md_path = write_markdown_report(stats, args.md_report, json_path)
        LOGGER.info("Markdown report: %s", md_path)

    LOGGER.info(
        "Done — inserted=%d already=%d orphans=%d (dry_run=%s)",
        stats["inserted"],
        stats["already_present"],
        len(stats["orphans"]),
        stats["dry_run"],
    )
    return stats


if __name__ == "__main__":  # pragma: no cover
    run_cli()
