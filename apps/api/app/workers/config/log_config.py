"""Logging config handed to arq's CLI via ``--custom-log-dict``.

arq's CLI runs ``logging.config.dictConfig`` *after* importing ``WorkerSettings``,
so whatever ``configure_loguru()`` set up for the ``arq`` logger at import time is
overwritten — arq re-attaches its own stderr ``StreamHandler`` and leaves
propagation on. Every arq line is then emitted twice: once as plaintext on stderr
and once as JSON through the root interceptor. Loki's ``| json`` drops the
plaintext copies and double-counts the rest, and the plaintext copy is written
straight to the descriptor, outside the structured sink's size cap.
``basicConfig(force=True)`` cannot prevent it: that only clears *root* handlers.

Passing this dict instead leaves arq's logger with no handlers of its own and
propagation on, so its records reach the root interceptor installed by
``configure_loguru()`` and come out as ordinary structured events — the same
treatment ``_route_through_root`` gives uvicorn.

Every command that launches the worker must pass it::

    arq app.worker.WorkerSettings \\
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
            # arq describes our own process (job start/finish/retry, worker
            # lifecycle), so it belongs on LOG_LEVEL like the other framework
            # namespaces configure_loguru() owns — not on the third-party floor
            # the root logger sits at, which would swallow every one of its
            # INFO lines the moment its own handler is removed.
            "level": LOG_CONFIG["level"],
        }
    },
}
