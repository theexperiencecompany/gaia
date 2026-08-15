"""Platform Link Service

Centralized service for managing platform account linking (Discord, Slack, Telegram, WhatsApp).

Storage contract: platform_links.{platform} is always a dict with at minimum an "id" key
containing the platform user ID as a non-empty plain string. Optional keys: "username",
"display_name". Any document storing a non-dict value (legacy string/int) is treated as
unlinked.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from app.db.repositories.users import user_repository
from app.models.platform_models import (
    DisconnectPlatformResponse,
    PlatformLinkEntry,
    PlatformLinkResult,
)
from app.models.user_models import PlatformLinkRecord, user_to_legacy_dict


class Platform(str, Enum):
    """Supported platforms for account linking."""

    DISCORD = "discord"
    SLACK = "slack"
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"

    @classmethod
    def is_valid(cls, platform: str) -> bool:
        """Check if platform is supported."""
        try:
            cls(platform)
            return True
        except ValueError:
            return False

    @classmethod
    def values(cls) -> list[str]:
        """Get list of all platform values."""
        return [p.value for p in cls]


class PlatformLinkService:
    """Service for platform account linking operations."""

    @staticmethod
    async def get_user_by_platform_id(
        platform: str, platform_user_id: str
    ) -> dict[str, Any] | None:
        """Find a GAIA user by their platform account ID (queries the nested .id field)."""
        user = await user_repository.get_by_platform_id(platform, platform_user_id)
        return user_to_legacy_dict(user) if user else None

    @staticmethod
    async def list_platform_user_ids(platform: str, limit: int = 500) -> list[str]:
        """List the platform_user_ids of every account linked to the given platform.

        Used by bots (e.g. Discord) to pre-warm DM-channel caches on startup so
        inbound DMs resolve even on a cold restart. Bounded by ``limit`` to keep
        startup cost predictable.
        """
        return await user_repository.list_platform_user_ids(platform, limit=limit)

    @staticmethod
    async def link_account(
        user_id: str,
        platform: str,
        platform_user_id: str,
        _use_object_id: bool = False,
        # A Mapping, not a dict: the OAuth callback path builds one whose values
        # may be None (a provider that omits a username), and dict's invariance
        # would then reject the dict[str, str] the token path builds.
        profile: Mapping[str, str | None] | None = None,
    ) -> PlatformLinkResult:
        """Link a platform account to a GAIA user.

        Stores the link as a dict {"id", "username"?, "display_name"?}. Raises
        ValueError if the id is empty, the user is not found, or either side is
        already linked to a different account.
        """
        platform_user_id = str(platform_user_id).strip()
        if not platform_user_id:
            raise ValueError("platform_user_id must not be empty")

        # Reject if this platform ID is already linked to a different user
        existing = await user_repository.get_by_platform_id(platform, platform_user_id)
        if existing and existing.id != user_id:
            raise ValueError(f"This {platform} account is already linked to another GAIA user")

        # Reject if the user already has a different platform ID stored
        user = await user_repository.get(user_id)
        if user:
            current_link = (user.platform_links or {}).get(platform)
            if isinstance(current_link, dict):
                current_id = current_link.get("id", "")
                if current_id and current_id != platform_user_id:
                    raise ValueError(
                        f"Your account already has a different {platform} account linked"
                    )

        now = datetime.now(UTC).isoformat()

        # Build the stored dict value
        link_value: PlatformLinkRecord = {"id": platform_user_id}
        if profile:
            if profile.get("username"):
                link_value["username"] = str(profile["username"])
            if profile.get("display_name"):
                link_value["display_name"] = str(profile["display_name"])

        result = await user_repository.link_platform(user_id, platform, link_value, now)
        if result is None:
            raise ValueError("User not found")

        prior_link = (user.platform_links or {}).get(platform) if user else None
        previously_linked_same = (
            isinstance(prior_link, dict) and prior_link.get("id") == platform_user_id
        )

        return PlatformLinkResult(
            status="linked",
            platform=platform,
            platform_user_id=platform_user_id,
            connected_at=now,
            # True only when this call created a brand-new link (not a re-link of
            # the same id) — lets the caller fire a one-off "connected" greeting.
            is_new_link=not previously_linked_same,
        )

    @staticmethod
    async def unlink_account(
        user_id: str, platform: str, _use_object_id: bool = False
    ) -> DisconnectPlatformResponse:
        """Unlink a platform account from a GAIA user. Raises ValueError if the user is not found."""
        result = await user_repository.unlink_platform(user_id, platform)
        if result is None:
            raise ValueError("User not found")
        return DisconnectPlatformResponse(status="disconnected", platform=platform)

    @staticmethod
    async def get_linked_platforms(user_id: str) -> dict[str, PlatformLinkEntry]:
        """Get all linked platforms for a user, mapping platform name to connection details.

        Only platforms stored as a dict with a non-empty "id" are returned;
        legacy string/int values are skipped.
        """
        user = await user_repository.get(user_id)
        if user is None:
            return {}

        platform_links = user.platform_links or {}
        connected_at = user.platform_links_connected_at or {}

        result: dict[str, PlatformLinkEntry] = {}
        for platform in Platform.values():
            stored = platform_links.get(platform)
            if isinstance(stored, dict) and stored.get("id"):
                result[platform] = {
                    "platform": platform,
                    "platformUserId": stored["id"],
                    "username": stored.get("username"),
                    "displayName": stored.get("display_name"),
                    "connectedAt": connected_at.get(platform),
                }

        return result
