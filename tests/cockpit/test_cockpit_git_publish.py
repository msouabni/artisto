"""Tests cockpit → git (commit = seule porte) sur Postgres éphémère.

Couvre :
  - commit d'un work_item → ``.md`` correct (frontmatter incl. ``launchSet``) ;
  - auteur du commit = identité bot ;
  - ``last_synced_hash`` posé == ``git_index.content_hash`` → drift 0 ;
  - idempotence / ADD-ONLY (refus de réécrire sans ``force``) ;
  - dry-run (montre le ``.md`` sans rien écrire) ;
  - end-to-end : 10 work_items marins commités dans un clone jetable, marqueur
    ``launchSet: animaux-marins``, drift global repassé à 0.

Aucun SQLite. Le repo contenu est un **clone git jetable** créé dans tmp_path.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from services.cockpit_git_publish import (
    CockpitPublishError,
    commit_work_item,
    serialize_post_md,
)
from services.git_indexer import DEFAULT_REPO, parse_doc, reindex, split_frontmatter
from services.git_states import compute_drift

REPO = DEFAULT_REPO
MOCK_POSTS_DIR = (
    Path(__file__).resolve().parents[2] / "data" / "mock-content" / "src" / "content" / "posts" / "fr"
)
MARINE_SLUGS = [
    "baleine", "poisson-simple", "tortue-de-mer", "hippocampe", "crabe",
    "poisson-rouge", "pieuvre", "baleine-bleue", "meduse", "poisson-rigolo",
]


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(root), capture_output=True, text=True, encoding="utf-8"
    )


@pytest.fixture
def content_clone(tmp_path) -> Path:
    """Clone git jetable du repo contenu (vide, structure src/content/posts)."""
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


def _staging_from_mock(slug: str) -> tuple[dict, str]:
    """Charge le frontmatter + corps d'un mock .md comme buffer de staging."""
    raw = (MOCK_POSTS_DIR / f"{slug}.md").read_text(encoding="utf-8")
    fm, body = split_frontmatter(raw)
    # Normalise les dates en str ISO (comme un JSONB le ferait côté staging).
    for k in ("publishDate", "datePublication", "dateModification"):
        if k in fm and hasattr(fm[k], "isoformat"):
            fm[k] = fm[k].isoformat()[:10]
    return fm, body


def _insert_staged_work_item(conn, wid: str, slug: str, fm: dict, body: str) -> None:
    import json

    conn.execute(
        "INSERT INTO work_item (id, repo, locale, slug, state, staging_frontmatter, "
        "staging_body, staging_state, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [wid, REPO, "fr", slug, "valide", json.dumps(fm), body, "pending_commit",
         "now", "now"],
    )
    conn.session.commit()


# ── Sérialisation ──────────────────────────────────────────────────────────────

def test_serialize_preserves_launch_set_and_extra_keys():
    fm = {
        "locale": "fr", "slug": "baleine", "title": "Coloriage baleine",
        "description": "desc", "categoryId": "animals_marine",
        "launchSet": "animaux-marins", "imageSvg": "https://x/y.svg",
        "plateId": "baleine-0001", "themeIds": [],
    }
    md = serialize_post_md(fm, "## corps\n")
    parsed_fm, body = split_frontmatter(md)
    assert parsed_fm["launchSet"] == "animaux-marins"
    assert parsed_fm["imageSvg"] == "https://x/y.svg"
    assert parsed_fm["plateId"] == "baleine-0001"
    assert parsed_fm["themeIds"] == []
    assert "corps" in body


# ── Commit unitaire ─────────────────────────────────────────────────────────────

def test_commit_work_item_writes_md_with_launchset(conn, content_clone):
    fm, body = _staging_from_mock("baleine")
    _insert_staged_work_item(conn, "wi_baleine", "baleine", fm, body)

    result = commit_work_item(
        conn, "wi_baleine", repo_root=content_clone, launch_set="animaux-marins"
    )
    conn.session.commit()

    assert result.committed is True
    md_path = content_clone / "src" / "content" / "posts" / "fr" / "baleine.md"
    assert md_path.exists()
    parsed_fm, _ = split_frontmatter(md_path.read_text(encoding="utf-8"))
    assert parsed_fm["launchSet"] == "animaux-marins"
    assert parsed_fm["categoryId"] == "animals_marine"
    assert parsed_fm["slug"] == "baleine"


