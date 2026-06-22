"""Providers de couverture moteur de recherche (indexation) — Phase 1, prio 4.

Contexte (DIRECTION-2026-06-22, ADR cockpit-plan-controle-git-verite, table
``index_status``) : le cockpit affiche, par page, son **état d'indexation**
côté Google (Search Console URL Inspection) et Bing (Webmaster). C'est un
**cache lecture** (``index_status``), jamais une vérité de contenu (qui reste
git).

Cap creds = **track Hamma** : ce module fournit les **deux providers réels**
(GSC + Bing) **gatés sur variables d'environnement** — implémentés mais
**inactifs sans creds** — et un ``MockIndexProvider`` **déterministe** qui tourne
*maintenant* (aucun appel réseau). La sélection est automatique :

    creds présents  → provider réel correspondant ;
    sinon           → mock (défaut).

**Aucun appel réseau n'est émis sans creds.** Brancher les vrais providers =
poser les variables d'env (``GSC_*`` / ``BING_WEBMASTER_API_KEY``) ; aucun
changement de code requis côté cockpit.

Périmètre strict : **URL Inspection / couverture** uniquement. La performance
(Search Analytics : impressions/clics/position) est en Phase 2 — PAS ici.

PostgreSQL unique côté cache (``index_status``). Ce module ne touche pas la DB :
il renvoie des dicts ``{url: {coverage_state, last_crawl}}`` ; l'upsert est fait
par ``src/services/index_sync.py``.
"""
from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Iterable, Protocol, runtime_checkable

from api.cockpit_models import COVERAGE_STATES, INDEX_ENGINES

logger = logging.getLogger(__name__)

# Base publique du site (pour dériver l'URL d'une page depuis (locale, slug)).
# Surchargeable par env ``COCKPIT_SITE_BASE`` ; défaut = prod alwanbooks.
DEFAULT_SITE_BASE = "https://alwanbooks.com"

# Quota indicatif GSC URL Inspection (~2000 inspections / jour / propriété).
# Le provider réel s'arrête à ce plafond par run (back-off documenté).
GSC_DAILY_QUOTA = 2000


def site_base() -> str:
    """Base publique du site (env ``COCKPIT_SITE_BASE``), sans slash final."""
    return os.environ.get("COCKPIT_SITE_BASE", DEFAULT_SITE_BASE).rstrip("/")


def work_item_url(locale: str, slug: str, base: str | None = None) -> str:
    """Dérive l'URL publique canonique d'une page depuis ``(locale, slug)``.

    Convention alwanbooks (cf. CLAUDE.md, route prompt-generator) ::

        {base}/{locale}/colorier/{slug}/

    Slash final inclus (forme canonique stockée dans ``index_status.url`` et
    interrogée auprès des moteurs).
    """
    b = (base or site_base()).rstrip("/")
    return f"{b}/{locale}/colorier/{slug}/"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@runtime_checkable
class IndexProvider(Protocol):
    """Contrat d'un fournisseur de couverture d'indexation.

    Un provider **lit** la couverture d'un lot d'URLs auprès d'un moteur et
    renvoie un mapping ``{url: {"coverage_state": <COVERAGE_STATES>,
    "last_crawl": <ISO str|None>}}``. Il ne touche pas la DB. Une URL absente du
    retour est traitée comme ``unknown`` par l'appelant (sync).
    """

    #: Moteur du provider (l'une des valeurs ``INDEX_ENGINES``).
    engine: str

    def inspect(self, urls: Iterable[str]) -> dict[str, dict[str, object]]:
        ...


def _validate_result(engine: str, out: dict[str, dict[str, object]]) -> dict[str, dict[str, object]]:
    """Garde-fou : normalise les états inconnus en ``unknown`` (jamais de 500)."""
    clean: dict[str, dict[str, object]] = {}
    for url, info in out.items():
        state = info.get("coverage_state")
        if state not in COVERAGE_STATES:
            logger.warning("index provider %s: état non normalisé %r pour %s → unknown",
                           engine, state, url)
            state = "unknown"
        clean[url] = {"coverage_state": state, "last_crawl": info.get("last_crawl")}
    return clean


