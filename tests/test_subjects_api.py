"""Tests pour ``src/api/routes/subjects.py`` (modèle subject éditorial).

Brief : ``docs/architect/briefs/2026-05-10_brief-modele-subject.md``.

Couvre :
- Liste vide, liste filtrée par term_id / vocabulary_id / status, pagination
- GET /{id} 404 sur id inconnu, 200 sur cas valide
- POST création : 201 sur cas nominal, 404 si term absent, 409 sur dup,
  validation Pydantic (name vide, status hors whitelist, note 0-6, tags
  hors whitelist), id auto-généré ou explicite
- PUT update partiel : 200 sur cas nominal, 404 si absent, 409 si rename
  collision ; champs absents = inchangés
- DELETE : 200 + 404 sur id inconnu
- Whitelists : valeurs exactes vérifiées
- NULL-safe : note=None, metadata=None, tags=[] correctement renvoyés
"""
from __future__ import annotations

import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, "src")


# ── Helpers ──────────────────────────────────────────────────────────────────


def _client(app):
    return TestClient(app)


def _insert_term(conn, *, term_id: str, vocab_id: str = "themes") -> None:
    """Insère un term parent (la conftest a déjà créé taxonomy + vocab themes)."""
    conn.execute(
        """
        INSERT INTO term (id, vocabulary_id, slug, slug_i18n, name_i18n,
                          weight, created_at, updated_at)
        VALUES (?, ?, ?, '{}', '{}', 0, '2026-05-10', '2026-05-10')
        """,
        [term_id, vocab_id, term_id],
    )


def _create_subject(client: TestClient, **overrides):
    """Helper de création POST /api/subjects avec overrides clé/valeur."""
    body = {
        "term_id": "lion",
        "vocabulary_id": "themes",
        "name": "lion mâle adulte",
        "status": "draft",
    }
    body.update(overrides)
    r = client.post("/api/subjects", json=body)
    return r


# ── GET /api/subjects (liste) ────────────────────────────────────────────────


def test_list_empty(app_with_test_db):
    """DB vide → count=0, items=[]."""
    r = _client(app_with_test_db).get("/api/subjects")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 0
    assert body["items"] == []


def test_list_with_filters_term_id_and_status(app_with_test_db, test_conn):
    """Filtrage combiné term_id + status."""
    _insert_term(test_conn, term_id="lion")
    _insert_term(test_conn, term_id="tiger")
    test_conn.session.commit()

    client = _client(app_with_test_db)
    assert _create_subject(client, term_id="lion", name="A", status="draft").status_code == 201
    assert _create_subject(client, term_id="lion", name="B", status="validated").status_code == 201
    assert _create_subject(client, term_id="tiger", name="C", status="draft").status_code == 201

    r = client.get("/api/subjects?term_id=lion")
    assert r.status_code == 200
    names = {item["name"] for item in r.json()["items"]}
    assert names == {"A", "B"}

    r = client.get("/api/subjects?term_id=lion&status=validated")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["name"] == "B"


def test_list_filter_unknown_status_400(app_with_test_db):
    """``status`` hors whitelist en query → 400."""
    r = _client(app_with_test_db).get("/api/subjects?status=bogus")
    assert r.status_code == 400
    assert "unknown status filter" in r.json()["detail"]


def test_list_pagination(app_with_test_db, test_conn):
    """``limit`` + ``offset`` : 5 items, limit=2 offset=2 → 2 items du milieu."""
    _insert_term(test_conn, term_id="lion")
    test_conn.session.commit()

    client = _client(app_with_test_db)
    for i in range(5):
        assert _create_subject(client, term_id="lion", name=f"name_{i}").status_code == 201

    r = client.get("/api/subjects?limit=2&offset=2")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2
    assert len(body["items"]) == 2


# ── GET /api/subjects/{id} ───────────────────────────────────────────────────


def test_get_404_on_unknown_id(app_with_test_db):
    r = _client(app_with_test_db).get("/api/subjects/does-not-exist")
    assert r.status_code == 404


def test_get_200_with_full_payload(app_with_test_db, test_conn):
    """Création + GET → tous les champs correctement renvoyés (NULL-safe)."""
    _insert_term(test_conn, term_id="lion")
    test_conn.session.commit()

    client = _client(app_with_test_db)
    r = _create_subject(
        client,
        term_id="lion",
        name="lionceau jouant",
        note=4,
        tags=["creatif", "parfait"],
        brief="Un lionceau de 3 mois jouant dans la savane.",
        metadata={"source": "brief-2026-05-10", "priority": 3},
    )
    assert r.status_code == 201, r.text
    sid = r.json()["id"]

    r2 = client.get(f"/api/subjects/{sid}")
    assert r2.status_code == 200
    body = r2.json()
    assert body["id"] == sid
    assert body["term_id"] == "lion"
    assert body["vocabulary_id"] == "themes"
    assert body["name"] == "lionceau jouant"
    assert body["status"] == "draft"
    assert body["note"] == 4
    assert body["tags"] == ["creatif", "parfait"]
    assert "lionceau" in body["brief"]
    assert body["metadata"] == {"source": "brief-2026-05-10", "priority": 3}
    assert body["created_at"]
    assert body["updated_at"]


