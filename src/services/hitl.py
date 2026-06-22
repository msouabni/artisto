"""Machine d'états HITL (supervision humaine) du buffer de staging — Phase 2.

Cap (cf. ``alwanbooks-docs/DIRECTION-PHASE-2026-06-22.md`` + ADR
``2026-06-22_DOSSIER-cockpit-plan-controle-git-verite.md`` §5) :

    git = vérité du contenu. Le staging d'un ``work_item`` (frontmatter + corps
    + plaque mock) n'est JAMAIS servi ni autoritaire. Sa seule issue est un
    **commit git** (seule porte d'entrée). Cette machine d'états encadre la
    supervision humaine PENDANT que le work_item est en orchestration
    ``state='construction'`` :

        none ──generate──► generating ──(plaque+méta prêtes)──► review_image
        review_image ──approve──► review_text ──approve──► approved ──commit──► none
        review_image ──reject──►  generating (re-générer) | drop → none
        review_text  ──reject──►  review_image | generating
        approved     ──commit──►  none  (buffer purgé ; le work_item avance)

``committed`` n'est pas un état stocké : après commit, ``staging_state`` repasse
à ``none`` (buffer purgé) — la preuve du commit vit dans git (réindexé).

Fonctions PURES (validation des transitions) + helpers DB. Les transitions sont
**gardées** (transition illégale → ``HitlTransitionError``) et **horodatées**
(``work_item.updated_at``). Aucune transition n'écrit du contenu autoritaire.

PostgreSQL unique. SQLite interdit (y compris tests).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from api.cockpit_models import HITL_STATES, PLATE_STATES

# ── Transitions autorisées (gardées) ──────────────────────────────────────────
#
# Chaque clé = état source ; valeur = ensemble des états cibles atteignables par
# une action HITL. ``approved → none`` est franchie UNIQUEMENT par le commit
# (cf. cockpit_git_publish.commit_work_item), modélisée ici pour la complétude.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "none": {"generating"},
    "generating": {"review_image"},          # quand la plaque mock + méta sont prêtes
    "review_image": {"review_text", "generating", "none"},  # approve | reject(regen) | drop
    "review_text": {"approved", "review_image", "generating"},  # approve | reject
    "approved": {"none"},                    # commit (purge) — porté par le commit git
    "rejected": {"none", "generating"},
}

# Action HITL → (état source attendu, état cible). Sert au routage des endpoints
# et aux messages d'erreur explicites.
GENERATE_FROM = ("none", "review_image", "generating", "rejected")


class HitlTransitionError(RuntimeError):
    """Transition HITL illégale (état source incompatible avec l'action)."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def can_transition(src: str, dst: str) -> bool:
    """Vrai si ``src → dst`` est une transition HITL autorisée (fonction pure)."""
    return dst in ALLOWED_TRANSITIONS.get(src, set())


def assert_transition(src: str, dst: str) -> None:
    """Lève ``HitlTransitionError`` si ``src → dst`` est illégale."""
    if dst not in HITL_STATES:
        raise HitlTransitionError(f"état cible inconnu : {dst!r}")
    if not can_transition(src, dst):
        allowed = sorted(ALLOWED_TRANSITIONS.get(src, set()))
        raise HitlTransitionError(
            f"transition HITL illégale : {src!r} → {dst!r} "
            f"(depuis {src!r}, autorisé : {allowed or '∅'})"
        )


# ── Helpers DB (lecture / écriture de staging_state, horodatée) ────────────────

def get_staging_state(conn: Any, work_item_id: str) -> str:
    """Lit ``work_item.staging_state``. Lève si le work_item est introuvable."""
    rows = conn.execute(
        "SELECT staging_state FROM work_item WHERE id = ?", [work_item_id]
    ).fetchall()
    if not rows:
        raise HitlTransitionError(f"work_item '{work_item_id}' introuvable")
    return rows[0][0] or "none"


def transition_staging(
    conn: Any,
    work_item_id: str,
    dst: str,
    *,
    src_expected: str | None = None,
) -> str:
    """Transitionne ``staging_state`` vers ``dst`` (gardé + horodaté).

    Args:
        conn: ``DBConnAdapter`` (Postgres).
        work_item_id: work_item à transitionner.
        dst: état cible (∈ HITL_STATES).
        src_expected: si fourni, vérifie que l'état courant == src_expected (garde
            anti-course : refuse d'approuver une image si on n'est pas en
            ``review_image``, etc.). Sinon on garde juste la légalité src→dst.

    Returns:
        L'état source observé (avant transition).
    """
    src = get_staging_state(conn, work_item_id)
    if src_expected is not None and src != src_expected:
        raise HitlTransitionError(
            f"work_item '{work_item_id}' en staging_state '{src}' "
            f"(attendu '{src_expected}' pour cette action)"
        )
    assert_transition(src, dst)
    conn.execute(
        "UPDATE work_item SET staging_state = ?, updated_at = ? WHERE id = ?",
        [dst, _now_iso(), work_item_id],
    )
    return src


# ── Plaque (état de génération) ────────────────────────────────────────────────

def set_plate_state(conn: Any, work_item_id: str, image_state: str) -> None:
    """Pose ``plate_image.image_state`` (upsert horodaté). ∈ PLATE_STATES."""
    if image_state not in PLATE_STATES:
        raise HitlTransitionError(f"plate image_state inconnu : {image_state!r}")
    now = _now_iso()
    rows = conn.execute(
        "SELECT id FROM plate_image WHERE work_item_id = ?", [work_item_id]
    ).fetchall()
    if rows:
        conn.execute(
            "UPDATE plate_image SET image_state = ?, updated_at = ? WHERE id = ?",
            [image_state, now, rows[0][0]],
        )
    else:
        from services.git_indexer import _new_id  # réutilise le générateur d'id

        conn.execute(
            "INSERT INTO plate_image (id, work_item_id, image_state, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            [_new_id("plate"), work_item_id, image_state, now, now],
        )


def get_plate(conn: Any, work_item_id: str) -> dict[str, Any] | None:
    """Lit la plaque d'un work_item (ou ``None``)."""
    cols = ["id", "work_item_id", "image_state", "style_source",
            "preview_url", "mock_meta", "created_at", "updated_at"]
    rows = conn.execute(
        f"SELECT {', '.join(cols)} FROM plate_image WHERE work_item_id = ?",
        [work_item_id],
    ).fetchall()
    if not rows:
        return None
    return dict(zip(cols, rows[0]))
