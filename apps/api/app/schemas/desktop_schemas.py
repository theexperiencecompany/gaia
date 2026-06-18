"""Pydantic schemas for the desktop tool bridge."""

from typing import Any

from pydantic import BaseModel, Field, field_validator

# Generous cap (~16 MB of base64) for the screenshot image fields. A 1568px
# long-edge PNG is well under this; the bound only rejects abusive payloads
# before they reach Redis pub/sub and the vision call.
MAX_RESULT_IMAGE_B64_CHARS = 16 * 1024 * 1024
_IMAGE_RESULT_FIELDS = ("image_b64", "thumbnail_b64")


class DesktopToolResultRequest(BaseModel):
    """Result of a desktop-executed action, POSTed back by the Electron app."""

    request_id: str = Field(min_length=1, description="Bridge request this result answers")
    ok: bool = Field(description="Whether the action executed successfully")
    data: dict[str, Any] | None = Field(default=None, description="Tool-specific result payload")
    error: str | None = Field(default=None, description="Human-readable failure reason")

    @field_validator("data")
    @classmethod
    def _bound_image_payload(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        """Reject oversized screenshot blobs before they hit Redis / the LLM."""
        if value:
            for key in _IMAGE_RESULT_FIELDS:
                blob = value.get(key)
                if isinstance(blob, str) and len(blob) > MAX_RESULT_IMAGE_B64_CHARS:
                    raise ValueError(f"'{key}' exceeds the maximum allowed size")
        return value


class DesktopToolResultResponse(BaseModel):
    """Acknowledgement that a desktop tool result was relayed."""

    success: bool
