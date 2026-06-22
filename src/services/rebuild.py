"""Rebuild — déclenchement de build+deploy du site statique (Phase 1, prio 3).

Contexte (décision 4 DIRECTION-2026-06-22) : le site est **statique**
(Astro → Cloudflare). Une page à ``publishDate`` future ne devient *live* que si
un build tourne **après** la date. Le cockpit pilote donc le rebuild :

  - **à la demande** (publication immédiate, bouton cockpit) ;
  - **par cron horaire** (``rebuild_due_run``) pour les ``publishDate`` programmées ;
  - sur **signal « rebuild dû »** (next-action / badge kanban).

Ce module est volontairement **agnostique du backend de build** : le câblage
réel Cloudflare (deploy hook, Pages build) appartient au track Hamma. Ici le
déclencheur est **configurable et mocké** :

  - ``REBUILD_HOOK_URL`` : POST sur un deploy hook (prod / staging) ;
  - ``REBUILD_CMD``      : commande locale (dev : ``npm run build`` etc.) ;
  - aucun des deux configuré → **no-op loggué** (mode mock, défaut).

Aucun déploiement réel n'est déclenché dans cet incrément : sans variable
d'environnement, ``trigger_rebuild`` reste un mock. La règle métier
(``compute_rebuild_due``) est une **fonction pure** testée avec ``now`` injecté.

PostgreSQL unique. Accès DB via le ``DBConnAdapter`` (placeholders ``?``).
``schedule.rebuild_due`` n'est JAMAIS stocké : dérivé à la lecture.
"""
from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

SCHEDULE_COLS = [
    "id", "work_item_id", "publish_date", "last_build_at",
    "created_at", "updated_at",
]
SCHEDULE_SELECT = ", ".join(SCHEDULE_COLS)

# Modes du résultat de trigger_rebuild (toujours renvoyé, jamais d'exception
# pour un mock — le câblage réel Cloudflare = track Hamma).
TRIGGER_MODE_HOOK = "hook"      # POST sur REBUILD_HOOK_URL
TRIGGER_MODE_CMD = "cmd"        # exécution de REBUILD_CMD (dev)
TRIGGER_MODE_MOCK = "mock"      # aucun backend configuré → no-op loggué

_ID_COUNTER = 0


def _new_id(prefix: str) -> str:
    global _ID_COUNTER
    _ID_COUNTER += 1
    return f"{prefix}_{int(time.time() * 1_000_000)}_{_ID_COUNTER}"


def _now_iso(now: datetime | None = None) -> str:
    ref = now or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    return ref.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Règle métier (fonction pure) ───────────────────────────────────────────────

