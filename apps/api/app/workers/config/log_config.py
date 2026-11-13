"""Logging config handed to arq's CLI via --custom-log-dict.

arq's CLI runs dictConfig AFTER importing WorkerSettings, undoing
configure_loguru(): it re-attaches its own stderr handler with propagation
on, so every line emits twice (plaintext + JSON) — Loki's | json drops the
plaintext copies and double-counts the rest. basicConfig(force=True) can't
fix this; it only clears root handlers.

This dict leaves arq's logger with no handlers and propagation on, so its
records reach the root interceptor and come out as ordinary structured
events, like _route_through_root does for uvicorn.

Every launch command must pass it: arq app.worker.WorkerSettings
--custom-log-dict app.workers.config.log_config.ARQ_LOG_CONFIG
"""

from typing import Any

from shared.py.logging import LOG_CONFIG

ARQ_LOG_CONFIG: dict[str, Any] = {
    "version": 1,
    # The root interceptor and every already-configured GAIA logger must survive
    # this dictConfig call; disabling them would silence the whole process.
    "disable_existing_loggers": False,
    "loggers": {
        "arq": {
            "handlers": [],
            "propagate": True,
            # arq describes our own process, so it belongs on LOG_LEVEL like other
            # framework namespaces configure_loguru() owns — not the third-party
            # floor the root logger sits at, which would swallow its INFO lines.
            "level": LOG_CONFIG["level"],
        }
    },
}