# ── Mock (actif par défaut, aucun réseau) ──────────────────────────────────────

class MockIndexProvider:
    """Provider **déterministe** sans réseau — actif tant que les creds manquent.

    Renvoie un état de couverture **plausible et stable** par URL (déterministe
    via un hash de l'URL), afin de peupler le cache et d'exercer l'affichage et
    l'état dérivé ``indexe`` de bout en bout sans aucun appel moteur.

    Heuristique : la majorité des pages publiées sont ``indexed`` ; une fraction
    minoritaire est répartie sur ``discovered`` / ``crawled_not_indexed`` pour
    que le cockpit montre des cas non triviaux (« publiée non indexée »). On
    peut forcer l'état d'une URL via ``overrides`` (tests / démo ciblée).
    """

    def __init__(self, engine: str = "gsc", overrides: dict[str, str] | None = None):
        if engine not in INDEX_ENGINES:
            raise ValueError(f"engine inconnu : {engine!r} (attendu {INDEX_ENGINES})")
        self.engine = engine
        self._overrides = overrides or {}

    def _state_for(self, url: str) -> str:
        if url in self._overrides:
            return self._overrides[url]
        # Distribution déterministe : ~80% indexed, ~10% discovered,
        # ~10% crawled_not_indexed. Hash stable → même URL = même état.
        bucket = int(hashlib.sha256(url.encode("utf-8")).hexdigest(), 16) % 10
        if bucket < 8:
            return "indexed"
        if bucket == 8:
            return "discovered"
        return "crawled_not_indexed"

    def inspect(self, urls: Iterable[str]) -> dict[str, dict[str, object]]:
        out: dict[str, dict[str, object]] = {}
        now = _now_iso()
        for url in urls:
            state = self._state_for(url)
            # last_crawl plausible uniquement si la page a été crawlée.
            last_crawl = now if state in ("indexed", "crawled_not_indexed") else None
            out[url] = {"coverage_state": state, "last_crawl": last_crawl}
        return _validate_result(self.engine, out)


# ── GSC URL Inspection (réel, gated sur creds, INACTIF sans env) ────────────────

# Mapping verdict/coverageState GSC → vocabulaire normalisé COVERAGE_STATES.
_GSC_COVERAGE_MAP = {
    "Submitted and indexed": "indexed",
    "Indexed, not submitted in sitemap": "indexed",
    "URL is on Google": "indexed",
    "Discovered - currently not indexed": "discovered",
    "Crawled - currently not indexed": "crawled_not_indexed",
    "Excluded by ‘noindex’ tag": "excluded",
    "Duplicate without user-selected canonical": "excluded",
    "Page with redirect": "excluded",
}


def _map_gsc_coverage(raw: str | None) -> str:
    if not raw:
        return "unknown"
    if raw in _GSC_COVERAGE_MAP:
        return _GSC_COVERAGE_MAP[raw]
    low = raw.lower()
    if "indexed" in low and "not" not in low:
        return "indexed"
    if "discovered" in low:
        return "discovered"
    if "crawled" in low and "not indexed" in low:
        return "crawled_not_indexed"
    if "exclud" in low or "noindex" in low or "duplicate" in low or "redirect" in low:
        return "excluded"
    return "unknown"


