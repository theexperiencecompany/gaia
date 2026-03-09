"""
Application factory for the GAIA FastAPI application.

This module provides functions to create and configure the FastAPI application.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, UJSONResponse
from fastapi.staticfiles import StaticFiles
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
