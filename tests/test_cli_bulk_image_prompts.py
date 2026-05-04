from __future__ import annotations

import json
import sys
from pathlib import Path

from typer.testing import CliRunner

sys.path.insert(0, "src")

import cli as cli_mod

runner = CliRunner()


def test_read_image_id_file_txt_and_comments(tmp_path: Path) -> None:
    p = tmp_path / "ids.txt"
    p.write_text("# skip\n\n  img_a  \nimg_b\n", encoding="utf-8")
    assert cli_mod._read_image_id_file(p) == ["img_a", "img_b"]


def test_read_image_id_file_json_array(tmp_path: Path) -> None:
    p = tmp_path / "ids.json"
    p.write_text(json.dumps([" x ", "y"]), encoding="utf-8")
    assert cli_mod._read_image_id_file(p) == ["x", "y"]


def test_fetch_all_image_ids_paginates(monkeypatch) -> None:
    all_rows = [{"id": "a"}, {"id": "b"}, {"id": "c"}]

    def fake_list(**kwargs: object) -> list[dict]:
        offset = int(kwargs["offset"])
        limit = int(kwargs["limit"])
        return all_rows[offset : offset + limit]

    monkeypatch.setattr(cli_mod, "_list_images_page", fake_list)
    ids = cli_mod._fetch_all_image_ids(
        status="draft",
        status_in=None,
        origin_term_id=None,
        origin_batch_id=None,
        origin_type=None,
        page_size=2,
    )
    assert ids == ["a", "b", "c"]


def test_jobs_images_export_ids_writes_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        cli_mod,
        "_fetch_all_image_ids",
        lambda **kwargs: ["i1", "i2"],
    )
    out = tmp_path / "out.txt"
    res = runner.invoke(cli_mod.app, ["jobs", "images", "export-ids", "--out", str(out), "--status", "draft"])
    assert res.exit_code == 0
    assert out.read_text(encoding="utf-8").strip().splitlines() == ["i1", "i2"]


def test_jobs_ai_bulk_create_prompts_dry_run(tmp_path: Path, monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def no_http(*args: object, **kwargs: object) -> None:
        calls.append(("http", ""))
        raise AssertionError("no HTTP in dry-run")

    monkeypatch.setattr(cli_mod, "_http_json_or_exit", no_http)
    idf = tmp_path / "ids.txt"
    idf.write_text("a\nb\n", encoding="utf-8")
    res = runner.invoke(
        cli_mod.app,
        ["jobs", "ai", "bulk-create-prompts", str(idf), "--dry-run"],
    )
    assert res.exit_code == 0
    assert not calls
    assert "dry-run" in res.output


def test_jobs_ai_bulk_create_prompts_posts_chunks(tmp_path: Path, monkeypatch) -> None:
    """Vérifie que 12 ids = 2 appels _enqueue_and_poll (lots de 10 + 2)."""
    calls: list[dict] = []

    def fake_enqueue_and_poll(job_type: str, config: dict, **kwargs: object) -> dict:
        assert job_type == "image_prompts_bulk"
        calls.append(config)
        items = config.get("items") or []
        return {
            "results": [{"image_id": it["image_id"], "ok": True, "prompt": "p", "negative_prompt": ""} for it in items],
            "summary": {"total": len(items), "success": len(items), "failed": 0},
        }

    monkeypatch.setattr(cli_mod, "_enqueue_and_poll", fake_enqueue_and_poll)
    idf = tmp_path / "ids.txt"
    idf.write_text("\n".join([f"id{i}" for i in range(12)]) + "\n", encoding="utf-8")
    res = runner.invoke(
        cli_mod.app,
        ["jobs", "ai", "bulk-create-prompts", str(idf), "--chunk-size", "10"],
    )
    assert res.exit_code == 0, res.output
    assert len(calls) == 2
    assert len(calls[0]["items"]) == 10
    assert len(calls[1]["items"]) == 2


def test_jobs_ai_bulk_create_prompts_resume_skips_checkpointed(tmp_path: Path, monkeypatch) -> None:
    """Vérifie que --resume + --checkpoint filtre les ids déjà traités."""
    calls: list[dict] = []

    def fake_enqueue_and_poll(job_type: str, config: dict, **kwargs: object) -> dict:
        calls.append(config)
        items = config.get("items") or []
        return {
            "results": [{"image_id": it["image_id"], "ok": True, "prompt": "p", "negative_prompt": ""} for it in items],
            "summary": {"total": len(items), "success": len(items), "failed": 0},
        }

    monkeypatch.setattr(cli_mod, "_enqueue_and_poll", fake_enqueue_and_poll)
    idf = tmp_path / "ids.txt"
    idf.write_text("a\nb\nc\n", encoding="utf-8")
    ck = tmp_path / "ck.txt"
    ck.write_text("a\nb\n", encoding="utf-8")
    res = runner.invoke(
        cli_mod.app,
        [
            "jobs",
            "ai",
            "bulk-create-prompts",
            str(idf),
            "--resume",
            "--checkpoint",
            str(ck),
            "--chunk-size",
            "10",
        ],
    )
    assert res.exit_code == 0, res.output
    assert len(calls) == 1
    assert [it["image_id"] for it in calls[0]["items"]] == ["c"]