class GscUrlInspectionProvider:
    """Provider **réel** Google Search Console — URL Inspection API.

    **Gated sur creds** : nécessite un service account OAuth (``GSC_*``). Sans
    creds, ``available()`` est faux et la sélection retombe sur le mock — ce
    provider n'émet alors **aucun appel réseau**.

    URL Inspection est en **lecture seule** (couverture/indexation) — pas
    d'API d'indexation/submit ici. Gère le **quota** (~2000 inspections/jour)
    en s'arrêtant au plafond par run, applique un **back-off** sur les erreurs
    transitoires, et mappe tout **non-200** vers ``unknown`` (jamais d'exception
    propagée à l'appelant : le cache reste cohérent).

    Variables d'env attendues (track Hamma) :
      - ``GSC_SERVICE_ACCOUNT_JSON`` : chemin du fichier de creds service account ;
      - ``GSC_PROPERTY`` (alias ``GSC_SITE_URL``) : propriété GSC (siteUrl) ;
      - ``GSC_DAILY_QUOTA`` (optionnel) : plafond d'inspections par run.
    """

    engine = "gsc"

    REQUIRED_ENV = ("GSC_SERVICE_ACCOUNT_JSON", "GSC_PROPERTY")

    def __init__(self) -> None:
        self.property = os.environ.get("GSC_PROPERTY") or os.environ.get("GSC_SITE_URL")
        self.creds_path = os.environ.get("GSC_SERVICE_ACCOUNT_JSON")
        try:
            self.quota = int(os.environ.get("GSC_DAILY_QUOTA", str(GSC_DAILY_QUOTA)))
        except ValueError:
            self.quota = GSC_DAILY_QUOTA

    @staticmethod
    def available() -> bool:
        """Vrai si toutes les creds GSC sont présentes (sinon → mock)."""
        return all(os.environ.get(k) for k in GscUrlInspectionProvider.REQUIRED_ENV)

    def _client(self):  # pragma: no cover - nécessite creds réelles (track Hamma)
        """Construit le client URL Inspection (google-api-python-client).

        Isolé pour rester importable sans la dépendance Google tant qu'aucun
        appel n'est fait (le mock couvre le défaut). Levé seulement si on tente
        un vrai run sans la lib installée — diagnostic clair côté Hamma.
        """
        from google.oauth2 import service_account  # type: ignore
        from googleapiclient.discovery import build  # type: ignore

        scopes = ["https://www.googleapis.com/auth/webmasters.readonly"]
        creds = service_account.Credentials.from_service_account_file(
            self.creds_path, scopes=scopes,
        )
        return build("searchconsole", "v1", credentials=creds, cache_discovery=False)

    def inspect(self, urls: Iterable[str]) -> dict[str, dict[str, object]]:  # pragma: no cover - réseau réel = track Hamma
        if not self.available():
            # Sécurité : jamais d'appel sans creds (ne devrait pas arriver car la
            # sélection retombe sur le mock — défense en profondeur).
            logger.warning("GscUrlInspectionProvider.inspect appelé sans creds — no-op")
            return {}

        import time

        service = self._client()
        out: dict[str, dict[str, object]] = {}
        count = 0
        for url in urls:
            if count >= self.quota:
                logger.warning("GSC: quota %d atteint, %s+ URLs non inspectées ce run",
                               self.quota, url)
                break
            body = {"inspectionUrl": url, "siteUrl": self.property, "languageCode": "fr"}
            backoff = 1.0
            for attempt in range(3):
                try:
                    resp = service.urlInspection().index().inspect(body=body).execute()
                    result = (resp or {}).get("inspectionResult", {})
                    idx = result.get("indexStatusResult", {})
                    out[url] = {
                        "coverage_state": _map_gsc_coverage(idx.get("coverageState")),
                        "last_crawl": idx.get("lastCrawlTime"),
                    }
                    break
                except Exception as exc:  # noqa: BLE001
                    logger.warning("GSC inspect %s (essai %d): %s", url, attempt + 1, exc)
                    if attempt == 2:
                        out[url] = {"coverage_state": "unknown", "last_crawl": None}
                    else:
                        time.sleep(backoff)
                        backoff *= 2
            count += 1
        return _validate_result(self.engine, out)


# ── Bing Webmaster (réel, gated sur creds, INACTIF sans env) ───────────────────

_BING_COVERAGE_MAP = {
    "Indexed": "indexed",
    "Discovered": "discovered",
    "Crawled": "crawled_not_indexed",
    "Excluded": "excluded",
    "Blocked": "excluded",
}


def _map_bing_coverage(raw: str | None) -> str:
    if not raw:
        return "unknown"
    if raw in _BING_COVERAGE_MAP:
        return _BING_COVERAGE_MAP[raw]
    low = raw.lower()
    if "index" in low and "not" not in low:
        return "indexed"
    if "discover" in low:
        return "discovered"
    if "crawl" in low:
        return "crawled_not_indexed"
    if "exclud" in low or "block" in low:
        return "excluded"
    return "unknown"


