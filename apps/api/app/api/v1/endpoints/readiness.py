"""Readiness route: liveness lives in health.py, which must stay import-light."""

from fastapi import APIRouter, Response

from app.models.health_models import ReadinessResponse
from app.services.readiness import check_readiness
from shared.py.wide_events import log

router = APIRouter(tags=["Health"])


@router.get("/health/ready", responses={503: {"model": ReadinessResponse}})
async def readiness_check(response: Response) -> ReadinessResponse:
    """Report whether every backing service answers a real request; 503 names the ones that do not."""
    readiness = await check_readiness()
    log.set(
        readiness={
            "status": readiness.status,
            "failed": [d.name for d in readiness.dependencies if not d.ok],
        }
    )
    if readiness.status == "not_ready":
        response.status_code = 503
    return readiness
