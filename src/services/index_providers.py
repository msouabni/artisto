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
import re
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

# Segment racine des catégories par locale dans l'URL publique du front
# (rimalab-v2 : ``src/lib/i18n/paths.ts::categoriesRoot``). C'est la SEULE source
# de vérité côté cockpit pour répliquer la route SEO catégorie-nichée. Toute
# feuille SEO vit sous ``/{locale}/{CATEGORIES_ROOT[locale]}/<chemin-cat>/<slug>``.
CATEGORIES_ROOT = {
    "ar": "talween",
    "fr": "coloriages",
    "en": "coloring",
}

# Catégorie SEO par défaut quand on ne sait pas résoudre le cluster d'un
# work_item (ex. work_item sans opportunité liée). Le lot marin « Cahier des
# mers » (DIRECTION-2026-06-22) est la racine catégorie ``cahier-des-mers``.
DEFAULT_CATEGORY_SLUG = "cahier-des-mers"

# Mapping cluster (libellé/id côté opportunity) → slug catégorie racine du front.
# Le CSV d'opportunités porte ``cluster`` en libellé humain (« animaux marins »)
# ou en id ; le front, lui, range ces planches sous la catégorie racine
# ``cahier-des-mers`` (id ``cahier_des_mers``). On normalise donc plusieurs
# variantes vers le même slug. Pour un arbre catégorie multi-niveaux futur,
# remplacer la valeur par le CHEMIN complet (``parent-slug/enfant-slug``) — la
# dérivation d'URL joint déjà les segments tels quels (cf. ``work_item_url``).
_CLUSTER_TO_CATEGORY_SLUG = {
    "cahier_des_mers": "cahier-des-mers",
    "cahier-des-mers": "cahier-des-mers",
    "animaux marins": "cahier-des-mers",
    "animaux-marins": "cahier-des-mers",
}


def site_base() -> str:
    """Base publique du site (env ``COCKPIT_SITE_BASE``), sans slash final."""
    return os.environ.get("COCKPIT_SITE_BASE", DEFAULT_SITE_BASE).rstrip("/")


def categories_root(locale: str) -> str:
    """Segment racine des catégories pour ``locale`` (fr=coloriages, ar=talween…).

    Retombe sur ``coloriages`` (fr) pour une locale inconnue — défensif, jamais
    de 500. Réplique ``categoriesRoot`` du front (rimalab-v2).
    """
    return CATEGORIES_ROOT.get(locale, CATEGORIES_ROOT["fr"])


def _slugify_cluster(cluster: str) -> str:
    """Slugifie un libellé cluster brut (« animaux marins » → « animaux-marins »).

    Fallback quand le cluster n'est pas dans ``_CLUSTER_TO_CATEGORY_SLUG`` : on
    produit un slug raisonnable plutôt que d'inventer une catégorie. Ne gère pas
    l'arbre multi-niveaux (réserve : un cluster mappera un jour un chemin complet).
    """
    return "-".join(cluster.strip().lower().split())


def category_slug_for_cluster(cluster: str | None) -> str:
    """Résout le slug (ou chemin) catégorie SEO depuis le cluster d'un work_item.

    - ``None`` / vide → ``DEFAULT_CATEGORY_SLUG`` (lot marin = ``cahier-des-mers``).
    - cluster connu (id ou libellé) → slug mappé (``_CLUSTER_TO_CATEGORY_SLUG``).
    - sinon → slugification du libellé (fallback raisonnable).

    Réserve : si l'arbre catégorie devient multi-niveaux, la valeur mappée doit
    porter le CHEMIN complet (``parent/enfant``) — ``work_item_url`` l'insère tel
    quel entre la racine et le slug de planche.
    """
    if not cluster:
        return DEFAULT_CATEGORY_SLUG
    key = cluster.strip()
    if key in _CLUSTER_TO_CATEGORY_SLUG:
        return _CLUSTER_TO_CATEGORY_SLUG[key]
    low = key.lower()
    if low in _CLUSTER_TO_CATEGORY_SLUG:
        return _CLUSTER_TO_CATEGORY_SLUG[low]
    return _slugify_cluster(key)


def work_item_url(
    locale: str,
    slug: str,
    category_slug: str | None = None,
    base: str | None = None,
) -> str:
    """Dérive l'URL publique **SEO indexable** d'une planche.

    Réplique la route catégorie-nichée du front (rimalab-v2 :
    ``getPostUrl`` / ``getCategoryPath`` + ``categoriesRoot``) ::

        {base}/{locale}/{categoriesRoot[locale]}/{chemin-catégorie}/{slug}

    Ex. : ``https://alwanbooks.com/fr/coloriages/cahier-des-mers/baleine``.

    **Pas** de ``/colorier/`` (= page colorieur ``noindex``, à ne PAS interroger
    en GSC) et **pas de slash final** (``trailingSlash: 'never'`` côté Astro).

    ``category_slug`` est le slug (ou chemin ``parent/enfant``) de la catégorie
    racine de la planche ; à défaut, on retombe sur ``DEFAULT_CATEGORY_SLUG``
    (lot marin = ``cahier-des-mers``). C'est la forme canonique stockée dans
    ``index_status.url`` et interrogée auprès des moteurs.
    """
    b = (base or site_base()).rstrip("/")
    cat = (category_slug or DEFAULT_CATEGORY_SLUG).strip("/")
    return f"{b}/{locale}/{categories_root(locale)}/{cat}/{slug}"


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