def test_commit_author_is_bot(conn, content_clone):
    fm, body = _staging_from_mock("crabe")
    _insert_staged_work_item(conn, "wi_crabe", "crabe", fm, body)
    result = commit_work_item(
        conn, "wi_crabe", repo_root=content_clone, launch_set="animaux-marins"
    )
    conn.session.commit()

    author = _git(content_clone, "log", "-1", "--format=%an <%ae>").stdout.strip()
    assert author == f"{result.bot_name} <{result.bot_email}>"
    assert result.bot_name == "artiste-pipeline"


def test_last_synced_hash_set_and_matches_git_index(conn, content_clone):
    fm, body = _staging_from_mock("pieuvre")
    _insert_staged_work_item(conn, "wi_pieuvre", "pieuvre", fm, body)
    result = commit_work_item(
        conn, "wi_pieuvre", repo_root=content_clone, launch_set="animaux-marins"
    )
    conn.session.commit()

    row = conn.execute(
        "SELECT last_synced_hash FROM work_item WHERE id = ?", ["wi_pieuvre"]
    ).fetchall()[0]
    assert row[0] == result.content_hash

    gi = conn.execute(
        "SELECT content_hash, exists FROM git_index WHERE repo = ? AND locale = ? AND slug = ?",
        [REPO, "fr", "pieuvre"],
    ).fetchall()[0]
    assert gi[0] == result.content_hash
    assert bool(gi[1]) is True

    # Drift résolu : last_synced_hash == git_index.content_hash.
    git_row = {"exists": True, "content_hash": gi[0]}
    drift, reason = compute_drift(git_row, row[0])
    assert drift is False
    assert reason is None


def test_add_only_refuses_existing_without_force(conn, content_clone):
    fm, body = _staging_from_mock("meduse")
    _insert_staged_work_item(conn, "wi_meduse", "meduse", fm, body)
    commit_work_item(conn, "wi_meduse", repo_root=content_clone, launch_set="animaux-marins")
    conn.session.commit()

    # 2e commit du même slug → ADD-ONLY refuse.
    with pytest.raises(CockpitPublishError, match="ADD-ONLY"):
        commit_work_item(conn, "wi_meduse", repo_root=content_clone)


def test_force_allows_rewrite(conn, content_clone):
    import json

    fm, body = _staging_from_mock("hippocampe")
    _insert_staged_work_item(conn, "wi_hippo", "hippocampe", fm, body)
    commit_work_item(conn, "wi_hippo", repo_root=content_clone, launch_set="animaux-marins")
    conn.session.commit()

    # Édite le staging (changement réel de contenu) puis force=True.
    fm2 = dict(fm)
    fm2["title"] = "Coloriage hippocampe modifie"
    conn.execute(
        "UPDATE work_item SET staging_frontmatter = ? WHERE id = ?",
        [json.dumps(fm2), "wi_hippo"],
    )
    conn.session.commit()
    result = commit_work_item(
        conn, "wi_hippo", repo_root=content_clone, launch_set="animaux-marins", force=True
    )
    conn.session.commit()
    assert result.committed is True
    md_path = content_clone / "src" / "content" / "posts" / "fr" / "hippocampe.md"
    parsed_fm, _ = split_frontmatter(md_path.read_text(encoding="utf-8"))
    assert parsed_fm["title"] == "Coloriage hippocampe modifie"


def test_dry_run_writes_nothing(conn, content_clone):
    fm, body = _staging_from_mock("poisson-rouge")
    _insert_staged_work_item(conn, "wi_pr", "poisson-rouge", fm, body)
    result = commit_work_item(
        conn, "wi_pr", repo_root=content_clone, launch_set="animaux-marins", dry_run=True
    )
    assert result.dry_run is True
    assert result.committed is False
    parsed_fm, _ = split_frontmatter(result.md)
    assert parsed_fm["launchSet"] == "animaux-marins"
    assert not (content_clone / "src" / "content" / "posts" / "fr" / "poisson-rouge.md").exists()
    # Aucun hash posé.
    row = conn.execute(
        "SELECT last_synced_hash FROM work_item WHERE id = ?", ["wi_pr"]
    ).fetchall()[0]
    assert row[0] is None


