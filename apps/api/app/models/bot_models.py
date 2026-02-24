"""Bot Models

Pydantic models for bot chat, sessions, and related operations.
"""

from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.services.platform_link_service import Platform


class BotChatRequest(BaseModel):
    """Request model for bot chat messages."""

    message: str = Field(
        ..., description="User's message text", min_length=1, max_length=32768
    )
    platform: str = Field(..., description="Platform name (discord, slack, etc.)")
    platform_user_id: str = Field(
        ..., description="User's ID on the platform", min_length=1
    )
    channel_id: Optional[str] = Field(
        None, description="Channel/group ID (None for DM)"
    )

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, v: str) -> str:
        if not Platform.is_valid(v):
            raise ValueError(f"Invalid platform '{v}'")
        return v


class BotAuthStatusResponse(BaseModel):
    """Response model for bot authentication status check."""

    authenticated: bool = Field(..., description="Whether user is linked to GAIA")
    platform: str = Field(..., description="Platform name")
    platform_user_id: str = Field(..., description="User's platform ID")


class CreateLinkTokenRequest(BaseModel):
    """Request model for creating a secure platform link token."""

    platform: str = Field(..., description="Platform name (discord, telegram, etc.)")
    platform_user_id: str = Field(
        ..., description="User's ID on the platform", min_length=1
    )
    username: Optional[str] = Field(None, description="Username on the platform")
    display_name: Optional[str] = Field(
        None, description="Display name on the platform"
    )

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, v: str) -> str:
        if not Platform.is_valid(v):
            raise ValueError(f"Invalid platform '{v}'")
        return v


class CreateLinkTokenResponse(BaseModel):
    """Response model for the created link token."""

    token: str = Field(..., description="Secure link token")
    auth_url: str = Field(..., description="Full auth URL for the user to visit")


class ResetSessionRequest(BaseModel):
    """Request model for resetting a bot session (starting a new conversation)."""

    platform: str = Field(..., description="Platform name (discord, slack, etc.)")
    platform_user_id: str = Field(
        ..., description="User's ID on the platform", min_length=1
    )
    channel_id: Optional[str] = Field(
        None, description="Channel/group ID (None for DM)"
    )

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, v: str) -> str:
        if not Platform.is_valid(v):
            raise ValueError(f"Invalid platform '{v}'")
        return v


class IntegrationInfo(BaseModel):
    """Integration information for bot settings."""

    name: str = Field(..., description="Integration name")
    logo_url: Optional[str] = Field(None, description="Integration logo URL")
    status: str = Field(..., description="Integration status: 'created' or 'connected'")


class BotSettingsResponse(BaseModel):
    """
    Response model for user settings.

    This is a union type:
    - If authenticated=False: Only authenticated field is relevant
    - If authenticated=True: All other fields contain user data (nullable where appropriate)
    """

    authenticated: bool = Field(..., description="Whether user is linked")
    user_name: Optional[str] = Field(
        None, description="User's display name (null if not set)"
    )
    account_created_at: Optional[str] = Field(
        None, description="Account creation date ISO string (null if not available)"
    )
    profile_image_url: Optional[str] = Field(
        None, description="User's profile image URL (null if not set)"
    )
    selected_model_name: Optional[str] = Field(
        None, description="Selected AI model name (null if using default)"
    )
    selected_model_icon_url: Optional[str] = Field(
        None, description="Model icon URL (null if using default)"
    )
    connected_integrations: list[IntegrationInfo] = Field(
        default_factory=list,
        description="List of connected integrations (empty if none)",
    )