class BingWebmasterProvider:
    """Provider **réel** Bing Webmaster — gated sur ``BING_WEBMASTER_API_KEY``.

    Sans clé, ``available()`` est faux → sélection mock, **aucun appel réseau**.
    Lecture seule (couverture). Tout non-200 → ``unknown``, back-off sur erreur
    transitoire.

    Variables d'env attendues (track Hamma) :
      - ``BING_WEBMASTER_API_KEY`` : clé API Bing Webmaster Tools ;
      - ``BING_SITE_URL`` : siteUrl enregistré dans Bing Webmaster.
    """

    engine = "bing"

    def __init__(self) -> None:
        self.api_key = os.environ.get("BING_WEBMASTER_API_KEY")
        self.site_url = os.environ.get("BING_SITE_URL")

    @staticmethod
    def available() -> bool:
        return bool(os.environ.get("BING_WEBMASTER_API_KEY"))

    def inspect(self, urls: Iterable[str]) -> dict[str, dict[str, object]]:  # pragma: no cover - réseau réel = track Hamma
        if not self.available():
            logger.warning("BingWebmasterProvider.inspect appelé sans clé — no-op")
            return {}

        import json
        import time
        import urllib.error
        import urllib.request

        endpoint = (
            "https://ssl.bing.com/webmaster/api.svc/json/GetUrlInfo"
            f"?apikey={self.api_key}"
        )
        out: dict[str, dict[str, object]] = {}
        for url in urls:
            payload = json.dumps({"siteUrl": self.site_url, "url": url}).encode("utf-8")
            backoff = 1.0
            for attempt in range(3):
                try:
                    req = urllib.request.Request(
                        endpoint, data=payload, method="POST",
                        headers={"Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
                        if getattr(resp, "status", 200) != 200:
                            out[url] = {"coverage_state": "unknown", "last_crawl": None}
                            break
                        data = json.loads(resp.read().decode("utf-8"))
                    info = (data or {}).get("d", {}) or {}
                    out[url] = {
                        "coverage_state": _map_bing_coverage(info.get("DocumentStatus")),
                        "last_crawl": info.get("LastCrawledDate"),
                    }
                    break
                except urllib.error.HTTPError as exc:
                    logger.warning("Bing GetUrlInfo %s HTTP %s", url, exc.code)
                    out[url] = {"coverage_state": "unknown", "last_crawl": None}
                    break
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Bing inspect %s (essai %d): %s", url, attempt + 1, exc)
                    if attempt == 2:
                        out[url] = {"coverage_state": "unknown", "last_crawl": None}
                    else:
                        time.sleep(backoff)
                        backoff *= 2
        return _validate_result(self.engine, out)


# ── Sélection automatique (creds → réel, sinon mock) ────────────────────────────

def select_provider(engine: str = "gsc") -> IndexProvider:
    """Sélectionne le provider du moteur : **réel si creds présentes, sinon mock**.

    C'est le SEUL point de choix. Tant que les creds (track Hamma) ne sont pas
    posées, on renvoie ``MockIndexProvider`` → **aucun appel réseau**. Dès que
    les ``GSC_*`` (ou ``BING_WEBMASTER_API_KEY``) sont présentes, le provider
    réel correspondant est activé sans toucher au code appelant.
    """
    if engine not in INDEX_ENGINES:
        raise ValueError(f"engine inconnu : {engine!r} (attendu {INDEX_ENGINES})")

    if engine == "gsc" and GscUrlInspectionProvider.available():
        logger.info("index provider: GSC réel (creds présentes)")
        return GscUrlInspectionProvider()
    if engine == "bing" and BingWebmasterProvider.available():
        logger.info("index provider: Bing réel (clé présente)")
        return BingWebmasterProvider()

    logger.info("index provider: MOCK (engine=%s, creds absentes) — aucun appel réseau", engine)
    return MockIndexProvider(engine=engine)


def provider_is_live(engine: str = "gsc") -> bool:
    """Vrai si le provider RÉEL serait sélectionné (creds présentes) pour ce moteur."""
    if engine == "gsc":
        return GscUrlInspectionProvider.available()
    if engine == "bing":
        return BingWebmasterProvider.available()
    return False