# ── POST /api/subjects ───────────────────────────────────────────────────────


def test_create_minimal_returns_201_and_generated_id(app_with_test_db, test_conn):
    """Cas minimal : id auto-généré (UUID4), status défaut, tags=[]."""
    _insert_term(test_conn, term_id="lion")
    test_conn.session.commit()

    r = _create_subject(_client(app_with_test_db), term_id="lion", name="solo")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["id"]
    # UUID parse OK
    uuid.UUID(body["id"])
    assert body["status"] == "draft"
    assert body["tags"] == []
    assert body["note"] is None
    assert body["metadata"] is None


def test_create_with_explicit_id_accepted(app_with_test_db, test_conn):
    """Si ``id`` explicite est fourni, il est utilisé."""
    _insert_term(test_conn, term_id="lion")
    test_conn.session.commit()

    r = _create_subject(
        _client(app_with_test_db),
        id="subj_lion_001",
        term_id="lion",
        name="solo male",
    )
    assert r.status_code == 201, r.text
    assert r.json()["id"] == "subj_lion_001"


def test_create_404_when_term_does_not_exist(app_with_test_db):
    """Term parent absent → 404 (avant tout INSERT)."""
    r = _create_subject(
        _client(app_with_test_db),
        term_id="ghost-term",
        vocabulary_id="themes",
        name="x",
    )
    assert r.status_code == 404
    assert "term not found" in r.json()["detail"]


def test_create_409_on_duplicate_term_id_name(app_with_test_db, test_conn):
    """Unicité ``(term_id, name)`` : 2e POST identique → 409."""
    _insert_term(test_conn, term_id="lion")
    test_conn.session.commit()

    client = _client(app_with_test_db)
    r1 = _create_subject(client, term_id="lion", name="duplicate-name")
    assert r1.status_code == 201

    r2 = _create_subject(client, term_id="lion", name="duplicate-name")
    assert r2.status_code == 409
    assert "already exists" in r2.json()["detail"]


def test_create_409_on_explicit_id_clash(app_with_test_db, test_conn):
    """Si l'``id`` explicite est déjà pris → 409."""
    _insert_term(test_conn, term_id="lion")
    test_conn.session.commit()

    client = _client(app_with_test_db)
    r1 = _create_subject(client, id="subj_clash", term_id="lion", name="A")
    assert r1.status_code == 201

    r2 = _create_subject(client, id="subj_clash", term_id="lion", name="B")
    assert r2.status_code == 409
    assert "id already exists" in r2.json()["detail"]


def test_create_validation_name_empty_422(app_with_test_db, test_conn):
    """``name`` vide → 422 (Pydantic)."""
    _insert_term(test_conn, term_id="lion")
    test_conn.session.commit()

    r = _create_subject(_client(app_with_test_db), term_id="lion", name="   ")
    assert r.status_code == 422


def test_create_validation_status_unknown_422(app_with_test_db, test_conn):
    """``status`` hors whitelist → 422."""
    _insert_term(test_conn, term_id="lion")
    test_conn.session.commit()

    r = _create_subject(
        _client(app_with_test_db),
        term_id="lion",
        name="x",
        status="not-a-real-status",
    )
    assert r.status_code == 422


def test_create_validation_note_out_of_range_422(app_with_test_db, test_conn):
    """``note`` ∉ [0, 6] → 422 (côté Pydantic, avant DB)."""
    _insert_term(test_conn, term_id="lion")
    test_conn.session.commit()

    client = _client(app_with_test_db)
    for bad in (-1, 7, 100):
        r = _create_subject(client, term_id="lion", name=f"n_{bad}", note=bad)
        assert r.status_code == 422, f"note={bad} should be rejected"


def test_create_validation_unknown_tag_422(app_with_test_db, test_conn):
    """``tags`` hors whitelist → 422."""
    _insert_term(test_conn, term_id="lion")
    test_conn.session.commit()

    r = _create_subject(
        _client(app_with_test_db),
        term_id="lion",
        name="bad-tag",
        tags=["creatif", "totally_fake_tag"],
    )
    assert r.status_code == 422


def test_create_all_whitelisted_tags_accepted(app_with_test_db, test_conn):
    """Tous les tags whitelisted ALLOWED_TAGS doivent être acceptés."""
    from api.routes.subjects import ALLOWED_TAGS

    _insert_term(test_conn, term_id="lion")
    test_conn.session.commit()

    r = _create_subject(
        _client(app_with_test_db),
        term_id="lion",
        name="all-tags",
        tags=sorted(ALLOWED_TAGS),
    )
    assert r.status_code == 201, r.text
    assert sorted(r.json()["tags"]) == sorted(ALLOWED_TAGS)


