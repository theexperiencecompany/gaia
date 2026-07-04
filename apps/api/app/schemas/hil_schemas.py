"""Request/response schemas for HIL approval + preference endpoints."""

from typing import Literal

from pydantic import BaseModel, Field

from app.models.hil_models import HILPreferences


class ApprovalDecisionRequest(BaseModel):
    decision: Literal["approve", "deny"]
    feedback: str | None = Field(None, max_length=2000)
    # once: this call only. always_tool: also persist to always_allowed_tools.
    scope: Literal["once", "always_tool"] = "once"


class ApprovalDecisionResponse(BaseModel):
    success: bool


class HILPreferencesResponse(HILPreferences):
    pass


class UpdateHILPreferencesRequest(BaseModel):
    enabled: bool | None = None
    always_allowed_tools: list[str] | None = None
