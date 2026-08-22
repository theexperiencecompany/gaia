"""Bot Models

Pydantic models for bot chat, sessions, and related operations.
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.repositories.base import MongoDocument
from app.models.message_models import FileData
from app.services.platform_link_service import Platform

# Shared field docs — the same platform identity fields recur across the
# request/response models below, so their descriptions live in one place.
_PLATFORM_DESC = "Platform name (discord, telegram, etc.)"
_PLATFORM_USER_ID_DESC = "User's ID on the platform"
_USERNAME_DESC = "Username on the platform"
_DISPLAY_NAME_DESC = "Display name on the platform"


class BotChatRequest(BaseModel):
    """Request model for bot chat messages."""

    message: str = Field(..., description="User's message text", min_length=1, max_length=32768)
    platform: str = Field(..., description="Platform name (discord, slack, etc.)")
    platform_user_id: str = Field(..., description=_PLATFORM_USER_ID_DESC, min_length=1)
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
    user_id: str | None = Field(
        None,
        description=(
            "Stable GAIA user id when linked, else null. Bots key PostHog on this "
            "so their events land on the same profile as web and API events."
        ),
    )


class LinkedUsersResponse(BaseModel):
    """Response model for the list of platform_user_ids linked on a platform."""

    platform_user_ids: list[str] = Field(
        default_factory=list,
        description="platform_user_ids of accounts linked to the platform.",
    )


class CreateLinkTokenRequest(BaseModel):
    """Request model for creating a secure platform link token."""

    platform: str = Field(..., description=_PLATFORM_DESC)
    platform_user_id: str = Field(..., description=_PLATFORM_USER_ID_DESC, min_length=1)
    username: str | None = Field(None, description=_USERNAME_DESC)
    display_name: str | None = Field(None, description=_DISPLAY_NAME_DESC)

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


class ResetSessionRequest(BaseModel):
    """Request model for resetting a bot session (starting a new conversation)."""

    platform: str = Field(..., description="Platform name (discord, slack, etc.)")
    platform_user_id: str = Field(..., description=_PLATFORM_USER_ID_DESC, min_length=1)
    channel_id: str | None = Field(None, description="Channel/group ID (None for DM)")

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, v: str) -> str:
        """Reject values that are not registered platform names."""
        if not Platform.is_valid(v):
            raise ValueError(f"Invalid platform '{v}'")
        return v


class ResetSessionResponse(BaseModel):
    """Response model for a bot session reset."""

    success: bool = Field(..., description="Whether the session reset succeeded")
    conversation_id: str = Field(..., description="The new conversation ID")


class LinkTokenRecord(BaseModel):
    """The display fields read from the Redis hash ``create_link_token`` writes
    for a pending platform link (the hash also carries ``platform_user_id``,
    which this read path never surfaces).

    Validated immediately after ``HGETALL`` returns the raw hash (see the API
    CLAUDE.md Type Safety rules on external boundaries).
    """

    platform: str = Field(..., description=_PLATFORM_DESC)
    username: str | None = Field(None, description=_USERNAME_DESC)
    display_name: str | None = Field(None, description=_DISPLAY_NAME_DESC)

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, v: str) -> str:
        """Reject values that are not registered platform names."""
        if not Platform.is_valid(v):
            raise ValueError(f"Invalid platform '{v}'")
        return v


class LinkTokenInfoResponse(BaseModel):
    """Response model for the link-token confirmation page's display metadata."""

    platform: str = Field(..., description="Platform name")
    username: str | None = Field(None, description=_USERNAME_DESC)
    display_name: str | None = Field(None, description=_DISPLAY_NAME_DESC)


class UnlinkAccountResponse(BaseModel):
    """Response model for unlinking a platform account."""

    success: bool = Field(..., description="Whether the account was unlinked")


class TranscribeAudioResponse(BaseModel):
    """Response model for a transcribed bot audio clip."""

    text: str = Field(..., description="Transcript of the audio clip")


class IntegrationInfo(BaseModel):
    """Integration information for bot settings."""

    name: str = Field(..., description="Integration name")
    logo_url: str | None = Field(None, description="Integration logo URL")
    status: str = Field(..., description="Integration status: 'created' or 'connected'")


class BotSettingsResponse(BaseModel):
    """Response model for user settings. When authenticated=False only that field is relevant."""

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


class BotSessionDocument(MongoDocument):
    """A bot chat session — the mapping from a platform conversation to a GAIA
    ``conversation_id``, keyed by a unique ``session_key``.

    Only the fields the app reads are modelled. ``created_at``/``updated_at`` are
    stored as ISO-format strings for the collection's TTL and are written raw by
    the repository (never surfaced here), so the base's ``updated_at`` datetime
    auto-stamp does not apply — preserving the existing on-disk string shape.
    """

    session_key: str
    conversation_id: str
    platform: str
    platform_user_id: str
    channel_id: str | None = None


class BotSessionUpdate(BaseModel):
    """Bot sessions are claimed via an atomic upsert, never typed-updated."""

    model_config = ConfigDict(extra="forbid")
