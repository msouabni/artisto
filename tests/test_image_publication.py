"""Tests pour ``src/api/image_publication.py`` + table ``image_publication``.

Brief : ``docs/architect/briefs/2026-05-10_brief-mep-v0-A-modele-publication.md``.

Couvre :
- Création des 3 lignes (1 image × 3 locales = 3 lignes) côté modèle.
- Unicité ``(locale, post_slug)`` (IntegrityError sur doublon dans une locale,
  OK sur même slug entre locales).
- FK ``image_id`` + ``ON DELETE CASCADE`` (suppression image → suppression
  publication) — testé avec ``PRAGMA foreign_keys=ON`` côté SQLite.
- ``mark_image_approved`` : transition ``generated`` → ``approved``, idempotence,
  ``ValueError`` sur statut invalide / image inconnue.
- ``mark_image_ready_for_export`` : OK si les 3 locales sont prêtes,
  ``ValueError`` si une locale incomplète, idempotence, statut invalide.
- ``mark_image_published_alwan`` : met ``external_url`` + ``published_at``,
  idempotence, ``ValueError`` sur locale inconnue / external_url vide /
  transition invalide.

Conventions :
- DB in-memory SQLite (cf. ``conftest.py``), schéma reconstruit depuis le
  modèle SQLAlchemy. La migration Alembic ``0007`` cible Postgres et n'est
  pas exécutée ici.
- Placeholders SQL ``?`` via ``DBConnAdapter``.
- Pas d'opérateur JSONB Postgres-only — colonnes scalaires uniquement.
"""
from __future__ import annotations

import sys
from typing import Iterable

import pytest
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError

sys.path.insert(0, "src")

from api.image_publication import (
    PUBLICATION_LOCALES,
    mark_image_approved,
    mark_image_published_alwan,
    mark_image_ready_for_export,
)


_NOW = "2026-05-10T10:00:00Z"
_LATER = "2026-05-10T11:00:00Z"


# ── Fixtures locales ─────────────────────────────────────────────────────────


@pytest.fixture
def conn_fk(test_conn):
    """Active ``PRAGMA foreign_keys=ON`` sur la connexion SQLite du test.

    SQLite ne respecte pas ``ON DELETE CASCADE`` sans ce PRAGMA. On l'active
    par event listener pour que la session courante (et toute nouvelle
    connection issue du pool) l'applique. Pas d'impact côté Postgres.
    """
    engine = test_conn.session.get_bind()

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_connection, _connection_record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    # Activer aussi sur la connexion déjà en cours.
    test_conn.execute("PRAGMA foreign_keys=ON")
    test_conn.session.commit()
    return test_conn


# ── Helpers ──────────────────────────────────────────────────────────────────


def _insert_image(
    conn,
    *,
    image_id: str = "img_lion_001",
    status: str = "generated",
    title: str = "Lion",
    prompt: str = "a lion in savanna",
) -> None:
    conn.execute(
        """
        INSERT INTO image (id, title, status, prompt, negative_prompt,
                           file_path, created_at, updated_at)
        VALUES (?, ?, ?, ?, '', '', ?, ?)
        """,
        [image_id, title, status, prompt, _NOW, _NOW],
    )


# Sentinel pour distinguer « argument non fourni » de « explicitement None ».
_UNSET = object()


