"""
Application factory for the GAIA FastAPI application.

This module provides functions to create and configure the FastAPI application.
"""

import secrets
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, UJSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from fastapi.utils import is_body_allowed_for_status_code
from prometheus_fastapi_instrumentator import Instrumentator
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.endpoints.dev import router as dev_router
from app.api.v1.endpoints.health import router as health_router
from app.api.v1.middleware.auth import get_current_user
from app.api.v1.routes import router as api_router
from app.config.posthog import POSTHOG_PROVIDER_KEY
from app.config.settings import settings
from app.constants.log_tags import LogTag
from app.core.lazy_loader import providers
from app.core.lifespan import lifespan
from app.core.middleware import configure_middleware
from app.core.openapi import api_operation_id
from app.schemas.errors import (
    ERROR_RESPONSES,
    ErrorEnvelope,
    ValidationIssue,
    error_response,
)
from app.services import latency_metrics as _latency_metrics  # noqa: F401 -- side effects

# Eager-import so Prometheus collectors register at startup; otherwise the
# storage layer lazy-imports on first use and /metrics omits fs_op_* metadata
# until the first FS-shaped operation runs.
from app.services.storage import metrics as _fs_metrics  # noqa: F401 -- side effects
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

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        """Convert AppError into a structured JSON response with wide event context.

        Emits an explicit error log so the wide-event final_level flips to ERROR
        and downstream LogQL filters (e.g. errors!="[]", level="ERROR") catch
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
        return error_response(exc.status_code, ErrorEnvelope.from_app_error(exc))

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request,  # noqa: ARG001 -- Starlette calls exception handlers as handler(conn, exc)
        exc: RequestValidationError,
    ) -> JSONResponse:
        """Log validation errors with field-level detail and return 422."""
        # Each entry is pydantic's ErrorDetails dict; the undeclared keys
        # (input, ctx, url) are ignored by the model.
        errors = [ValidationIssue.model_validate(err) for err in exc.errors()]
        wide_log.warning(
            "validation_failed",
            validation_errors=[issue.model_dump() for issue in errors],
            error_count=len(errors),
        )
        return error_response(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorEnvelope(
                message="Request validation failed", code="validation_error", errors=errors
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> Response:
        """Record the failure on the wide event, then render it as the envelope.

        Starlette's ExceptionMiddleware converts HTTPException into a response
        inside call_next, so LoggingMiddleware's except path never sees it —
        without this, every HTTPException(500) wide event had no errors[] entry.
        Preserves exc.headers and drops the body for statuses that forbid one (204/304).
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

        if not is_body_allowed_for_status_code(exc.status_code):
            return Response(status_code=exc.status_code, headers=exc.headers)
        return error_response(
            exc.status_code, ErrorEnvelope.from_http_exception(exc), headers=exc.headers
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Capture uncaught exceptions and return the generic 500 body.

        No wide-event logging happens here: this handler runs in
        ServerErrorMiddleware, outside the LoggingMiddleware boundary, so those
        calls would land on an orphan state. The shared PostHog client is
        initialized during lifespan startup and records the exception centrally.
        """
        # Guard like PostHogRequestContextMiddleware: without the production lifespan
        # (tests, scripts) the provider is never registered, so providers.get raises
        # KeyError, turning this 500-handler's JSON body into a bare Starlette 500.
        posthog_client = (
            providers.get(POSTHOG_PROVIDER_KEY)
            if providers.is_available(POSTHOG_PROVIDER_KEY)
            else None
        )
        if posthog_client is not None:
            # Attribute explicitly: PostHogRequestContextMiddleware's identify context
            # unwinds before an exception reaches this handler in ServerErrorMiddleware,
            # so every 500 would otherwise land on an anonymous profile.
            user = get_current_user(request)
            if user is not None and user.user_id:
                posthog_client.capture_exception(exc, distinct_id=user.user_id)
            else:
                posthog_client.capture_exception(exc)

        return error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            ErrorEnvelope(message="Internal server error", code="internal_server_error"),
        )

    app.include_router(api_router, prefix="/api/v1", responses=ERROR_RESPONSES)
    app.include_router(health_router, responses=ERROR_RESPONSES)

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
