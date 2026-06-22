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
