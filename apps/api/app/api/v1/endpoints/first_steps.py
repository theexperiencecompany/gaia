"""Activation checklist endpoints backing the first-steps widget."""

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.services import first_steps_service
from shared.py.wide_events import log

router = APIRouter(prefix="/users/me/first-steps", tags=["First Steps"])


@router.get("")
async def get_first_steps(user: Annotated[dict, Depends(get_current_user)]) -> dict[str, Any]:
    log.set(user={"id": user["user_id"]}, operation="first_steps_get")
    return await first_steps_service.get_steps(user["user_id"])


@router.patch("")
async def mark_first_step(
    user: Annotated[dict, Depends(get_current_user)],
    step: str = Body(embed=True),
) -> dict[str, Any]:
    log.set(user={"id": user["user_id"]}, operation="first_steps_mark", first_step=step)
    await first_steps_service.mark_step(user["user_id"], step)
    return await first_steps_service.get_steps(user["user_id"])


@router.patch("/hide")
async def hide_first_step(
    user: Annotated[dict, Depends(get_current_user)],
    step: str = Body(embed=True),
) -> dict[str, Any]:
    log.set(user={"id": user["user_id"]}, operation="first_steps_hide", first_step=step)
    await first_steps_service.hide_step(user["user_id"], step)
    return await first_steps_service.get_steps(user["user_id"])