def _as_datetime(value: Any) -> datetime | None:
    """Normalise une valeur (date / datetime / ISO str) en ``datetime`` UTC.

    Une ``date`` nue devient minuit UTC ce jour-là (comparaison homogène avec
    ``last_build_at`` qui est un timestamp). Une chaîne ``YYYY-MM-DD`` idem.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    if isinstance(value, str):
        txt = value.strip()
        if not txt:
            return None
        if txt.endswith("Z"):
            txt = txt[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(txt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            try:
                d = date.fromisoformat(txt[:10])
                return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
            except ValueError:
                return None
    return None


def compute_rebuild_due(
    publish_date: Any,
    last_build_at: Any,
    now: datetime | date | None = None,
) -> bool:
    """Une page programmée est-elle **due au rebuild** ? (fonction pure)

    Règle (décision 4 DIRECTION-2026-06-22) ::

        rebuild_due = (publish_date <= now)
                      ET (last_build_at IS NULL OU last_build_at < publish_date)

    Autrement dit : la page est **arrivée à échéance** (sa ``publishDate`` est
    passée — elle devrait être live) **mais aucun build couvrant cette date n'a
    encore été déployé**. Un site statique ne publie une page programmée
    qu'après un build postérieur à sa ``publishDate``.

    Args:
        publish_date: ``date`` / ``datetime`` / ISO str (miroir git_index) ou
            ``None``. ``None`` → page sans publishDate → jamais due (publiée à
            la date de commit, aucun rebuild programmé en attente).
        last_build_at: timestamp ISO du dernier build déployé, ou ``None``
            (jamais buildée depuis l'enregistrement).
        now: instant de référence (défaut : maintenant UTC). Injectable en test.

    Returns:
        ``True`` si un rebuild est dû, ``False`` sinon.
    """
    pub = _as_datetime(publish_date)
    if pub is None:
        # Pas de publishDate → pas de programmation en attente.
        return False

    ref = now if now is not None else datetime.now(timezone.utc)
    ref_dt = _as_datetime(ref)
    if ref_dt is None:
        return False

    # Pas encore à échéance → la page n'est pas censée être live, rien à faire.
    if pub > ref_dt:
        return False

    # Échue : due tant qu'aucun build postérieur (ou égal) à publish_date.
    build = _as_datetime(last_build_at)
    if build is None:
        return True
    return build < pub


# ── Déclencheur de rebuild (configurable, mocké) ────────────────────────────────

@dataclass
class RebuildResult:
    """Résultat d'un déclenchement de rebuild (jamais d'exception sur mock)."""

    triggered: bool                      # un build a-t-il été (tenté d') effectué
    mode: str                            # TRIGGER_MODE_* (hook / cmd / mock)
    built_at: str | None = None          # timestamp ISO posé si succès
    detail: str = ""                     # message lisible (cause / cible)
    error: str | None = None             # message d'erreur si échec

    def as_dict(self) -> dict[str, Any]:
        return {
            "triggered": self.triggered,
            "mode": self.mode,
            "built_at": self.built_at,
            "detail": self.detail,
            "error": self.error,
        }


def _resolve_trigger_mode() -> str:
    if os.environ.get("REBUILD_HOOK_URL"):
        return TRIGGER_MODE_HOOK
    if os.environ.get("REBUILD_CMD"):
        return TRIGGER_MODE_CMD
    return TRIGGER_MODE_MOCK


def trigger_rebuild(now: datetime | None = None) -> RebuildResult:
    """Déclenche **un** build+deploy du site statique (configurable, mocké).

    Backend choisi par environnement, dans l'ordre :
      1. ``REBUILD_HOOK_URL`` → POST (deploy hook Cloudflare / staging) ;
      2. ``REBUILD_CMD``      → exécution shell locale (dev) ;
      3. aucun                → **no-op loggué** (mode mock, défaut).

    Un seul build couvre toutes les pages : on ne déclenche jamais plus d'un
    build par appel. Renvoie toujours un ``RebuildResult`` (pas d'exception en
    mode mock — l'appelant décide). Le timestamp ``built_at`` est l'instant à
    poser sur ``schedule.last_build_at`` en cas de succès.

    NB : aucun déploiement RÉEL n'est attendu dans cet incrément (env absent →
    mock). Le câblage Cloudflare effectif relève du track Hamma.
    """
    mode = _resolve_trigger_mode()
    built_at = _now_iso(now)

    if mode == TRIGGER_MODE_HOOK:
        url = os.environ["REBUILD_HOOK_URL"]
        try:
            import urllib.request

            req = urllib.request.Request(url, data=b"{}", method="POST",
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
                status = getattr(resp, "status", 200)
            logger.info("rebuild: deploy hook POST %s → %s", url, status)
            return RebuildResult(True, mode, built_at, detail=f"hook {url} (HTTP {status})")
        except Exception as exc:  # noqa: BLE001
            logger.exception("rebuild: échec POST deploy hook %s", url)
            return RebuildResult(False, mode, None, detail=f"hook {url}", error=str(exc))

    if mode == TRIGGER_MODE_CMD:
        cmd = os.environ["REBUILD_CMD"]
        try:
            proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=600)
            if proc.returncode != 0:
                logger.error("rebuild: REBUILD_CMD rc=%s : %s", proc.returncode, proc.stderr[-500:])
                return RebuildResult(False, mode, None, detail=f"cmd `{cmd}`",
                                     error=f"rc={proc.returncode}")
            logger.info("rebuild: REBUILD_CMD `%s` OK", cmd)
            return RebuildResult(True, mode, built_at, detail=f"cmd `{cmd}`")
        except Exception as exc:  # noqa: BLE001
            logger.exception("rebuild: échec REBUILD_CMD `%s`", cmd)
            return RebuildResult(False, mode, None, detail=f"cmd `{cmd}`", error=str(exc))

    # Mode mock : aucun backend configuré. No-op loggué, succès « virtuel »
    # (on pose tout de même built_at pour que la mécanique rebuild_due se teste
    # de bout en bout sans deploy réel).
    logger.info(
        "rebuild: MOCK (ni REBUILD_HOOK_URL ni REBUILD_CMD configuré) — "
        "aucun build réel déclenché ; built_at=%s", built_at
    )
    return RebuildResult(
        True, TRIGGER_MODE_MOCK, built_at,
        detail="mock — configurez REBUILD_HOOK_URL ou REBUILD_CMD pour un build réel",
    )


# ── Accès schedule (miroir publishDate + last_build_at) ─────────────────────────

def _schedule_to_dict(row: Any) -> dict[str, Any]:
    d = dict(zip(SCHEDULE_COLS, row))
    pub = d.get("publish_date")
    d["publish_date"] = pub.isoformat() if pub is not None and hasattr(pub, "isoformat") else (
        str(pub) if pub is not None else None
    )
    return d


def sync_schedule_from_git(conn: Any, repo: str, now: datetime | None = None) -> dict[str, int]:
    """Aligne ``schedule.publish_date`` sur ``git_index`` pour les work_items.

    Pour chaque ``work_item`` du ``repo`` joint à ``git_index`` par
    ``(repo, locale, slug)``, garantit une ligne ``schedule`` dont
    ``publish_date`` reflète ``git_index.publish_date`` (la seule vérité de
    planification). ``last_build_at`` n'est jamais touché ici (fait
    opérationnel, posé par ``trigger_rebuild``). Idempotent.
    """
    ts = _now_iso(now)
    rows = conn.execute(
        "SELECT wi.id, gi.publish_date "
        "FROM work_item wi "
        "JOIN git_index gi ON gi.repo = wi.repo AND gi.locale = wi.locale "
        "  AND gi.slug = wi.slug "
        "WHERE wi.repo = ?",
        [repo],
    ).fetchall()

    inserted = updated = 0
    for wi_id, pub in rows:
        existing = conn.execute(
            "SELECT id, publish_date FROM schedule WHERE work_item_id = ?", [wi_id],
        ).fetchall()
        if existing:
            sid, cur_pub = existing[0][0], existing[0][1]
            if cur_pub != pub:
                conn.execute(
                    "UPDATE schedule SET publish_date = ?, updated_at = ? WHERE id = ?",
                    [pub, ts, sid],
                )
                updated += 1
        else:
            conn.execute(
                "INSERT INTO schedule (id, work_item_id, publish_date, last_build_at, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                [_new_id("sched"), wi_id, pub, None, ts, ts],
            )
            inserted += 1
    return {"inserted": inserted, "updated": updated, "total": len(rows)}


def fetch_due_schedules(conn: Any, now: datetime | None = None) -> list[dict[str, Any]]:
    """Liste les ``schedule`` actuellement **dues au rebuild** (dérivé, pas stocké).

    Joint au ``work_item`` (slug/locale/repo) pour un affichage parlant côté
    cockpit. Le filtre ``rebuild_due`` est appliqué en Python via la fonction
    pure ``compute_rebuild_due`` (source unique de la règle).
    """
    ref = now if now is not None else datetime.now(timezone.utc)
    rows = conn.execute(
        "SELECT s.id, s.work_item_id, s.publish_date, s.last_build_at, "
        "       wi.repo, wi.locale, wi.slug "
        "FROM schedule s JOIN work_item wi ON wi.id = s.work_item_id"
    ).fetchall()
    due: list[dict[str, Any]] = []
    for r in rows:
        if compute_rebuild_due(r[2], r[3], ref):
            due.append({
                "schedule_id": r[0],
                "work_item_id": r[1],
                "publish_date": r[2].isoformat() if hasattr(r[2], "isoformat") else r[2],
                "last_build_at": r[3],
                "repo": r[4],
                "locale": r[5],
                "slug": r[6],
            })
    return due


@dataclass
class RebuildRunReport:
    """Résultat d'un passage cron ``rebuild_due_run``."""

    due_before: int = 0                  # pages dues avant le run
    triggered: bool = False              # un build a-t-il été déclenché
    mode: str = TRIGGER_MODE_MOCK
    built_at: str | None = None
    updated_schedules: int = 0           # nb de last_build_at posés
    due_after: int = 0                   # pages encore dues après (devrait être 0)
    slugs: list[str] = field(default_factory=list)
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "due_before": self.due_before,
            "triggered": self.triggered,
            "mode": self.mode,
            "built_at": self.built_at,
            "updated_schedules": self.updated_schedules,
            "due_after": self.due_after,
            "slugs": self.slugs,
            "error": self.error,
        }