# Format date .NET renvoyé par l'API Bing : ``/Date(<ms>[±<offset>])/``.
# Ex. réel : ``/Date(-62135568000000-0800)/`` = DateTime.MinValue = sentinelle
# « jamais crawlé/découvert ». Le ms peut être négatif (sentinelle) ou positif.
_DOTNET_DATE_RE = re.compile(r"/Date\((-?\d+)(?:[+-]\d{4})?\)/")


def _parse_dotnet_date(raw: object) -> str | None:
    """Parse une date .NET ``/Date(<ms>[±offset])/`` → ISO8601 UTC, sinon ``None``.

    - L'offset (``±HHMM``) est **ignoré** : les ms .NET sont déjà en UTC (epoch).
    - Sentinelle ``DateTime.MinValue`` (ms négatif, ex. ``-62135568000000``) ou
      toute valeur absente/non-parsable → ``None`` (= jamais crawlé/découvert).
    - **Ne lève jamais** : toute exception/format invalide → ``None``.
    """
    if not raw or not isinstance(raw, str):
        return None
    m = _DOTNET_DATE_RE.search(raw)
    if not m:
        return None
    try:
        ms = int(m.group(1))
    except (ValueError, TypeError):
        return None
    if ms < 0:
        # Sentinelle MinValue (et toute date antérieure à l'epoch = non pertinent ici).
        return None
    try:
        dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _bing_coverage_from_info(info: dict) -> str:
    """Dérive ``coverage_state`` depuis les champs réels d'un ``UrlInfo`` Bing.

    L'API Bing ne renvoie PAS d'« état de couverture » textuel : on le DÉRIVE des
    champs ``LastCrawledDate`` / ``DiscoveryDate`` / ``HttpStatus`` (cf. contrat
    réel observé en live, HTTP 200). Règle :

    - ``LastCrawledDate`` réelle (≠ sentinelle MinValue) ET ``HttpStatus == 200``
      → ``"indexed"`` ;
    - ``LastCrawledDate`` réelle mais ``HttpStatus`` non-200 (≠ 0)
      → ``"crawled_not_indexed"`` ;
    - ``DiscoveryDate`` réelle mais ``LastCrawledDate`` à la sentinelle (jamais
      crawlé) → ``"discovered"`` ;
    - tout à la sentinelle / ``HttpStatus == 0`` (jamais découvert) → ``"unknown"``.
    """
    last_crawl = _parse_dotnet_date(info.get("LastCrawledDate"))
    discovery = _parse_dotnet_date(info.get("DiscoveryDate"))
    try:
        http_status = int(info.get("HttpStatus") or 0)
    except (ValueError, TypeError):
        http_status = 0

    if last_crawl is not None:
        if http_status == 200:
            return "indexed"
        if http_status != 0:
            return "crawled_not_indexed"
        # Crawlé mais HttpStatus inconnu (0) : on reste prudent → discovered si
        # découvert, sinon unknown. En pratique un crawl réel porte un status.
        return "discovered" if discovery is not None else "unknown"
    if discovery is not None:
        return "discovered"
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
        import urllib.parse
        import urllib.request

        # Contrat réel observé en live (HTTP 200) : l'endpoint est un **GET** avec
        # query params (le POST renvoie HTTP 405 Method Not Allowed). La réponse
        # est un objet unique sous la clé ``d`` (pas de champ ``DocumentStatus``) ;
        # on DÉRIVE coverage_state des champs réels via ``_bing_coverage_from_info``.
        base_endpoint = "https://ssl.bing.com/webmaster/api.svc/json/GetUrlInfo"
        out: dict[str, dict[str, object]] = {}
        for url in urls:
            qs = urllib.parse.urlencode({
                "apikey": self.api_key,
                "siteUrl": self.site_url,
                "url": url,
            })
            endpoint = f"{base_endpoint}?{qs}"
            backoff = 1.0
            for attempt in range(3):
                try:
                    # GET : pas de body, pas de méthode POST.
                    req = urllib.request.Request(endpoint, method="GET")
                    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
                        if getattr(resp, "status", 200) != 200:
                            out[url] = {"coverage_state": "unknown", "last_crawl": None}
                            break
                        data = json.loads(resp.read().decode("utf-8"))
                    info = (data or {}).get("d", {}) or {}
                    out[url] = {
                        "coverage_state": _bing_coverage_from_info(info),
                        "last_crawl": _parse_dotnet_date(info.get("LastCrawledDate")),
                    }
                    break
                except urllib.error.HTTPError as exc:
                    # Ne jamais logger la query string (contient apikey) : seul ``url``.
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
