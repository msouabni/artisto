"""Helpers de transition statut publication (brief MEP-v0/A, 2026-05-10).

Trois helpers purs (= prennent un ``DBConnAdapter``, ne sont **pas** des
endpoints HTTP) qui font progresser une image dans son cycle de publication :

- :func:`mark_image_approved`           : ``image.status`` ``generated`` → ``approved``
- :func:`mark_image_ready_for_export`   : ``image_publication.status`` ``pending`` → ``ready_for_export`` (pour les 3 locales)
- :func:`mark_image_published_alwan`    : ``image_publication.status`` ``ready_for_export`` → ``published_alwan`` (1 locale)

Conventions (cf. ``CLAUDE.md`` §Database) :
- Placeholders SQL ``?`` via ``DBConnAdapter`` (pas de SQL Postgres-only).
- Idempotence : si l'objet est déjà au statut cible → NoOp (pas d'exception).
- ``ValueError`` (Python natif) sur transition invalide (ex. image pas
  ``generated`` quand on appelle ``mark_image_approved``).

Ces helpers sont consommés par le script export (brief C) et plus tard par un
worker publication post-v0. **Aucun endpoint HTTP n'est exposé par ce module.**
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from api.db import DBConnAdapter


# Locales reconnues pour la couche publication MEP v0. Toute extension passe
# par un brief explicite (cohérence avec ``PIPELINE-CONTRACT.md``).
PUBLICATION_LOCALES: tuple[str, ...] = ("fr", "en", "ar")


def mark_image_approved(
    conn: "DBConnAdapter", image_id: str, now: str,
) -> bool:
    """Passe ``image.status`` de ``generated`` à ``approved``.

    Idempotent : si l'image est déjà ``approved`` → NoOp et retourne ``False``.
    Retourne ``True`` si une transition a eu lieu.

    Lève :
    - ``ValueError`` si l'image n'existe pas.
    - ``ValueError`` si le statut courant n'est ni ``generated`` ni ``approved``.

    **Note** : ce helper ne crée pas de lignes ``image_publication`` (responsabilité
    du brief B qui génère le contenu i18n).
    """
    row = conn.execute(
        "SELECT status FROM image WHERE id = ?", [image_id],
    ).fetchone()
    if row is None:
        raise ValueError(f"Image '{image_id}' introuvable")

    current_status = row[0]
    if current_status == "approved":
        return False  # NoOp idempotent
    if current_status != "generated":
        raise ValueError(
            f"Image '{image_id}' a le statut '{current_status}' ; "
            "transition vers 'approved' impossible "
            "(requis : 'generated' ou 'approved').",
        )

    conn.execute(
        "UPDATE image SET status = ?, updated_at = ? WHERE id = ?",
        ["approved", now, image_id],
    )
    return True


def _fetch_publication_rows(
    conn: "DBConnAdapter", image_id: str,
) -> dict[str, dict[str, object | None]]:
    """Retourne ``{locale: row_dict}`` pour les lignes publication d'une image."""
    rows = conn.execute(
        """
        SELECT locale, title, description, post_slug, r2_slug, status
        FROM image_publication WHERE image_id = ?
        """,
        [image_id],
    ).fetchall()
    out: dict[str, dict[str, object | None]] = {}
    for row in rows:
        out[str(row[0])] = {
            "locale": row[0],
            "title": row[1],
            "description": row[2],
            "post_slug": row[3],
            "r2_slug": row[4],
            "status": row[5],
        }
    return out


