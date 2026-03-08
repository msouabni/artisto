"""Routes API pour la taxonomie."""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
import duckdb

from api.db import get_db

router = APIRouter(prefix="/api/taxonomy", tags=["taxonomy"])


def _to_json_safe(obj: Any) -> Any:
    """Convertit récursivement toute structure en types JSON-sérialisables (évite numpy, bytes, etc.)."""
    if obj is None:
        return None
    if hasattr(obj, "item"):  # numpy scalar (int64, float64, etc.)
        return obj.item()
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _to_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_json_safe(v) for v in obj]
    return str(obj)


def _term_row_to_dict(row: tuple, cols: list[str]) -> dict[str, Any]:
    d = dict(zip(cols, row))
    # Convertir keywords JSON en liste
    if isinstance(d.get("keywords"), str):
        try:
            d["keywords"] = json.loads(d["keywords"]) if d["keywords"] else []
        except json.JSONDecodeError:
            d["keywords"] = []
    # Normaliser types pour sérialisation JSON (DuckDB peut renvoyer numpy.int64, etc.)
    for key in ("id", "vocabulary_id", "parent_id", "slug", "slug_i18n"):
        if key in d and d[key] is not None:
            d[key] = str(d[key])
    w = d.get("weight")
    d["weight"] = int(w) if w is not None else 0
    return d


def _build_terms_tree(rows: list[dict], parent_id: str | None = None) -> list[dict]:
    """Construit l'arbre des termes avec children. Ignore les lignes sans id valide."""
    tree = []
    for r in rows:
        if r.get("parent_id") != parent_id:
            continue
        term_id = r.get("id")
        if term_id is None or (isinstance(term_id, str) and not term_id.strip()):
            continue
        children = _build_terms_tree(rows, term_id)
        w = r.get("weight")
        weight = int(w) if w is not None else 0
        node = {
            "id": str(term_id),
            "slug": str(r.get("slug") or term_id),
            "parent_id": r.get("parent_id") if r.get("parent_id") is None else str(r.get("parent_id")),
            "name_fr": _get_i18n(r.get("name_i18n"), "fr"),
            "name_en": _get_i18n(r.get("name_i18n"), "en"),
            "name_ar": _get_i18n(r.get("name_i18n"), "ar"),
            "description_fr": _get_i18n(r.get("description_i18n"), "fr"),
            "description_en": _get_i18n(r.get("description_i18n"), "en"),
            "description_ar": _get_i18n(r.get("description_i18n"), "ar"),
            "weight": weight,
            "keywords": r.get("keywords") or [],
        }
        if children:
            node["children"] = children
        tree.append(node)
    tree.sort(key=lambda t: t.get("weight") if t.get("weight") is not None else 0)
    return tree


def _get_i18n(val: str | None, key: str) -> str:
    if not val:
        return ""
    try:
        data = json.loads(val) if isinstance(val, str) else val
        out = data.get(key, "") or ""
        return str(out) if out is not None else ""
    except (json.JSONDecodeError, TypeError):
        return ""


def _to_i18n(fr: str = "", en: str = "", ar: str = "") -> str:
    d = {}
    if fr:
        d["fr"] = fr
    if en:
        d["en"] = en
    if ar:
        d["ar"] = ar
    return json.dumps(d, ensure_ascii=False) if d else "{}"


