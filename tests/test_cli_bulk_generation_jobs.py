from __future__ import annotations

import json
import sys
from pathlib import Path

from typer.testing import CliRunner

sys.path.insert(0, "src")

import cli as cli_mod

runner = CliRunner()


def test_read_image_id_file_json_export_object(tmp_path: Path) -> None:
    p = tmp_path / "export.json"
    p.write_text(
        json.dumps({"image_ids": ["a", "b"], "filters": {}, "count": 2}),
        encoding="utf-8",
    )
    assert cli_mod._read_image_id_file(p) == ["a", "b"]


def test_jobs_images_bulk_create_generation_dry_run(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []

    def no_http(*args: object, **kwargs: object) -> None:
        calls.append("http")
        raise AssertionError("no HTTP in dry-run")

    monkeypatch.setattr(cli_mod, "_http_json_or_exit", no_http)
    idf = tmp_path / "ids.txt"
    idf.write_text("x\ny\n", encoding="utf-8")
    res = runner.invoke(
        cli_mod.app,
        ["jobs", "images", "bulk-create-generation-jobs", str(idf), "--dry-run", "--chunk-size", "1"],
    )
    assert res.exit_code == 0
    assert not calls
    assert "dry-run" in res.output


def test_jobs_images_bulk_create_generation_posts_chunks(tmp_path: Path, monkeypatch) -> None:
    posts: list[dict] = []

    def fake_http(method: str, url: str, **kwargs: object) -> dict:
        if method == "POST" and "bulk-create-generation-jobs" in url:
            body = kwargs.get("json") or {}
            posts.append(body)
            ids = body.get("image_ids") or []
            return {
                "results": [{"image_id": i, "ok": True, "job_id": f"j_{i}"} for i in ids],
                "summary": {"total": len(ids), "success": len(ids), "failed": 0},
            }
        raise AssertionError((method, url))

    monkeypatch.setattr(cli_mod, "_http_json_or_exit", fake_http)
    idf = tmp_path / "ids.txt"
    idf.write_text("\n".join([f"id{i}" for i in range(30)]) + "\n", encoding="utf-8")
    res = runner.invoke(
        cli_mod.app,
        ["jobs", "images", "bulk-create-generation-jobs", str(idf), "--chunk-size", "25"],
    )
    assert res.exit_code == 0
    assert len(posts) == 2
    assert len(posts[0]["image_ids"]) == 25
    assert len(posts[1]["image_ids"]) == 5


def test_jobs_images_bulk_create_generation_resume_skips_done(tmp_path: Path, monkeypatch) -> None:
    posts: list[dict] = []

    def fake_http(method: str, url: str, **kwargs: object) -> dict:
        if method == "POST" and "bulk-create-generation-jobs" in url:
            body = kwargs.get("json") or {}
            posts.append(body)
            ids = body.get("image_ids") or []
            return {
                "results": [{"image_id": i, "ok": True, "job_id": "j"} for i in ids],
                "summary": {"total": len(ids), "success": len(ids), "failed": 0},
            }
        raise AssertionError((method, url))

    monkeypatch.setattr(cli_mod, "_http_json_or_exit", fake_http)
    idf = tmp_path / "ids.txt"
    idf.write_text("a\nb\nc\n", encoding="utf-8")
    ck = tmp_path / "ck.txt"
    ck.write_text("a\nb\n", encoding="utf-8")
    res = runner.invoke(
        cli_mod.app,
        [
            "jobs",
            "images",
            "bulk-create-generation-jobs",
            str(idf),
            "--resume",
            "--checkpoint",
            str(ck),
            "--chunk-size",
            "25",
        ],
    )
    assert res.exit_code == 0
    assert len(posts) == 1
    assert posts[0]["image_ids"] == ["c"]


def test_jobs_ai_bulk_image_prompt_create_posts_enqueue(tmp_path: Path, monkeypatch) -> None:
    posts: list[dict] = []
    gets: list[str] = []

    def fake_http(method: str, url: str, **kwargs: object) -> dict:
        if method == "GET" and "/api/images/" in url:
            gets.append(url)
            iid = url.rstrip("/").split("/")[-1]
            return {"id": iid, "title": f"T-{iid}", "prompt": ""}
        raise AssertionError((method, url))

    class _Resp:
        def __init__(self, ok: bool, body: dict) -> None:
            self.is_error = not ok
            self._body = body
            self.text = ""

        def json(self) -> dict:
            return self._body

    def fake_post(url: str, **kwargs: object) -> _Resp:
        posts.append(kwargs.get("json") or {})
        return _Resp(True, {"status": "enqueued", "id": f"job_{len(posts)}", "type": "image_prompt_create"})

    monkeypatch.setattr(cli_mod, "_http_json_or_exit", fake_http)
    monkeypatch.setattr(cli_mod.httpx, "post", fake_post)
    monkeypatch.setattr(cli_mod, "_ensure_job_type_enabled", lambda _t: None)

    idf = tmp_path / "ids.txt"
    idf.write_text("img1\nimg2\n", encoding="utf-8")
    res = runner.invoke(
        cli_mod.app,
        ["jobs", "ai", "bulk-image-prompt-create", str(idf), "--chunk-size", "10"],
    )
    assert res.exit_code == 0
    assert len(gets) == 2
    assert len(posts) == 2
    assert posts[0]["type"] == "image_prompt_create"
    assert posts[0]["config"]["image_id"] == "img1"


def test_jobs_ai_bulk_image_prompt_create_partial_error(tmp_path: Path, monkeypatch) -> None:
    posts: list[dict] = []

    class _Resp:
        def __init__(self, ok: bool, body: dict | None = None) -> None:
            self.is_error = not ok
            self._body = body or {}
            self.text = '{"detail":"nope"}'

        def json(self) -> dict:
            return self._body

    def fake_post(url: str, **kwargs: object) -> _Resp:
        posts.append(kwargs.get("json") or {})
        if len(posts) == 1:
            return _Resp(False)
        return _Resp(True, {"status": "enqueued", "id": "job_ok", "type": "image_prompt_create"})

    def no_get(*_a: object, **_k: object) -> dict:
        raise AssertionError("no GET")

    monkeypatch.setattr(cli_mod, "_http_json_or_exit", no_get)
    monkeypatch.setattr(cli_mod.httpx, "post", fake_post)
    monkeypatch.setattr(cli_mod, "_ensure_job_type_enabled", lambda _t: None)

    idf = tmp_path / "ids.txt"
    idf.write_text("a\nb\n", encoding="utf-8")
    res = runner.invoke(
        cli_mod.app,
        ["jobs", "ai", "bulk-image-prompt-create", str(idf), "--keywords", "k"],
    )
    assert res.exit_code == 0
    out = json.loads(res.output.strip().splitlines()[-1])
    assert out["success"] == 1
    assert out["failed"] == 1


def test_jobs_ai_bulk_image_prompt_create_dry_run_requires_keywords(tmp_path: Path) -> None:
    idf = tmp_path / "ids.txt"
    idf.write_text("a\n", encoding="utf-8")
    res = runner.invoke(
        cli_mod.app,
        ["jobs", "ai", "bulk-image-prompt-create", str(idf), "--dry-run"],
    )
    assert res.exit_code == 1


def test_jobs_images_bulk_create_generation_results_out(
    tmp_path: Path, monkeypatch
) -> None:
    def fake_http(method: str, url: str, **kwargs: object) -> dict:
        body = kwargs.get("json") or {}
        ids = body.get("image_ids") or []
        return {
            "results": [{"image_id": i, "ok": True, "job_id": "j"} for i in ids],
            "summary": {"total": len(ids), "success": len(ids), "failed": 0},
        }

    monkeypatch.setattr(cli_mod, "_http_json_or_exit", fake_http)
    idf = tmp_path / "ids.txt"
    idf.write_text("x\ny\n", encoding="utf-8")
    out_nd = tmp_path / "r.ndjson"
    res = runner.invoke(
        cli_mod.app,
        [
            "jobs",
            "images",
            "bulk-create-generation-jobs",
            str(idf),
            "--results-out",
            str(out_nd),
        ],
    )
    assert res.exit_code == 0
    lines = [ln for ln in out_nd.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["summary"]["success"] == 2