def mark_image_ready_for_export(
    conn: "DBConnAdapter", image_id: str, now: str,
) -> bool:
    """Passe les 3 lignes ``image_publication`` de ``pending`` à ``ready_for_export``.

    Vérifie que les 3 locales (``fr`` / ``en`` / ``ar``) ont :
    - une ligne en base ;
    - ``title`` non vide ;
    - ``description`` non vide ;
    - ``post_slug`` non vide ;
    - ``r2_slug`` non vide.

    Idempotent : si les 3 lignes sont déjà ``ready_for_export`` (ou plus avancé,
    càd ``published_alwan``) → NoOp et retourne ``False``. Sinon transitionne et
    retourne ``True``.

    Lève :
    - ``ValueError`` si l'image n'a pas exactement 3 lignes publication
      (1 par locale).
    - ``ValueError`` si une locale a un champ obligatoire vide/NULL.
    - ``ValueError`` si une locale a un statut différent de ``pending`` /
      ``ready_for_export`` / ``published_alwan`` (transition invalide).
    """
    rows_by_locale = _fetch_publication_rows(conn, image_id)
    missing = [loc for loc in PUBLICATION_LOCALES if loc not in rows_by_locale]
    if missing:
        raise ValueError(
            f"Image '{image_id}' : lignes publication manquantes pour locales "
            f"{missing} (3 requises : {list(PUBLICATION_LOCALES)}).",
        )
    extra = [loc for loc in rows_by_locale if loc not in PUBLICATION_LOCALES]
    if extra:
        raise ValueError(
            f"Image '{image_id}' : locales inconnues en base "
            f"{extra} (autorisées : {list(PUBLICATION_LOCALES)}).",
        )

    # Validation des champs obligatoires + statuts cohérents.
    required_fields = ("title", "description", "post_slug", "r2_slug")
    incomplete: list[tuple[str, str]] = []
    invalid_status: list[tuple[str, str]] = []
    already_done: list[str] = []
    needs_transition: list[str] = []
    for locale in PUBLICATION_LOCALES:
        row = rows_by_locale[locale]
        for field in required_fields:
            value = row[field]
            if value is None or (isinstance(value, str) and not value.strip()):
                incomplete.append((locale, field))
        status_val = row["status"]
        if status_val in ("ready_for_export", "published_alwan"):
            already_done.append(locale)
        elif status_val == "pending" or status_val is None:
            needs_transition.append(locale)
        else:
            invalid_status.append((locale, str(status_val)))

    if invalid_status:
        raise ValueError(
            f"Image '{image_id}' : statuts publication invalides "
            f"{invalid_status} (attendus : 'pending' / 'ready_for_export' / "
            "'published_alwan').",
        )
    if incomplete:
        raise ValueError(
            f"Image '{image_id}' : champs obligatoires manquants pour "
            f"{incomplete} (title, description, post_slug, r2_slug requis).",
        )

    # Idempotence : si rien à transitionner, NoOp.
    if not needs_transition:
        return False

    for locale in needs_transition:
        conn.execute(
            """
            UPDATE image_publication
            SET status = ?, updated_at = ?
            WHERE image_id = ? AND locale = ?
            """,
            ["ready_for_export", now, image_id, locale],
        )
    return True


def mark_image_published_alwan(
    conn: "DBConnAdapter",
    image_id: str,
    locale: str,
    external_url: str,
    now: str,
) -> bool:
    """Passe une ligne ``image_publication`` de ``ready_for_export`` à ``published_alwan``.

    Met à jour ``external_url`` (URL publique côté Alwan) et ``published_at``.

    Idempotent : si la ligne est déjà ``published_alwan`` → NoOp et retourne
    ``False`` (sans toucher à ``external_url`` ni ``published_at`` ; un re-publish
    avec une autre URL doit passer par un endpoint explicite hors v0).

    Lève :
    - ``ValueError`` si la locale n'est pas reconnue.
    - ``ValueError`` si ``external_url`` est vide.
    - ``ValueError`` si la ligne n'existe pas.
    - ``ValueError`` si le statut courant n'est pas ``ready_for_export``
      (transition invalide depuis ``pending`` ou autre).
    """
    if locale not in PUBLICATION_LOCALES:
        raise ValueError(
            f"Locale '{locale}' inconnue (autorisées : "
            f"{list(PUBLICATION_LOCALES)}).",
        )
    if not external_url or not external_url.strip():
        raise ValueError(
            f"external_url vide pour image '{image_id}' locale '{locale}'.",
        )

    row = conn.execute(
        "SELECT status FROM image_publication WHERE image_id = ? AND locale = ?",
        [image_id, locale],
    ).fetchone()
    if row is None:
        raise ValueError(
            f"Ligne publication absente pour image '{image_id}' locale "
            f"'{locale}'.",
        )

    current_status = row[0]
    if current_status == "published_alwan":
        return False  # NoOp idempotent
    if current_status != "ready_for_export":
        raise ValueError(
            f"Image '{image_id}' locale '{locale}' : statut '{current_status}' "
            "; transition vers 'published_alwan' impossible "
            "(requis : 'ready_for_export').",
        )

    conn.execute(
        """
        UPDATE image_publication
        SET status = ?, external_url = ?, published_at = ?, updated_at = ?
        WHERE image_id = ? AND locale = ?
        """,
        ["published_alwan", external_url, now, now, image_id, locale],
    )
    return True
