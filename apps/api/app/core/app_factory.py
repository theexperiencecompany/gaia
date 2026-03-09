"""
Application factory for the GAIA FastAPI application.

This module provides functions to create and configure the FastAPI application.
"""

import secrets

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse, UJSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator
from shared.py.wide_events import log as wide_log

from app.api.v1.endpoints.health import router as health_router
from app.api.v1.routes import router as api_router
from app.config.settings import settings
from app.core.lifespan import lifespan
from app.core.middleware import configure_middleware
from app.utils.errors import AppError


def create_app() -> FastAPI:
    """
    Create and configure a FastAPI application instance.

    Returns:
        FastAPI: Configured FastAPI application
    """
    app = FastAPI(
        lifespan=lifespan,
        title="GAIA API",
        description="Backend for General-purpose AI assistant (GAIA)",
        contact={
            "name": "The Experience Company",
            "url": "http://heygaia.io",
            "email": "hi@heygaia.io",
        },
        docs_url=None if settings.ENV == "production" else "/docs",
        redoc_url=None if settings.ENV == "production" else "/redoc",
        default_response_class=UJSONResponse,
    )

    configure_middleware(app)

    # Expose /metrics for Prometheus scraping.
    # In production, guard with a bearer token so /metrics is not publicly readable.
    # The LoggingMiddleware already skips /metrics so it won't pollute request logs.
    instrumentator = Instrumentator().instrument(app)
    if settings.METRICS_TOKEN:
        _bearer = HTTPBearer(auto_error=True)

        def _verify_metrics_token(
            credentials: HTTPAuthorizationCredentials = Depends(_bearer),
        ) -> None:
            if not secrets.compare_digest(
                credentials.credentials, settings.METRICS_TOKEN
            ):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

        instrumentator.expose(
            app, include_in_schema=False, dependencies=[Depends(_verify_metrics_token)]
        )
    else:
        # No token configured — only expose in non-production environments.
        if settings.ENV != "production":
            instrumentator.expose(app, include_in_schema=False)

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        """Convert AppError into a structured JSON response with wide event context."""
        wide_log.set(error=exc.to_dict())
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.to_dict(),
        )

    app.include_router(api_router, prefix="/api/v1")
    app.include_router(health_router)

    app.mount("/static", StaticFiles(directory="app/static"), name="static")

    return app
