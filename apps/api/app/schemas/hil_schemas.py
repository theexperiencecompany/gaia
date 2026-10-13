"""Request/response schemas for HIL approval + preference endpoints."""

from typing import Literal

from pydantic import BaseModel, Field

from app.models.hil_models import HILMode, HILPreferences
from app.schemas.common import ResponseModel


class ApprovalDecisionRequest(BaseModel):
    """Body for a button approval decision (approve/deny, with scope and feedback)."""

    decision: Literal["approve", "deny"]
    feedback: str | None = Field(None, max_length=2000)
    # once: this call only. always_tool: also set a "never ask" override for the tool.
    scope: Literal["once", "always_tool"] = "once"
    # Row version the client rendered. Ledger path only: a stale v refreshes
    # instead of overwriting. Omitted (None) skips the check.
    v: int | None = None


class ApprovalDecisionResponse(BaseModel):
    """Result of relaying an approval decision to the awaiting gate."""

    success: bool
    # Ledger path only: why success is False ("stale" — refresh the row from
    # status instead of retrying) and the row's current state. Old path leaves
    # both unset; a committed ledger tap sets status to the decided state.
    reason: str | None = None
    status: str | None = None


class BatchDecisionItem(BaseModel):
    """One approval's decision within a batch."""

    approval_id: str
    decision: Literal["approve", "deny"]
    feedback: str | None = Field(None, max_length=2000)
    # Row version the client rendered; see ApprovalDecisionRequest.v.
    v: int | None = None


class BatchApprovalDecisionRequest(BaseModel):
    """Body for deciding several pending approvals in one submission."""

    decisions: list[BatchDecisionItem] = Field(min_length=1, max_length=25)


class BatchDecisionOutcome(BaseModel):
    """Per-approval outcome of a batch decision."""

    approval_id: str
    resolved: bool
    # Set when resolved is False: "not_found" (already decided/expired),
    # "forbidden", or "not_resumable".
    reason: str | None = None
    # Current ledger state when a ledger item did not commit (stale client
    # refreshes the row instead of retrying blind). Old path leaves it unset.
    status: str | None = None


class BatchApprovalDecisionResponse(BaseModel):
    """Result of a batch decision: each approval's individual outcome."""

    outcomes: list[BatchDecisionOutcome]


class HILPreferencesResponse(ResponseModel, HILPreferences):
    """A user's HIL preferences as returned by the preferences endpoints."""


class UpdateHILPreferencesRequest(BaseModel):
    """Partial update to a user's HIL preferences; omitted fields are left unchanged."""

    mode: HILMode | None = None
    tool_overrides: dict[str, bool] | None = None
    never_auto_tools: list[str] | None = None


class SetToolOverrideRequest(BaseModel):
    """Body for setting or clearing one tool's approval override."""

    # True = always ask, False = never ask, None = clear override (use default).
    ask: bool | None = None
