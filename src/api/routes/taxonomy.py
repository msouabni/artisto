"""Routes API pour la taxonomie."""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Body, Depends, HTTPException

from api.db import DBConnAdapter, get_db_read, get_db_write
from api.helpers import get_i18n, json_response, to_i18n, to_json_safe, transaction

router = APIRouter(prefix="/api/taxonomy", tags=["taxonomy"])


def _term_row_to_dict(row: tuple, cols: list[str]) -> dict[str, Any]:
    d = dict(zip(cols, row))
    # Convertir keywords JSON en liste
    if isinstance(d.get("keywords"), str):
        try:
            d["keywords"] = json.loads(d["keywords"]) if d["keywords"] else []
        except json.JSONDecodeError:
            d["keywords"] = []
    for key in ("id", "vocabulary_id", "parent_id", "slug", "slug_i18n"):
        if key in d and d[key] is not None:
            d[key] = str(d[key])
    w = d.get("weight")
    d["weight"] = int(w) if w is not None else 0
    sc = d.get("subjects_count")
    d["subjects_count"] = int(sc) if sc is not None else 0
    cc = d.get("concept_count")
    d["concept_count"] = int(cc) if cc is not None else 0
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
        sc = r.get("subjects_count")
        subjects_count = int(sc) if sc is not None else 0
        cc = r.get("concept_count")
        concept_count = int(cc) if cc is not None else 0
        node = {
            "id": str(term_id),
            "slug": str(r.get("slug") or term_id),
            "parent_id": r.get("parent_id") if r.get("parent_id") is None else str(r.get("parent_id")),
            "name_fr": get_i18n(r.get("name_i18n"), "fr"),
            "name_en": get_i18n(r.get("name_i18n"), "en"),
            "name_ar": get_i18n(r.get("name_i18n"), "ar"),
            "description_fr": get_i18n(r.get("description_i18n"), "fr"),
            "description_en": get_i18n(r.get("description_i18n"), "en"),
            "description_ar": get_i18n(r.get("description_i18n"), "ar"),
            "weight": weight,
            "keywords": r.get("keywords") or [],
            "subjects_count": subjects_count,
            "concept_count": concept_count,
        }
        if children:
            node["children"] = children
        tree.append(node)
    tree.sort(key=lambda t: t.get("weight") if t.get("weight") is not None else 0)
    return tree



# get_i18n, to_i18n, to_json_safe, json_response, transaction → importés depuis api.helpers