@router.get("")
def get_taxonomy(conn: duckdb.DuckDBPyConnection = Depends(get_db)) -> dict:
    """Taxonomie complète (format éditeur : name_fr, name_en, name_ar)."""
    tx = conn.execute(
        "SELECT taxonomy_id, label_i18n, languages FROM taxonomy LIMIT 1"
    ).fetchone()
    if not tx:
        raise HTTPException(status_code=404, detail="Taxonomie non trouvée")

    taxonomy_id, label_i18n, languages = tx
    label = _get_i18n(label_i18n, "fr") or _get_i18n(label_i18n, "en") or taxonomy_id
    langs = json.loads(languages) if isinstance(languages, str) else ["fr", "en", "ar"]

    vocabs = []
    for v in conn.execute(
        "SELECT id, taxonomy_id, label_i18n FROM vocabulary WHERE taxonomy_id = ?",
        [taxonomy_id],
    ).fetchall():
        vid, _, vlabel_i18n = v
        terms_rows = conn.execute(
            """
            SELECT id, vocabulary_id, parent_id, slug, slug_i18n, name_i18n, description_i18n, weight, keywords
            FROM term WHERE vocabulary_id = ?
            ORDER BY weight
            """,
            [vid],
        ).fetchall()
        cols = [
            "id",
            "vocabulary_id",
            "parent_id",
            "slug",
            "slug_i18n",
            "name_i18n",
            "description_i18n",
            "weight",
            "keywords",
        ]
        rows = [_term_row_to_dict(list(r), cols) for r in terms_rows]
        tree = _build_terms_tree(rows, None)

        vocabs.append(
            {
                "id": vid,
                "label_fr": _get_i18n(vlabel_i18n, "fr"),
                "label_en": _get_i18n(vlabel_i18n, "en"),
                "label_ar": _get_i18n(vlabel_i18n, "ar"),
                "terms": tree,
            }
        )

    return {
        "taxonomy_id": taxonomy_id,
        "label": label,
        "languages": langs,
        "vocabularies": vocabs,
    }


@router.put("")
def put_taxonomy(
    payload: dict,
    conn: duckdb.DuckDBPyConnection = Depends(get_db),
) -> dict:
    """Remplace la taxonomie complète (payload format éditeur)."""
    taxonomy_id = payload.get("taxonomy_id", "universal_v0")
    label = payload.get("label", "Taxonomie universelle v0")
    languages = payload.get("languages", ["fr", "en", "ar"])
    vocabularies = payload.get("vocabularies", [])

    label_i18n = _to_i18n(fr=label, en=label, ar=label)
    languages_json = json.dumps(languages)

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
        raise HTTPException(status_code=500, detail=str(e)) from e

    try:
        conn.execute("BEGIN")
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
    except Exception as e:
        conn.execute("ROLLBACK")
        raise HTTPException(status_code=500, detail=str(e)) from e

    return {"status": "ok", "taxonomy_id": taxonomy_id}


def _insert_terms(
    conn: duckdb.DuckDBPyConnection,
    vocabulary_id: str,
    terms: list[dict],
    parent_id: str | None,
) -> None:
    def _weight_key(x: dict) -> int:
        w = x.get("weight")
        return int(w) if w is not None else 0

    for t in sorted(terms, key=_weight_key):
        tid = t.get("id") or ""
        if not tid or not str(tid).strip():
            raise ValueError(f"Terme sans id valide (parent_id={parent_id})")
        tid = str(tid).strip()
        slug = t.get("slug") or tid
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


def _get_terms_flat(conn: duckdb.DuckDBPyConnection, vocabulary_id: str) -> list[dict]:
    """Retourne les termes d'un vocabulaire en liste plate (avec parent_id)."""
    terms_rows = conn.execute(
        """
        SELECT id, vocabulary_id, parent_id, slug, slug_i18n, name_i18n, description_i18n, weight, keywords
        FROM term WHERE vocabulary_id = ?
        ORDER BY weight
        """,
        [vocabulary_id],
    ).fetchall()
    cols = [
        "id", "vocabulary_id", "parent_id", "slug", "slug_i18n",
        "name_i18n", "description_i18n", "weight", "keywords",
    ]
    return [_term_row_to_dict(list(r), cols) for r in terms_rows]


def _term_to_response(r: dict) -> dict[str, Any]:
    """Transforme une ligne term en format API (name_fr, name_en, etc.)."""
    w = r.get("weight")
    weight = int(w) if w is not None else 0
    return {
        "id": r["id"],
        "slug": r["slug"],
        "parent_id": r.get("parent_id"),
        "name_fr": _get_i18n(r.get("name_i18n"), "fr"),
        "name_en": _get_i18n(r.get("name_i18n"), "en"),
        "name_ar": _get_i18n(r.get("name_i18n"), "ar"),
        "description_fr": _get_i18n(r.get("description_i18n"), "fr"),
        "description_en": _get_i18n(r.get("description_i18n"), "en"),
        "description_ar": _get_i18n(r.get("description_i18n"), "ar"),
        "weight": weight,
        "keywords": r.get("keywords") or [],
    }


