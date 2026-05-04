"""Classe de base pour les workers de la queue de jobs.

Pattern 3-phases : connexions DB courtes, pas de DB ouverte pendant le traitement.
Garde-fous PostgreSQL : heartbeat fire-and-forget, max_concurrent=1 enforced.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Backoff exponentiel pour retry (secondes)
RETRY_DELAYS = [60, 300, 900]  # 1min, 5min, 15min
STALE_HEARTBEAT_MINUTES = 5
HEARTBEAT_INTERVAL_SECONDS = 30


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _compute_duration_ms(job: dict[str, Any]) -> int | None:
    """Calcule duration_ms depuis started_at jusqu'à maintenant."""
    started_at = job.get("started_at")
    if not started_at:
        return None
    try:
        from datetime import timedelta  # noqa: F401 already imported elsewhere
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - started
        return int(delta.total_seconds() * 1000)
    except Exception:
        return None


class BaseWorker(ABC):
    """Worker abstrait pour un type de job."""

    job_type: str = ""
    category: str = ""
    #: Si défini, ce worker réclame n'importe quel job dont le type est dans ce tuple (sinon ``job_type`` seul).
    job_types: tuple[str, ...] | None = None

    def __init__(self, db_path: Path | None = None) -> None:
        # db_path conservé pour rétrocompatibilité CLI ; ignoré avec PostgreSQL.
        self.db_path = db_path
        label = ",".join(self._types_for_query()) if self._types_for_query() else (self.job_type or "worker")
        self._worker_id = f"{label}_{os.getpid()}_{threading.get_ident()}"
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None

    def _types_for_query(self) -> tuple[str, ...]:
        if self.job_types:
            return self.job_types
        return (self.job_type,) if self.job_type else tuple()

    def _conn(self, read_only: bool = False):
        from api.db import get_db_sync
        return get_db_sync(read_only=read_only, db_path=self.db_path)

    def _check_type_enabled(self) -> bool:
        """Vérifie qu'au moins un type géré a job_type_config.enabled=1."""
        types = self._types_for_query()
        if not types:
            return False
        conn = self._conn(read_only=False)
        try:
            ph = ",".join("?" * len(types))
            row = conn.execute(
                f"SELECT COUNT(*) FROM job_type_config WHERE type IN ({ph}) AND enabled = ?",
                list(types) + [True],
            ).fetchone()
            return bool(row and row[0] and row[0] > 0)
        finally:
            conn.close()

    def _max_concurrent(self) -> int:
        """Lit le max_concurrent agrégé (max) pour les types gérés depuis job_type_config."""
        types = self._types_for_query()
        if not types:
            return 1
        conn = self._conn(read_only=False)
        try:
            ph = ",".join("?" * len(types))
            row = conn.execute(
                f"SELECT MAX(max_concurrent) FROM job_type_config WHERE type IN ({ph})",
                list(types),
            ).fetchone()
            val = row[0] if row and row[0] is not None else 1
            return max(int(val), 1)
        except Exception:
            return 1
        finally:
            conn.close()

    def _count_running(self) -> int:
        """Nombre de jobs running pour les types gérés."""
        types = self._types_for_query()
        if not types:
            return 0
        conn = self._conn(read_only=False)
        try:
            ph = ",".join("?" * len(types))
            row = conn.execute(
                f"SELECT COUNT(*) FROM job WHERE type IN ({ph}) AND status = 'running'",
                list(types),
            ).fetchone()
            return row[0] if row else 0
        finally:
            conn.close()

    def _recover_stale_jobs(self) -> None:
        """Reset jobs running sans heartbeat depuis >5min en pending. Silencieux si DB verrouillée."""
        try:
            conn = self._conn(read_only=False)
        except Exception as e:
            logger.debug("_recover_stale_jobs : DB indisponible (ignoré) : %s", e)
            return
        try:
            threshold = datetime.now(timezone.utc)
            from datetime import timedelta
            threshold = (threshold - timedelta(minutes=STALE_HEARTBEAT_MINUTES)).strftime("%Y-%m-%dT%H:%M:%SZ")
            types = self._types_for_query()
            if not types:
                return
            ph = ",".join("?" * len(types))
            conn.execute(
                f"""
                UPDATE job SET status = 'pending', worker_id = NULL, last_heartbeat_at = NULL
                WHERE type IN ({ph}) AND status = 'running'
                  AND (last_heartbeat_at IS NULL OR last_heartbeat_at < ?)
                """,
                list(types) + [threshold],
            )
            conn.session.commit()
        finally:
            conn.close()

    def _heartbeat_fire_and_forget(self, job_id: str) -> None:
        """Met à jour last_heartbeat_at. 1 retry max — échec silencieux."""
        for attempt in range(2):
            try:
                conn = self._conn(read_only=False)
                try:
                    conn.execute(
                        "UPDATE job SET last_heartbeat_at = ? WHERE id = ? AND status = 'running'",
                        [_now(), job_id],
                    )
                    conn.session.commit()
                finally:
                    conn.close()
                return
            except Exception as e:
                if attempt == 0:
                    logger.debug("Heartbeat job %s échoué (retry): %s", job_id, e)
                else:
                    logger.debug("Heartbeat job %s échoué (ignoré): %s", job_id, e)

    def _start_heartbeat(self, job_id: str) -> None:
        """Lance un thread qui envoie un heartbeat toutes les 30s."""
        self._heartbeat_stop.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(job_id,),
            daemon=True,
        )
        self._heartbeat_thread.start()

    def _heartbeat_loop(self, job_id: str) -> None:
        while not self._heartbeat_stop.wait(HEARTBEAT_INTERVAL_SECONDS):
            self._heartbeat_fire_and_forget(job_id)

    def _stop_heartbeat(self) -> None:
        self._heartbeat_stop.set()
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=2)
            self._heartbeat_thread = None

    def _progress_fire_and_forget(self, job_id: str, progress: int, message: str | None = None) -> None:
        """Met à jour progress. 1 retry max — échec silencieux."""
        for attempt in range(2):
            try:
                conn = self._conn(read_only=False)
                try:
                    if message is not None:
                        conn.execute(
                            "UPDATE job SET progress = ?, progress_message = ? WHERE id = ? AND status = 'running'",
                            [progress, message, job_id],
                        )
                    else:
                        conn.execute(
                            "UPDATE job SET progress = ? WHERE id = ? AND status = 'running'",
                            [progress, job_id],
                        )
                    conn.session.commit()
                finally:
                    conn.close()
                return
            except Exception as e:
                if attempt == 0:
                    logger.debug("Progress job %s échoué (retry): %s", job_id, e)
                else:
                    logger.debug("Progress job %s échoué (ignoré): %s", job_id, e)

    def _update_progress(self, job_id: str, progress: int, message: str | None = None) -> None:
        """Alias public pour _progress_fire_and_forget (utilisé par les workers concrets)."""
        self._progress_fire_and_forget(job_id, progress, message)

    def fetch_and_start(self) -> dict[str, Any] | None:
        """Phase 1 : claim atomique d'un job pending via FOR UPDATE SKIP LOCKED."""
        if not self._check_type_enabled():
            return None
        if self._count_running() >= self._max_concurrent():
            return None

        types = self._types_for_query()
        if not types:
            return None
        conn = self._conn(read_only=False)
        try:
            now = _now()
            ph = ",".join("?" * len(types))
            claim_row = conn.execute(
                f"""
                WITH candidate AS (
                    SELECT id
                    FROM job
                    WHERE type IN ({ph}) AND status = 'pending'
                      AND (scheduled_at IS NULL OR scheduled_at <= ?)
                    ORDER BY priority ASC, created_at ASC
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE job j
                SET status = 'running', started_at = ?, worker_id = ?, last_heartbeat_at = ?
                FROM candidate
                WHERE j.id = candidate.id
                RETURNING j.id, j.type, j.entity_type, j.entity_id, j.image_id, j.config, j.retry_count, j.max_retries, j.started_at
                """,
                list(types) + [now, now, self._worker_id, now],
            ).fetchone()
            conn.session.commit()
            if not claim_row:
                return None

            r = claim_row
            job_id = r[0]
            claimed_type = r[1]
            entity_type = r[2]
            entity_id = r[3]
            image_id = r[4]
            config_json = r[5]
            retry_count = r[6] or 0
            max_retries = r[7] if r[7] is not None else 3
            started_at = r[8]

            config = json.loads(config_json) if config_json else {}
            entity_id = entity_id or image_id
            return {
                "job_id": job_id,
                "type": claimed_type,
                "entity_type": entity_type or "image",
                "entity_id": entity_id,
                "image_id": image_id,
                "config": config,
                "retry_count": retry_count,
                "max_retries": max_retries,
                "started_at": started_at,
            }
        finally:
            conn.close()

    @abstractmethod
    def process(self, job: dict[str, Any]) -> dict[str, Any]:
        """Phase 2 : exécute le job. Aucune connexion DB ouverte.
        Retourne un dict avec les résultats (ex. file_path, result, etc.).
        Lève une exception en cas d'échec.
        """

    def save_result(self, job: dict[str, Any], result: dict[str, Any]) -> None:
        """Phase 3 : enregistre le résultat. À surcharger par les workers concrets."""

    def handle_failure(self, job: dict[str, Any], error: Exception) -> None:
        """Gère l'échec : retry avec backoff ou status=failed."""
        job_id = job["job_id"]
        retry_count = job.get("retry_count", 0)
        max_retries = job.get("max_retries", 3)

        conn = self._conn(read_only=False)
        try:
            now = _now()
            if retry_count < max_retries:
                delay_idx = min(retry_count, len(RETRY_DELAYS) - 1)
                delay_sec = RETRY_DELAYS[delay_idx]
                from datetime import timedelta
                scheduled = (datetime.now(timezone.utc) + timedelta(seconds=delay_sec)).strftime("%Y-%m-%dT%H:%M:%SZ")
                conn.execute(
                    """
                    UPDATE job SET status = 'pending', started_at = NULL, worker_id = NULL,
                                   last_heartbeat_at = NULL, retry_count = ?, scheduled_at = ?,
                                   error_message = ?
                    WHERE id = ?
                    """,
                    [retry_count + 1, scheduled, str(error), job_id],
                )
                conn.session.commit()
                logger.info("Job %s échoué, replanifié dans %ds (retry %d/%d)", job_id, delay_sec, retry_count + 1, max_retries)
            else:
                duration_ms = _compute_duration_ms(job)
                conn.execute(
                    """
                    UPDATE job SET status = 'failed', finished_at = ?, error_message = ?,
                                   duration_ms = ?
                    WHERE id = ?
                    """,
                    [now, str(error), duration_ms, job_id],
                )
                conn.session.commit()
                logger.warning("Job %s échoué définitivement après %d retries", job_id, max_retries)
        finally:
            conn.close()

    def run_one(self) -> bool:
        """Traite un job. Retourne True si un job a été traité."""
        self._recover_stale_jobs()

        job = self.fetch_and_start()
        if not job:
            return False

        job_id = job["job_id"]
        logger.info("Traitement job %s (%s)", job_id, job.get("entity_id", ""))

        self._start_heartbeat(job_id)
        try:
            result = self.process(job)
            self._stop_heartbeat()
            self.save_result(job, result)
            logger.info("Job %s terminé", job_id)
            return True
        except Exception as e:
            self._stop_heartbeat()
            logger.exception("Erreur job %s: %s", job_id, e)
            self.handle_failure(job, e)
            return True

    def run_loop(self, once: bool = False, poll_interval: float = 2.0) -> None:
        """Boucle principale."""
        try:
            if once:
                self.run_one()
                return
            while True:
                try:
                    self.run_one()
                except Exception as e:
                    if "being used by another process" in str(e) or "IO Error" in str(e):
                        logger.warning("DB verrouillée, retry dans %ds : %s", int(poll_interval * 3), e)
                        time.sleep(poll_interval * 3)
                    else:
                        logger.exception("Erreur inattendue dans run_one: %s", e)
                time.sleep(poll_interval)
        except KeyboardInterrupt:
            logger.info("Interruption")