def test_whitelist_constants_match_brief():
    """Les whitelists doivent matcher exactement le brief 2026-05-10.

    Test miroir : si quelqu'un ajoute/retire un tag ou un status sans
    revue, ce test casse et force une mise à jour cohérente du brief +
    de la migration 0007 (CHECK contraint Postgres).
    """
    from api.routes.subjects import ALLOWED_STATUSES, ALLOWED_TAGS

    assert ALLOWED_TAGS == frozenset({
        "ambigu", "simpliste", "incomprehensible", "creatif",
        "parfait", "complique", "bug", "blacklist",
    })
    assert ALLOWED_STATUSES == frozenset({
        "draft", "annotated", "validated", "enriched",
        "prompted", "generated", "qc_done", "published", "rejected",
    })


# ── PUT /api/subjects/{id} ───────────────────────────────────────────────────


def test_update_404_on_unknown_id(app_with_test_db):
    r = _client(app_with_test_db).put("/api/subjects/ghost", json={"status": "validated"})
    assert r.status_code == 404


def test_update_partial_fields_only(app_with_test_db, test_conn):
    """Champs absents du payload → inchangés."""
    _insert_term(test_conn, term_id="lion")
    test_conn.session.commit()

    client = _client(app_with_test_db)
    r = _create_subject(
        client, term_id="lion", name="orig", note=2, tags=["creatif"], brief="orig brief",
    )
    assert r.status_code == 201
    sid = r.json()["id"]

    # Update uniquement le status — les autres champs doivent rester.
    r2 = client.put(f"/api/subjects/{sid}", json={"status": "validated"})
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["status"] == "validated"
    assert body["name"] == "orig"
    assert body["note"] == 2
    assert body["tags"] == ["creatif"]
    assert body["brief"] == "orig brief"


def test_update_409_on_rename_collision(app_with_test_db, test_conn):
    """Rename vers un nom déjà pris pour le même term → 409."""
    _insert_term(test_conn, term_id="lion")
    test_conn.session.commit()

    client = _client(app_with_test_db)
    r1 = _create_subject(client, term_id="lion", name="A")
    assert r1.status_code == 201
    sid_a = r1.json()["id"]
    r2 = _create_subject(client, term_id="lion", name="B")
    assert r2.status_code == 201

    # On tente de renommer A → B (déjà pris).
    r3 = client.put(f"/api/subjects/{sid_a}", json={"name": "B"})
    assert r3.status_code == 409
    assert "already exists" in r3.json()["detail"]


def test_update_validation_unknown_tag_422(app_with_test_db, test_conn):
    """Validation tags whitelist côté update aussi."""
    _insert_term(test_conn, term_id="lion")
    test_conn.session.commit()

    client = _client(app_with_test_db)
    r = _create_subject(client, term_id="lion", name="x")
    sid = r.json()["id"]

    r2 = client.put(f"/api/subjects/{sid}", json={"tags": ["nope"]})
    assert r2.status_code == 422


def test_update_can_reset_note_to_null(app_with_test_db, test_conn):
    """``note: null`` doit remettre la note à NULL (sentinel reset)."""
    _insert_term(test_conn, term_id="lion")
    test_conn.session.commit()

    client = _client(app_with_test_db)
    r = _create_subject(client, term_id="lion", name="x", note=5)
    sid = r.json()["id"]

    r2 = client.put(f"/api/subjects/{sid}", json={"note": None})
    assert r2.status_code == 200
    assert r2.json()["note"] is None


# ── DELETE /api/subjects/{id} ────────────────────────────────────────────────


def test_delete_404_on_unknown_id(app_with_test_db):
    r = _client(app_with_test_db).delete("/api/subjects/does-not-exist")
    assert r.status_code == 404


def test_delete_200_then_get_404(app_with_test_db, test_conn):
    """Suppression OK : 200 puis GET 404."""
    _insert_term(test_conn, term_id="lion")
    test_conn.session.commit()

    client = _client(app_with_test_db)
    r = _create_subject(client, term_id="lion", name="to-delete")
    sid = r.json()["id"]

    r2 = client.delete(f"/api/subjects/{sid}")
    assert r2.status_code == 200
    assert r2.json() == {"deleted": True, "id": sid}

    r3 = client.get(f"/api/subjects/{sid}")
    assert r3.status_code == 404


# ── Cohérence relation Term.subjects ─────────────────────────────────────────


def test_term_subjects_relationship_navigates(app_with_test_db, test_conn):
    """La relation SQLAlchemy ``Term.subjects`` est navigable depuis un Term.

    Test de plomberie ORM (pas un endpoint) — assure que le ``relationship``
    est bien câblé et que les FK composites côté SQLite trouvent les bons
    subjects (cf. brief : back_populates + cascade delete-orphan).
    """
    from api.models import Subject, Term

    _insert_term(test_conn, term_id="lion")
    test_conn.session.commit()

    client = _client(app_with_test_db)
    assert _create_subject(client, term_id="lion", name="A").status_code == 201
    assert _create_subject(client, term_id="lion", name="B").status_code == 201

    term = (
        test_conn.session.query(Term)
        .filter_by(id="lion", vocabulary_id="themes")
        .one()
    )
    subject_names = {s.name for s in term.subjects}
    assert subject_names == {"A", "B"}
    assert all(isinstance(s, Subject) for s in term.subjects)