def _get_term_references(
    conn: duckdb.DuckDBPyConnection, taxonomy_id: str, term_id: str
) -> dict[str, int]:
    """Compte les références à un terme (collections, tags, coverage_stats)."""
    refs: dict[str, int] = {}
    # image_taxonomy_tag (term_id + taxonomy_id)
    row = conn.execute(
        "SELECT COUNT(*) FROM image_taxonomy_tag WHERE taxonomy_id = ? AND term_id = ?",
        [taxonomy_id, term_id],
    ).fetchone()
    refs["image_tags"] = row[0] if row else 0
    # collection (term_id)
    row = conn.execute(
        "SELECT COUNT(*) FROM collection WHERE term_id = ?",
        [term_id],
    ).fetchone()
    refs["collections"] = row[0] if row else 0
    # coverage_stats
    row = conn.execute(
        "SELECT COUNT(*) FROM coverage_stats WHERE taxonomy_id = ? AND term_id = ?",
        [taxonomy_id, term_id],
    ).fetchone()
    refs["coverage_stats"] = row[0] if row else 0
    return refs


def _ensure_vocabulary_exists(conn: duckdb.DuckDBPyConnection, vocabulary_id: str) -> str:
    """Vérifie que le vocabulaire existe et retourne taxonomy_id."""
    row = conn.execute(
        "SELECT taxonomy_id FROM vocabulary WHERE id = ?",
        [vocabulary_id],
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Vocabulaire '{vocabulary_id}' non trouvé")
    return row[0]


@router.get("/vocabularies/{vocabulary_id}/terms")
def get_vocabulary_terms(
    vocabulary_id: str,
    conn: duckdb.DuckDBPyConnection = Depends(get_db),
):
    """Liste des termes d'un vocabulaire (arbre).
    Sérialise en bytes UTF-8 nous-mêmes : évite tout UnicodeEncodeError Windows
    et tout échec de sérialisation côté framework."""
    try:
        _ensure_vocabulary_exists(conn, vocabulary_id)
        rows = _get_terms_flat(conn, vocabulary_id)
        tree = _build_terms_tree(rows, None)
        out = {"vocabulary_id": vocabulary_id, "terms": tree}
        out = _to_json_safe(out)
        body_bytes: bytes = json.dumps(out, ensure_ascii=False).encode("utf-8")
        return Response(content=body_bytes, media_type="application/json; charset=utf-8")
    except HTTPException:
        raise
    except (TypeError, ValueError, UnicodeEncodeError) as e:
        logger.exception("get_vocabulary_terms serialization failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Sérialisation JSON : {type(e).__name__}: {e}") from e
    except Exception as e:
        logger.exception("get_vocabulary_terms failed: %s", e)
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}") from e


@router.get("/vocabularies/{vocabulary_id}/terms/{term_id}")
def get_term(
    vocabulary_id: str,
    term_id: str,
    conn: duckdb.DuckDBPyConnection = Depends(get_db),
) -> dict[str, Any]:
    """Détail d'un terme. Tables lues : term."""
    _ensure_vocabulary_exists(conn, vocabulary_id)
    rows = _get_terms_flat(conn, vocabulary_id)
    term_row = next((r for r in rows if r["id"] == term_id), None)
    if not term_row:
        raise HTTPException(status_code=404, detail=f"Terme '{term_id}' non trouvé")
    out = _term_to_response(term_row)
    out["vocabulary_id"] = vocabulary_id
    return out


