"""Request/response schemas for HIL approval + preference endpoints."""

from typing import Literal

from pydantic import BaseModel, Field

from app.models.hil_models import HILMode, HILPreferences


class ApprovalDecisionRequest(BaseModel):
    """Body for a button approval decision (approve/deny, with scope and feedback)."""

    decision: Literal["approve", "deny"]
    feedback: str | None = Field(None, max_length=2000)
    # once: this call only. always_tool: also set a "never ask" override for the tool.
    scope: Literal["once", "always_tool"] = "once"


class ApprovalDecisionResponse(BaseModel):
    """Result of relaying an approval decision to the awaiting gate."""

    success: bool


class HILPreferencesResponse(HILPreferences):
    """A user's HIL preferences as returned by the preferences endpoints."""


class UpdateHILPreferencesRequest(BaseModel):
    """Partial update to a user's HIL preferences; omitted fields are left unchanged."""

    mode: HILMode | None = None
    tool_overrides: dict[str, bool] | None = None


class SetToolOverrideRequest(BaseModel):
    """Body for setting or clearing one tool's approval override."""

    # True = always ask, False = never ask, None = clear override (use default).
    ask: bool | None = None
