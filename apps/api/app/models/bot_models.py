"""Bot Models

Pydantic models for bot chat, sessions, and related operations.
"""

from pydantic import BaseModel, Field, field_validator

from app.models.message_models import FileData
from app.services.platform_link_service import Platform


class BotChatRequest(BaseModel):
    """Request model for bot chat messages."""

    message: str = Field(..., description="User's message text", min_length=1, max_length=32768)
    platform: str = Field(..., description="Platform name (discord, slack, etc.)")
    platform_user_id: str = Field(..., description="User's ID on the platform", min_length=1)
    channel_id: str | None = Field(None, description="Channel/group ID (None for DM)")
    file_ids: list[str] | None = Field(
        None,
        description="IDs of files attached to this message (uploaded via /api/v1/upload).",
    )
    file_data: list[FileData] | None = Field(
        None,
        description=(
            "Full metadata for attached files. Mirrors the web chat payload so "
            "the agent can resolve URL/filename without an extra DB lookup."
        ),
    )

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, v: str) -> str:
        """Reject values that are not registered platform names."""
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
    platform_user_id: str = Field(..., description="User's ID on the platform", min_length=1)
    username: str | None = Field(None, description="Username on the platform")
    display_name: str | None = Field(None, description="Display name on the platform")

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, v: str) -> str:
        """Reject values that are not registered platform names."""
        if not Platform.is_valid(v):
            raise ValueError(f"Invalid platform '{v}'")
        return v


class CreateLinkTokenResponse(BaseModel):
    """Response model for the created link token."""

    token: str = Field(..., description="Secure link token")
    auth_url: str = Field(..., description="Full auth URL for the user to visit")


class BotWorkflowsListResponse(BaseModel):
    """Response model for listing bot workflows."""

    workflows: list = Field(..., description="List of workflow objects")


class BotWorkflowResponse(BaseModel):
    """Response model for single workflow operations."""

    workflow: dict = Field(..., description="Workflow object")


class BotConversationResponse(BaseModel):
    """Response model for single conversation."""

    conversation_id: str = Field(..., description="Conversation ID")
    user_id: str = Field(..., description="User ID")
    description: str | None = Field(None, description="Conversation description")
    messages: list = Field(default_factory=list, description="List of messages")
    created_at: str | None = Field(None, description="Creation timestamp")
    updated_at: str | None = Field(None, description="Last update timestamp")

    class Config:
        extra = "allow"  # Allow additional fields from MongoDB


class ResetSessionRequest(BaseModel):
    """Request model for resetting a bot session (starting a new conversation)."""

    platform: str = Field(..., description="Platform name (discord, slack, etc.)")
    platform_user_id: str = Field(..., description="User's ID on the platform", min_length=1)
    channel_id: str | None = Field(None, description="Channel/group ID (None for DM)")

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, v: str) -> str:
        """Reject values that are not registered platform names."""
        if not Platform.is_valid(v):
            raise ValueError(f"Invalid platform '{v}'")
        return v


class IntegrationInfo(BaseModel):
    """Integration information for bot settings."""

    name: str = Field(..., description="Integration name")
    logo_url: str | None = Field(None, description="Integration logo URL")
    status: str = Field(..., description="Integration status: 'created' or 'connected'")


class BotSettingsResponse(BaseModel):
    """
    Response model for user settings.

    This is a union type:
    - If authenticated=False: Only authenticated field is relevant
    - If authenticated=True: All other fields contain user data (nullable where appropriate)
    """

    authenticated: bool = Field(..., description="Whether user is linked")
    user_name: str | None = Field(None, description="User's display name (null if not set)")
    account_created_at: str | None = Field(
        None, description="Account creation date ISO string (null if not available)"
    )
    profile_image_url: str | None = Field(
        None, description="User's profile image URL (null if not set)"
    )
    connected_integrations: list[IntegrationInfo] = Field(
        default_factory=list,
        description="List of connected integrations (empty if none)",
    )
