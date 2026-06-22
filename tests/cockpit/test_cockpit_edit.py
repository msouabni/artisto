"""Tests édition légère cockpit → git (UPDATE gardé) sur Postgres éphémère.

Couvre (Phase 2, incrément 2) :
  - ``edit_load`` lit le ``.md`` COURANT de git → remplit le buffer staging +
    pose ``last_synced_hash`` = base content_hash (git autoritaire) ;
  - ``edit_patch`` patche le buffer (frontmatter merge / corps remplacé) ;
  - commit UPDATE **hash match → succès** (``.md`` mis à jour, ``last_synced_hash``
    réaligné, drift 0) ;
  - commit UPDATE **hash mismatch (git changé hors cockpit) → CockpitDriftError**,
    AUCUN écrasement du ``.md`` ;
  - la création (nouveau slug) reste **ADD-ONLY** (mode='create') ;
  - endpoints edit-load / PATCH edit / commit mode=update (200 / 409 + drift).

Aucun SQLite. Le repo contenu est un **clone git jetable** créé dans tmp_path.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from services.cockpit_edit import CockpitEditError, edit_load, edit_patch
from services.cockpit_git_publish import (
    CockpitDriftError,
    CockpitPublishError,
    commit_work_item,
)
from services.git_indexer import DEFAULT_REPO, parse_doc, split_frontmatter
from services.git_states import compute_drift

REPO = DEFAULT_REPO


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(root), capture_output=True, text=True, encoding="utf-8"
    )


@pytest.fixture
def content_clone(tmp_path) -> Path:
    """Clone git jetable du repo contenu (structure src/content/posts/fr)."""
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


def _seed_published_page(root: Path, slug: str, title: str = "Coloriage baleine") -> str:
    """Écrit + commite un .md (page publiée). Retourne son content_hash git."""
    rel = f"src/content/posts/fr/{slug}.md"
    md = (
        "---\n"
        "locale: 'fr'\n"
        f"slug: '{slug}'\n"
        f"title: '{title}'\n"
        "description: 'Une jolie baleine a colorier'\n"
        "categoryId: 'cahier_des_mers'\n"
        "themeIds: []\n"
        "---\n\n"
        "## Corps original\n"
    )
    abs_path = root / rel
    abs_path.write_text(md, encoding="utf-8")
    _git(root, "add", rel)
    _git(root, "commit", "-q", "-m", f"seed {slug}")
    return parse_doc(abs_path, "fr", rel).content_hash


def _insert_work_item(conn, wid: str, slug: str, *, last_synced_hash=None) -> None:
    conn.execute(
        "INSERT INTO work_item (id, repo, locale, slug, state, staging_state, "
        "last_synced_hash, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [wid, REPO, "fr", slug, "valide", "none", last_synced_hash, "now", "now"],
    )
    conn.session.commit()


# ── edit_load ────────────────────────────────────────────────────────────────────

def test_edit_load_reads_from_git_and_sets_base_hash(conn, content_clone):
    base_hash = _seed_published_page(content_clone, "baleine")
    _insert_work_item(conn, "wi_b", "baleine")

    res = edit_load(conn, "wi_b", repo_root=content_clone)
    conn.session.commit()

    assert res.base_content_hash == base_hash
    assert res.frontmatter["title"] == "Coloriage baleine"
    assert "Corps original" in (res.body or "")

    # Buffer rempli + last_synced_hash posé (référence d'optimistic concurrency).
    row = conn.execute(
        "SELECT staging_state, last_synced_hash, staging_body FROM work_item WHERE id = ?",
        ["wi_b"],
    ).fetchall()[0]
    assert row[0] == "editing"
    assert row[1] == base_hash
    assert "Corps original" in row[2]


def test_edit_load_refuses_absent_page(conn, content_clone):
    _insert_work_item(conn, "wi_x", "inexistant")
    with pytest.raises(CockpitEditError, match="absent de git"):
        edit_load(conn, "wi_x", repo_root=content_clone)


# ── edit_patch ─────────────────────────────────────────────────────────────────

def test_edit_patch_merges_frontmatter_and_replaces_body(conn, content_clone):
    _seed_published_page(content_clone, "crabe")
    _insert_work_item(conn, "wi_c", "crabe")
    edit_load(conn, "wi_c", repo_root=content_clone)
    conn.session.commit()

    res = edit_patch(
        conn, "wi_c",
        frontmatter={"title": "Coloriage crabe (revu)", "featured": True},
        body="## Nouveau corps\n",
    )
    conn.session.commit()

    assert res.edited is True
    assert res.frontmatter["title"] == "Coloriage crabe (revu)"
    assert res.frontmatter["featured"] is True
    assert res.frontmatter["slug"] == "crabe"  # clés d'origine préservées
    assert res.body == "## Nouveau corps\n"


def test_edit_patch_requires_loaded_buffer(conn, content_clone):
    _seed_published_page(content_clone, "pieuvre")
    _insert_work_item(conn, "wi_p", "pieuvre")  # staging_state='none', pas chargé
    with pytest.raises(CockpitEditError, match="edit-load"):
        edit_patch(conn, "wi_p", frontmatter={"title": "x"})


# ── commit UPDATE : hash match → succès ─────────────────────────────────────────

def test_commit_update_hash_match_succeeds(conn, content_clone):
    _seed_published_page(content_clone, "meduse")
    _insert_work_item(conn, "wi_m", "meduse")

    edit_load(conn, "wi_m", repo_root=content_clone)
    conn.session.commit()
    edit_patch(conn, "wi_m", frontmatter={"title": "Coloriage meduse (edite)"})
    conn.session.commit()

    result = commit_work_item(conn, "wi_m", repo_root=content_clone, mode="update")
    conn.session.commit()

    assert result.committed is True
    md_path = content_clone / "src" / "content" / "posts" / "fr" / "meduse.md"
    parsed_fm, _ = split_frontmatter(md_path.read_text(encoding="utf-8"))
    assert parsed_fm["title"] == "Coloriage meduse (edite)"

    # last_synced_hash réaligné == git_index.content_hash → drift 0.
    row = conn.execute(
        "SELECT last_synced_hash FROM work_item WHERE id = ?", ["wi_m"]
    ).fetchall()[0]
    assert row[0] == result.content_hash
    gi = conn.execute(
        "SELECT content_hash, exists FROM git_index WHERE repo=? AND locale=? AND slug=?",
        [REPO, "fr", "meduse"],
    ).fetchall()[0]
    assert gi[0] == result.content_hash
    drift, reason = compute_drift({"exists": True, "content_hash": gi[0]}, row[0])
    assert drift is False and reason is None


def test_commit_update_is_bot_author(conn, content_clone):
    _seed_published_page(content_clone, "tortue")
    _insert_work_item(conn, "wi_t", "tortue")
    edit_load(conn, "wi_t", repo_root=content_clone)
    conn.session.commit()
    edit_patch(conn, "wi_t", body="## Edited\n")
    conn.session.commit()
    result = commit_work_item(conn, "wi_t", repo_root=content_clone, mode="update")
    conn.session.commit()
    author = _git(content_clone, "log", "-1", "--format=%an <%ae>").stdout.strip()
    assert author == f"{result.bot_name} <{result.bot_email}>"


# ── commit UPDATE : hash mismatch (git changé hors cockpit) → 409, pas d'écrasement ─

def test_commit_update_hash_mismatch_refuses_no_clobber(conn, content_clone):
    _seed_published_page(content_clone, "hippocampe", title="Original")
    _insert_work_item(conn, "wi_h", "hippocampe")

    edit_load(conn, "wi_h", repo_root=content_clone)
    conn.session.commit()
    edit_patch(conn, "wi_h", frontmatter={"title": "Edit cockpit"})
    conn.session.commit()

    # Édition EXTERNE (hors cockpit) : git change après le edit-load.
    rel = "src/content/posts/fr/hippocampe.md"
    abs_path = content_clone / rel
    external = abs_path.read_text(encoding="utf-8").replace(
        "Original", "Edite hors cockpit"
    )
    abs_path.write_text(external, encoding="utf-8")
    _git(content_clone, "add", rel)
    _git(content_clone, "commit", "-q", "-m", "edition externe")

    before = abs_path.read_text(encoding="utf-8")
    with pytest.raises(CockpitDriftError) as ei:
        commit_work_item(conn, "wi_h", repo_root=content_clone, mode="update")
    # Pas d'écrasement : le .md garde l'édition externe.
    assert abs_path.read_text(encoding="utf-8") == before
    assert "Edite hors cockpit" in abs_path.read_text(encoding="utf-8")
    assert "Edit cockpit" not in abs_path.read_text(encoding="utf-8")
    # Détail drift exploitable côté API.
    detail = ei.value.drift_detail()
    assert detail["drift"] is True
    assert detail["drift_reason"] == "content_hash_changed"
    assert detail["expected_hash"] != detail["current_hash"]


def test_commit_update_absent_page_refuses(conn, content_clone):
    _insert_work_item(conn, "wi_n", "neant", last_synced_hash="deadbeef")
    with pytest.raises(CockpitPublishError, match="absent de git"):
        commit_work_item(conn, "wi_n", repo_root=content_clone, mode="update")


def test_commit_update_without_reference_refuses(conn, content_clone):
    _seed_published_page(content_clone, "etoile")
    _insert_work_item(conn, "wi_e", "etoile")  # last_synced_hash NULL, pas de edit-load
    # Buffer minimal pour passer la garde "staging vide".
    conn.execute(
        "UPDATE work_item SET staging_frontmatter = ?, staging_state = ? WHERE id = ?",
        [json.dumps({"locale": "fr", "slug": "etoile", "title": "x"}), "editing", "wi_e"],
    )
    conn.session.commit()
    with pytest.raises(CockpitPublishError, match="last_synced_hash absent"):
        commit_work_item(conn, "wi_e", repo_root=content_clone, mode="update")


# ── Création reste ADD-ONLY (mode=create) ───────────────────────────────────────

def test_create_mode_stays_add_only(conn, content_clone):
    _seed_published_page(content_clone, "existant")
    # work_item avec staging prêt pour une CRÉATION sur un slug déjà publié.
    conn.execute(
        "INSERT INTO work_item (id, repo, locale, slug, state, staging_frontmatter, "
        "staging_body, staging_state, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ["wi_dup", REPO, "fr", "existant", "valide",
         json.dumps({"locale": "fr", "slug": "existant", "title": "Doublon",
                     "themeIds": []}),
         "## x\n", "pending_commit", "now", "now"],
    )
    conn.session.commit()
    # mode=create (défaut) → ADD-ONLY refuse de réécrire la page publiée.
    with pytest.raises(CockpitPublishError, match="ADD-ONLY"):
        commit_work_item(conn, "wi_dup", repo_root=content_clone)


# ── Endpoints ────────────────────────────────────────────────────────────────────

def test_endpoints_edit_load_patch_commit_update(client, conn, content_clone, monkeypatch):
    monkeypatch.setenv("CONTENT_REPO_PATH", str(content_clone))
    _seed_published_page(content_clone, "poisson", title="Poisson original")
    _insert_work_item(conn, "wi_api", "poisson")

    # edit-load
    r = client.post("/api/cockpit/work-items/wi_api/edit-load")
    assert r.status_code == 200, r.text
    assert r.json()["frontmatter"]["title"] == "Poisson original"
    base_hash = r.json()["base_content_hash"]

    # PATCH edit
    r = client.patch(
        "/api/cockpit/work-items/wi_api/edit",
        json={"frontmatter": {"title": "Poisson edite"}, "body": "## Corps edite\n"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["frontmatter"]["title"] == "Poisson edite"

    # commit mode=update (hash ok) → 200
    r = client.post(
        "/api/cockpit/work-items/wi_api/commit", json={"mode": "update"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["committed"] is True
    md_path = content_clone / "src" / "content" / "posts" / "fr" / "poisson.md"
    parsed_fm, _ = split_frontmatter(md_path.read_text(encoding="utf-8"))
    assert parsed_fm["title"] == "Poisson edite"
    assert base_hash != r.json()["content_hash"]


def test_endpoint_commit_update_drift_409(client, conn, content_clone, monkeypatch):
    monkeypatch.setenv("CONTENT_REPO_PATH", str(content_clone))
    _seed_published_page(content_clone, "raie", title="Raie originale")
    _insert_work_item(conn, "wi_d", "raie")

    client.post("/api/cockpit/work-items/wi_d/edit-load")
    client.patch(
        "/api/cockpit/work-items/wi_d/edit", json={"frontmatter": {"title": "Cockpit"}}
    )

    # Édition externe.
    rel = "src/content/posts/fr/raie.md"
    abs_path = content_clone / rel
    abs_path.write_text(
        abs_path.read_text(encoding="utf-8").replace("Raie originale", "Hors cockpit"),
        encoding="utf-8",
    )
    _git(content_clone, "add", rel)
    _git(content_clone, "commit", "-q", "-m", "ext")

    r = client.post("/api/cockpit/work-items/wi_d/commit", json={"mode": "update"})
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["drift"] is True
    assert detail["drift_reason"] == "content_hash_changed"
    # Pas d'écrasement.
    assert "Hors cockpit" in abs_path.read_text(encoding="utf-8")
