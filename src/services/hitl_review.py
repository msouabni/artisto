"""Gates de revue HITL (image / texte) — Phase 2, incrément 1.

Cap (ADR §5) : supervision humaine du staging avant commit git. Le staging
n'est jamais servi ; seul l'approuvé entre dans git (via cockpit_git_publish).

Deux gates :

  revue IMAGE  (``review_image``) :
      approve → ``review_text``
      reject  → ``generating`` (re-générer) | drop → ``none``

  revue TEXTE  (``review_text``) :
      ``edits`` (optionnel) patche ``staging_frontmatter`` / ``staging_body``
                (édition LÉGÈRE en revue — pas une seconde vérité : reste du
                 staging transitoire, purgé au commit)
      approve → ``approved``  (autorise le commit git)
      reject  → ``review_image`` | ``generating``

L'approbation finale (``approved``) autorise ``commit_work_item`` (seule porte
d'entrée git). Le commit repasse ``staging_state`` à ``none`` (buffer purgé).

Fonctions métier + horodatage. PostgreSQL unique. SQLite interdit.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from services.hitl import (
    HitlTransitionError,
    get_staging_state,
    set_plate_state,
    transition_staging,
)


class ReviewError(RuntimeError):
    """Erreur métier d'un gate de revue (décision inconnue, état incompatible…)."""


@dataclass
class ReviewResult:
    work_item_id: str
    gate: str                 # 'image' | 'text'
    decision: str             # 'approve' | 'reject'
    from_state: str
    to_state: str
    edited: bool = False
    note: str | None = None
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "work_item_id": self.work_item_id,
            "gate": self.gate,
            "decision": self.decision,
            "from_state": self.from_state,
            "to_state": self.to_state,
            "edited": self.edited,
            "note": self.note,
            "notes": self.notes,
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_fm(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ReviewError(f"staging_frontmatter JSON invalide : {exc}") from exc
        return data if isinstance(data, dict) else {}
    return {}


# ── Gate IMAGE ─────────────────────────────────────────────────────────────────

def review_image(
    conn: Any,
    work_item_id: str,
    decision: str,
    *,
    note: str | None = None,
    drop: bool = False,
) -> ReviewResult:
    """Gate revue IMAGE. ``decision`` ∈ {approve, reject}.

    - approve → ``review_text`` (l'image convient, on passe au texte).
    - reject  → ``generating`` (re-générer) ; ``drop=True`` → ``none`` (abandon).

    Garde : doit partir de ``review_image``. Transition gardée + horodatée.
    """
    if decision not in ("approve", "reject"):
        raise ReviewError(f"décision image inconnue : {decision!r} (approve|reject)")

    src = get_staging_state(conn, work_item_id)
    if src != "review_image":
        raise HitlTransitionError(
            f"revue IMAGE impossible : staging_state '{src}' (attendu 'review_image')"
        )

    notes: list[str] = []
    if decision == "approve":
        transition_staging(conn, work_item_id, "review_text", src_expected="review_image")
        notes.append("image approuvée → review_text")
        to_state = "review_text"
    else:
        if drop:
            transition_staging(conn, work_item_id, "none", src_expected="review_image")
            set_plate_state(conn, work_item_id, "none")
            notes.append("image rejetée + drop → none (abandon)")
            to_state = "none"
        else:
            transition_staging(conn, work_item_id, "generating", src_expected="review_image")
            set_plate_state(conn, work_item_id, "pending")
            notes.append("image rejetée → generating (re-générer)")
            to_state = "generating"

    return ReviewResult(
        work_item_id=work_item_id, gate="image", decision=decision,
        from_state=src, to_state=to_state, note=note, notes=notes,
    )


# ── Gate TEXTE ──────────────────────────────────────────────────────────────────

def review_text(
    conn: Any,
    work_item_id: str,
    decision: str,
    *,
    edits: dict[str, Any] | None = None,
    note: str | None = None,
    back_to_generating: bool = False,
) -> ReviewResult:
    """Gate revue TEXTE. ``decision`` ∈ {approve, reject}.

    ``edits`` (optionnel) = édition LÉGÈRE en revue, patchée dans le staging
    (jamais une seconde vérité : reste transitoire, purgé au commit) :
      - ``edits['frontmatter']`` (dict) : merge superficiel dans
        ``staging_frontmatter`` ;
      - ``edits['body']`` (str) : remplace ``staging_body``.

    - approve → ``approved`` (autorise le commit git).
    - reject  → ``review_image`` (revoir l'image) ; ``back_to_generating=True``
      → ``generating`` (re-générer).

    Garde : doit partir de ``review_text``. L'édition s'applique AVANT la
    transition (le commit ultérieur lira le staging patché).
    """
    if decision not in ("approve", "reject"):
        raise ReviewError(f"décision texte inconnue : {decision!r} (approve|reject)")

    src = get_staging_state(conn, work_item_id)
    if src != "review_text":
        raise HitlTransitionError(
            f"revue TEXTE impossible : staging_state '{src}' (attendu 'review_text')"
        )

    notes: list[str] = []
    edited = False

    # Édition légère : patch du staging buffer (transitoire). Appliquée même si
    # la décision finale est reject (on conserve les corrections pour la reprise).
    if edits:
        rows = conn.execute(
            "SELECT staging_frontmatter, staging_body FROM work_item WHERE id = ?",
            [work_item_id],
        ).fetchall()
        if not rows:
            raise ReviewError(f"work_item '{work_item_id}' introuvable")
        fm = _normalize_fm(rows[0][0])
        body = rows[0][1]

        fm_patch = edits.get("frontmatter")
        if isinstance(fm_patch, dict):
            fm.update(fm_patch)
            edited = True
        if "body" in edits and edits["body"] is not None:
            body = str(edits["body"])
            edited = True

        if edited:
            conn.execute(
                "UPDATE work_item SET staging_frontmatter = ?, staging_body = ?, "
                "updated_at = ? WHERE id = ?",
                [json.dumps(fm), body, _now_iso(), work_item_id],
            )
            notes.append("édition légère appliquée au staging (transitoire)")

    if decision == "approve":
        transition_staging(conn, work_item_id, "approved", src_expected="review_text")
        notes.append("texte approuvé → approved (commit autorisé)")
        to_state = "approved"
    else:
        if back_to_generating:
            transition_staging(conn, work_item_id, "generating", src_expected="review_text")
            set_plate_state(conn, work_item_id, "pending")
            notes.append("texte rejeté → generating (re-générer)")
            to_state = "generating"
        else:
            transition_staging(conn, work_item_id, "review_image", src_expected="review_text")
            notes.append("texte rejeté → review_image (revoir l'image)")
            to_state = "review_image"

    return ReviewResult(
        work_item_id=work_item_id, gate="text", decision=decision,
        from_state=src, to_state=to_state, edited=edited, note=note, notes=notes,
    )
