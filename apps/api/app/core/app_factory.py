"""
Application factory for the GAIA FastAPI application.

This module provides functions to create and configure the FastAPI application.
"""

import secrets

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import UJSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator

from app.api.v1.endpoints.browser_live_view import router as browser_live_view_router
from app.api.v1.endpoints.dev import router as dev_router
from app.api.v1.endpoints.health import router as health_router
from app.api.v1.routes import router as api_router
from app.config.settings import settings
from app.constants.log_tags import LogTag
from app.core.exception_handlers import register_exception_handlers
from app.core.lifespan import lifespan
from app.core.middleware import configure_middleware
from app.core.openapi import api_operation_id
from app.schemas.errors import ERROR_RESPONSES
from app.services import latency_metrics as _latency_metrics  # noqa: F401 -- side effects

# Eager-import so Prometheus collectors register at startup; otherwise the
# storage layer lazy-imports on first use and /metrics omits fs_op_* metadata
# until the first FS-shaped operation runs.
from app.services.storage import metrics as _fs_metrics  # noqa: F401 -- side effects
from shared.py.wide_events import log as wide_log


def create_app() -> FastAPI:
    """
    Create and configure a FastAPI application instance.

    Returns:
        FastAPI: Configured FastAPI application
    """
    # In production, disable the OpenAPI schema entirely so /openapi.json,
    # /docs, and /redoc all 404 — no endpoint listing or model shapes leak.
    is_prod = settings.ENV == "production"
    app = FastAPI(
        lifespan=lifespan,
        title="GAIA API",
        description="Backend for General-purpose AI assistant (GAIA)",
        contact={
            "name": "The Experience Company",
            "url": "http://heygaia.io",
            "email": "hi@heygaia.io",
        },
        openapi_url=None if is_prod else "/openapi.json",
        docs_url=None if is_prod else "/docs",
        redoc_url=None if is_prod else "/redoc",
        default_response_class=UJSONResponse,
        generate_unique_id_function=api_operation_id,
    )

    configure_middleware(app)

    # Default buckets (0.1, 0.5, 1) capped p95 at 1.0s, so Grafana's >1s/>3s
    # latency alerts never fired; these straddle both thresholds. LoggingMiddleware
    # already skips /metrics, so exposing it here won't pollute request logs.
    instrumentator = Instrumentator().instrument(
        app, latency_lowr_buckets=(0.1, 0.25, 0.5, 1, 2.5, 5, 10)
    )
    if settings.METRICS_TOKEN:
        _bearer = HTTPBearer(auto_error=True)

        def _verify_metrics_token(
            credentials: HTTPAuthorizationCredentials = Depends(_bearer),
        ) -> None:
            if not secrets.compare_digest(credentials.credentials, settings.METRICS_TOKEN):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

        instrumentator.expose(
            app, include_in_schema=False, dependencies=[Depends(_verify_metrics_token)]
        )
    # No token configured — only expose in non-production environments.
    elif settings.ENV != "production":
        instrumentator.expose(app, include_in_schema=False)

    register_exception_handlers(app)

    app.include_router(api_router, prefix="/api/v1", responses=ERROR_RESPONSES)
    app.include_router(health_router, responses=ERROR_RESPONSES)
    # Root-mounted on purpose: these are the links a user is handed, fronted by a
    # friendly vhost that proxies here, so they carry no /api/v1 prefix. Each one
    # authenticates itself with the capability in its own URL.
    app.include_router(browser_live_view_router, responses=ERROR_RESPONSES)

    # Dev-only identity + seeding router. Mounted only when the auth bypass is
    # active in development, so it never exists in production (every route 404s).
    if settings.ENV == "development" and settings.DEV_AUTH_BYPASS_EMAIL:
        app.include_router(dev_router, prefix="/api/v1", responses=ERROR_RESPONSES)
        wide_log.warning(
            f"{LogTag.STARTUP} Dev identity router mounted at /api/v1/dev "
            "(development only — mint/seed/delete users)"
        )

    app.mount("/static", StaticFiles(directory="app/static"), name="static")

    return app
