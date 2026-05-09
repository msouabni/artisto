"""Rechargement de la taxonomie après purge.

Format source attendu : liste JSON de racines, chaque racine ayant des
``children`` (sous-thèmes), chaque sous-thème ayant des ``children`` (feuilles).
Chaque nœud porte ``id``, ``name_en``, ``name_fr``, ``name_ar``, et un objet
``seo`` optionnel.

Mapping vers le schéma :
- 1 ligne ``taxonomy`` (id="coloring_themes")
- 1 ligne ``vocabulary`` (id="themes", taxonomy_id="coloring_themes")
- 1 ligne ``term`` par nœud ; ``parent_id=null`` pour les racines, sinon id
  du parent. ``vocabulary_id="themes"``.

Le champ ``seo`` (si présent) est mappé sur ``term.metadata`` (JSONB sur Postgres,
JSON sur SQLite via le type ``sa.JSON`` cross-dialect). Migration Alembic
``0005_term_metadata_jsonb`` requise. Le champ ``keywords`` reste NULL (réservé
à un usage différent côté code).

Le ``level`` est calculé pour les stats post-import (0=racine, 1=sous-thème,
2=feuille) mais n'est pas persisté (pas de colonne dédiée).

Usage :
    python scripts/db_reload.py docs/xchange/coloring_taxonomy_seo.json
"""
from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

from sqlalchemy import text  # noqa: E402

from api.db import ENGINE  # noqa: E402

TAXONOMY_ID = "coloring_themes"
VOCABULARY_ID = "themes"
LANGUAGES = ["fr", "en", "ar"]


# ════════════════════════════════════════════════════════════════════════════
# ÉTAPE 1 : validation du fichier source
# ════════════════════════════════════════════════════════════════════════════
def _walk(nodes, depth=0):
    """Itère (depth, node) pour tous les nœuds (DFS)."""
    for n in nodes:
        yield depth, n
        for sub in _walk(n.get("children") or [], depth + 1):
            yield sub


def validate_source(roots) -> tuple[list[str], dict]:
    """Valide la structure et renvoie (errors, stats)."""
    errors: list[str] = []
    if not isinstance(roots, list):
        errors.append("source root is not a list")
        return errors, {}
    seen_ids: set[str] = set()
    counts_by_level = {0: 0, 1: 0, 2: 0, 3: 0}
    for depth, node in _walk(roots):
        if not isinstance(node, dict):
            errors.append(f"non-dict node at depth {depth}: {node!r}")
            continue
        nid = node.get("id")
        if not nid or not isinstance(nid, str):
            errors.append(f"missing/invalid id at depth {depth}: {node}")
            continue
        if nid in seen_ids:
            errors.append(f"duplicate id: {nid!r}")
        seen_ids.add(nid)
        for fld in ("name_en", "name_fr", "name_ar"):
            v = node.get(fld)
            if not v or not isinstance(v, str) or not v.strip():
                errors.append(f"node {nid!r} : missing/empty {fld}")
        counts_by_level[min(depth, 3)] = counts_by_level.get(min(depth, 3), 0) + 1
    return errors, {"total_nodes": len(seen_ids), "counts_by_level": counts_by_level}


# ════════════════════════════════════════════════════════════════════════════
# ÉTAPE 2 : import dans l'ordre FK correct (parents AVANT enfants)
# ════════════════════════════════════════════════════════════════════════════
def _to_i18n_json(en: str, fr: str, ar: str = "") -> str:
    d = {"en": en or "", "fr": fr or ""}
    if ar:
        d["ar"] = ar
    return json.dumps(d, ensure_ascii=False)


