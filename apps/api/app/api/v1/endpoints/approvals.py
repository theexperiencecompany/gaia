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
from app.services.hil.ledger_decide import decide_ledger_batch, decide_ledger_card
from app.services.hil.preferences import (
    get_hil_preferences,
    set_tool_override,
    update_hil_preferences,
)
from shared.py.analytics.catalog.properties import Identifier
from shared.py.wide_events import log

router = APIRouter(prefix="/approvals")


@router.post("/{approval_id}/decision")
async def post_approval_decision(
    approval_id: str,
    payload: ApprovalDecisionRequest,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> ApprovalDecisionResponse:
    """Commit a button decision on the approval ledger, run the approved action and wake its owner.

    A stale or gone row commits nothing and says so, so the client refreshes instead of trusting the tap.
    """
    user_id = user.user_id
    if not user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="user_id is required")
    log.set(user={"id": user_id}, hil={"approval_id": approval_id, "decision": payload.decision})
    outcome = await decide_ledger_card(approval_id, user_id=user_id, tap=payload)
    log.set(hil={"resolved": outcome.committed})
    if outcome.committed:
        return ApprovalDecisionResponse(
            success=True, outcome=outcome.outcome, action=outcome.action
        )
    return ApprovalDecisionResponse(
        success=False,
        reason="stale" if outcome.stale else "not_found",
        outcome=outcome.outcome,
        action=outcome.action,
    )


@router.post("/batch-decision")
async def post_batch_decision(
    payload: BatchApprovalDecisionRequest,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> BatchApprovalDecisionResponse:
    """Decide several pending approvals in one submission (the batch review).

    Each item commits exactly once on the ledger; one already decided or expired never fails the rest.
    """
    user_id = user.user_id
    if not user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="user_id is required")
    log.set(
        user={"id": user_id},
        hil={"operation": "batch_decision", "count": len(payload.decisions)},
    )
    outcomes = await decide_ledger_batch(user_id, payload.decisions)
    log.set(hil={"resolved": sum(1 for o in outcomes if o.resolved)})
    return BatchApprovalDecisionResponse(outcomes=outcomes)


@router.get("/preferences")
async def get_preferences(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> HILPreferencesResponse:
    """Return the current user's HIL approval preferences."""
    log.set(user={"id": user.user_id}, hil={"operation": "get_preferences"})
    prefs = await get_hil_preferences(user.user_id)
    return HILPreferencesResponse(**prefs.model_dump())


@router.put("/preferences")
async def put_preferences(
    payload: UpdateHILPreferencesRequest,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> HILPreferencesResponse:
    """Apply a partial update to the current user's HIL preferences."""
    log.set(user={"id": user.user_id}, hil={"operation": "update_preferences"})
    prefs = await update_hil_preferences(
        user.user_id,
        mode=payload.mode,
        tool_overrides=payload.tool_overrides,
        never_auto_tools=payload.never_auto_tools,
    )
    return HILPreferencesResponse(**prefs.model_dump())


@router.put("/tools/{tool_name}")
async def set_tool_approval(
    tool_name: Identifier,
    payload: SetToolOverrideRequest,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> HILPreferencesResponse:
    """Set (``ask`` true/false) or clear (``ask`` null) one tool's approval override.

    tool_name is the HIL tool key the client was given (an MCP tool's is server-scoped).
    """
    log.set(
        user={"id": user.user_id},
        hil={"operation": "set_tool_override", "tool": tool_name, "ask": payload.ask},
    )
    prefs = await set_tool_override(user.user_id, tool_name, payload.ask)
    return HILPreferencesResponse(**prefs.model_dump())
