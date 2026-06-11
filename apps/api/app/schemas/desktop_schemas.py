"""Pydantic schemas for the desktop tool bridge."""

from typing import Any

from pydantic import BaseModel, Field


class DesktopToolResultRequest(BaseModel):
    """Result of a desktop-executed action, POSTed back by the Electron app."""

    request_id: str = Field(min_length=1, description="Bridge request this result answers")
    ok: bool = Field(description="Whether the action executed successfully")
    data: dict[str, Any] | None = Field(default=None, description="Tool-specific result payload")
    error: str | None = Field(default=None, description="Human-readable failure reason")


class DesktopToolResultResponse(BaseModel):
    """Acknowledgement that a desktop tool result was relayed."""

    success: bool
