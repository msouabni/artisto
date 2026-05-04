from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_TAXONOMY_PATH = DATA_DIR / "taxonomy_universal_v0.json"
DEFAULT_DB_PATH = DATA_DIR / "artiste_coloriage.duckdb"


@dataclass
class Term:
    id: str
    slug: str
    name_fr: str
    name_en: str
    name_ar: str
    description_fr: Optional[str] = None
    description_en: Optional[str] = None
    description_ar: Optional[str] = None
    weight: int = 0
    keywords: List[str] = field(default_factory=list)
    parent_id: Optional[str] = None
    children: List["Term"] = field(default_factory=list)


@dataclass
class Vocabulary:
    id: str
    label_fr: str
    label_en: str
    label_ar: Optional[str] = None
    terms: List[Term] = field(default_factory=list)


@dataclass
class Taxonomy:
    taxonomy_id: str
    label: str
    languages: List[str]
    vocabularies: List[Vocabulary]

    def find_term(self, term_id: str) -> Optional[Term]:
        for vocab in self.vocabularies:
            for term in iter_terms(vocab.terms):
                if term.id == term_id:
                    return term
        return None


def iter_terms(terms: List[Term]) -> List[Term]:
    for term in terms:
        yield term
        if term.children:
            yield from iter_terms(term.children)


def load_taxonomy(path: Path = DEFAULT_TAXONOMY_PATH) -> Taxonomy:
    if not path.exists():
        raise FileNotFoundError(f"Taxonomy file not found at {path}")

    with path.open("r", encoding="utf-8") as f:
        if path.suffix in (".yaml", ".yml"):
            import yaml
            raw = yaml.safe_load(f)
        else:
            raw = json.load(f)

    taxonomy_id = raw.get("taxonomy_id", "universal_v0")
    label = raw.get("label", "Taxonomie universelle v0")
    languages = raw.get("languages", ["fr", "en", "ar"])

    vocabularies: List[Vocabulary] = []
    for vocab_data in raw.get("vocabularies", []):
        vocab_terms = _build_terms_tree(vocab_data.get("terms", []), parent_id=None)
        vocabularies.append(
            Vocabulary(
                id=vocab_data["id"],
                label_fr=vocab_data.get("label_fr", vocab_data["id"]),
                label_en=vocab_data.get("label_en", vocab_data["id"]),
                label_ar=vocab_data.get("label_ar"),
                terms=vocab_terms,
            )
        )

    return Taxonomy(
        taxonomy_id=taxonomy_id,
        label=label,
        languages=languages,
        vocabularies=vocabularies,
    )


def _build_terms_tree(
    terms_data: List[Dict[str, Any]],
    parent_id: Optional[str],
) -> List[Term]:
    terms: List[Term] = []
    for data in terms_data:
        term = Term(
            id=data["id"],
            slug=data["slug"],
            name_fr=data.get("name_fr", data["id"]),
            name_en=data.get("name_en", data["id"]),
            name_ar=data.get("name_ar", data.get("name_en", data["id"])),
            description_fr=data.get("description_fr"),
            description_en=data.get("description_en"),
            description_ar=data.get("description_ar"),
            weight=int(data.get("weight", 0)),
            keywords=list(data.get("keywords", [])),
            parent_id=parent_id,
        )
        children_data = data.get("children", [])
        term.children = _build_terms_tree(children_data, parent_id=term.id)
        terms.append(term)
    terms.sort(key=lambda t: t.weight)
    return terms


