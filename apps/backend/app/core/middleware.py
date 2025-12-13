"""
Middleware configuration for the GAIA FastAPI application.

This module provides functions to configure middleware for the FastAPI application.
"""

from app.config.settings import settings
from app.api.v1.middleware import (
    LoggingMiddleware,
    ProfilingMiddleware,
    WorkOSAuthMiddleware,
)
from app.api.v1.middleware.rate_limiter import limiter
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from workos import AsyncWorkOSClient


async def rate_limit_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle rate limit exceeded exceptions."""
    return JSONResponse(
        status_code=429,
        content={
            "error": "rate_limit_exceeded",
            "detail": str(exc),
            "retry_after": getattr(exc, "retry_after", None),
        },
    )


def configure_middleware(app: FastAPI) -> None:
    """
    Configure middleware for the FastAPI application.

    Args:
        app (FastAPI): FastAPI application instance
    """

    # Attach limiter to app state
    app.state.limiter = limiter

    # Exception handler for rate limiting
    app.add_exception_handler(RateLimitExceeded, rate_limit_handler)

    # Add rate limiting middleware
    app.add_middleware(SlowAPIMiddleware)

    # Add pyinstrument profiling middleware for detailed call stack analysis
    app.add_middleware(ProfilingMiddleware)

    # Add logging middleware
    app.add_middleware(LoggingMiddleware)

    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_allowed_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        allow_headers=["*"],
    )

    # Add WorkOS authentication middleware
    workos_client = AsyncWorkOSClient(
        api_key=settings.WORKOS_API_KEY, client_id=settings.WORKOS_CLIENT_ID
    )
    app.add_middleware(WorkOSAuthMiddleware, workos_client=workos_client)


def get_allowed_origins() -> list[str]:
    """
    Get allowed origins for CORS based on environment.

    Returns:
        list[str]: List of allowed origins
    """
    # Always include configured frontend URL
    allowed_origins = [settings.FRONTEND_URL]

    # Add additional origins based on environment
    if settings.ENV == "production":
        # Only allow trusted HTTPS origins in production
        allowed_origins.extend(
            [
                "https://heygaia.io",
                "https://heygaia.app",
            ]
        )
    else:
        # Allow development origins
        allowed_origins.extend(
            [
                "http://localhost:5173",
                "https://localhost:5173",
                "http://localhost:3000",
                "http://192.168.138.215:5173",
                "https://192.168.13.215:5173",
            ]
        )

    return allowed_origins