@router.put("/vocabularies/{vocabulary_id}/terms/{term_id}")
def put_term(
    vocabulary_id: str,
    term_id: str,
    payload: dict,
    conn: duckdb.DuckDBPyConnection = Depends(get_db),
) -> dict[str, Any]:
    """Crée ou met à jour un terme (upsert). Tables modifiées : term."""
    taxonomy_id = _ensure_vocabulary_exists(conn, vocabulary_id)
    term_id = term_id.strip()
    if not term_id:
        raise HTTPException(status_code=400, detail="term_id vide")

    slug = (payload.get("slug") or term_id).strip() or term_id
    name_i18n = _to_i18n(
        fr=payload.get("name_fr", ""),
        en=payload.get("name_en", ""),
        ar=payload.get("name_ar", ""),
    )
    desc_i18n = _to_i18n(
        fr=payload.get("description_fr", ""),
        en=payload.get("description_en", ""),
        ar=payload.get("description_ar", ""),
    )
    weight = int(payload.get("weight", 0))
    keywords = payload.get("keywords", [])
    keywords_json = json.dumps(keywords) if keywords else "[]"
    parent_id = payload.get("parent_id")  # None pour racine

    conn.execute("BEGIN")
    try:
        existing = conn.execute(
            "SELECT 1 FROM term WHERE id = ? AND vocabulary_id = ?",
            [term_id, vocabulary_id],
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE term SET slug = ?, name_i18n = ?, description_i18n = ?, weight = ?, keywords = ?, parent_id = ?
                WHERE id = ? AND vocabulary_id = ?
                """,
                [slug, name_i18n, desc_i18n, weight, keywords_json, parent_id, term_id, vocabulary_id],
            )
        else:
            conn.execute(
                """
                INSERT INTO term (id, vocabulary_id, parent_id, slug, name_i18n, description_i18n, weight, keywords)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [term_id, vocabulary_id, parent_id, slug, name_i18n, desc_i18n, weight, keywords_json],
            )
        conn.execute("COMMIT")
    except Exception as e:
        conn.execute("ROLLBACK")
        raise HTTPException(status_code=500, detail=str(e)) from e

    return {"status": "ok", "vocabulary_id": vocabulary_id, "term_id": term_id}