@router.get("")
def get_taxonomy(conn: DBConnAdapter = Depends(get_db_read)) -> dict:
    """Taxonomie complète (format éditeur : name_fr, name_en, name_ar)."""
    tx = conn.execute(
        "SELECT taxonomy_id, label_i18n, languages FROM taxonomy LIMIT 1"
    ).fetchone()
    if not tx:
        raise HTTPException(status_code=404, detail="Taxonomie non trouvée")

    taxonomy_id, label_i18n, languages = tx
    label = get_i18n(label_i18n, "fr") or get_i18n(label_i18n, "en") or taxonomy_id
    langs = json.loads(languages) if isinstance(languages, str) else ["fr", "en", "ar"]

    vocabs = []
    for v in conn.execute(
        "SELECT id, taxonomy_id, label_i18n FROM vocabulary WHERE taxonomy_id = ?",
        [taxonomy_id],
    ).fetchall():
        vid, _, vlabel_i18n = v
        rows = _get_terms_flat(conn, vid)
        tree = _build_terms_tree(rows, None)

        vocabs.append(
            {
                "id": vid,
                "label_fr": get_i18n(vlabel_i18n, "fr"),
                "label_en": get_i18n(vlabel_i18n, "en"),
                "label_ar": get_i18n(vlabel_i18n, "ar"),
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
    conn: DBConnAdapter = Depends(get_db_write),
) -> dict:
    """Remplace la taxonomie complète (payload format éditeur)."""
    taxonomy_id = payload.get("taxonomy_id", "universal_v0")
    label = payload.get("label", "Taxonomie universelle v0")
    languages = payload.get("languages", ["fr", "en", "ar"])
    vocabularies = payload.get("vocabularies", [])

    label_i18n = to_i18n(fr=label, en=label, ar=label)
    languages_json = json.dumps(languages)

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

    with transaction(conn):
        conn.execute(
            "INSERT INTO taxonomy (taxonomy_id, label_i18n, languages) VALUES (?, ?, ?)",
            [taxonomy_id, label_i18n, languages_json],
        )
        for v in vocabularies:
            vid = v.get("id", "themes")
            vlabel_i18n = to_i18n(
                fr=v.get("label_fr", ""),
                en=v.get("label_en", ""),
                ar=v.get("label_ar", ""),
            )
            conn.execute(
                "INSERT INTO vocabulary (id, taxonomy_id, label_i18n) VALUES (?, ?, ?)",
                [vid, taxonomy_id, vlabel_i18n],
            )
            _insert_terms(conn, vid, v.get("terms", []), None)

    return {"status": "ok", "taxonomy_id": taxonomy_id}


def _insert_terms(
    conn: DBConnAdapter,
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
        name_i18n = to_i18n(
            fr=t.get("name_fr", ""),
            en=t.get("name_en", ""),
            ar=t.get("name_ar", ""),
        )
        desc_i18n = to_i18n(
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


def _get_terms_flat(conn: DBConnAdapter, vocabulary_id: str) -> list[dict]:
    """Retourne les termes d'un vocabulaire en liste plate (avec parent_id)."""
    terms_rows = conn.execute(
        """
        SELECT
            t.id,
            t.vocabulary_id,
            t.parent_id,
            t.slug,
            t.slug_i18n,
            t.name_i18n,
            t.description_i18n,
            t.weight,
            t.keywords,
            COALESCE((
                SELECT COUNT(DISTINCT it.image_id)
                FROM image_taxonomy_tag it
                WHERE it.term_id = t.id AND it.taxonomy_id = v.taxonomy_id
            ), 0) AS subjects_count,
            COALESCE((
                SELECT COUNT(*)
                FROM image ic
                WHERE ic.origin_term_id = t.id
            ), 0) AS concept_count
        FROM term t
        JOIN vocabulary v ON v.id = t.vocabulary_id
        WHERE t.vocabulary_id = ?
        ORDER BY t.weight
        """,
        [vocabulary_id],
    ).fetchall()
    cols = [
        "id", "vocabulary_id", "parent_id", "slug", "slug_i18n",
        "name_i18n", "description_i18n", "weight", "keywords", "subjects_count", "concept_count",
    ]
    return [_term_row_to_dict(list(r), cols) for r in terms_rows]


def _term_to_response(r: dict) -> dict[str, Any]:
    """Transforme une ligne term en format API (name_fr, name_en, etc.)."""
    w = r.get("weight")
    weight = int(w) if w is not None else 0
    sc = r.get("subjects_count")
    cc = r.get("concept_count")
    return {
        "id": r["id"],
        "slug": r["slug"],
        "parent_id": r.get("parent_id"),
        "name_fr": get_i18n(r.get("name_i18n"), "fr"),
        "name_en": get_i18n(r.get("name_i18n"), "en"),
        "name_ar": get_i18n(r.get("name_i18n"), "ar"),
        "description_fr": get_i18n(r.get("description_i18n"), "fr"),
        "description_en": get_i18n(r.get("description_i18n"), "en"),
        "description_ar": get_i18n(r.get("description_i18n"), "ar"),
        "weight": weight,
        "keywords": r.get("keywords") or [],
        "subjects_count": int(sc) if sc is not None else 0,
        "concept_count": int(cc) if cc is not None else 0,
    }


def _get_term_references(
    conn: DBConnAdapter, taxonomy_id: str, term_id: str
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


def _ensure_vocabulary_exists(conn: DBConnAdapter, vocabulary_id: str) -> str:
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
    conn: DBConnAdapter = Depends(get_db_read),
):
    """Liste des termes d'un vocabulaire (arbre).
    Sérialise en bytes UTF-8 nous-mêmes : évite tout UnicodeEncodeError Windows
    et tout échec de sérialisation côté framework."""
    try:
        _ensure_vocabulary_exists(conn, vocabulary_id)
        rows = _get_terms_flat(conn, vocabulary_id)
        tree = _build_terms_tree(rows, None)
        return json_response({"vocabulary_id": vocabulary_id, "terms": tree})
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
    conn: DBConnAdapter = Depends(get_db_read),
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
    conn: DBConnAdapter = Depends(get_db_write),
) -> dict[str, Any]:
    """Crée ou met à jour un terme (upsert). Tables modifiées : term."""
    taxonomy_id = _ensure_vocabulary_exists(conn, vocabulary_id)
    term_id = term_id.strip()
    if not term_id:
        raise HTTPException(status_code=400, detail="term_id vide")

    slug = (payload.get("slug") or term_id).strip() or term_id
    name_i18n = to_i18n(
        fr=payload.get("name_fr", ""),
        en=payload.get("name_en", ""),
        ar=payload.get("name_ar", ""),
    )
    desc_i18n = to_i18n(
        fr=payload.get("description_fr", ""),
        en=payload.get("description_en", ""),
        ar=payload.get("description_ar", ""),
    )
    weight = int(payload.get("weight", 0))
    keywords = payload.get("keywords", [])
    keywords_json = json.dumps(keywords) if keywords else "[]"
    parent_id = payload.get("parent_id")  # None pour racine

    with transaction(conn):
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

    return {"status": "ok", "vocabulary_id": vocabulary_id, "term_id": term_id}


@router.post("/vocabularies/{vocabulary_id}/terms")
def post_term(
    vocabulary_id: str,
    payload: dict,
    conn: DBConnAdapter = Depends(get_db_write),
) -> dict[str, Any]:
    """Crée un terme. Tables modifiées : term. Body doit contenir id (ou généré)."""
    _ensure_vocabulary_exists(conn, vocabulary_id)
    term_id = (payload.get("id") or "").strip()
    if not term_id:
        import time
        term_id = f"term_{int(time.time() * 1000)}"
    slug = (payload.get("slug") or term_id).strip() or term_id
    name_i18n = to_i18n(
        fr=payload.get("name_fr", ""),
        en=payload.get("name_en", ""),
        ar=payload.get("name_ar", ""),
    )
    desc_i18n = to_i18n(
        fr=payload.get("description_fr", ""),
        en=payload.get("description_en", ""),
        ar=payload.get("description_ar", ""),
    )
    weight = int(payload.get("weight", 0))
    keywords = payload.get("keywords", [])
    keywords_json = json.dumps(keywords) if keywords else "[]"
    parent_id = payload.get("parent_id")

    try:
        with transaction(conn):
            conn.execute(
                """
                INSERT INTO term (id, vocabulary_id, parent_id, slug, name_i18n, description_i18n, weight, keywords)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [term_id, vocabulary_id, parent_id, slug, name_i18n, desc_i18n, weight, keywords_json],
            )
    except HTTPException as e:
        if e.status_code == 500 and (
            "constraint" in str(e.detail).lower()
            or "duplicate" in str(e.detail).lower()
            or "unique" in str(e.detail).lower()
        ):
            raise HTTPException(status_code=409, detail=f"Terme '{term_id}' existe déjà") from None
        raise

    return {"status": "created", "vocabulary_id": vocabulary_id, "term_id": term_id}


def _delete_term_cascade(conn: DBConnAdapter, vocabulary_id: str, term_id: str) -> None:
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
    conn: DBConnAdapter = Depends(get_db_write),
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

    if cascade and has_children:
        with transaction(conn):
            _delete_term_cascade(conn, vocabulary_id, term_id)
    else:
        conn.execute("DELETE FROM term WHERE id = ? AND vocabulary_id = ?", [term_id, vocabulary_id])
    return {"status": "deleted", "vocabulary_id": vocabulary_id, "term_id": term_id}


@router.get("/terms/search")
def search_terms(
    q: str = "",
    vocabulary_id: str | None = None,
    conn: DBConnAdapter = Depends(get_db_read),
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
        name_fr = get_i18n(row_dict.get("name_i18n"), "fr")
        name_en = get_i18n(row_dict.get("name_i18n"), "en")
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
def export_taxonomy_json(conn: DBConnAdapter = Depends(get_db_read)) -> dict:
    """Export JSON (même format que GET)."""
    return get_taxonomy(conn)


# ─── Import diff ────────────────────────────────────────────────────────────

_DIFF_FIELDS = [
    "slug", "parent_id",
    "name_fr", "name_en", "name_ar",
    "description_fr", "description_en", "description_ar",
    "weight", "keywords",
]

_VALID_OPS = {"add", "upsert", "update", "remove"}


def _normalize_diff_op(raw_op: dict) -> dict:
    """Normalise une opération diff (supporte le format JSON Patch avec 'path')."""
    op = raw_op.get("op", "")
    value = raw_op.get("value") or {}
    # Compatibilité JSON Patch : le champ 'path' est ignoré (vocabulary vient du endpoint).
    # Si op == "replace" (JSON Patch), on mappe vers "upsert".
    if op == "replace":
        op = "upsert"
    return {"op": op, "value": value}


def _term_to_flat(r: dict) -> dict:
    """Convertit une ligne DB (name_i18n, etc.) en dict plat pour la comparaison."""
    return {
        "id": r.get("id", ""),
        "slug": r.get("slug", ""),
        "parent_id": r.get("parent_id"),
        "name_fr": get_i18n(r.get("name_i18n"), "fr"),
        "name_en": get_i18n(r.get("name_i18n"), "en"),
        "name_ar": get_i18n(r.get("name_i18n"), "ar"),
        "description_fr": get_i18n(r.get("description_i18n"), "fr"),
        "description_en": get_i18n(r.get("description_i18n"), "en"),
        "description_ar": get_i18n(r.get("description_i18n"), "ar"),
        "weight": int(r.get("weight") or 0),
        "keywords": r.get("keywords") or [],
    }


def _compute_diff(current: dict, incoming: dict) -> dict:
    """Retourne les champs modifiés entre current et incoming.
    N'inclut que les champs explicitement fournis dans incoming (évite d'afficher
    slug→"" etc. quand l'enrichissement IA n'envoie que name_fr, name_en, name_ar)."""
    diff: dict[str, dict] = {}
    for field in _DIFF_FIELDS:
        if field not in incoming:
            continue
        cur_val = current.get(field)
        inc_val = incoming.get(field)
        # Normaliser les valeurs comparables
        if field == "weight":
            cur_val = int(cur_val) if cur_val is not None else 0
            inc_val = int(inc_val) if inc_val is not None else 0
        elif field == "keywords":
            cur_val = sorted(cur_val or [])
            inc_val = sorted(inc_val or [])
        elif field == "parent_id":
            cur_val = cur_val or None
            inc_val = inc_val if inc_val is not None and str(inc_val).strip() else None
        else:
            cur_val = (cur_val or "").strip()
            inc_val = (inc_val or "").strip()
        if cur_val != inc_val:
            diff[field] = {"from": cur_val, "to": inc_val}
    return diff


def _validate_diff_operations(
    operations: list[dict],
    existing_ids: set[str],
    vocab_id: str,
) -> list[dict]:
    """
    Valide chaque opération et retourne la liste enrichie avec status, message, diff.
    existing_ids : set des term_id actuellement en DB pour ce vocabulaire.
    """
    # IDs des termes qui seront ajoutés dans ce batch (pour résolution intra-batch)
    batch_added_ids: set[str] = set()
    results: list[dict] = []

    for i, raw_op in enumerate(operations):
        normalized = _normalize_diff_op(raw_op)
        op = normalized["op"]
        value = normalized["value"]

        term_id = str(value.get("id") or "").strip()
        parent_id = value.get("parent_id") or None
        if parent_id:
            parent_id = str(parent_id).strip() or None

        result: dict[str, Any] = {
            "index": i,
            "op": op,
            "term_id": term_id,
            "status": "ready",
            "message": None,
            "incoming": value,
            "current": None,
            "diff": None,
        }

        # Validation op
        if op not in _VALID_OPS:
            result["status"] = "error"
            result["message"] = f"Opération inconnue : '{op}'. Valeurs acceptées : {', '.join(sorted(_VALID_OPS))}"
            results.append(result)
            continue

        # Validation id
        if not term_id:
            result["status"] = "error"
            result["message"] = "Champ 'id' manquant ou vide"
            results.append(result)
            continue

        # Validation slug pour add/upsert
        slug = str(value.get("slug") or "").strip()
        if op in ("add", "upsert") and not slug:
            # slug par défaut = id, on note mais pas bloquant
            result["message"] = f"Champ 'slug' absent, sera déduit de l'id : '{term_id}'"

        # Validation parent_id : doit exister en DB ou dans le batch courant
        if parent_id and parent_id not in existing_ids and parent_id not in batch_added_ids:
            result["status"] = "error"
            result["message"] = f"parent_id '{parent_id}' introuvable (ni en DB ni dans ce batch)"
            results.append(result)
            continue

        exists = term_id in existing_ids

        if op == "add":
            if exists:
                result["status"] = "conflict"
                result["message"] = f"Terme '{term_id}' existe déjà (utilisez 'upsert' pour mettre à jour)"
            else:
                result["status"] = "ready"
                batch_added_ids.add(term_id)

        elif op == "upsert":
            if exists:
                result["status"] = "update"
                # Diff calculé côté apply (current chargé depuis DB)
            else:
                result["status"] = "ready"
                batch_added_ids.add(term_id)

        elif op == "update":
            if not exists:
                result["status"] = "error"
                result["message"] = f"Terme '{term_id}' n'existe pas (utilisez 'add' ou 'upsert')"
            else:
                result["status"] = "update"

        elif op == "remove":
            if not exists:
                result["status"] = "skip"
                result["message"] = f"Terme '{term_id}' introuvable, suppression ignorée"
            else:
                result["status"] = "ready"

        results.append(result)

    return results


@router.post("/vocabularies/{vocabulary_id}/import/diff")
def import_diff(
    vocabulary_id: str,
    operations: list = Body(...),
    dry_run: bool = True,
    conn: DBConnAdapter = Depends(get_db_write),
) -> Any:
    """
    Import de diffs JSON pour un vocabulaire.
    dry_run=true (défaut) : retourne le preview sans appliquer.
    dry_run=false : applique les opérations sélectionnées dans une transaction unique.
    Supporte le format JSON Patch (avec 'path') et le format simplifié.
    """
    _ensure_vocabulary_exists(conn, vocabulary_id)

    # Charger tous les termes existants en une passe
    existing_rows = _get_terms_flat(conn, vocabulary_id)
    existing_map: dict[str, dict] = {r["id"]: r for r in existing_rows}
    existing_ids: set[str] = set(existing_map.keys())

    # Validation de toutes les opérations
    validated = _validate_diff_operations(operations, existing_ids, vocabulary_id)

    # Enrichir avec le diff réel pour les updates (upsert/update sur terme existant)
    for op_result in validated:
        if op_result["status"] == "update":
            current_row = existing_map.get(op_result["term_id"])
            if current_row:
                current_flat = _term_to_flat(current_row)
                op_result["current"] = current_flat
                op_result["diff"] = _compute_diff(current_flat, op_result["incoming"])
                if not op_result["diff"]:
                    op_result["status"] = "skip"
                    op_result["message"] = "Aucune modification détectée"

    # Résumé
    summary: dict[str, int] = {"ready": 0, "update": 0, "conflict": 0, "error": 0, "skip": 0}
    for r in validated:
        s = r["status"]
        summary[s] = summary.get(s, 0) + 1

    # Réponse dry_run
    if dry_run:
        return json_response({
            "vocabulary_id": vocabulary_id,
            "dry_run": True,
            "summary": summary,
            "operations": validated,
        })

    out = apply_taxonomy_import_operations(conn, vocabulary_id, operations)
    return json_response(out)


def apply_taxonomy_import_operations(
    conn: DBConnAdapter,
    vocabulary_id: str,
    operations: list[dict],
) -> dict[str, Any]:
    """
    Applique des opérations import/diff (même logique que POST import/diff avec dry_run=false).
    Utilisable depuis la validation d'un job (artefact taxonomy_import_ops).
    """
    _ensure_vocabulary_exists(conn, vocabulary_id)

    existing_rows = _get_terms_flat(conn, vocabulary_id)
    existing_map: dict[str, dict] = {r["id"]: r for r in existing_rows}
    existing_ids: set[str] = set(existing_map.keys())

    validated = _validate_diff_operations(operations, existing_ids, vocabulary_id)

    for op_result in validated:
        if op_result["status"] == "update":
            current_row = existing_map.get(op_result["term_id"])
            if current_row:
                current_flat = _term_to_flat(current_row)
                op_result["current"] = current_flat
                op_result["diff"] = _compute_diff(current_flat, op_result["incoming"])
                if not op_result["diff"]:
                    op_result["status"] = "skip"
                    op_result["message"] = "Aucune modification détectée"

    summary: dict[str, int] = {"ready": 0, "update": 0, "conflict": 0, "error": 0, "skip": 0}
    for r in validated:
        s = r["status"]
        summary[s] = summary.get(s, 0) + 1

    applied: list[str] = []
    errors: list[str] = []

    with transaction(conn):
        for op_result in validated:
            op = op_result["op"]
            term_id = op_result["term_id"]
            status = op_result["status"]
            value = op_result["incoming"]

            if status in ("skip", "conflict", "error"):
                continue

            if op in ("add", "upsert") and status in ("ready", "update"):
                if term_id in existing_ids and op == "upsert":
                    current_row = existing_map.get(term_id)
                    current_flat = _term_to_flat(current_row) if current_row else {}
                    merged = dict(current_flat)
                    for field in _DIFF_FIELDS:
                        if field in value:
                            merged[field] = value[field]
                    value = merged

                slug = (str(value.get("slug") or term_id)).strip() or term_id
                name_i18n = to_i18n(
                    fr=value.get("name_fr", ""),
                    en=value.get("name_en", ""),
                    ar=value.get("name_ar", ""),
                )
                desc_i18n = to_i18n(
                    fr=value.get("description_fr", ""),
                    en=value.get("description_en", ""),
                    ar=value.get("description_ar", ""),
                )
                weight = int(value.get("weight", 0))
                keywords = value.get("keywords", [])
                keywords_json = json.dumps(keywords) if keywords else "[]"
                parent_id = value.get("parent_id") or None
                if parent_id:
                    parent_id = str(parent_id).strip() or None

                if term_id in existing_ids and op == "upsert":
                    conn.execute(
                        """
                        UPDATE term SET slug=?, name_i18n=?, description_i18n=?,
                            weight=?, keywords=?, parent_id=?
                        WHERE id=? AND vocabulary_id=?
                        """,
                        [slug, name_i18n, desc_i18n, weight, keywords_json,
                         parent_id, term_id, vocabulary_id],
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO term
                            (id, vocabulary_id, parent_id, slug, name_i18n, description_i18n, weight, keywords)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        [term_id, vocabulary_id, parent_id, slug,
                         name_i18n, desc_i18n, weight, keywords_json],
                    )
                existing_ids.add(term_id)
                applied.append(term_id)

            elif op == "update" and status == "update":
                current_row = existing_map.get(term_id)
                current_flat = _term_to_flat(current_row) if current_row else {}
                value_merged = dict(current_flat)
                for field in _DIFF_FIELDS:
                    if field in value:
                        value_merged[field] = value[field]
                slug = (str(value_merged.get("slug") or term_id)).strip() or term_id
                name_i18n = to_i18n(
                    fr=value_merged.get("name_fr", ""),
                    en=value_merged.get("name_en", ""),
                    ar=value_merged.get("name_ar", ""),
                )
                desc_i18n = to_i18n(
                    fr=value_merged.get("description_fr", ""),
                    en=value_merged.get("description_en", ""),
                    ar=value_merged.get("description_ar", ""),
                )
                weight = int(value_merged.get("weight", 0))
                keywords = value_merged.get("keywords", [])
                keywords_json = json.dumps(keywords) if keywords else "[]"
                parent_id = value_merged.get("parent_id") or None
                conn.execute(
                    """
                    UPDATE term SET slug=?, name_i18n=?, description_i18n=?,
                        weight=?, keywords=?, parent_id=?
                    WHERE id=? AND vocabulary_id=?
                    """,
                    [slug, name_i18n, desc_i18n, weight, keywords_json,
                     parent_id, term_id, vocabulary_id],
                )
                applied.append(term_id)

            elif op == "remove" and status == "ready":
                conn.execute(
                    "DELETE FROM term WHERE id=? AND vocabulary_id=?",
                    [term_id, vocabulary_id],
                )
                applied.append(term_id)

    return {
        "vocabulary_id": vocabulary_id,
        "dry_run": False,
        "applied_count": len(applied),
        "applied": applied,
        "errors": errors,
        "summary": summary,
    }