def _insert_publication_row(
    conn,
    *,
    image_id: str,
    locale: str,
    title: str | None = "Lion FR",
    description: str | None = "Un lion dans la savane.",
    post_slug=_UNSET,
    r2_slug: str | None = "lion-001",
    status: str | None = "pending",
    external_url: str | None = None,
    published_at: str | None = None,
) -> None:
    if post_slug is _UNSET:
        post_slug = f"lion-{locale}"
    conn.execute(
        """
        INSERT INTO image_publication
            (image_id, locale, title, description, post_slug, r2_slug,
             status, external_url, created_at, updated_at, published_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            image_id, locale, title, description, post_slug, r2_slug,
            status, external_url, _NOW, _NOW, published_at,
        ],
    )


def _create_complete_publication(
    conn, image_id: str, *, status: str = "pending",
) -> None:
    """Crée les 3 lignes publication complètes pour une image."""
    for locale in PUBLICATION_LOCALES:
        _insert_publication_row(
            conn,
            image_id=image_id,
            locale=locale,
            title=f"Title {locale}",
            description=f"Description {locale} non vide.",
            post_slug=f"slug-post-{locale}",
            r2_slug="shared-r2-slug",
            status=status,
        )


def _fetch_publication_statuses(
    conn, image_id: str,
) -> dict[str, str | None]:
    rows = conn.execute(
        "SELECT locale, status FROM image_publication WHERE image_id = ?",
        [image_id],
    ).fetchall()
    return {str(r[0]): r[1] for r in rows}


def _fetch_pub_row(conn, image_id: str, locale: str) -> dict:
    row = conn.execute(
        """
        SELECT image_id, locale, title, description, post_slug, r2_slug,
               status, external_url, published_at
        FROM image_publication WHERE image_id = ? AND locale = ?
        """,
        [image_id, locale],
    ).fetchone()
    assert row is not None
    cols: Iterable[str] = (
        "image_id", "locale", "title", "description", "post_slug", "r2_slug",
        "status", "external_url", "published_at",
    )
    return dict(zip(cols, row))


# ── Schéma + contraintes ─────────────────────────────────────────────────────


class TestSchemaAndConstraints:
    def test_3_locales_par_image(self, test_conn):
        _insert_image(test_conn, image_id="img_a")
        _create_complete_publication(test_conn, "img_a")
        statuses = _fetch_publication_statuses(test_conn, "img_a")
        assert set(statuses.keys()) == {"fr", "en", "ar"}
        assert all(s == "pending" for s in statuses.values())

    def test_unicite_locale_post_slug(self, test_conn):
        _insert_image(test_conn, image_id="img_a")
        _insert_image(test_conn, image_id="img_b")
        _insert_publication_row(
            test_conn, image_id="img_a", locale="fr",
            post_slug="conflit-fr",
        )
        # Même slug, même locale → IntegrityError
        with pytest.raises(IntegrityError):
            _insert_publication_row(
                test_conn, image_id="img_b", locale="fr",
                post_slug="conflit-fr",
            )
        test_conn.session.rollback()

    def test_meme_post_slug_locales_differentes_ok(self, test_conn):
        """Le slug peut coexister entre locales différentes."""
        _insert_image(test_conn, image_id="img_a")
        _insert_publication_row(
            test_conn, image_id="img_a", locale="fr",
            post_slug="le-lion",
        )
        # Même slug, locale différente → autorisé (pas d'unicité globale)
        _insert_publication_row(
            test_conn, image_id="img_a", locale="en",
            post_slug="le-lion",
        )
        test_conn.session.commit()
        rows = test_conn.execute(
            "SELECT locale FROM image_publication WHERE post_slug = ?",
            ["le-lion"],
        ).fetchall()
        assert sorted(r[0] for r in rows) == ["en", "fr"]

    def test_fk_cascade_delete_image(self, conn_fk):
        """Supprimer l'image supprime toutes les lignes publication."""
        _insert_image(conn_fk, image_id="img_cascade")
        _create_complete_publication(conn_fk, "img_cascade")
        conn_fk.session.commit()
        count_before = conn_fk.execute(
            "SELECT COUNT(*) FROM image_publication WHERE image_id = ?",
            ["img_cascade"],
        ).fetchone()[0]
        assert count_before == 3

        conn_fk.execute("DELETE FROM image WHERE id = ?", ["img_cascade"])
        conn_fk.session.commit()

        count_after = conn_fk.execute(
            "SELECT COUNT(*) FROM image_publication WHERE image_id = ?",
            ["img_cascade"],
        ).fetchone()[0]
        assert count_after == 0


# ── mark_image_approved ──────────────────────────────────────────────────────


class TestMarkImageApproved:
    def test_transition_generated_vers_approved(self, test_conn):
        _insert_image(test_conn, image_id="img_a", status="generated")
        changed = mark_image_approved(test_conn, "img_a", _NOW)
        assert changed is True
        row = test_conn.execute(
            "SELECT status, updated_at FROM image WHERE id = ?", ["img_a"],
        ).fetchone()
        assert row[0] == "approved"
        assert row[1] == _NOW

    def test_idempotence_noop_si_deja_approved(self, test_conn):
        _insert_image(test_conn, image_id="img_a", status="approved")
        changed = mark_image_approved(test_conn, "img_a", _LATER)
        assert changed is False
        row = test_conn.execute(
            "SELECT status, updated_at FROM image WHERE id = ?", ["img_a"],
        ).fetchone()
        assert row[0] == "approved"
        # updated_at non touché par le NoOp
        assert row[1] == _NOW

    def test_image_inconnue_leve_value_error(self, test_conn):
        with pytest.raises(ValueError, match="introuvable"):
            mark_image_approved(test_conn, "img_inexistant", _NOW)

    def test_statut_invalide_leve_value_error(self, test_conn):
        _insert_image(test_conn, image_id="img_a", status="draft")
        with pytest.raises(ValueError, match="transition vers 'approved'"):
            mark_image_approved(test_conn, "img_a", _NOW)

    def test_statut_scheduled_leve_value_error(self, test_conn):
        """Toute autre transition que 'generated' (ou 'approved' = NoOp) est rejetée."""
        _insert_image(test_conn, image_id="img_a", status="scheduled")
        with pytest.raises(ValueError):
            mark_image_approved(test_conn, "img_a", _NOW)


# ── mark_image_ready_for_export ──────────────────────────────────────────────


class TestMarkImageReadyForExport:
    def test_transition_si_3_locales_pretes(self, test_conn):
        _insert_image(test_conn, image_id="img_a")
        _create_complete_publication(test_conn, "img_a", status="pending")
        changed = mark_image_ready_for_export(test_conn, "img_a", _NOW)
        assert changed is True
        statuses = _fetch_publication_statuses(test_conn, "img_a")
        assert all(s == "ready_for_export" for s in statuses.values())

    def test_value_error_si_une_locale_manquante(self, test_conn):
        _insert_image(test_conn, image_id="img_a")
        # 2 locales sur 3 seulement
        _insert_publication_row(
            test_conn, image_id="img_a", locale="fr",
            title="t", description="d", post_slug="s-fr", r2_slug="r2",
        )
        _insert_publication_row(
            test_conn, image_id="img_a", locale="en",
            title="t", description="d", post_slug="s-en", r2_slug="r2",
        )
        with pytest.raises(ValueError, match="manquantes"):
            mark_image_ready_for_export(test_conn, "img_a", _NOW)

    def test_value_error_si_title_vide(self, test_conn):
        _insert_image(test_conn, image_id="img_a")
        for locale in PUBLICATION_LOCALES:
            _insert_publication_row(
                test_conn, image_id="img_a", locale=locale,
                title=("OK" if locale != "ar" else ""),
                description="d", post_slug=f"s-{locale}", r2_slug="r2",
            )
        with pytest.raises(ValueError, match="champs obligatoires"):
            mark_image_ready_for_export(test_conn, "img_a", _NOW)

    def test_value_error_si_description_null(self, test_conn):
        _insert_image(test_conn, image_id="img_a")
        for locale in PUBLICATION_LOCALES:
            _insert_publication_row(
                test_conn, image_id="img_a", locale=locale,
                title="t",
                description=(None if locale == "fr" else "d"),
                post_slug=f"s-{locale}", r2_slug="r2",
            )
        with pytest.raises(ValueError, match="champs obligatoires"):
            mark_image_ready_for_export(test_conn, "img_a", _NOW)

    def test_value_error_si_post_slug_null(self, test_conn):
        _insert_image(test_conn, image_id="img_a")
        for locale in PUBLICATION_LOCALES:
            _insert_publication_row(
                test_conn, image_id="img_a", locale=locale,
                title="t", description="d",
                post_slug=(None if locale == "en" else f"s-{locale}"),
                r2_slug="r2",
            )
        with pytest.raises(ValueError, match="champs obligatoires"):
            mark_image_ready_for_export(test_conn, "img_a", _NOW)

    def test_value_error_si_r2_slug_null(self, test_conn):
        _insert_image(test_conn, image_id="img_a")
        for locale in PUBLICATION_LOCALES:
            _insert_publication_row(
                test_conn, image_id="img_a", locale=locale,
                title="t", description="d",
                post_slug=f"s-{locale}",
                r2_slug=(None if locale == "ar" else "r2"),
            )
        with pytest.raises(ValueError, match="champs obligatoires"):
            mark_image_ready_for_export(test_conn, "img_a", _NOW)

    def test_idempotence_noop_si_deja_ready(self, test_conn):
        _insert_image(test_conn, image_id="img_a")
        _create_complete_publication(
            test_conn, "img_a", status="ready_for_export",
        )
        changed = mark_image_ready_for_export(test_conn, "img_a", _LATER)
        assert changed is False
        statuses = _fetch_publication_statuses(test_conn, "img_a")
        assert all(s == "ready_for_export" for s in statuses.values())

    def test_value_error_si_statut_invalide(self, test_conn):
        _insert_image(test_conn, image_id="img_a")
        # 2 pending + 1 statut farfelu
        for locale in PUBLICATION_LOCALES:
            _insert_publication_row(
                test_conn, image_id="img_a", locale=locale,
                title="t", description="d",
                post_slug=f"s-{locale}", r2_slug="r2",
                status=("draft" if locale == "fr" else "pending"),
            )
        with pytest.raises(ValueError, match="statuts publication invalides"):
            mark_image_ready_for_export(test_conn, "img_a", _NOW)

    def test_transition_partielle_si_certaines_deja_ready(self, test_conn):
        """Mix pending + ready_for_export → on transitionne uniquement les pending."""
        _insert_image(test_conn, image_id="img_a")
        _insert_publication_row(
            test_conn, image_id="img_a", locale="fr",
            title="t", description="d", post_slug="s-fr", r2_slug="r2",
            status="ready_for_export",
        )
        _insert_publication_row(
            test_conn, image_id="img_a", locale="en",
            title="t", description="d", post_slug="s-en", r2_slug="r2",
            status="pending",
        )
        _insert_publication_row(
            test_conn, image_id="img_a", locale="ar",
            title="t", description="d", post_slug="s-ar", r2_slug="r2",
            status="pending",
        )
        changed = mark_image_ready_for_export(test_conn, "img_a", _LATER)
        assert changed is True
        statuses = _fetch_publication_statuses(test_conn, "img_a")
        assert statuses == {
            "fr": "ready_for_export",
            "en": "ready_for_export",
            "ar": "ready_for_export",
        }


# ── mark_image_published_alwan ───────────────────────────────────────────────


class TestMarkImagePublishedAlwan:
    def test_transition_met_external_url_et_published_at(self, test_conn):
        _insert_image(test_conn, image_id="img_a")
        _create_complete_publication(
            test_conn, "img_a", status="ready_for_export",
        )
        changed = mark_image_published_alwan(
            test_conn, "img_a", "fr",
            "https://alwanbooks.com/fr/lion", _NOW,
        )
        assert changed is True
        row = _fetch_pub_row(test_conn, "img_a", "fr")
        assert row["status"] == "published_alwan"
        assert row["external_url"] == "https://alwanbooks.com/fr/lion"
        assert row["published_at"] == _NOW
        # Les autres locales ne sont pas touchées
        row_en = _fetch_pub_row(test_conn, "img_a", "en")
        assert row_en["status"] == "ready_for_export"
        assert row_en["external_url"] is None

    def test_idempotence_si_deja_published(self, test_conn):
        _insert_image(test_conn, image_id="img_a")
        _insert_publication_row(
            test_conn, image_id="img_a", locale="fr",
            title="t", description="d", post_slug="s-fr", r2_slug="r2",
            status="published_alwan",
            external_url="https://existing.com",
            published_at=_NOW,
        )
        changed = mark_image_published_alwan(
            test_conn, "img_a", "fr",
            "https://new-url-ignoree.com", _LATER,
        )
        assert changed is False
        row = _fetch_pub_row(test_conn, "img_a", "fr")
        # URL et published_at non écrasés par NoOp
        assert row["external_url"] == "https://existing.com"
        assert row["published_at"] == _NOW

    def test_value_error_locale_inconnue(self, test_conn):
        _insert_image(test_conn, image_id="img_a")
        with pytest.raises(ValueError, match="Locale 'de' inconnue"):
            mark_image_published_alwan(
                test_conn, "img_a", "de", "https://x", _NOW,
            )

    def test_value_error_external_url_vide(self, test_conn):
        _insert_image(test_conn, image_id="img_a")
        _create_complete_publication(
            test_conn, "img_a", status="ready_for_export",
        )
        with pytest.raises(ValueError, match="external_url vide"):
            mark_image_published_alwan(
                test_conn, "img_a", "fr", "", _NOW,
            )
        with pytest.raises(ValueError, match="external_url vide"):
            mark_image_published_alwan(
                test_conn, "img_a", "fr", "   ", _NOW,
            )

    def test_value_error_ligne_absente(self, test_conn):
        _insert_image(test_conn, image_id="img_a")
        # Pas de ligne image_publication
        with pytest.raises(ValueError, match="Ligne publication absente"):
            mark_image_published_alwan(
                test_conn, "img_a", "fr",
                "https://alwanbooks.com/fr/x", _NOW,
            )

    def test_value_error_transition_invalide_depuis_pending(self, test_conn):
        _insert_image(test_conn, image_id="img_a")
        _create_complete_publication(test_conn, "img_a", status="pending")
        with pytest.raises(ValueError, match="transition vers 'published_alwan'"):
            mark_image_published_alwan(
                test_conn, "img_a", "fr",
                "https://alwanbooks.com/fr/x", _NOW,
            )
