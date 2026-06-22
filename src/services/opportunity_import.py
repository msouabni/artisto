"""Import léger des opportunités (score de demande) depuis un CSV scoré.

Cap : ce module reflète un signal de **priorisation** (demande SEO) ; il n'est
JAMAIS la vérité du contenu (qui reste git). Il alimente la table
``opportunity`` (lecture seule côté cockpit) et relie chaque ``work_item`` à son
opportunité **par slug**.

Source par défaut : ``data/clusters/cluster-marin-sujets.csv``. Colonnes
attendues (souples) :

    keyword_fr, sujet_fr, slug_fr, volume, pilier_fr, ... (cf. fichier réel)

Le CSV **n'a pas de colonne ``score`` brute**. On dérive donc un **proxy** :

    score = round(100 * volume / max_volume_du_cluster, 1)

normalisé 0-100 sur le volume max du cluster importé. C'est documenté et
volontairement simple : le vrai scoring ``alawseo`` (volume × intention / KD)
arrivera par un CSV déjà scoré, qui sera alors lu tel quel via la colonne
``score`` si présente (l'importeur la respecte si elle existe).

PostgreSQL unique. Upsert portable (SELECT puis INSERT/UPDATE) via le
``DBConnAdapter`` (placeholders ``?``).
"""
from __future__ import annotations

import csv
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OPPORTUNITY_CSV = PROJECT_ROOT / "data" / "clusters" / "cluster-marin-sujets.csv"

_ID_COUNTER = 0


def _new_id(prefix: str) -> str:
    global _ID_COUNTER
    _ID_COUNTER += 1
    return f"{prefix}_{int(time.time() * 1_000_000)}_{_ID_COUNTER}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    txt = str(value).strip()
    if not txt:
        return None
    try:
        return int(float(txt))
    except ValueError:
        return None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    txt = str(value).strip()
    if not txt:
        return None
    try:
        return float(txt)
    except ValueError:
        return None


@dataclass
class ParsedOpportunity:
    keyword: str
    sujet: str | None
    slug: str
    volume: int | None
    kd: int | None
    score: float | None  # peut être None à ce stade ; rempli par le proxy
    cluster: str | None


@dataclass
class ImportReport:
    source: str
    parsed: int = 0
    inserted: int = 0
    updated: int = 0
    linked: int = 0
    score_proxy_used: bool = False
    errors: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "parsed": self.parsed,
            "inserted": self.inserted,
            "updated": self.updated,
            "linked": self.linked,
            "score_proxy_used": self.score_proxy_used,
            "errors": self.errors,
        }


# ── Parsing CSV ────────────────────────────────────────────────────────────────

# Noms de colonnes acceptés par champ (le CSV réel utilise les variantes _fr).
_KEYWORD_KEYS = ("keyword", "keyword_fr", "kw")
_SUJET_KEYS = ("sujet", "sujet_fr", "subject")
_SLUG_KEYS = ("slug", "slug_fr")
_VOLUME_KEYS = ("volume", "search_volume", "vol")
_KD_KEYS = ("kd", "keyword_difficulty", "difficulty")
_SCORE_KEYS = ("score", "demand_score")
_CLUSTER_KEYS = ("cluster", "pilier_fr", "pilier", "clusterId")


def _first(row: dict[str, str], keys: tuple[str, ...]) -> str | None:
    for k in keys:
        if k in row and row[k] is not None and str(row[k]).strip():
            return str(row[k]).strip()
    return None


def parse_csv(path: Path) -> tuple[list[ParsedOpportunity], bool]:
    """Parse un CSV scoré → ``(opportunités, score_proxy_used)``.

    ``score_proxy_used`` est vrai si aucune colonne ``score`` n'était présente
    (ou toutes vides) et que le proxy volume a dû être appliqué.
    """
    opps: list[ParsedOpportunity] = []
    any_raw_score = False

    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            slug = _first(row, _SLUG_KEYS)
            keyword = _first(row, _KEYWORD_KEYS)
            if not slug:
                # Sans slug, pas de jointure possible → on saute (trace).
                continue
            raw_score = _to_float(_first(row, _SCORE_KEYS))
            if raw_score is not None:
                any_raw_score = True
            opps.append(
                ParsedOpportunity(
                    keyword=keyword or slug,
                    sujet=_first(row, _SUJET_KEYS),
                    slug=slug,
                    volume=_to_int(_first(row, _VOLUME_KEYS)),
                    kd=_to_int(_first(row, _KD_KEYS)),
                    score=raw_score,
                    cluster=_first(row, _CLUSTER_KEYS),
                )
            )

    score_proxy_used = not any_raw_score
    if score_proxy_used:
        _apply_volume_proxy(opps)
    return opps, score_proxy_used


