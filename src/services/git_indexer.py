"""Indexeur git — reflète un clone de contenu dans la table ``git_index``.

Cap : **autorité = git**. L'indexeur ne fait que *refléter* le dépôt ; il
n'écrit jamais de contenu, ne corrige jamais git, ne sert jamais de page. Il
scanne un clone de contenu, parse les ``*.md`` / ``*.mdx`` sous
``src/content/{posts,pages}/<locale>/``, en extrait le frontmatter + le corps,
calcule un ``content_hash`` stable (idempotent) et fait un upsert dans
``git_index``.

Le chemin du clone est configurable via ``CONTENT_REPO_PATH`` (défaut : le
dossier de mocks ``data/mock-content`` du repo cockpit). Les vraies plaques /
pages remplaceront les mocks **par commit**, sans autre changement.

PostgreSQL unique. Upsert portable (SELECT puis INSERT/UPDATE) via le
``DBConnAdapter`` (placeholders ``?``).
"""
from __future__ import annotations

import hashlib
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Dossier de mocks par défaut (à la spec réelle : src/content/{posts,pages}/<locale>/).
DEFAULT_CONTENT_REPO_PATH = PROJECT_ROOT / "data" / "mock-content"

# Repo logique par défaut (clé de jointure work_item ↔ git_index). Le repo
# contenu réel est ``rimalab-v2`` ; sur les mocks on garde le même nom logique
# pour que la bascule mocks → vrai clone ne change pas les clés.
DEFAULT_REPO = "rimalab-v2"

CONTENT_SUBDIRS = ("posts", "pages")
MARKDOWN_SUFFIXES = (".md", ".mdx")

_ID_COUNTER = 0


def _new_id(prefix: str) -> str:
    global _ID_COUNTER
    _ID_COUNTER += 1
    return f"{prefix}_{int(time.time() * 1_000_000)}_{_ID_COUNTER}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def content_repo_path() -> Path:
    """Chemin du clone de contenu à indexer (env ``CONTENT_REPO_PATH``)."""
    env = os.environ.get("CONTENT_REPO_PATH")
    return Path(env).expanduser().resolve() if env else DEFAULT_CONTENT_REPO_PATH


@dataclass
class ParsedDoc:
    """Document markdown parsé (frontmatter + corps)."""

    locale: str
    slug: str
    rel_path: str
    frontmatter: dict[str, Any]
    body: str
    publish_date: date | None
    content_hash: str
    frontmatter_digest: str


@dataclass
class IndexReport:
    """Résultat d'un scan d'indexation."""

    repo: str
    root: str
    scanned: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    marked_absent: int = 0
    errors: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "root": self.root,
            "scanned": self.scanned,
            "inserted": self.inserted,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "marked_absent": self.marked_absent,
            "errors": self.errors,
        }


# ── Parsing frontmatter ───────────────────────────────────────────────────────