def import_taxonomy(roots, engine) -> dict:
    """Insère taxonomy → vocabulary → racines → sous-thèmes → feuilles."""
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    inserted = {"taxonomy": 0, "vocabulary": 0, "term": 0, "by_level": {0: 0, 1: 0, 2: 0}}

    with engine.begin() as conn:
        # 2.1 — taxonomy
        conn.execute(
            text("""
                INSERT INTO taxonomy (taxonomy_id, label_i18n, languages, created_at, updated_at)
                VALUES (:tid, :label, :langs, :now, :now)
            """),
            {
                "tid": TAXONOMY_ID,
                "label": json.dumps({"en": "Coloring Themes", "fr": "Thèmes de coloriage", "ar": "موضوعات التلوين"}, ensure_ascii=False),
                "langs": json.dumps(LANGUAGES),
                "now": now,
            },
        )
        inserted["taxonomy"] = 1

        # 2.2 — vocabulary
        conn.execute(
            text("""
                INSERT INTO vocabulary (id, taxonomy_id, label_i18n, created_at, updated_at)
                VALUES (:vid, :tid, :label, :now, :now)
            """),
            {
                "vid": VOCABULARY_ID,
                "tid": TAXONOMY_ID,
                "label": json.dumps({"en": "Themes", "fr": "Thèmes", "ar": "الموضوعات"}, ensure_ascii=False),
                "now": now,
            },
        )
        inserted["vocabulary"] = 1

        # 2.3 — terms en BFS (parents avant enfants).
        #       parent_id à null pour les racines. seo → metadata (JSONB).
        def _insert_node(node: dict, parent_id: str | None, weight: int, depth: int) -> None:
            seo = node.get("seo")
            meta_json = json.dumps(seo, ensure_ascii=False) if isinstance(seo, dict) else None
            conn.execute(
                text("""
                    INSERT INTO term (id, vocabulary_id, parent_id, slug, name_i18n,
                                      weight, metadata, created_at, updated_at)
                    VALUES (:id, :vid, :pid, :slug, :name_i18n, :w,
                            CAST(:meta AS jsonb), :now, :now)
                """),
                {
                    "id": node["id"],
                    "vid": VOCABULARY_ID,
                    "pid": parent_id,
                    "slug": node["id"],  # slug = id (kebab/snake déjà conforme)
                    "name_i18n": _to_i18n_json(
                        node.get("name_en", ""), node.get("name_fr", ""), node.get("name_ar", "")
                    ),
                    "w": weight,
                    "meta": meta_json,
                    "now": now,
                },
            )
            inserted["term"] += 1
            inserted["by_level"][depth] = inserted["by_level"].get(depth, 0) + 1

        # BFS niveau par niveau
        # Niveau 0 — racines
        for w, root in enumerate(roots):
            _insert_node(root, None, w, 0)
        # Niveau 1 — sous-thèmes
        for root in roots:
            for w, sub in enumerate(root.get("children") or []):
                _insert_node(sub, root["id"], w, 1)
        # Niveau 2 — feuilles
        for root in roots:
            for sub in root.get("children") or []:
                for w, leaf in enumerate(sub.get("children") or []):
                    _insert_node(leaf, sub["id"], w, 2)

    return inserted