@router.post("/vocabularies/{vocabulary_id}/terms")
def post_term(
    vocabulary_id: str,
    payload: dict,
    conn: duckdb.DuckDBPyConnection = Depends(get_db),
) -> dict[str, Any]:
    """Crée un terme. Tables modifiées : term. Body doit contenir id (ou généré)."""
    _ensure_vocabulary_exists(conn, vocabulary_id)
    term_id = (payload.get("id") or "").strip()
    if not term_id:
        import time
        term_id = f"term_{int(time.time() * 1000)}"
    slug = (payload.get("slug") or term_id).strip() or term_id
    name_i18n = _to_i18n(
        fr=payload.get("name_fr", ""),
        en=payload.get("name_en", ""),
        ar=payload.get("name_ar", ""),
    )
    desc_i18n = _to_i18n(
        fr=payload.get("description_fr", ""),
        en=payload.get("description_en", ""),
        ar=payload.get("description_ar", ""),
    )
    weight = int(payload.get("weight", 0))
    keywords = payload.get("keywords", [])
    keywords_json = json.dumps(keywords) if keywords else "[]"
    parent_id = payload.get("parent_id")

    conn.execute("BEGIN")
    try:
        conn.execute(
            """
            INSERT INTO term (id, vocabulary_id, parent_id, slug, name_i18n, description_i18n, weight, keywords)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [term_id, vocabulary_id, parent_id, slug, name_i18n, desc_i18n, weight, keywords_json],
        )
        conn.execute("COMMIT")
    except Exception as e:
        conn.execute("ROLLBACK")
        if "constraint" in str(e).lower() or "duplicate" in str(e).lower() or "unique" in str(e).lower():
            raise HTTPException(status_code=409, detail=f"Terme '{term_id}' existe déjà") from None
        raise HTTPException(status_code=500, detail=str(e)) from e

    return {"status": "created", "vocabulary_id": vocabulary_id, "term_id": term_id}


def _delete_term_cascade(conn: duckdb.DuckDBPyConnection, vocabulary_id: str, term_id: str) -> None:
    """Supprime un terme et récursivement tous ses enfants (sans vérifier les refs sur les enfants)."""
    children = conn.execute(
        "SELECT id FROM term WHERE vocabulary_id = ? AND parent_id = ?",
        [vocabulary_id, term_id],
    ).fetchall()
    for row in children:
        child_id = row[0] if isinstance(row, (list, tuple)) else row["id"]
        _delete_term_cascade(conn, vocabulary_id, child_id)
    conn.execute("DELETE FROM term WHERE id = ? AND vocabulary_id = ?", [term_id, vocabulary_id])


@router.delete("/vocabularies/{vocabulary_id}/terms/{term_id}")
def delete_term(
    vocabulary_id: str,
    term_id: str,
    cascade: bool = False,
    conn: duckdb.DuckDBPyConnection = Depends(get_db),
) -> dict[str, Any]:
    """Supprime un terme. 409 si le terme est référencé ou a des enfants (sauf si cascade=true).
    cascade=true : supprime le terme et tous ses descendants. Tables modifiées : term uniquement."""
    taxonomy_id = _ensure_vocabulary_exists(conn, vocabulary_id)
    refs = _get_term_references(conn, taxonomy_id, term_id)
    if any(refs.values()):
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Terme encore référencé, suppression refusée",
                "references": refs,
            },
        )
    children = conn.execute(
        "SELECT COUNT(*) FROM term WHERE vocabulary_id = ? AND parent_id = ?",
        [vocabulary_id, term_id],
    ).fetchone()
    has_children = children and children[0] > 0
    if has_children and not cascade:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Terme ayant des enfants, supprimez d'abord les enfants",
                "children_count": children[0],
            },
        )

    try:
        if cascade and has_children:
            conn.execute("BEGIN")
            try:
                _delete_term_cascade(conn, vocabulary_id, term_id)
                conn.execute("COMMIT")
            except Exception as e:
                conn.execute("ROLLBACK")
                raise HTTPException(
                    status_code=500,
                    detail={"message": "Erreur lors de la suppression en cascade", "error": str(e)},
                ) from e
        else:
            conn.execute("DELETE FROM term WHERE id = ? AND vocabulary_id = ?", [term_id, vocabulary_id])
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail={"message": "Erreur suppression terme", "error": str(e)}) from e
    return {"status": "deleted", "vocabulary_id": vocabulary_id, "term_id": term_id}


@router.get("/terms/search")
def search_terms(
    q: str = "",
    vocabulary_id: str | None = None,
    conn: duckdb.DuckDBPyConnection = Depends(get_db),
) -> dict[str, Any]:
    """Recherche de termes par id, slug ou libellés. Tables lues : term, vocabulary."""
    if not (q or "").strip():
        return {"results": []}
    q_like = f"%{(q or '').strip().lower()}%"
    if vocabulary_id:
        rows = conn.execute(
            """
            SELECT t.id, t.vocabulary_id, t.parent_id, t.slug, t.name_i18n
            FROM term t
            WHERE t.vocabulary_id = ?
            AND (LOWER(t.id) LIKE ? OR LOWER(t.slug) LIKE ?
                 OR LOWER(t.name_i18n) LIKE ?)
            ORDER BY t.vocabulary_id, t.weight
            LIMIT 50
            """,
            [vocabulary_id, q_like, q_like, q_like],
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT t.id, t.vocabulary_id, t.parent_id, t.slug, t.name_i18n
            FROM term t
            WHERE LOWER(t.id) LIKE ? OR LOWER(t.slug) LIKE ? OR LOWER(t.name_i18n) LIKE ?
            ORDER BY t.vocabulary_id, t.weight
            LIMIT 50
            """,
            [q_like, q_like, q_like],
        ).fetchall()
    cols = ["id", "vocabulary_id", "parent_id", "slug", "name_i18n"]
    results = []
    for r in rows:
        row_dict = dict(zip(cols, r))
        name_fr = _get_i18n(row_dict.get("name_i18n"), "fr")
        name_en = _get_i18n(row_dict.get("name_i18n"), "en")
        results.append({
            "id": row_dict["id"],
            "vocabulary_id": row_dict["vocabulary_id"],
            "parent_id": row_dict["parent_id"],
            "slug": row_dict["slug"],
            "name_fr": name_fr,
            "name_en": name_en,
        })
    return {"results": results}


@router.get("/export/json")
def export_taxonomy_json(conn: duckdb.DuckDBPyConnection = Depends(get_db)) -> dict:
    """Export JSON (même format que GET)."""
    return get_taxonomy(conn)
