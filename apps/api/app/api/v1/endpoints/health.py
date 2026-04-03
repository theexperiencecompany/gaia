"""
Health check routes for the GAIA FastAPI application.

This module provides routes for checking the health and status of the API.
"""

import asyncio
import time

from app.utils.general_utils import get_project_info
from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse

router = APIRouter()

EVENT_LOOP_LAG_THRESHOLD_MS = 2000  # 2 seconds


async def measure_event_loop_lag() -> float:
    """Measure event loop responsiveness in milliseconds."""
    start = time.monotonic()
    await asyncio.sleep(0)  # Yield to event loop and come back
    return (time.monotonic() - start) * 1000


@router.get("/")
@router.get("/ping")
@router.get("/health")
@router.get("/api/v1/")
@router.get("/api/v1/ping")
async def health_check() -> JSONResponse:
    """
    Health check endpoint for the API.

    Returns:
        JSONResponse: Status information about the API
    """
    # Lazy import to avoid loading settings during module import
    from app.config.settings import settings

    lag_ms = await measure_event_loop_lag()
    if lag_ms > EVENT_LOOP_LAG_THRESHOLD_MS:
        return JSONResponse(
            status_code=503,
            content={
                "status": "degraded",
                "event_loop_lag_ms": round(lag_ms, 2),
                "detail": "Event loop is severely lagged",
            },
        )

    project_info = get_project_info()

    return JSONResponse(
        content={
            "status": "online",
            "message": "Welcome to the GAIA API!",
            "name": project_info["name"],
            "version": project_info["version"],
            "description": project_info["description"],
            "environment": settings.ENV,
            "event_loop_lag_ms": round(lag_ms, 2),
        }
    )


@router.get("/favicon.ico", include_in_schema=False)
async def favicon() -> FileResponse:
    """
    Serve favicon.ico file.

    Returns:
        FileResponse: Favicon file
    """
    return FileResponse("app/static/favicon.ico")
