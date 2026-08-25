"""HIL approval endpoints: decision relay + per-user preferences."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.models.user_models import AuthenticatedUser
from app.schemas.hil_schemas import (
    ApprovalDecisionRequest,
    ApprovalDecisionResponse,
    BatchApprovalDecisionRequest,
    BatchApprovalDecisionResponse,
    HILPreferencesResponse,
    SetToolOverrideRequest,
    UpdateHILPreferencesRequest,
)
from app.services.hil.preferences import (
    get_hil_preferences,
    set_tool_override,
    update_hil_preferences,
)
from app.services.hil.resolution import resolve_approval, resolve_approvals_batch
from shared.py.wide_events import log

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.post("/{approval_id}/decision")
async def post_approval_decision(
    approval_id: str,
    payload: ApprovalDecisionRequest,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> ApprovalDecisionResponse:
    """Apply a button decision and resume the paused run.

    ``resolve_approval`` raises :class:`ApprovalRequestNotFoundError` (410) or
    :class:`ApprovalRequestForbiddenError` (403) — both ``AppError`` subclasses — so
    late/duplicate or cross-user deliveries can't double-resolve a request.
    """
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="user_id is required")
    log.set(user={"id": user_id}, hil={"approval_id": approval_id, "decision": payload.decision})
    await resolve_approval(
        approval_id=approval_id,
        user_id=user_id,
        kind=payload.decision,
        feedback=payload.feedback,
        scope=payload.scope,
    )
    log.set(hil={"resolved": True})
    return ApprovalDecisionResponse(success=True)


@router.post("/batch-decision")
async def post_batch_decision(
    payload: BatchApprovalDecisionRequest,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> BatchApprovalDecisionResponse:
    """Decide several pending approvals in one submission (the batch review).

    Per-item outcomes: one already-decided or expired approval never fails the
    rest. Only the first resolvable decision dispatches the paused executor; the
    join round it wakes collects the remaining decisions durably.
    """
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="user_id is required")
    log.set(
        user={"id": user_id},
        hil={"operation": "batch_decision", "count": len(payload.decisions)},
    )
    outcomes = await resolve_approvals_batch(
        user_id,
        [(item.approval_id, item.decision, item.feedback) for item in payload.decisions],
    )
    log.set(hil={"resolved": sum(1 for o in outcomes if o.resolved)})
    return BatchApprovalDecisionResponse(outcomes=outcomes)


@router.get("/preferences")
async def get_preferences(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> HILPreferencesResponse:
    """Return the current user's HIL approval preferences."""
    log.set(user={"id": user["user_id"]}, hil={"operation": "get_preferences"})
    prefs = await get_hil_preferences(user["user_id"])
    return HILPreferencesResponse(**prefs.model_dump())


@router.put("/preferences")
async def put_preferences(
    payload: UpdateHILPreferencesRequest,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> HILPreferencesResponse:
    """Apply a partial update to the current user's HIL preferences."""
    log.set(user={"id": user["user_id"]}, hil={"operation": "update_preferences"})
    prefs = await update_hil_preferences(
        user["user_id"],
        mode=payload.mode,
        tool_overrides=payload.tool_overrides,
    )
    return HILPreferencesResponse(**prefs.model_dump())


@router.put("/tools/{tool_name}")
async def set_tool_approval(
    tool_name: str,
    payload: SetToolOverrideRequest,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> HILPreferencesResponse:
    """Set (``ask`` true/false) or clear (``ask`` null) one tool's approval override."""
    log.set(
        user={"id": user["user_id"]},
        hil={"operation": "set_tool_override", "tool": tool_name, "ask": payload.ask},
    )
    prefs = await set_tool_override(user["user_id"], tool_name, payload.ask)
    return HILPreferencesResponse(**prefs.model_dump())
