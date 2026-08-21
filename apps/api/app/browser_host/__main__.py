"""Entrypoint: ``python -m app.browser_host`` runs the browser-host service."""

from __future__ import annotations

import uvicorn

from app.browser_host.server import app
from app.config.settings import settings

if __name__ == "__main__":
    # Binds all interfaces by design: the host runs in its own container on the
    # internal overlay network and its port is never published to the outside.
    uvicorn.run(  # NOSONAR python:S8392 — see BROWSER_HOST_BIND's own noqa/nosec
        app,
        host=settings.BROWSER_HOST_BIND,
        port=settings.BROWSER_HOST_PORT,
        log_config=None,
    )