def rebuild_due_run(conn: Any, now: datetime | None = None) -> RebuildRunReport:
    """Passage cron : déclenche **un** rebuild si des pages sont dues, pose les
    ``last_build_at``, et vérifie que plus aucune n'est due.

    Pensé pour être appelé par un planificateur horaire (cf. docstring module +
    PLAN-PHASE1 « 3 options de déclencheur »). Un seul build couvre toutes les
    pages dues : on déclenche au plus un ``trigger_rebuild`` puis on stampe
    ``last_build_at`` sur **toutes** les pages qui étaient dues. Si aucune page
    n'est due → no-op (pas de build inutile).

    Idempotent : un second appel immédiat ne trouve plus de page due → aucun
    build, ``due_before == 0``.
    """
    ref = now if now is not None else datetime.now(timezone.utc)
    report = RebuildRunReport()

    due = fetch_due_schedules(conn, ref)
    report.due_before = len(due)
    report.slugs = [d["slug"] for d in due]

    if not due:
        # Rien à publier : surtout pas de build inutile (coûteux + bruit deploy).
        logger.info("rebuild_due_run: aucune page due, no-op")
        return report

    result = trigger_rebuild(ref)
    report.triggered = result.triggered
    report.mode = result.mode
    report.built_at = result.built_at
    report.error = result.error

    if not result.triggered:
        # Build échoué (hook/cmd KO) : on NE pose PAS last_build_at — les pages
        # restent dues, un prochain run réessaiera. (En mock, triggered=True.)
        logger.warning("rebuild_due_run: build NON déclenché (%s), pages restent dues",
                       result.error)
        report.due_after = report.due_before
        return report

    built_at = result.built_at or _now_iso(ref)
    ts = _now_iso(ref)
    for d in due:
        conn.execute(
            "UPDATE schedule SET last_build_at = ?, updated_at = ? WHERE id = ?",
            [built_at, ts, d["schedule_id"]],
        )
        report.updated_schedules += 1

    # Vérification : plus aucune page due après le build.
    report.due_after = len(fetch_due_schedules(conn, ref))
    logger.info("rebuild_due_run: %d page(s) publiée(s) via build %s (mode=%s), restantes=%d",
                report.updated_schedules, built_at, result.mode, report.due_after)
    return report
