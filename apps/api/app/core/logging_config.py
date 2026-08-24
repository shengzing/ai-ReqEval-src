"""Console logging configuration.

Centralizes the format and level for the API backend's console output so
every logger (uvicorn, the app, pymongo, langchain, …) emits a consistent
``时间 级别 模块 位置: 消息`` line instead of the divergent defaults
(uvicorn's flat "INFO:     text", app loggers with no handler, library
loggers spamming at WARNING).

Call :func:`configure_logging` once at startup (see ``main.create_app``).
Level is ``LOG_LEVEL`` (default INFO); ``LOG_LEVEL=DEBUG`` enables debug
output for the app's own loggers while keeping noisy libraries at WARNING.
"""

from __future__ import annotations

import logging
import logging.config
import os
from typing import Any

# App loggers whose DEBUG output is meaningful (route handlers, services,
# harness). Keep this list curated — blanket DEBUG on every app module
# dumps harness step-level noise.
_APP_LOGGERS = ("src.apps.api", "api", "app")

# Third-party loggers that are noisy at INFO/DEBUG. Clamp to WARNING unless
# LOG_LEVEL=DEBUG_FOR_LIBS is set (mostly for diagnosing driver/parsing
# issues). pymongo at INFO emits a connection line per op otherwise.
_LIBRARY_LOGGERS = (
    "pymongo",
    "pymongo.command",
    "httpx",
    "httpcore",
    "openai",
    "anthropic",
    "urllib3",
    "filelock",
    "watchfiles.main",
)

# Format pieces:
#   2026-08-14 21:03:12,340  INFO  src.apps.api.app.services.project_service
#       create_file:1075  upload ok file-xxx parsed
# Module name + function:line lets you jump straight to the emit site —
# the "position" the user asked for.
_CONSOLE_FORMAT = (
    "%(asctime)s  %(levelname)-5s  %(name)s  %(funcName)s:%(lineno)s  %(message)s"
)
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def _resolve_level() -> int:
    raw = (os.getenv("LOG_LEVEL") or "INFO").strip().upper()
    if raw in {"1", "TRUE", "YES", "ON"}:
        raw = "DEBUG"
    return getattr(logging, raw, logging.INFO) if hasattr(logging, raw) else logging.INFO


def _library_level(app_level: int) -> int:
    # Clamp noisy libraries to WARNING unless the operator explicitly opts
    # into library debug noise.
    if app_level <= logging.DEBUG and os.getenv("LOG_LEVEL_LIBS", "").strip().lower() in {"debug", "1", "true", "yes", "on"}:
        return logging.DEBUG
    return logging.WARNING


def configure_logging() -> None:
    """Configure root + app + library loggers for console output.

    Idempotent: calling twice just re-applies the same config (handlers
    are replaced, not duplicated).
    """
    app_level = _resolve_level()
    lib_level = _library_level(app_level)

    config: dict[str, Any] = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "console": {
                "format": _CONSOLE_FORMAT,
                "datefmt": _DATE_FORMAT,
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "console",
                "stream": "ext://sys.stderr",
                "level": "DEBUG",  # handler allows everything; loggers gate it
            },
        },
        "root": {
            "level": "WARNING",  # third-party default; refined per-logger below
            "handlers": ["console"],
        },
        "loggers": {},
    }

    # App loggers follow the resolved level so DEBUG surfaces them.
    for name in _APP_LOGGERS:
        config["loggers"][name] = {"level": app_level, "propagate": True, "handlers": []}
    # uvicorn's own loggers (access + errors) — keep their events, just
    # reformat them through the same console formatter.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        config["loggers"][name] = {"level": app_level, "propagate": False, "handlers": ["console"]}
    # Noisy libraries clamped.
    for name in _LIBRARY_LOGGERS:
        config["loggers"][name] = {"level": lib_level, "propagate": True, "handlers": []}

    logging.config.dictConfig(config)
    # Make sure the root actually has our handler attached even if a prior
    # basicConfig ran (e.g. a library called it at import time).
    root = logging.getLogger()
    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_CONSOLE_FORMAT, _DATE_FORMAT))
        root.addHandler(handler)