def load_taxonomy_from_db(path: Path = DEFAULT_DB_PATH) -> Taxonomy:
    """Charge la taxonomie depuis la base applicative courante.

    ``path`` est conservé pour compatibilité d'API, mais n'est plus utilisé
    maintenant que l'accès direct via ``duckdb.connect`` est désactivé.
    """
    _ = path
    from api.db import get_db_sync

    conn = get_db_sync(read_only=True)
    try:
        tx = conn.execute(
            "SELECT taxonomy_id, label_i18n, languages FROM taxonomy LIMIT 1"
        ).fetchone()
        if not tx:
            raise ValueError("Taxonomie non trouvée dans la base")

        taxonomy_id, label_i18n, languages = tx
        label = taxonomy_id
        try:
            if label_i18n:
                data = json.loads(label_i18n) if isinstance(label_i18n, str) else label_i18n
                label = data.get("fr") or data.get("en") or taxonomy_id
            langs = json.loads(languages) if isinstance(languages, str) else ["fr", "en", "ar"]
        except Exception:
            langs = ["fr", "en", "ar"]

        vocabularies: List[Vocabulary] = []
        for v in conn.execute(
            "SELECT id, taxonomy_id, label_i18n FROM vocabulary WHERE taxonomy_id = ?",
            [taxonomy_id],
        ).fetchall():
            vid, _, vlabel_i18n = v
            terms_data = _fetch_terms_from_db(conn, vid, None)
            vocab_terms = _build_terms_tree(terms_data, parent_id=None)
            label_fr = label_en = vid
            label_ar = None
            try:
                if vlabel_i18n:
                    data = json.loads(vlabel_i18n) if isinstance(vlabel_i18n, str) else vlabel_i18n
                    label_fr = data.get("fr", vid)
                    label_en = data.get("en", vid)
                    label_ar = data.get("ar")
            except Exception:
                pass
            vocabularies.append(
                Vocabulary(id=vid, label_fr=label_fr, label_en=label_en, label_ar=label_ar, terms=vocab_terms)
            )

        return Taxonomy(taxonomy_id=taxonomy_id, label=label, languages=langs, vocabularies=vocabularies)
    finally:
        conn.close()


def _fetch_terms_from_db(
    conn, vocabulary_id: str, parent_id: Optional[str]
) -> List[Dict[str, Any]]:
    if parent_id is None:
        rows = conn.execute(
            """
            SELECT id, parent_id, slug, name_i18n, description_i18n, weight, keywords
            FROM term WHERE vocabulary_id = ? AND parent_id IS NULL ORDER BY weight
            """,
            [vocabulary_id],
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, parent_id, slug, name_i18n, description_i18n, weight, keywords
            FROM term WHERE vocabulary_id = ? AND parent_id = ? ORDER BY weight
            """,
            [vocabulary_id, parent_id],
        ).fetchall()
    result = []
    for r in rows:
        tid, pid, slug, name_i18n, desc_i18n, weight, keywords = r
        name_fr = name_en = tid
        name_ar = tid
        desc_fr = desc_en = desc_ar = None
        try:
            if name_i18n:
                n = json.loads(name_i18n) if isinstance(name_i18n, str) else name_i18n
                name_fr, name_en, name_ar = n.get("fr", tid), n.get("en", tid), n.get("ar", tid)
            if desc_i18n:
                d = json.loads(desc_i18n) if isinstance(desc_i18n, str) else desc_i18n
                desc_fr, desc_en, desc_ar = d.get("fr"), d.get("en"), d.get("ar")
        except Exception:
            pass
        kw = json.loads(keywords) if isinstance(keywords, str) and keywords else []
        result.append(
            {
                "id": tid,
                "slug": slug,
                "name_fr": name_fr,
                "name_en": name_en,
                "name_ar": name_ar,
                "description_fr": desc_fr,
                "description_en": desc_en,
                "description_ar": desc_ar,
                "weight": weight or 0,
                "keywords": kw,
                "children": _fetch_terms_from_db(conn, vocabulary_id, tid),
            }
        )
    return result


def get_taxonomy() -> Taxonomy:
    """
    Charger la taxonomie universelle par défaut.
    Utilise la base applicative si elle est disponible, sinon le fichier JSON.
    """
    try:
        return load_taxonomy_from_db()
    except Exception:
        return load_taxonomy()


def get_terms_for_branch(
    taxonomy: Taxonomy,
    term_id: str,
) -> List[Term]:
    """
    Retourner un terme et tous ses descendants directs/indirects.
    """
    root = taxonomy.find_term(term_id)
    if root is None:
        return []
    return list(iter_terms([root]))


if __name__ == "__main__":
    tx = get_taxonomy()
    print(f"Taxonomie: {tx.taxonomy_id} – {tx.label}")
    for vocab in tx.vocabularies:
        print(f"- Vocabulaire: {vocab.id} ({vocab.label_fr} / {vocab.label_en})")
        for term in iter_terms(vocab.terms):
            indent = "  " * (1 + (1 if term.parent_id else 0))
            print(f"{indent}- {term.id} ({term.name_fr} / {term.name_en})")

