"""États dérivés de git — fonctions pures, jamais stockées en dur.

Cap : git = vérité. Les états affichés au cockpit sont **calculés** depuis
``git_index`` (+ ``now`` / ``build_time``), jamais persistés. Persister un état
réintroduirait une seconde vérité (ce que le cap interdit).

États dérivés (incrément 1) :
  - ``ecrit``     : la page existe dans git (``git_index.exists`` vrai).
  - ``programme`` : existe ET ``publish_date > now`` (publication future).
  - ``publie``    : existe ET ``publish_date <= now``.

``indexe`` (couverture moteur de recherche) = TODO : dépend de la table
``index_status`` (cache Search Console / Bing), tâche ultérieure du plan vivant.

Note : l'état ``publie`` « pleinement correct » dépendra aussi, en tâche
ultérieure, du dernier build déployé (``schedule.last_build_at >= publish_date``).
Dans cet incrément, on s'en tient à ``publish_date <= now`` (build non modélisé
encore). ``build_time`` est accepté en paramètre pour préparer ce raffinement
sans changer la signature publique plus tard.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

# Valeurs possibles de l'état dérivé « cycle de vie git » d'une page.
DERIVED_STATES = ("absent", "ecrit", "programme", "publie")

# Raisons de drift (cache cockpit ≠ git). Le cockpit SIGNALE, il ne corrige
# jamais git (cap : git = vérité du contenu).
DRIFT_NONE = None
DRIFT_ABSENT = "absent_from_git"          # (a) work_item → page absente de git
DRIFT_HASH_CHANGED = "content_hash_changed"  # (b) édition hors cockpit (hash ≠ last_synced)


def _as_date(value: Any) -> date | None:
    """Normalise une valeur publish_date (date / datetime / ISO str) en ``date``."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        txt = value.strip()
        if not txt:
            return None
        if txt.endswith("Z"):
            txt = txt[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(txt).date()
        except ValueError:
            try:
                return date.fromisoformat(txt[:10])
            except ValueError:
                return None
    return None


def derive_git_state(
    git_row: dict[str, Any] | None,
    now: date | datetime | None = None,
    build_time: date | datetime | None = None,
) -> str:
    """Calcule l'état dérivé d'une page depuis sa ligne ``git_index``.

    Args:
        git_row: dict du ``git_index`` (clés ``exists``, ``publish_date``) ou
            ``None`` si la page n'est pas dans le cache git.
        now: instant de référence (défaut : maintenant, UTC). ``date`` ou
            ``datetime`` acceptés.
        build_time: réservé (TODO build filter) — non utilisé dans cet incrément.

    Returns:
        Un des ``DERIVED_STATES``.
    """
    _ = build_time  # TODO : raffiner ``publie`` avec last_build_at (tâche ultérieure)

    if not git_row or not git_row.get("exists"):
        return "absent"

    ref = now if now is not None else datetime.now(timezone.utc)
    ref_date = ref.date() if isinstance(ref, datetime) else ref

    pub = _as_date(git_row.get("publish_date"))
    if pub is None:
        # Présente sans publishDate : considérée publiée (défaut = date de commit,
        # cf. ADR §6). Pas de programmation => visible.
        return "publie"

    if pub > ref_date:
        return "programme"
    return "publie"


def compute_drift(
    git_row: dict[str, Any] | None,
    last_synced_hash: str | None = None,
) -> tuple[bool, str | None]:
    """Détecte le drift entre un work_item et l'état git (fonction pure).

    Le cockpit est un MIROIR de git : il signale les écarts, il ne corrige
    jamais git. Deux cas de drift (cf. brief priorité 1) :

      (a) ``DRIFT_ABSENT`` — le work_item référence une page **absente de git**
          (pas de ``git_index`` correspondant, ou ``exists`` faux : page jamais
          indexée ou disparue du dépôt).
      (b) ``DRIFT_HASH_CHANGED`` — le ``content_hash`` git **a changé** depuis le
          ``last_synced_hash`` mémorisé sur le work_item : la page a été éditée
          hors cockpit. On ne compare que si une référence existe
          (``last_synced_hash`` non NULL) — un work_item neuf sur une page
          existante mais jamais synchronisée n'est PAS en drift hash.

    Args:
        git_row: dict du ``git_index`` (clés ``exists``, ``content_hash``) ou
            ``None`` si la page n'est pas dans le cache git.
        last_synced_hash: dernier ``content_hash`` synchronisé par le cockpit
            (``work_item.last_synced_hash``) ou ``None``.

    Returns:
        ``(drift: bool, reason: str | None)``. ``reason`` est l'une des
        constantes ``DRIFT_*`` (``None`` si pas de drift). Le cas (a) est
        prioritaire sur (b) : une page absente ne peut pas être comparée par hash.
    """
    if not git_row or not git_row.get("exists"):
        return True, DRIFT_ABSENT

    if last_synced_hash is not None:
        current = git_row.get("content_hash")
        if current is not None and current != last_synced_hash:
            return True, DRIFT_HASH_CHANGED

    return False, DRIFT_NONE