def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Sépare le frontmatter YAML (entre ``---``) du corps. Tolérant.

    Retourne ``({}, text)`` si aucun frontmatter délimité n'est présent.
    """
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    # lines[0] == '---' (ou '--- ' avec espaces) ; cherche le ``---`` de clôture.
    if lines[0].strip() != "---":
        return {}, text
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            fm_block = "\n".join(lines[1:idx])
            body = "\n".join(lines[idx + 1:])
            try:
                data = yaml.safe_load(fm_block) or {}
            except yaml.YAMLError as exc:
                raise ValueError(f"frontmatter YAML invalide : {exc}") from exc
            if not isinstance(data, dict):
                raise ValueError("frontmatter n'est pas un mapping YAML")
            return data, body
    # Pas de clôture → pas de frontmatter exploitable.
    return {}, text


def _coerce_publish_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        txt = value.strip()
        if not txt:
            return None
        if txt.endswith("Z"):
            txt = txt[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(txt).date()
        except ValueError:
            try:
                return date.fromisoformat(txt[:10])
            except ValueError:
                logger.warning("publishDate non parsable : %r", value)
                return None
    return None


def _digest(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _canonical_frontmatter(fm: dict[str, Any]) -> str:
    """Sérialisation déterministe du frontmatter (pour un hash stable)."""
    return yaml.safe_dump(fm, sort_keys=True, allow_unicode=True, default_flow_style=False)


def parse_doc(path: Path, locale: str, rel_path: str) -> ParsedDoc:
    """Parse un fichier markdown en ``ParsedDoc`` (slug = nom de fichier sans ext)."""
    raw = path.read_text(encoding="utf-8")
    fm, body = split_frontmatter(raw)

    slug = (str(fm.get("slug")).strip() if fm.get("slug") else path.stem)
    publish_date = _coerce_publish_date(fm.get("publishDate"))

    fm_canon = _canonical_frontmatter(fm)
    frontmatter_digest = _digest(fm_canon)
    # content_hash = frontmatter canonique + corps normalisé (newlines uniformes).
    body_norm = body.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    content_hash = _digest(fm_canon + "\n\x00\n" + body_norm)

    return ParsedDoc(
        locale=locale,
        slug=slug,
        rel_path=rel_path,
        frontmatter=fm,
        body=body,
        publish_date=publish_date,
        content_hash=content_hash,
        frontmatter_digest=frontmatter_digest,
    )


# ── Scan FS ───────────────────────────────────────────────────────────────────

def scan_docs(root: Path) -> list[ParsedDoc]:
    """Scanne ``root/src/content/{posts,pages}/<locale>/*.md(x)``.

    Le ``<locale>`` est le nom du dossier immédiatement sous ``posts``/``pages``.
    """
    content_root = root / "src" / "content"
    docs: list[ParsedDoc] = []
    if not content_root.is_dir():
        logger.warning("git_indexer: pas de src/content sous %s", root)
        return docs

    for sub in CONTENT_SUBDIRS:
        sub_root = content_root / sub
        if not sub_root.is_dir():
            continue
        for locale_dir in sorted(sub_root.iterdir()):
            if not locale_dir.is_dir():
                continue
            locale = locale_dir.name
            for f in sorted(locale_dir.iterdir()):
                if f.suffix.lower() not in MARKDOWN_SUFFIXES or not f.is_file():
                    continue
                rel = str(f.relative_to(root)).replace("\\", "/")
                docs.append(parse_doc(f, locale, rel))
    return docs


# ── Upsert dans git_index (autorité = git ; cette table est un miroir) ────────

def _upsert_git_index(conn: Any, repo: str, doc: ParsedDoc, now: str) -> str:
    """Upsert idempotent d'une ligne ``git_index``. Retourne 'inserted' /
    'updated' / 'unchanged'."""
    rows = conn.execute(
        "SELECT id, content_hash, exists FROM git_index "
        "WHERE repo = ? AND locale = ? AND slug = ?",
        [repo, doc.locale, doc.slug],
    ).fetchall()

    pub = doc.publish_date  # date | None — psycopg gère les date natives

    if rows:
        row = rows[0]
        existing_id, existing_hash, existing_exists = row[0], row[1], row[2]
        if existing_hash == doc.content_hash and bool(existing_exists):
            # Idempotence : même hash + déjà présent → on ne touche que la
            # date de scan (n'altère pas le hash, garde l'idempotence sémantique).
            conn.execute(
                "UPDATE git_index SET last_indexed_at = ? WHERE id = ?",
                [now, existing_id],
            )
            return "unchanged"
        conn.execute(
            "UPDATE git_index SET exists = ?, publish_date = ?, "
            "frontmatter_digest = ?, content_hash = ?, rel_path = ?, "
            "last_indexed_at = ? WHERE id = ?",
            [True, pub, doc.frontmatter_digest, doc.content_hash,
             doc.rel_path, now, existing_id],
        )
        return "updated"

    conn.execute(
        "INSERT INTO git_index "
        "(id, repo, locale, slug, exists, publish_date, frontmatter_digest, "
        " content_hash, rel_path, last_indexed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [_new_id("gidx"), repo, doc.locale, doc.slug, True, pub,
         doc.frontmatter_digest, doc.content_hash, doc.rel_path, now],
    )
    return "inserted"


def _locale_slug_from_rel(rel_path: str) -> tuple[str, str] | None:
    """Extrait ``(locale, slug)`` d'un chemin ``src/content/{posts,pages}/<locale>/<slug>.md``.

    Retourne ``None`` si le chemin n'est pas un markdown de contenu reconnu
    (autre dossier, autre extension) — le webhook ignore alors ce chemin.
    """
    norm = rel_path.replace("\\", "/").lstrip("/")
    parts = norm.split("/")
    # Attendu : src / content / {posts|pages} / <locale> / <file>.md(x)
    if len(parts) < 5:
        return None
    if parts[0] != "src" or parts[1] != "content" or parts[2] not in CONTENT_SUBDIRS:
        return None
    file_name = parts[-1]
    suffix = Path(file_name).suffix.lower()
    if suffix not in MARKDOWN_SUFFIXES:
        return None
    locale = parts[3]
    slug = Path(file_name).stem
    return locale, slug


def reindex_paths(
    conn: Any,
    rel_paths: list[str],
    repo: str = DEFAULT_REPO,
    root: Path | None = None,
) -> IndexReport:
    """Réindexe ``git_index`` pour un ENSEMBLE de chemins touchés (webhook push).

    Autorité = git. Pour chaque chemin de contenu reconnu :
      - le fichier existe dans le clone → upsert (inserted/updated/unchanged) ;
      - le fichier a disparu (suppression côté git) → ligne marquée ``exists=false``.
    Les chemins non reconnus (hors ``src/content/{posts,pages}/<locale>/*.md``)
    sont ignorés (pas une erreur). Idempotent. Ne touche QUE les chemins fournis
    (n'efface pas le reste de l'index, contrairement à ``reindex``).
    """
    scan_root = root or content_repo_path()
    report = IndexReport(repo=repo, root=str(scan_root))
    now = _now_iso()
    seen: set[tuple[str, str]] = set()

    for rel in rel_paths:
        ls = _locale_slug_from_rel(rel)
        if ls is None:
            continue
        locale, slug = ls
        if (locale, slug) in seen:
            continue  # idempotence : un chemin listé 2× ne compte qu'une fois
        seen.add((locale, slug))
        report.scanned += 1

        norm = rel.replace("\\", "/").lstrip("/")
        abs_path = scan_root / norm
        try:
            if abs_path.is_file():
                doc = parse_doc(abs_path, locale, norm)
                outcome = _upsert_git_index(conn, repo, doc, now)
                if outcome == "inserted":
                    report.inserted += 1
                elif outcome == "updated":
                    report.updated += 1
                else:
                    report.unchanged += 1
            else:
                # Fichier supprimé côté git → marque la ligne absente (drift = absent).
                rows = conn.execute(
                    "SELECT id FROM git_index WHERE repo = ? AND locale = ? AND slug = ?",
                    [repo, locale, slug],
                ).fetchall()
                if rows:
                    conn.execute(
                        "UPDATE git_index SET exists = ?, last_indexed_at = ? WHERE id = ?",
                        [False, now, rows[0][0]],
                    )
                    report.marked_absent += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception("git_indexer: échec réindex chemin %s", rel)
            report.errors.append({"slug": f"{locale}/{slug}", "error": str(exc)})

    return report


def reindex(conn: Any, repo: str = DEFAULT_REPO, root: Path | None = None) -> IndexReport:
    """Indexe le clone de contenu → upsert ``git_index``. Autorité = git.

    Les lignes ``git_index`` du même ``repo`` qui ne correspondent plus à aucun
    fichier sont marquées ``exists = false`` (la page a disparu de git → l'état
    dérivé deviendra ``absent``). On ne supprime pas la ligne (trace + drift).
    """
    scan_root = root or content_repo_path()
    report = IndexReport(repo=repo, root=str(scan_root))

    docs = scan_docs(scan_root)
    report.scanned = len(docs)
    seen: set[tuple[str, str]] = set()
    now = _now_iso()

    for doc in docs:
        try:
            outcome = _upsert_git_index(conn, repo, doc, now)
            seen.add((doc.locale, doc.slug))
            if outcome == "inserted":
                report.inserted += 1
            elif outcome == "updated":
                report.updated += 1
            else:
                report.unchanged += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception("git_indexer: échec upsert %s/%s", doc.locale, doc.slug)
            report.errors.append({"slug": f"{doc.locale}/{doc.slug}", "error": str(exc)})

    # Marquer absentes les lignes git_index orphelines (présentes en cache mais
    # plus dans git). git reste l'autorité : le cache se réaligne.
    existing = conn.execute(
        "SELECT id, locale, slug FROM git_index WHERE repo = ? AND exists = ?",
        [repo, True],
    ).fetchall()
    for r in existing:
        key = (r[1], r[2])
        if key not in seen:
            conn.execute(
                "UPDATE git_index SET exists = ?, last_indexed_at = ? WHERE id = ?",
                [False, now, r[0]],
            )
            report.marked_absent += 1

    return report