# ════════════════════════════════════════════════════════════════════════════
# ÉTAPE 3 : vérification post-import
# ════════════════════════════════════════════════════════════════════════════
def verify_post_import(source_stats: dict, inserted: dict, engine) -> dict:
    """Comptages réels vs attendus + sanity checks."""
    expected_total = source_stats["total_nodes"]
    report: dict = {"errors": [], "warnings": [], "checks": {}}

    with engine.connect() as conn:
        # Comptages globaux
        n_tax = conn.execute(text('SELECT COUNT(*) FROM "taxonomy"')).scalar() or 0
        n_voc = conn.execute(text('SELECT COUNT(*) FROM "vocabulary"')).scalar() or 0
        n_term = conn.execute(text('SELECT COUNT(*) FROM "term"')).scalar() or 0
        report["checks"]["taxonomy_count"] = {"expected": 1, "actual": n_tax}
        report["checks"]["vocabulary_count"] = {"expected": 1, "actual": n_voc}
        report["checks"]["term_count"] = {"expected": expected_total, "actual": n_term}
        if n_tax != 1:
            report["errors"].append(f"taxonomy count expected 1, got {n_tax}")
        if n_voc != 1:
            report["errors"].append(f"vocabulary count expected 1, got {n_voc}")
        if n_term != expected_total:
            report["errors"].append(f"term count expected {expected_total}, got {n_term}")

        # Comptages par niveau (parent_id NULL = racine ; parent qui pointe vers une racine = sous-thème ; etc.)
        n_roots = conn.execute(text('SELECT COUNT(*) FROM "term" WHERE parent_id IS NULL')).scalar() or 0
        n_lvl1 = conn.execute(text("""
            SELECT COUNT(*) FROM "term" t
            WHERE t.parent_id IN (SELECT id FROM "term" WHERE parent_id IS NULL)
        """)).scalar() or 0
        n_lvl2 = n_term - n_roots - n_lvl1
        report["checks"]["level_counts"] = {
            "expected": source_stats["counts_by_level"],
            "actual": {0: n_roots, 1: n_lvl1, 2: n_lvl2},
        }

        # FK : aucun term avec parent_id pointant vers un term inexistant
        orphans = conn.execute(text("""
            SELECT t.id, t.parent_id FROM "term" t
            LEFT JOIN "term" p ON p.id = t.parent_id
            WHERE t.parent_id IS NOT NULL AND p.id IS NULL
        """)).fetchall()
        report["checks"]["orphan_parents"] = len(orphans)
        if orphans:
            report["errors"].append(
                f"{len(orphans)} term(s) avec parent_id introuvable : {[(r[0], r[1]) for r in orphans[:5]]}"
            )

        # Sanity AR : 5 feuilles aléatoires (PostgreSQL ORDER BY RANDOM())
        sample_rows = conn.execute(text("""
            SELECT id, name_i18n FROM "term"
            WHERE id NOT IN (SELECT DISTINCT parent_id FROM "term" WHERE parent_id IS NOT NULL)
            ORDER BY RANDOM() LIMIT 5
        """)).fetchall()
        ar_check = []
        for row in sample_rows:
            d = dict(row._mapping)
            try:
                names = json.loads(d.get("name_i18n") or "{}")
            except json.JSONDecodeError:
                names = {}
            name_ar = (names.get("ar") or "").strip()
            ar_check.append({"id": d["id"], "name_ar_present": bool(name_ar), "name_ar": name_ar[:40]})
            if not name_ar:
                report["warnings"].append(f"feuille {d['id']!r} : name_ar absent")
        report["checks"]["sample_leaves_ar"] = ar_check

        # Couverture AR globale
        all_terms = conn.execute(text('SELECT name_i18n FROM "term"')).fetchall()
        ar_present = 0
        for row in all_terms:
            try:
                names = json.loads(row[0] or "{}")
            except json.JSONDecodeError:
                names = {}
            if (names.get("ar") or "").strip():
                ar_present += 1
        report["checks"]["ar_coverage"] = f"{ar_present}/{n_term}"
        if ar_present < n_term:
            report["warnings"].append(f"{n_term - ar_present} terme(s) sans name_ar")

    return report


# ════════════════════════════════════════════════════════════════════════════
# Main
# ════════════════════════════════════════════════════════════════════════════
def main() -> int:
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} path/to/source.json", file=sys.stderr)
        return 2
    source_path = Path(sys.argv[1])
    if not source_path.exists():
        print(f"❌ Fichier introuvable : {source_path}", file=sys.stderr)
        return 2

    print("=" * 80)
    print(f"DB Reload — taxonomie depuis {source_path}")
    print("=" * 80)

    print("\n[1] Lecture + validation")
    roots = json.loads(source_path.read_text(encoding="utf-8"))
    errors, stats = validate_source(roots)
    print(f"  total nodes : {stats['total_nodes']}")
    print(f"  par niveau  : {stats['counts_by_level']}")
    if errors:
        print(f"  ❌ {len(errors)} erreur(s) de validation :")
        for e in errors[:10]:
            print(f"     - {e}")
        if len(errors) > 10:
            print(f"     ... et {len(errors) - 10} de plus")
        return 3
    print("  ✓ validation OK")

    print("\n[2] Import")
    inserted = import_taxonomy(roots, ENGINE)
    print(f"  taxonomy   : {inserted['taxonomy']}")
    print(f"  vocabulary : {inserted['vocabulary']}")
    print(f"  term       : {inserted['term']}  par niveau : {inserted['by_level']}")

    print("\n[3] Vérification post-import")
    report = verify_post_import(stats, inserted, ENGINE)
    for k, v in report["checks"].items():
        print(f"  {k}: {v}")
    print(f"  errors  : {len(report['errors'])}")
    print(f"  warnings: {len(report['warnings'])}")
    for w in report["warnings"][:5]:
        print(f"     ⚠ {w}")
    if report["errors"]:
        print("  ❌ ERRORS:")
        for e in report["errors"]:
            print(f"     - {e}")

    # Sauvegarder le rapport pour le .md final
    out = PROJECT_ROOT / "scripts" / "_reload_summary.json"
    out.write_text(
        json.dumps(
            {"source_stats": stats, "inserted": inserted, "verification": report},
            ensure_ascii=False, indent=2, default=str,
        ),
        encoding="utf-8",
    )
    print(f"\nRécap → {out}")
    return 0 if not report["errors"] else 4


if __name__ == "__main__":
    sys.exit(main())
