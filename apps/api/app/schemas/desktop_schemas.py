"""Pydantic schemas for the desktop tool bridge."""

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

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

    @model_validator(mode="after")
    def _enforce_result_contract(self) -> "DesktopToolResultRequest":
        """Reject internally-inconsistent payloads without ever dropping a result.

        A success must not carry an error, and a failure must not carry data.
        We deliberately do NOT require a non-empty ``error`` on failure: the
        bridge guarantees a tool result always reaches the awaiting tool, so a
        failure with an empty message is relayed, not rejected into a timeout.
        """
        if self.ok and self.error:
            raise ValueError("'error' must be omitted when ok is true")
        if not self.ok and self.data is not None:
            raise ValueError("'data' must be omitted when ok is false")
        return self


class DesktopToolResultResponse(BaseModel):
    """Acknowledgement that a desktop tool result was relayed."""

    success: bool


class DesktopReleaseAsset(BaseModel):
    """One downloadable binary attached to a desktop release."""

    name: str = Field(description="Asset filename, e.g. GAIA-x64.exe")
    download_url: str = Field(description="Direct browser download URL for the asset")
    size: int = Field(description="Asset size in bytes")
    content_type: str | None = Field(
        default=None, description="Asset MIME type as reported by GitHub"
    )


class DesktopReleaseResponse(BaseModel):
    """Latest published desktop (Electron) release and its per-platform binaries."""

    tag: str = Field(description="Release tag, e.g. desktop-v0.3.0")
    name: str | None = Field(default=None, description="Human-readable release name")
    html_url: str = Field(description="GitHub release page URL")
    published_at: str | None = Field(default=None, description="ISO 8601 publish timestamp")
    assets: list[DesktopReleaseAsset] = Field(
        description="Downloadable binaries for every platform/arch in this release"
    )
