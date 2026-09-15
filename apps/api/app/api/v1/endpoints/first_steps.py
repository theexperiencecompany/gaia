from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.models.first_steps_models import FirstStepsCollapseRequest, FirstStepsResponse
from app.models.user_models import AuthenticatedUser
from app.services.first_steps_service import get_first_steps, set_first_steps_collapsed
from shared.py.wide_events import log

router = APIRouter(prefix="/user/first-steps", tags=["First Steps"])


@router.get("")
async def read_first_steps(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> FirstStepsResponse:
    """The activation checklist; every ``done`` is derived server-side."""
    log.set(user={"id": user["user_id"]}, first_steps={"operation": "read"})
    checklist = await get_first_steps(user["user_id"])
    log.set_ns(
        "first_steps",
        done=sum(step.done for step in checklist.steps),
        collapsed=checklist.collapsed,
    )
    return checklist


@router.post("/collapse")
async def collapse(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    body: FirstStepsCollapseRequest,
) -> FirstStepsResponse:
    """Collapse the checklist to its header, or expand it again. Idempotent."""
    log.set(user={"id": user["user_id"]}, first_steps={"operation": "collapse"})
    checklist = await set_first_steps_collapsed(user["user_id"], body.collapsed)
    log.set_ns(
        "first_steps",
        done=sum(step.done for step in checklist.steps),
        collapsed=checklist.collapsed,
    )
    return checklist
