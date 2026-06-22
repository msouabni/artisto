"""Tests des états dérivés de git (fonction pure, jamais stockée)."""
from __future__ import annotations

from datetime import date

from services.git_states import derive_git_state


NOW = date(2026, 6, 22)


def test_absent_when_no_git_row():
    assert derive_git_state(None, now=NOW) == "absent"


def test_absent_when_exists_false():
    assert derive_git_state({"exists": False, "publish_date": NOW}, now=NOW) == "absent"


def test_ecrit_publie_when_no_publish_date():
    # Présente sans publishDate → publiée (défaut = date de commit, ADR §6).
    assert derive_git_state({"exists": True, "publish_date": None}, now=NOW) == "publie"


def test_programme_when_publish_date_future():
    assert derive_git_state(
        {"exists": True, "publish_date": date(2026, 7, 1)}, now=NOW
    ) == "programme"


def test_publie_when_publish_date_past_or_now():
    assert derive_git_state(
        {"exists": True, "publish_date": date(2026, 6, 1)}, now=NOW
    ) == "publie"
    assert derive_git_state(
        {"exists": True, "publish_date": NOW}, now=NOW
    ) == "publie"


def test_publish_date_accepts_iso_string():
    assert derive_git_state(
        {"exists": True, "publish_date": "2026-07-01"}, now=NOW
    ) == "programme"
