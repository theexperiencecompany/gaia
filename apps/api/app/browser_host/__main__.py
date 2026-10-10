"""Entrypoint: python -m app.browser_host runs the browser-host service."""

from __future__ import annotations

import os
import sys

import uvicorn

from app.browser_host.server import app, host_failed
from app.config.browser_host_settings import browser_host_settings
from shared.py.logging import configure_file_logging

#: The in-line service field every log line carries; must equal the host's
#: Promtail label (its container name), as arq_worker's does for the worker.
BROWSER_HOST_SERVICE_NAME = "browser-host"
#: Where a natively run host writes its rotating and structured log files, beside
#: the API's ./logs and the worker's ./logs/worker. A no-op under LOG_FORMAT=json.
BROWSER_HOST_LOG_DIR = "./logs/browser-host"


def main() -> None:
    """Give this process its own log identity and local log files, then serve the host.

    Exits non-zero when it shut itself down for want of an engine, so a restart policy brings it back.
    """
    os.environ.setdefault("GAIA_SERVICE_NAME", BROWSER_HOST_SERVICE_NAME)
    configure_file_logging(BROWSER_HOST_LOG_DIR)
    uvicorn.run(
        app,
        host=browser_host_settings.BROWSER_HOST_BIND_ADDRESS,
        port=browser_host_settings.BROWSER_HOST_PORT,
        log_config=None,
    )
    if host_failed():
        sys.exit(1)


if __name__ == "__main__":
    main()
