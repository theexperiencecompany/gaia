"""HIL approval endpoints: decision relay + per-user preferences."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.schemas.hil_schemas import (
    ApprovalDecisionRequest,
    ApprovalDecisionResponse,
    HILPreferencesResponse,
    UpdateHILPreferencesRequest,
)
from app.services.hil.bridge import relay_approval_decision
from app.services.hil.preferences import get_hil_preferences, update_hil_preferences
from shared.py.wide_events import log

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.post("/{approval_id}/decision")
async def post_approval_decision(
    approval_id: str,
    payload: ApprovalDecisionRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> ApprovalDecisionResponse:
    """Relay a button decision to the awaiting HIL gate.

    ``relay_approval_decision`` raises :class:`ApprovalRequestNotFound` (410) or
    :class:`ApprovalRequestForbidden` (403) — both ``AppError`` subclasses — so
    late/duplicate or cross-user deliveries can't double-resolve a request.
    """
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="user_id is required")
    log.set(user={"id": user_id}, hil={"approval_id": approval_id, "decision": payload.decision})
    await relay_approval_decision(
        approval_id=approval_id,
        user_id=user_id,
        decision=payload.decision,
        feedback=payload.feedback,
        scope=payload.scope,
    )
    log.set(hil={"relayed": True})
    return ApprovalDecisionResponse(success=True)


@router.get("/preferences")
async def get_preferences(
    user: Annotated[dict, Depends(get_current_user)],
) -> HILPreferencesResponse:
    log.set(user={"id": user["user_id"]}, hil={"operation": "get_preferences"})
    prefs = await get_hil_preferences(user["user_id"])
    return HILPreferencesResponse(**prefs.model_dump())


@router.put("/preferences")
async def put_preferences(
    payload: UpdateHILPreferencesRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> HILPreferencesResponse:
    log.set(user={"id": user["user_id"]}, hil={"operation": "update_preferences"})
    prefs = await update_hil_preferences(
        user["user_id"],
        enabled=payload.enabled,
        always_allowed_tools=payload.always_allowed_tools,
    )
    return HILPreferencesResponse(**prefs.model_dump())
