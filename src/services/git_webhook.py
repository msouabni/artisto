"""Webhook post-commit git — réconciliation des éditions hors cockpit (P2 inc.2).

Cap inchangé : **git = vérité du contenu**. Quand une page est éditée directement
dans git (hors cockpit), le cache ``git_index`` doit se réaligner. Le poll
horaire (Phase 1) le capte avec latence ; ce webhook le capte **immédiatement** :

  ``POST /api/cockpit/webhook/git`` reçoit un payload type GitHub *push* (liste de
  fichiers modifiés/ajoutés/supprimés) → réindexe ``git_index`` POUR LES CHEMINS
  TOUCHÉS (réutilise ``git_indexer.reindex_paths``) → le drift est recalculé à la
  lecture (les work_items dont la page a changé hors cockpit passent en drift).

Sécurité : signature HMAC-SHA256 type GitHub (en-tête ``X-Hub-Signature-256:
sha256=<hex>``) vérifiée contre le secret partagé ``GIT_WEBHOOK_SECRET``. Pas de
secret en dur : si le secret n'est pas configuré, le webhook REFUSE tout
(503 — pas de bypass silencieux). Comparaison à temps constant.

Dégradation propre : payload illisible → rejet 400 ; signature invalide → 401 ;
repo injoignable / erreur d'indexation isolée → loggué, jamais de crash
(idempotent, on réindexe ce qu'on peut).

PostgreSQL unique. SQLite interdit.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

from services.git_indexer import DEFAULT_REPO, reindex_paths

logger = logging.getLogger(__name__)

SIGNATURE_HEADER = "X-Hub-Signature-256"
_SIG_PREFIX = "sha256="


class WebhookError(RuntimeError):
    """Erreur métier du webhook (payload illisible, repo absent…)."""


class WebhookAuthError(RuntimeError):
    """Échec d'authentification du webhook (secret absent ou signature invalide)."""

    def __init__(self, message: str, *, status: int = 401) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class WebhookResult:
    """Résultat du traitement d'un payload webhook."""

    repo: str
    received_paths: int = 0
    content_paths: int = 0
    reindexed: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    marked_absent: int = 0
    errors: list[dict[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "received_paths": self.received_paths,
            "content_paths": self.content_paths,
            "reindexed": self.reindexed,
            "inserted": self.inserted,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "marked_absent": self.marked_absent,
            "errors": self.errors,
            "notes": self.notes,
        }


def get_secret() -> str | None:
    """Secret partagé du webhook (env ``GIT_WEBHOOK_SECRET``). Jamais en dur."""
    sec = os.environ.get("GIT_WEBHOOK_SECRET")
    return sec if sec else None


def compute_signature(secret: str, raw_body: bytes) -> str:
    """Calcule la signature GitHub-style ``sha256=<hex>`` d'un corps brut."""
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return f"{_SIG_PREFIX}{digest}"


def verify_signature(raw_body: bytes, signature_header: str | None) -> None:
    """Vérifie la signature HMAC du webhook. Lève ``WebhookAuthError`` sinon.

    - Secret non configuré → 503 (refus, pas de bypass : pas de secret en dur).
    - En-tête absent ou mal formé → 401.
    - Signature ne correspondant pas (compare_digest, temps constant) → 401.
    """
    secret = get_secret()
    if not secret:
        raise WebhookAuthError(
            "webhook désactivé : GIT_WEBHOOK_SECRET non configuré (aucun secret en dur)",
            status=503,
        )
    if not signature_header or not signature_header.startswith(_SIG_PREFIX):
        raise WebhookAuthError("signature manquante ou mal formée", status=401)

    expected = compute_signature(secret, raw_body)
    if not hmac.compare_digest(expected, signature_header):
        raise WebhookAuthError("signature invalide", status=401)


def extract_paths(payload: dict[str, Any]) -> list[str]:
    """Extrait les chemins touchés d'un payload push GitHub-style.

    Agrège ``added`` + ``modified`` + ``removed`` sur tous les ``commits`` (et,
    par tolérance, sur un éventuel bloc ``head_commit``). Dédupliqué en
    préservant l'ordre. Un payload sans aucun de ces champs → liste vide (no-op).
    """
    paths: list[str] = []

    def _collect(obj: Any) -> None:
        if not isinstance(obj, dict):
            return
        for key in ("added", "modified", "removed"):
            vals = obj.get(key)
            if isinstance(vals, list):
                for v in vals:
                    if isinstance(v, str) and v:
                        paths.append(v)

    commits = payload.get("commits")
    if isinstance(commits, list):
        for c in commits:
            _collect(c)
    _collect(payload.get("head_commit"))

    # Dédup en préservant l'ordre (idempotence du fan-out).
    seen: set[str] = set()
    out: list[str] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def parse_payload(raw_body: bytes) -> dict[str, Any]:
    """Parse le corps JSON du webhook. Lève ``WebhookError`` si illisible."""
    try:
        data = json.loads(raw_body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise WebhookError(f"payload JSON illisible : {exc}") from exc
    if not isinstance(data, dict):
        raise WebhookError("payload webhook n'est pas un objet JSON")
    return data


def handle_push(
    conn: Any,
    payload: dict[str, Any],
    *,
    repo: str = DEFAULT_REPO,
) -> WebhookResult:
    """Traite un payload push : réindexe les chemins de contenu touchés.

    Idempotent (réindexer 2× le même chemin = même état). Si le clone est
    injoignable ou qu'un chemin échoue, on dégrade proprement (loggué dans
    ``errors``, jamais de crash). N'efface PAS le reste de l'index (réindex ciblé).
    """
    result = WebhookResult(repo=repo)
    paths = extract_paths(payload)
    result.received_paths = len(paths)
    if not paths:
        result.notes.append("aucun chemin dans le payload — no-op")
        return result

    try:
        report = reindex_paths(conn, paths, repo=repo)
    except Exception as exc:  # noqa: BLE001  (dégrade proprement : repo injoignable…)
        logger.exception("git_webhook: réindexation échouée (repo injoignable ?)")
        result.errors.append({"path": "*", "error": str(exc)})
        result.notes.append("réindexation dégradée (voir errors) — pas de crash")
        return result

    result.content_paths = report.scanned
    result.inserted = report.inserted
    result.updated = report.updated
    result.unchanged = report.unchanged
    result.marked_absent = report.marked_absent
    result.reindexed = report.inserted + report.updated + report.unchanged + report.marked_absent
    result.errors.extend(report.errors)
    result.notes.append(
        f"{result.content_paths} chemin(s) de contenu réindexé(s) "
        f"(+{report.inserted} / ~{report.updated} / ={report.unchanged} / "
        f"absent {report.marked_absent})"
    )
    return result
