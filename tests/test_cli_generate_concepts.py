from __future__ import annotations

import sys

from typer.testing import CliRunner

sys.path.insert(0, "src")

import cli as cli_mod


runner = CliRunner()


def test_jobs_generate_concepts_auto_enables_and_enqueues(monkeypatch):
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(
        cli_mod,
        "_fetch_term_for_cli",
        lambda vocabulary_id, term_id: {
            "id": term_id,
            "name_en": "Cats in Houses",
            "name_fr": "Chats dans des maisons",
            "vocabulary_id": vocabulary_id,
        },
    )

    def fake_enable(job_type: str) -> None:
        calls.append(("enable", job_type))

    def fake_enqueue(payload: dict) -> None:
        calls.append(("enqueue", payload))

    monkeypatch.setattr(cli_mod, "_ensure_job_type_enabled", fake_enable)
    monkeypatch.setattr(cli_mod, "_post_enqueue", fake_enqueue)

    res = runner.invoke(
        cli_mod.app,
        ["jobs", "generate-concepts", "--term-id", "animaux_domestiques_cats_houses", "--count", "10"],
    )

    assert res.exit_code == 0
    assert calls[0] == ("enable", "image_generate_concepts")
    kind, payload = calls[1]
    assert kind == "enqueue"
    assert payload["type"] == "image_generate_concepts"
    assert payload["config"]["term_id"] == "animaux_domestiques_cats_houses"
    assert payload["config"]["vocabulary_id"] == "themes"
    assert payload["config"]["theme"] == "Cats in Houses"
    assert payload["config"]["count"] == 10


def test_jobs_generate_concepts_http_error_exits_cleanly(monkeypatch):
    monkeypatch.setattr(cli_mod, "_ensure_job_type_enabled", lambda job_type: None)
    monkeypatch.setattr(cli_mod, "_post_enqueue", lambda payload: (_ for _ in ()).throw(SystemExit(1)))

    res = runner.invoke(
        cli_mod.app,
        ["jobs", "generate-concepts", "Mon thème", "--count", "5"],
    )

    assert res.exit_code == 1