def test_missing_staging_raises(conn, content_clone):
    conn.execute(
        "INSERT INTO work_item (id, repo, locale, slug, state, staging_state, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ["wi_empty", REPO, "fr", "vide", "candidat", "none", "now", "now"],
    )
    conn.session.commit()
    with pytest.raises(CockpitPublishError, match="staging_frontmatter"):
        commit_work_item(conn, "wi_empty", repo_root=content_clone)


# ── End-to-end : 10 marins ──────────────────────────────────────────────────────

def test_e2e_ten_marine_commits_drift_zero(conn, content_clone):
    """Commit les 10 work_items marins → 10 .md, auteur bot, drift global 0."""
    for i, slug in enumerate(MARINE_SLUGS):
        fm, body = _staging_from_mock(slug)
        _insert_staged_work_item(conn, f"wi_{i}", slug, fm, body)

    for i, slug in enumerate(MARINE_SLUGS):
        res = commit_work_item(
            conn, f"wi_{i}", repo_root=content_clone, launch_set="animaux-marins"
        )
        assert res.committed is True
    conn.session.commit()

    # 10 .md créés.
    md_files = sorted((content_clone / "src" / "content" / "posts" / "fr").glob("*.md"))
    assert len(md_files) == 10
    for f in md_files:
        parsed_fm, _ = split_frontmatter(f.read_text(encoding="utf-8"))
        assert parsed_fm["launchSet"] == "animaux-marins"

    # Tous les commits sont du bot.
    authors = _git(content_clone, "log", "--format=%an <%ae>").stdout.strip().splitlines()
    bot_line = "artiste-pipeline <bot@artiste-coloriage.local>"
    assert authors.count(bot_line) == 10

    # Réindexe le clone complet → git_index reflète les 10.
    reindex(conn, repo=REPO, root=content_clone)
    conn.session.commit()

    # Drift global = 0 : chaque work_item a last_synced_hash == git_index.content_hash.
    rows = conn.execute(
        "SELECT slug, last_synced_hash FROM work_item WHERE repo = ?", [REPO]
    ).fetchall()
    gi_rows = conn.execute(
        "SELECT slug, content_hash, exists FROM git_index WHERE repo = ?", [REPO]
    ).fetchall()
    gi_by_slug = {r[0]: {"content_hash": r[1], "exists": bool(r[2])} for r in gi_rows}

    drift_count = 0
    for slug, lsh in rows:
        drift, _ = compute_drift(gi_by_slug.get(slug), lsh)
        if drift:
            drift_count += 1
    assert drift_count == 0
    assert len(rows) == 10


# ── Endpoint POST /api/cockpit/work-items/{id}/commit ───────────────────────────

def test_endpoint_dry_run_then_commit(client, conn, content_clone, monkeypatch):
    # Force le service à viser le clone jetable via CONTENT_REPO_PATH.
    # ``conn`` et ``client`` partagent la même Postgres éphémère (pg_engine).
    monkeypatch.setenv("CONTENT_REPO_PATH", str(content_clone))

    fm, body = _staging_from_mock("tortue-de-mer")
    _insert_staged_work_item(conn, "wi_ep", "tortue-de-mer", fm, body)

    # dry-run : montre le .md, n'écrit rien.
    resp = client.post(
        "/api/cockpit/work-items/wi_ep/commit",
        json={"launch_set": "animaux-marins", "dry_run": True},
    )
    assert resp.status_code == 200, resp.text
    body_json = resp.json()
    assert body_json["dry_run"] is True
    assert body_json["committed"] is False
    assert "launchSet" in body_json["md"]
    assert not (content_clone / "src" / "content" / "posts" / "fr" / "tortue-de-mer.md").exists()

    # commit réel.
    resp = client.post(
        "/api/cockpit/work-items/wi_ep/commit",
        json={"launch_set": "animaux-marins"},
    )
    assert resp.status_code == 200, resp.text
    body_json = resp.json()
    assert body_json["committed"] is True
    assert body_json["content_hash"]
    assert (content_clone / "src" / "content" / "posts" / "fr" / "tortue-de-mer.md").exists()

    # 2e commit réel → ADD-ONLY → 409.
    resp = client.post("/api/cockpit/work-items/wi_ep/commit", json={})
    assert resp.status_code == 409, resp.text

    # work_item inconnu → 404.
    resp = client.post("/api/cockpit/work-items/nope/commit", json={})
    assert resp.status_code == 404, resp.text