def _apply_volume_proxy(opps: list[ParsedOpportunity]) -> None:
    """Dérive ``score`` 0-100 depuis ``volume`` (normalisé sur le max présent).

    Proxy documenté : faute de score brut dans la source, le volume de
    recherche est le meilleur signal de demande disponible. Normalisation sur le
    max du lot → 100 = sujet le plus demandé du cluster.
    """
    max_vol = max((o.volume or 0) for o in opps) if opps else 0
    for o in opps:
        if max_vol > 0 and o.volume:
            o.score = round(100.0 * o.volume / max_vol, 1)
        else:
            o.score = 0.0


# ── Upsert opportunity + lien work_item ─────────────────────────────────────────

def _upsert_opportunity(conn: Any, opp: ParsedOpportunity, source: str, now: str) -> str:
    rows = conn.execute(
        "SELECT id FROM opportunity WHERE source = ? AND keyword = ?",
        [source, opp.keyword],
    ).fetchall()
    if rows:
        oid = rows[0][0]
        conn.execute(
            "UPDATE opportunity SET sujet = ?, slug = ?, volume = ?, kd = ?, "
            "score = ?, cluster = ?, imported_at = ? WHERE id = ?",
            [opp.sujet, opp.slug, opp.volume, opp.kd, opp.score, opp.cluster, now, oid],
        )
        return "updated"
    oid = _new_id("opp")
    conn.execute(
        "INSERT INTO opportunity "
        "(id, keyword, sujet, slug, volume, kd, score, cluster, source, imported_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [oid, opp.keyword, opp.sujet, opp.slug, opp.volume, opp.kd,
         opp.score, opp.cluster, source, now],
    )
    return "inserted"


def link_work_items(conn: Any, repo: str | None = None) -> int:
    """Relie ``work_item.opportunity_id`` à ``opportunity.id`` par slug.

    Un work_item est relié à l'opportunité partageant son ``slug`` (la plus
    forte par ``score`` si plusieurs sources). Lien souple (id texte), idempotent.
    Retourne le nombre de work_items reliés (ou re-confirmés).
    """
    sql = "SELECT id, slug FROM work_item"
    params: list[Any] = []
    if repo:
        sql += " WHERE repo = ?"
        params.append(repo)
    work_items = conn.execute(sql, params).fetchall()

    linked = 0
    for wid, slug in work_items:
        opp = conn.execute(
            "SELECT id FROM opportunity WHERE slug = ? "
            "ORDER BY score DESC NULLS LAST LIMIT 1",
            [slug],
        ).fetchall()
        if opp:
            conn.execute(
                "UPDATE work_item SET opportunity_id = ? WHERE id = ?",
                [opp[0][0], wid],
            )
            linked += 1
    return linked


def import_opportunities(
    conn: Any,
    source_csv: Path | None = None,
    repo: str | None = None,
) -> ImportReport:
    """Importe le CSV d'opportunités → table ``opportunity`` + lien work_items.

    Idempotent (upsert par ``(source, keyword)``). Relie ensuite les work_items
    présents par slug. Le ``source`` enregistré est le nom du fichier CSV.
    """
    path = source_csv or DEFAULT_OPPORTUNITY_CSV
    source = path.name
    report = ImportReport(source=source)

    if not path.is_file():
        report.errors.append({"file": str(path), "error": "fichier introuvable"})
        return report

    opps, proxy = parse_csv(path)
    report.parsed = len(opps)
    report.score_proxy_used = proxy
    now = _now_iso()

    for opp in opps:
        try:
            outcome = _upsert_opportunity(conn, opp, source, now)
            if outcome == "inserted":
                report.inserted += 1
            else:
                report.updated += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception("opportunity_import: échec upsert %s", opp.slug)
            report.errors.append({"slug": opp.slug, "error": str(exc)})

    report.linked = link_work_items(conn, repo=repo)
    return report
