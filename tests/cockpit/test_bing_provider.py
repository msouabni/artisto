"""Tests unitaires du provider Bing Webmaster — corrections post smoke-test.

Contexte : un smoke-test contre l'API Bing réelle (HTTP 200) a révélé que
``BingWebmasterProvider.inspect`` (a) utilisait un POST → HTTP 405, et (b) lisait
un champ ``DocumentStatus`` INEXISTANT dans la réponse réelle (toujours
``unknown``). La correction passe en GET avec query params et DÉRIVE le
``coverage_state`` des champs réels (``LastCrawledDate`` / ``DiscoveryDate`` /
``HttpStatus``), avec parsing des dates .NET ``/Date(<ms>±offset)/``.

PostgreSQL uniquement (cap projet) — mais ces tests sont PURS (aucun réseau,
aucune DB) : ils testent le parsing de date, la dérivation de coverage_state, et
la sélection live du provider via env. Pas d'appel ``inspect`` réseau.
"""
from __future__ import annotations

import pytest

from services.index_providers import (
    _bing_coverage_from_info,
    _parse_dotnet_date,
    provider_is_live,
)

# Sentinelle réelle observée en live = DateTime.MinValue = jamais crawlé/découvert.
SENTINEL = "/Date(-62135568000000-0800)/"


# ── _parse_dotnet_date ──────────────────────────────────────────────────────────

def test_parse_dotnet_date_real():
    """Date .NET réelle (ms positifs) → ISO8601 UTC ``YYYY-MM-DDTHH:MM:SSZ``."""
    # 1700000000000 ms = 2023-11-14T22:13:20Z (UTC).
    assert _parse_dotnet_date("/Date(1700000000000)/") == "2023-11-14T22:13:20Z"


def test_parse_dotnet_date_real_with_offset_ignored():
    """L'offset ``±HHMM`` est ignoré (les ms .NET sont déjà en UTC)."""
    assert _parse_dotnet_date("/Date(1700000000000-0800)/") == "2023-11-14T22:13:20Z"
    assert _parse_dotnet_date("/Date(1700000000000+0530)/") == "2023-11-14T22:13:20Z"


def test_parse_dotnet_date_sentinel_min_value():
    """La sentinelle MinValue (ms négatif) → None (jamais crawlé/découvert)."""
    assert _parse_dotnet_date(SENTINEL) is None
    assert _parse_dotnet_date("/Date(-62135568000000)/") is None


def test_parse_dotnet_date_empty_or_malformed():
    """Entrée vide / non-str / malformée → None, jamais d'exception."""
    assert _parse_dotnet_date("") is None
    assert _parse_dotnet_date(None) is None
    assert _parse_dotnet_date(0) is None
    assert _parse_dotnet_date("not-a-date") is None
    assert _parse_dotnet_date("/Date(abc)/") is None
    assert _parse_dotnet_date("/Date()/") is None


# ── _bing_coverage_from_info (dérivation des 4 états) ───────────────────────────

def test_coverage_indexed():
    """LastCrawledDate réelle + HttpStatus 200 → indexed."""
    info = {
        "LastCrawledDate": "/Date(1700000000000)/",
        "DiscoveryDate": "/Date(1699000000000)/",
        "HttpStatus": 200,
    }
    assert _bing_coverage_from_info(info) == "indexed"


def test_coverage_crawled_not_indexed():
    """LastCrawledDate réelle mais HttpStatus non-200 (≠0) → crawled_not_indexed."""
    info = {
        "LastCrawledDate": "/Date(1700000000000)/",
        "DiscoveryDate": "/Date(1699000000000)/",
        "HttpStatus": 404,
    }
    assert _bing_coverage_from_info(info) == "crawled_not_indexed"


def test_coverage_discovered():
    """DiscoveryDate réelle mais LastCrawledDate au sentinel → discovered."""
    info = {
        "LastCrawledDate": SENTINEL,
        "DiscoveryDate": "/Date(1699000000000)/",
        "HttpStatus": 0,
    }
    assert _bing_coverage_from_info(info) == "discovered"


def test_coverage_unknown():
    """Tout au sentinel / HttpStatus 0 (jamais découvert) → unknown.

    Reproduit la réponse réelle observée en live pour une URL pas encore vue.
    """
    info = {
        "LastCrawledDate": SENTINEL,
        "DiscoveryDate": SENTINEL,
        "HttpStatus": 0,
        "IsPage": True,
        "Url": "https://alwanbooks.com/fr/coloriages/cahier-des-mers/baleine",
    }
    assert _bing_coverage_from_info(info) == "unknown"


def test_coverage_unknown_empty_info():
    """Info vide → unknown, jamais d'exception."""
    assert _bing_coverage_from_info({}) == "unknown"


def test_coverage_malformed_httpstatus():
    """HttpStatus non-numérique ne lève pas — traité comme 0."""
    info = {"LastCrawledDate": SENTINEL, "DiscoveryDate": SENTINEL, "HttpStatus": "x"}
    assert _bing_coverage_from_info(info) == "unknown"


# ── provider_is_live("bing") ────────────────────────────────────────────────────

def test_provider_is_live_bing_true_with_key(monkeypatch):
    """provider_is_live('bing') True quand BING_WEBMASTER_API_KEY est posé."""
    monkeypatch.setenv("BING_WEBMASTER_API_KEY", "fake-key-not-used")
    assert provider_is_live("bing") is True


def test_provider_is_live_bing_false_without_key(monkeypatch):
    """provider_is_live('bing') False quand la clé est absente."""
    monkeypatch.delenv("BING_WEBMASTER_API_KEY", raising=False)
    assert provider_is_live("bing") is False
