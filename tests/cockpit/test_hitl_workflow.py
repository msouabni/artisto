"""Tests du workflow HITL (Phase 2, incrément 1) sur Postgres éphémère.

Couvre :
  - machine d'états gardée : transitions légales / illégales (pures) ;
  - génération MOCKÉE : generate → plaque ready + staging brouillon → review_image ;
  - gate IMAGE : approve → review_text ; reject → generating ; drop → none ;
  - gate TEXTE : edits patchent le staging ; approve → approved ; reject → review_image ;
  - approbation → commit (réutilise cockpit_git_publish, ADD-ONLY, identité bot) ;
  - refus du commit hors 'approved' (seul l'approuvé entre dans git) ;
  - refus des transitions illégales (approve image sans generate, etc.) ;
  - flux complet generate→review_image→review_text→approved→commit (.md + committed).

Aucun SQLite. Aucun réseau (ComfyUI / LLM mockés). Repo contenu = clone jetable.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from services.cockpit_git_publish import CockpitPublishError, commit_work_item
from services.generation_mock import generate
from services.git_indexer import DEFAULT_REPO, split_frontmatter
from services.hitl import (
    HitlTransitionError,
    assert_transition,
    can_transition,
    get_plate,
    get_staging_state,
)
from services.hitl_review import ReviewError, review_image, review_text

REPO = DEFAULT_REPO


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(root), capture_output=True, text=True, encoding="utf-8"
    )


@pytest.fixture
def content_clone(tmp_path) -> Path:
    """Clone git jetable du repo contenu (vide, structure src/content/posts/fr)."""
    root = tmp_path / "content-clone"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "seed")
    _git(root, "config", "user.email", "seed@local")
    (root / "src" / "content" / "posts" / "fr").mkdir(parents=True)
    (root / "README.md").write_text("seed\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-q", "-m", "seed")
    return root


def _insert_work_item(conn, wid: str, slug: str, *, staging_state="none",
                      opportunity_id=None) -> None:
    conn.execute(
        "INSERT INTO work_item (id, repo, locale, slug, state, opportunity_id, "
        "staging_state, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [wid, REPO, "fr", slug, "construction", opportunity_id, staging_state,
         "now", "now"],
    )
    conn.session.commit()


def _insert_opportunity(conn, oid: str, slug: str, keyword: str, volume: int) -> None:
    conn.execute(
        "INSERT INTO opportunity (id, keyword, sujet, slug, volume, score, cluster, "
        "source, imported_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [oid, keyword, slug, slug, volume, 88.0, "cahier_des_mers", "test.csv", "now"],
    )
    conn.session.commit()


# ── Machine d'états (fonctions pures gardées) ──────────────────────────────────

def test_legal_transitions_pure():
    assert can_transition("none", "generating")
    assert can_transition("generating", "review_image")
    assert can_transition("review_image", "review_text")
    assert can_transition("review_image", "generating")   # reject → regen
    assert can_transition("review_text", "approved")
    assert can_transition("review_text", "review_image")  # reject
    assert can_transition("approved", "none")             # commit purge


def test_illegal_transitions_pure():
    assert not can_transition("none", "review_image")     # pas de saut
    assert not can_transition("none", "approved")
    assert not can_transition("review_image", "approved") # texte non revu
    assert not can_transition("approved", "review_image")
    with pytest.raises(HitlTransitionError):
        assert_transition("none", "approved")
    with pytest.raises(HitlTransitionError):
        assert_transition("review_image", "approved")


# ── Génération mockée ───────────────────────────────────────────────────────────

def test_generate_mock_produces_plate_and_staging(conn):
    _insert_opportunity(conn, "opp_b", "baleine", "coloriage baleine", 1600)
    _insert_work_item(conn, "wi_b", "baleine", opportunity_id="opp_b")

    res = generate(conn, "wi_b")
    conn.session.commit()

    assert res.mocked is True
    assert res.staging_state == "review_image"
    assert res.plate_state == "ready"
    assert res.preview_url.startswith("data:image/svg+xml;base64,")
    # Métadonnées brouillon dérivées du slug.
    assert "baleine" in res.frontmatter["title"].lower()
    assert res.frontmatter["searchVolume"] == 1600  # dérivé de l'opportunité
    assert res.body

    # Persisté : staging_state + plaque.
    assert get_staging_state(conn, "wi_b") == "review_image"
    plate = get_plate(conn, "wi_b")
    assert plate["image_state"] == "ready"
    assert plate["preview_url"].startswith("data:image/svg+xml;base64,")


def test_generate_illegal_from_review_text_raises(conn):
    _insert_work_item(conn, "wi_x", "crabe", staging_state="review_text")
    with pytest.raises(HitlTransitionError):
        generate(conn, "wi_x")


def test_generate_unknown_work_item_raises(conn):
    from services.generation_mock import GenerationError
    with pytest.raises(GenerationError, match="introuvable"):
        generate(conn, "nope")


# ── Gate IMAGE ──────────────────────────────────────────────────────────────────

def test_review_image_approve(conn):
    _insert_work_item(conn, "wi1", "pieuvre")
    generate(conn, "wi1")
    conn.session.commit()

    res = review_image(conn, "wi1", "approve")
    conn.session.commit()
    assert res.to_state == "review_text"
    assert get_staging_state(conn, "wi1") == "review_text"


def test_review_image_reject_regenerates(conn):
    _insert_work_item(conn, "wi2", "meduse")
    generate(conn, "wi2")
    conn.session.commit()

    res = review_image(conn, "wi2", "reject")
    conn.session.commit()
    assert res.to_state == "generating"
    assert get_staging_state(conn, "wi2") == "generating"
    assert get_plate(conn, "wi2")["image_state"] == "pending"

    # On peut re-générer depuis generating (re-entre dans le flux).
    res2 = generate(conn, "wi2")
    conn.session.commit()
    assert res2.staging_state == "review_image"


def test_review_image_drop(conn):
    _insert_work_item(conn, "wi3", "hippocampe")
    generate(conn, "wi3")
    conn.session.commit()
    res = review_image(conn, "wi3", "reject", drop=True)
    conn.session.commit()
    assert res.to_state == "none"
    assert get_staging_state(conn, "wi3") == "none"


def test_review_image_illegal_without_generate(conn):
    _insert_work_item(conn, "wi4", "tortue")  # staging none
    with pytest.raises(HitlTransitionError):
        review_image(conn, "wi4", "approve")


def test_review_image_bad_decision(conn):
    _insert_work_item(conn, "wi5", "crabe")
    generate(conn, "wi5")
    conn.session.commit()
    with pytest.raises(ReviewError):
        review_image(conn, "wi5", "maybe")


# ── Gate TEXTE (+ edits) ────────────────────────────────────────────────────────

def test_review_text_approve(conn):
    _insert_work_item(conn, "wt1", "poisson-rouge")
    generate(conn, "wt1")
    review_image(conn, "wt1", "approve")
    conn.session.commit()

    res = review_text(conn, "wt1", "approve")
    conn.session.commit()
    assert res.to_state == "approved"
    assert get_staging_state(conn, "wt1") == "approved"


def test_review_text_edits_patch_staging(conn):
    import json
    _insert_work_item(conn, "wt2", "baleine-bleue")
    generate(conn, "wt2")
    review_image(conn, "wt2", "approve")
    conn.session.commit()

    res = review_text(
        conn, "wt2", "approve",
        edits={"frontmatter": {"title": "Titre révisé baleine bleue"},
               "body": "Corps réécrit par l'humain en revue."},
    )
    conn.session.commit()
    assert res.edited is True
    assert res.to_state == "approved"

    row = conn.execute(
        "SELECT staging_frontmatter, staging_body FROM work_item WHERE id = ?",
        ["wt2"],
    ).fetchall()[0]
    fm = row[0] if isinstance(row[0], dict) else json.loads(row[0])
    assert fm["title"] == "Titre révisé baleine bleue"
    assert row[1] == "Corps réécrit par l'humain en revue."


def test_review_text_reject_back_to_image(conn):
    _insert_work_item(conn, "wt3", "poisson-facile")
    generate(conn, "wt3")
    review_image(conn, "wt3", "approve")
    conn.session.commit()
    res = review_text(conn, "wt3", "reject")
    conn.session.commit()
    assert res.to_state == "review_image"
    assert get_staging_state(conn, "wt3") == "review_image"


def test_review_text_illegal_from_review_image(conn):
    _insert_work_item(conn, "wt4", "poisson-rigolo")
    generate(conn, "wt4")  # review_image
    conn.session.commit()
    with pytest.raises(HitlTransitionError):
        review_text(conn, "wt4", "approve")


# ── Approbation → commit (réutilise cockpit_git_publish) ────────────────────────

def test_commit_refused_unless_approved(conn, content_clone):
    """Un work_item en cours de revue HITL ne peut PAS committer (gate)."""
    _insert_work_item(conn, "wc1", "crabe")
    generate(conn, "wc1")  # review_image
    conn.session.commit()
    with pytest.raises(CockpitPublishError, match="approved"):
        commit_work_item(conn, "wc1", repo_root=content_clone, require_approved=None)


def test_full_flow_generate_to_commit(conn, content_clone):
    """Flux complet : generate → review_image → review_text → approved → commit."""
    _insert_opportunity(conn, "opp_t", "tortue-de-mer", "coloriage tortue", 900)
    _insert_work_item(conn, "wf1", "tortue-de-mer", opportunity_id="opp_t")

    # 1. génération mock → review_image
    g = generate(conn, "wf1")
    assert g.staging_state == "review_image"
    conn.session.commit()

    # 2. approve image → review_text
    review_image(conn, "wf1", "approve")
    conn.session.commit()
    assert get_staging_state(conn, "wf1") == "review_text"

    # 3. approve texte (avec édition légère) → approved
    review_text(conn, "wf1", "approve",
                edits={"frontmatter": {"title": "Coloriage tortue de mer · Alwan"}})
    conn.session.commit()
    assert get_staging_state(conn, "wf1") == "approved"

    # 4. commit (gate approved OK) → .md écrit, bot, committed, staging purgé
    res = commit_work_item(
        conn, "wf1", repo_root=content_clone,
        launch_set="cahier-des-mers", require_approved=None,
    )
    conn.session.commit()
    assert res.committed is True
    md_path = content_clone / "src" / "content" / "posts" / "fr" / "tortue-de-mer.md"
    assert md_path.exists()
    fm, _ = split_frontmatter(md_path.read_text(encoding="utf-8"))
    assert fm["title"] == "Coloriage tortue de mer · Alwan"
    assert fm["launchSet"] == "cahier-des-mers"

    # Commit = identité bot.
    author = _git(content_clone, "log", "-1", "--format=%an <%ae>").stdout.strip()
    assert author == f"{res.bot_name} <{res.bot_email}>"

    # staging purgé (buffer consommé → none ; le work_item avance).
    assert get_staging_state(conn, "wf1") == "none"
