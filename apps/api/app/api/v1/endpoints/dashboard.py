"""Today view endpoint.

One sectioned payload per fetch — the dashboard is a read-only lens over
records other systems already write (see ``dashboard_service``).
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.api.v1.dependencies.oauth_dependencies import (
    get_current_user,
    get_user_timezone_from_preferences,
)
from app.services.dashboard_service import build_today_payload
from app.services.payments.payment_service import payment_service
from shared.py.wide_events import log

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/today")
async def get_today(
    user: Annotated[dict, Depends(get_current_user)],
    user_timezone: str = Depends(get_user_timezone_from_preferences),
) -> dict[str, Any]:
    """The Today view: headline + five status-grouped todo sections + runs quota."""
    user_id = user["user_id"]
    log.set(user={"id": user_id}, dashboard={"operation": "today"})
    user_plan = await payment_service.get_cached_plan_type(user_id)
    payload = await build_today_payload(user_id, user_timezone, user_plan)
    log.set(dashboard={"needs_you": payload["subline"]["needs_you"]})
    return payload
