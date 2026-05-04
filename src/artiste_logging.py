"""Configuration centralisée du logging (console + fichier rotatif par composant)."""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_VALID_COMPONENTS = frozenset({"api", "image_worker", "text_worker"})
_DEFAULT_LEVEL: dict[str, int] = {
    "api": logging.DEBUG,
    "image_worker": logging.INFO,
    "text_worker": logging.INFO,
}

_ROTATE_BYTES = 10 * 1024 * 1024
_BACKUP_COUNT = 5

_configured_for: str | None = None


def _parse_log_level(name: str | None, fallback: int) -> int:
    if not name:
        return fallback
    level = logging.getLevelName(name.upper())
    if isinstance(level, int):
        return level
    return fallback


def _log_dir() -> Path:
    override = os.environ.get("ARTISTE_LOG_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return PROJECT_ROOT / "logs"


def _file_logging_enabled() -> bool:
    v = os.environ.get("ARTISTE_LOG_TO_FILE", "").strip().lower()
    if v in ("0", "false", "no", "off"):
        return False
    if "pytest" in sys.modules:
        return False
    return True


def setup_logging(component: str, *, level: int | None = None) -> Path | None:
    """Configure le logger racine : stderr + optionnellement fichier rotatif.

    Returns
    -------
    Path | None
        Chemin du fichier log si activé, sinon None.
    """
    global _configured_for

    if component not in _VALID_COMPONENTS:
        raise ValueError(f"component must be one of {sorted(_VALID_COMPONENTS)}, got {component!r}")

    if _configured_for == component:
        return _log_dir() / f"{component}.log" if _file_logging_enabled() else None

    root = logging.getLogger()
    root.handlers.clear()

    env_level = os.environ.get("ARTISTE_LOG_LEVEL", "").strip()
    default_lvl = _DEFAULT_LEVEL[component]
    resolved = level if level is not None else _parse_log_level(env_level or None, default_lvl)
    root.setLevel(resolved)

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(formatter)
    root.addHandler(sh)

    log_path: Path | None = None
    if _file_logging_enabled():
        log_dir = _log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{component}.log"
        fh = RotatingFileHandler(
            log_path,
            maxBytes=_ROTATE_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        fh.setFormatter(formatter)
        root.addHandler(fh)

    _configured_for = component
    return log_path
