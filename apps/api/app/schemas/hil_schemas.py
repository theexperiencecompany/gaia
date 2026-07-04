"""Request/response schemas for HIL approval + preference endpoints."""

from typing import Literal

from pydantic import BaseModel, Field

from app.models.hil_models import HILPreferences


class ApprovalDecisionRequest(BaseModel):
    decision: Literal["approve", "deny"]
    feedback: str | None = Field(None, max_length=2000)
    # once: this call only. always_tool: also set a "never ask" override for the tool.
    scope: Literal["once", "always_tool"] = "once"


class ApprovalDecisionResponse(BaseModel):
    success: bool


class HILPreferencesResponse(HILPreferences):
    pass


class UpdateHILPreferencesRequest(BaseModel):
    enabled: bool | None = None
    tool_overrides: dict[str, bool] | None = None


class SetToolOverrideRequest(BaseModel):
    # True = always ask, False = never ask, None = clear override (use default).
    ask: bool | None = None
