"""
Application factory for the GAIA FastAPI application.

This module provides functions to create and configure the FastAPI application.
"""

import secrets
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.exception_handlers import (
    http_exception_handler as default_http_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, UJSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.endpoints.dev import router as dev_router
from app.api.v1.endpoints.health import router as health_router
from app.api.v1.routes import router as api_router
from app.config.settings import settings
from app.constants.log_tags import LogTag
from app.core.lifespan import lifespan
from app.core.middleware import configure_middleware

# Eager-import the FsOps metrics module so its Prometheus collectors register
# on the default registry at app startup. Without this the storage layer is
# lazy-imported on first use, and /metrics omits the fs_op_* metadata lines
# until the first FS-shaped operation runs.
from app.services.storage import metrics as _fs_metrics  # noqa: F401
from app.utils.errors import AppError
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
    )

    configure_middleware(app)

    # Expose /metrics for Prometheus scraping.
    # In production, guard with a bearer token so /metrics is not publicly readable.
    # The LoggingMiddleware already skips /metrics so it won't pollute request logs.
    # `latency_lowr_buckets` defaults to (0.1, 0.5, 1), and histogram_quantile
    # cannot return a value above the highest finite bucket — so p95 was capped
    # at 1.0s and the Grafana latency alerts (>1s warning, >3s critical) could
    # never fire. These buckets straddle both thresholds so the alerts work and
    # the latency panels stop flat-lining at 1s.
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

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        """Convert AppError into a structured JSON response with wide event context.

        Emits an explicit error log so the wide-event final_level flips to ERROR
        and downstream LogQL filters (e.g. `errors!="[]"`, `level="ERROR"`) catch
        it. Without this the AppError only showed up in Sentry and was invisible
        to Loki searches that look for application errors by level.
        """
        wide_log.error(
            "app_error",
            error=exc.to_dict(),
            status_code=exc.status_code,
            path=request.url.path,
            method=request.method,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.to_dict(),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Log validation errors with field-level detail and return 422."""
        errors = [
            {"loc": list(err["loc"]), "msg": err["msg"], "type": err["type"]}
            for err in exc.errors()
        ]
        wide_log.warning(
            "validation_failed",
            validation_errors=errors,
            error_count=len(errors),
        )
        return JSONResponse(
            status_code=422,
            content={"detail": errors},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> Response:
        """Record the failure on the wide event, then defer the response to FastAPI.

        Starlette's ExceptionMiddleware converts an HTTPException into a
        response INSIDE call_next, so LoggingMiddleware's except path never
        sees it: every `raise HTTPException(500, ...)` emitted a wide event
        whose `errors` key was absent entirely. The status said 500 but the
        event carried no record of what failed, and the exception the handler
        had caught was nowhere in the telemetry.

        The response is delegated verbatim rather than rebuilt because the
        default handler is what preserves `exc.headers` (WWW-Authenticate on
        401, Retry-After on 429) and drops the body for statuses that may not
        carry one (204/304) — recording a failure must not change what the API
        returns.
        """
        failure: dict[str, Any] = {
            "status_code": exc.status_code,
            "detail": exc.detail,
            "path": request.url.path,
            "method": request.method,
        }
        # Only an explicit `raise ... from e` counts: __context__ is set by any
        # exception raised inside an except block and is usually unrelated.
        cause = exc.__cause__
        if cause is not None:
            failure["error_type"] = type(cause).__name__
            failure["error"] = str(cause)

        # Mirrors the status -> level mapping the logging middleware applies.
        record = wide_log.error if exc.status_code >= 500 else wide_log.warning
        record("http_exception", **failure)

        return await default_http_exception_handler(request, exc)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Return the generic 500 body for exceptions that escaped everything.

        No logging here on purpose: this handler runs in ServerErrorMiddleware,
        OUTSIDE the LoggingMiddleware boundary, so wide-event calls would land
        on an orphan state — and the boundary's own except path has already
        recorded the exception and emitted the http_request line by the time
        this runs.
        """
        return JSONResponse(
            status_code=500,
            content={"error": "internal_server_error"},
        )

    app.include_router(api_router, prefix="/api/v1")
    app.include_router(health_router)

    # Dev-only identity + seeding router. Mounted only when the auth bypass is
    # active in development, so it never exists in production (every route 404s).
    if settings.ENV == "development" and settings.DEV_AUTH_BYPASS_EMAIL:
        app.include_router(dev_router, prefix="/api/v1")
        wide_log.warning(
            f"{LogTag.STARTUP} Dev identity router mounted at /api/v1/dev "
            "(development only — mint/seed/delete users)"
        )

    app.mount("/static", StaticFiles(directory="app/static"), name="static")

    return app
