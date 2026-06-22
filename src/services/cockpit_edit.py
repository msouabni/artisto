"""Édition légère cockpit → git d'une page DÉJÀ publiée (Phase 2, incrément 2).

Cap inchangé : **git = vérité du contenu**. Éditer une page committée se fait en
repartant TOUJOURS de git (jamais d'un état parallèle conservé en base) :

  1. ``edit_load`` : lit le ``.md`` courant DANS LE CLONE git → remplit le buffer
     de staging (``staging_frontmatter`` / ``staging_body``) + mémorise le
     ``content_hash`` de base (= la version de git qu'on s'apprête à éditer).
  2. ``edit_patch`` : applique des edits LÉGERS au buffer staging (merge
     superficiel du frontmatter, remplacement du corps). Transitoire, jamais
     servi.
  3. Le commit UPDATE (``cockpit_git_publish.commit_work_item(mode="update")``)
     applique le buffer sur le ``.md`` existant SSI le ``content_hash`` courant de
     git == ``last_synced_hash`` (optimistic concurrency). Si git a bougé
     entre-temps (édition hors cockpit) → refus (drift), aucun écrasement.

La création (nouveau slug) reste ADD-ONLY ; l'édition (slug existant) = UPDATE
gardé. Pas de ``--force`` dans le flux d'édition.

PostgreSQL unique. SQLite interdit (y compris tests).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.git_indexer import DEFAULT_REPO, content_repo_path, parse_doc

logger = logging.getLogger(__name__)


class CockpitEditError(RuntimeError):
    """Erreur métier de l'édition légère (page absente de git, buffer vide…)."""


@dataclass
class EditLoadResult:
    """Résultat d'un ``edit_load`` (chargement du buffer depuis git)."""

    work_item_id: str
    repo: str
    locale: str
    slug: str
    rel_path: str
    frontmatter: dict[str, Any]
    body: str | None
    base_content_hash: str
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "work_item_id": self.work_item_id,
            "repo": self.repo,
            "locale": self.locale,
            "slug": self.slug,
            "rel_path": self.rel_path,
            "frontmatter": self.frontmatter,
            "body": self.body,
            "base_content_hash": self.base_content_hash,
            "notes": self.notes,
        }


@dataclass
class EditPatchResult:
    """Résultat d'un ``edit_patch`` (mise à jour du buffer staging)."""

    work_item_id: str
    edited: bool
    frontmatter: dict[str, Any]
    body: str | None
    staging_state: str
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "work_item_id": self.work_item_id,
            "edited": self.edited,
            "frontmatter": self.frontmatter,
            "body": self.body,
            "staging_state": self.staging_state,
            "notes": self.notes,
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fetch_work_item(conn: Any, work_item_id: str) -> dict[str, Any]:
    cols = [
        "id", "repo", "locale", "slug", "state",
        "last_synced_hash", "staging_frontmatter", "staging_body", "staging_state",
    ]
    rows = conn.execute(
        f"SELECT {', '.join(cols)} FROM work_item WHERE id = ?", [work_item_id]
    ).fetchall()
    if not rows:
        raise CockpitEditError(f"work_item '{work_item_id}' introuvable")
    return dict(zip(cols, rows[0]))


def _normalize_fm(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CockpitEditError(f"staging_frontmatter JSON invalide : {exc}") from exc
        return data if isinstance(data, dict) else {}
    return {}


def edit_load(
    conn: Any,
    work_item_id: str,
    *,
    repo_root: Path | None = None,
) -> EditLoadResult:
    """Charge le buffer de staging à partir du ``.md`` COURANT de git.

    git autoritaire : on repart TOUJOURS de git, jamais d'un état parallèle.
    Lit ``src/content/posts/<locale>/<slug>.md`` dans le clone, en extrait
    frontmatter + corps, calcule le ``content_hash`` de base (= la version de git
    qu'on édite), pose ce hash en ``last_synced_hash`` (référence d'optimistic
    concurrency) et remplit ``staging_frontmatter`` / ``staging_body``.

    Lève ``CockpitEditError`` si la page n'existe pas dans git (rien à éditer —
    une page non publiée passe par le flux de création, pas d'édition).
    """
    root = repo_root or content_repo_path()
    wi = _fetch_work_item(conn, work_item_id)
    locale = wi["locale"]
    slug = wi["slug"]

    rel_path = f"src/content/posts/{locale}/{slug}.md"
    abs_path = root / rel_path
    if not abs_path.exists():
        raise CockpitEditError(
            f"édition impossible : {rel_path} absent de git "
            f"(une page non publiée passe par la création, pas l'édition)"
        )

    parsed = parse_doc(abs_path, locale, rel_path)
    base_hash = parsed.content_hash

    now = _now_iso()
    # Remplit le buffer staging depuis git + pose la référence d'optimistic
    # concurrency (last_synced_hash = la version de git qu'on s'apprête à éditer).
    conn.execute(
        "UPDATE work_item SET staging_frontmatter = ?, staging_body = ?, "
        "staging_state = ?, last_synced_hash = ?, updated_at = ? WHERE id = ?",
        [json.dumps(parsed.frontmatter), parsed.body, "editing", base_hash, now,
         work_item_id],
    )

    return EditLoadResult(
        work_item_id=work_item_id,
        repo=wi.get("repo") or DEFAULT_REPO,
        locale=locale,
        slug=slug,
        rel_path=rel_path,
        frontmatter=parsed.frontmatter,
        body=parsed.body,
        base_content_hash=base_hash,
        notes=[f"buffer chargé depuis git ({rel_path}), base_hash {base_hash[:10]}"],
    )


def edit_patch(
    conn: Any,
    work_item_id: str,
    *,
    frontmatter: dict[str, Any] | None = None,
    body: str | None = None,
) -> EditPatchResult:
    """Applique des edits LÉGERS au buffer staging (pré-commit, transitoire).

    - ``frontmatter`` (dict) : merge superficiel dans ``staging_frontmatter``
      (une clé à ``None`` la supprime du frontmatter).
    - ``body`` (str) : remplace ``staging_body``.

    Garde : le buffer doit avoir été chargé depuis git (``staging_state`` ∈
    {``editing``}). Refuse d'éditer un buffer non chargé pour éviter d'inventer
    un contenu parallèle (git autoritaire).
    """
    wi = _fetch_work_item(conn, work_item_id)
    staging_state = wi.get("staging_state") or "none"
    if staging_state != "editing":
        raise CockpitEditError(
            f"patch refusé : staging_state '{staging_state}' "
            f"(chargez d'abord le buffer depuis git via edit-load)"
        )

    fm = _normalize_fm(wi.get("staging_frontmatter"))
    cur_body = wi.get("staging_body")
    edited = False
    notes: list[str] = []

    if isinstance(frontmatter, dict):
        for k, v in frontmatter.items():
            if v is None:
                fm.pop(k, None)
            else:
                fm[k] = v
        edited = True
        notes.append("frontmatter patché (merge superficiel)")

    if body is not None:
        cur_body = str(body)
        edited = True
        notes.append("corps remplacé")

    if edited:
        conn.execute(
            "UPDATE work_item SET staging_frontmatter = ?, staging_body = ?, "
            "updated_at = ? WHERE id = ?",
            [json.dumps(fm), cur_body, _now_iso(), work_item_id],
        )

    return EditPatchResult(
        work_item_id=work_item_id,
        edited=edited,
        frontmatter=fm,
        body=cur_body,
        staging_state=staging_state,
        notes=notes,
    )
