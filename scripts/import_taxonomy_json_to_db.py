#!/usr/bin/env python3
"""
Importe taxonomy_universal_v0.json dans la base DuckDB.
Usage: python scripts/import_taxonomy_json_to_db.py [chemin_json] [chemin_db]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_JSON = DATA_DIR / "taxonomy_universal_v0.json"
DEFAULT_DB = DATA_DIR / "artiste_coloriage.duckdb"


def _to_i18n(fr: str = "", en: str = "", ar: str = "") -> str:
    d = {}
    if fr:
        d["fr"] = fr
    if en:
        d["en"] = en
    if ar:
        d["ar"] = ar
    return json.dumps(d, ensure_ascii=False) if d else "{}"


def _insert_terms(conn, vocabulary_id: str, terms: list[dict], parent_id: str | None) -> None:
    for t in sorted(terms, key=lambda x: x.get("weight", 0)):
        tid = t.get("id", "")
        slug = t.get("slug", tid)
        name_i18n = _to_i18n(
            fr=t.get("name_fr", ""),
            en=t.get("name_en", ""),
            ar=t.get("name_ar", ""),
        )
        desc_i18n = _to_i18n(
            fr=t.get("description_fr", ""),
            en=t.get("description_en", ""),
            ar=t.get("description_ar", ""),
        )
        keywords = t.get("keywords", [])
        keywords_json = json.dumps(keywords) if keywords else "[]"
        weight = int(t.get("weight", 0))

        conn.execute(
            """
            INSERT INTO term (id, vocabulary_id, parent_id, slug, name_i18n, description_i18n, weight, keywords)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [tid, vocabulary_id, parent_id, slug, name_i18n, desc_i18n, weight, keywords_json],
        )
        children = t.get("children", [])
        if children:
            _insert_terms(conn, vocabulary_id, children, tid)


def import_json(json_path: Path, db_path: Path) -> None:
    """Importe le JSON dans DuckDB."""
    import duckdb

    if not json_path.exists():
        raise FileNotFoundError(f"JSON not found: {json_path}")

    data = json.loads(json_path.read_text(encoding="utf-8"))
    taxonomy_id = data.get("taxonomy_id", "universal_v0")
    label = data.get("label", "Taxonomie universelle v0")
    languages = data.get("languages", ["fr", "en", "ar"])
    vocabularies = data.get("vocabularies", [])

    label_i18n = _to_i18n(fr=label, en=label, ar=label)
    languages_json = json.dumps(languages)

    # Init schéma si nécessaire
    schema_path = DATA_DIR / "schema.sql"
    if schema_path.exists():
        conn = duckdb.connect(str(db_path))
        for stmt in schema_path.read_text(encoding="utf-8").split(";"):
            stmt = stmt.strip()
            if stmt and not stmt.startswith("--"):
                try:
                    conn.execute(stmt)
                except Exception:
                    pass  # ignore "already exists"
        conn.close()

    conn = duckdb.connect(str(db_path))

    # DuckDB valide les FK trop tôt dans une même transaction.
    # Suppressions sans transaction (auto-commit), ordre enfants → parents.
    # Voir .cursor/rules/duckdb-fk-constraints.mdc
    try:
        conn.execute("DELETE FROM term")
        conn.execute("DELETE FROM export")
        conn.execute("DELETE FROM collection_image")
        conn.execute("DELETE FROM collection")
        conn.execute("DELETE FROM image_taxonomy_tag")
        conn.execute("DELETE FROM coverage_stats")
        conn.execute("DELETE FROM site_taxonomy")
        conn.execute("DELETE FROM vocabulary")
        conn.execute("DELETE FROM taxonomy")
    except Exception as e:
        conn.close()
        raise

    conn.execute("BEGIN")
    try:
        conn.execute(
            "INSERT INTO taxonomy (taxonomy_id, label_i18n, languages) VALUES (?, ?, ?)",
            [taxonomy_id, label_i18n, languages_json],
        )

        for v in vocabularies:
            vid = v.get("id", "themes")
            vlabel_i18n = _to_i18n(
                fr=v.get("label_fr", ""),
                en=v.get("label_en", ""),
                ar=v.get("label_ar", ""),
            )
            conn.execute(
                "INSERT INTO vocabulary (id, taxonomy_id, label_i18n) VALUES (?, ?, ?)",
                [vid, taxonomy_id, vlabel_i18n],
            )
            _insert_terms(conn, vid, v.get("terms", []), None)

        conn.execute("COMMIT")
        print(f"Importé: {taxonomy_id} ({len(vocabularies)} vocabulaire(s)) -> {db_path}")
    except Exception as e:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    json_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_JSON
    db_path = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_DB
    import_json(json_path, db_path)
