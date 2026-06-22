"""Tests des endpoints HITL (Phase 2, incrément 1) via TestClient — Postgres.

Couvre la surface HTTP du workflow de supervision :
  - POST /generate (mock) → review_image + plaque ready ;
  - POST /review/image {approve} → review_text ;
  - POST /review/text {approve, edits} → approved (staging patché) ;
  - POST /commit → .md committé (bot, ADD-ONLY), staging purgé ;
  - GET  /validation-queue → buckets review_image/review_text/approved ;
  - refus HTTP : commit hors approved (409), transitions illégales (409),
    décision inconnue (400), work_item inconnu (404).

``conn`` (DDL/seed) et ``client`` (HTTP) partagent la Postgres éphémère.
Aucun réseau (ComfyUI/LLM mockés). Repo contenu = clone jetable via CONTENT_REPO_PATH.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from services.git_indexer import DEFAULT_REPO

REPO = DEFAULT_REPO


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(root), capture_output=True, text=True, encoding="utf-8"
    )


@pytest.fixture
def content_clone(tmp_path) -> Path:
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


def _insert_work_item(conn, wid: str, slug: str) -> None:
    conn.execute(
        "INSERT INTO work_item (id, repo, locale, slug, state, staging_state, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [wid, REPO, "fr", slug, "construction", "none", "now", "now"],
    )
    conn.session.commit()


def test_full_http_flow(client, conn, content_clone, monkeypatch):
    monkeypatch.setenv("CONTENT_REPO_PATH", str(content_clone))
    _insert_work_item(conn, "wh1", "tortue-de-mer")

    # 1. generate (mock).
    r = client.post("/api/cockpit/work-items/wh1/generate", json={})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["staging_state"] == "review_image"
    assert b["plate_state"] == "ready"
    assert b["preview_url"].startswith("data:image/svg+xml")
    assert b["mocked"] is True

    # 2. validation-queue : 1 candidat en review_image.
    r = client.get("/api/cockpit/validation-queue")
    assert r.status_code == 200, r.text
    q = r.json()
    assert q["count"] == 1
    assert len(q["buckets"]["review_image"]) == 1
    item = q["buckets"]["review_image"][0]
    assert item["plate"]["image_state"] == "ready"
    assert item["frontmatter"]["slug"] == "tortue-de-mer"

    # 3. review image approve → review_text.
    r = client.post("/api/cockpit/work-items/wh1/review/image", json={"decision": "approve"})
    assert r.status_code == 200, r.text
    assert r.json()["to_state"] == "review_text"

    # 4. review text approve + edits → approved.
    r = client.post(
        "/api/cockpit/work-items/wh1/review/text",
        json={"decision": "approve",
              "edits": {"frontmatter": {"title": "Titre revu HTTP"}}},
    )
    assert r.status_code == 200, r.text
    rt = r.json()
    assert rt["to_state"] == "approved"
    assert rt["edited"] is True

    # validation-queue : maintenant dans le bucket 'approved'.
    q = client.get("/api/cockpit/validation-queue").json()
    assert len(q["buckets"]["approved"]) == 1
    assert q["buckets"]["approved"][0]["frontmatter"]["title"] == "Titre revu HTTP"

    # 5. commit → .md écrit, committed, staging purgé.
    r = client.post("/api/cockpit/work-items/wh1/commit",
                    json={"launch_set": "cahier-des-mers"})
    assert r.status_code == 200, r.text
    cb = r.json()
    assert cb["committed"] is True
    md_path = content_clone / "src" / "content" / "posts" / "fr" / "tortue-de-mer.md"
    assert md_path.exists()
    assert "Titre revu HTTP" in md_path.read_text(encoding="utf-8")
    author = _git(content_clone, "log", "-1", "--format=%an <%ae>").stdout.strip()
    assert author == "artiste-pipeline <bot@artiste-coloriage.local>"

    # queue vide après commit (staging purgé → plus en revue).
    q = client.get("/api/cockpit/validation-queue").json()
    assert q["count"] == 0


def test_http_commit_refused_before_approval(client, conn, content_clone, monkeypatch):
    monkeypatch.setenv("CONTENT_REPO_PATH", str(content_clone))
    _insert_work_item(conn, "wh2", "crabe")
    client.post("/api/cockpit/work-items/wh2/generate", json={})  # review_image
    # commit sans approbation → 409 (gate HITL).
    r = client.post("/api/cockpit/work-items/wh2/commit", json={})
    assert r.status_code == 409, r.text
    assert "approved" in r.json()["detail"]


def test_http_illegal_transitions(client, conn):
    _insert_work_item(conn, "wh3", "meduse")
    # approve image sans generate → 409.
    r = client.post("/api/cockpit/work-items/wh3/review/image", json={"decision": "approve"})
    assert r.status_code == 409, r.text

    client.post("/api/cockpit/work-items/wh3/generate", json={})  # review_image
    # approve texte alors qu'on est en review_image → 409.
    r = client.post("/api/cockpit/work-items/wh3/review/text", json={"decision": "approve"})
    assert r.status_code == 409, r.text

    # décision inconnue → 400.
    r = client.post("/api/cockpit/work-items/wh3/review/image", json={"decision": "huh"})
    assert r.status_code == 400, r.text


def test_http_generate_unknown_work_item(client):
    r = client.post("/api/cockpit/work-items/nope/generate", json={})
    assert r.status_code == 404, r.text


def test_http_review_image_reject_then_regen(client, conn):
    _insert_work_item(conn, "wh4", "pieuvre")
    client.post("/api/cockpit/work-items/wh4/generate", json={})
    r = client.post("/api/cockpit/work-items/wh4/review/image",
                    json={"decision": "reject"})
    assert r.json()["to_state"] == "generating"
    # re-generate depuis generating.
    r = client.post("/api/cockpit/work-items/wh4/generate", json={})
    assert r.status_code == 200, r.text
    assert r.json()["staging_state"] == "review_image"
