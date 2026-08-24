"""
Health check routes for the GAIA FastAPI application.

This module provides routes for checking the health and status of the API.
"""

import asyncio
import time
from typing import Any

from fastapi import APIRouter, Response
from fastapi.responses import FileResponse

from app.models.health_models import DegradedHealthResponse, HealthResponse
from app.utils.general_utils import get_project_info

router = APIRouter()

EVENT_LOOP_LAG_THRESHOLD_MS = 2000  # 2 seconds


async def measure_event_loop_lag() -> float:
    """Measure event loop responsiveness in milliseconds."""
    start = time.monotonic()
    await asyncio.sleep(0)  # Yield to event loop and come back
    return (time.monotonic() - start) * 1000


# Typed as FastAPI declares the `responses=` parameter — the open dict[str, Any]
# is its own contract (an entry may carry description/headers/content too), not
# a loose annotation of ours.
_DEGRADED_RESPONSE_SCHEMA: dict[int | str, dict[str, Any]] = {
    503: {"model": DegradedHealthResponse}
}


@router.get("/", responses=_DEGRADED_RESPONSE_SCHEMA)
@router.get("/ping", responses=_DEGRADED_RESPONSE_SCHEMA)
@router.get("/health", responses=_DEGRADED_RESPONSE_SCHEMA)
@router.get("/api/v1/", responses=_DEGRADED_RESPONSE_SCHEMA)
@router.get("/api/v1/ping", responses=_DEGRADED_RESPONSE_SCHEMA)
async def health_check(response: Response) -> HealthResponse | DegradedHealthResponse:
    """Report API liveness, build identity, and current event-loop responsiveness."""
    from app.config.settings import (  # noqa: PLC0415 -- importing this module must not pay settings init; the cost moves to first request
        settings,
    )

    lag_ms = await measure_event_loop_lag()
    if lag_ms > EVENT_LOOP_LAG_THRESHOLD_MS:
        # The 503 body is a different model than the 200 body, so the return type
        # is a union and the status is set on the injected response rather than by
        # handing back a JSONResponse — that would skip validation of both shapes.
        response.status_code = 503
        return DegradedHealthResponse(
            event_loop_lag_ms=round(lag_ms, 2),
            detail="Event loop is severely lagged",
        )

    project_info = get_project_info()

    return HealthResponse(
        message="Welcome to the GAIA API!",
        name=project_info["name"],
        version=project_info["version"],
        description=project_info["description"],
        environment=settings.ENV,
        event_loop_lag_ms=round(lag_ms, 2),
    )


@router.get("/favicon.ico", include_in_schema=False)
async def favicon() -> FileResponse:
    """
    Serve favicon.ico file.

    Returns:
        FileResponse: Favicon file
    """
    return FileResponse("app/static/favicon.ico")
