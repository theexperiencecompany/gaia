"""Platform Link Service

Centralized service for managing platform account linking (Discord, Slack, Telegram, WhatsApp).

Storage contract: platform_links.{platform} is always a dict with at minimum an "id" key
containing the platform user ID as a non-empty plain string. Optional keys: "username",
"display_name". Any document storing a non-dict value (legacy string/int) is treated as
unlinked.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from app.db.mongodb.collections import users_collection
from bson import ObjectId


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
    ) -> Optional[dict]:
        """
        Find a GAIA user by their platform account ID.

        Queries by the nested .id field (new dict format only).

        Args:
            platform: Platform name (discord, slack, telegram, whatsapp)
            platform_user_id: User's ID on the platform (plain string)

        Returns:
            User document if found, None otherwise
        """
        return await users_collection.find_one(
            {f"platform_links.{platform}.id": platform_user_id}
        )

    @staticmethod
    async def is_authenticated(platform: str, platform_user_id: str) -> bool:
        """
        Check if a platform user is linked to a GAIA account.

        Args:
            platform: Platform name
            platform_user_id: User's ID on the platform

        Returns:
            True if linked, False otherwise
        """
        user = await PlatformLinkService.get_user_by_platform_id(
            platform, platform_user_id
        )
        return user is not None

    @staticmethod
    async def link_account(
        user_id: str,
        platform: str,
        platform_user_id: str,
        use_object_id: bool = False,
        profile: Optional[dict] = None,
    ) -> dict:
        """
        Link a platform account to a GAIA user.

        Stores platform_user_id as a dict: {"id": "...", "username": "...", "display_name": "..."}.
        The "username" and "display_name" keys are optional.

        Args:
            user_id: GAIA user ID (string representation of MongoDB _id)
            platform: Platform name
            platform_user_id: User's ID on the platform
            use_object_id: Deprecated - no longer used
            profile: Optional dict with "username" and/or "display_name" keys

        Returns:
            Result dict with status and details

        Raises:
            ValueError: If platform_user_id is empty
            ValueError: If platform account already linked to a different user
            ValueError: If user already has a different platform account linked
            ValueError: If user not found
        """
        platform_user_id = str(platform_user_id).strip()
        if not platform_user_id:
            raise ValueError("platform_user_id must not be empty")

        query_value = ObjectId(user_id)

        # Reject if this platform ID is already linked to a different user
        existing = await users_collection.find_one(
            {f"platform_links.{platform}.id": platform_user_id}
        )
        if existing and str(existing.get("_id")) != user_id:
            raise ValueError(
                f"This {platform} account is already linked to another GAIA user"
            )

        # Reject if the user already has a different platform ID stored
        user = await users_collection.find_one({"_id": query_value})
        if user:
            current_link = user.get("platform_links", {}).get(platform)
            if isinstance(current_link, dict):
                current_id = current_link.get("id", "")
                if current_id and current_id != platform_user_id:
                    raise ValueError(
                        f"Your account already has a different {platform} account linked"
                    )

        now = datetime.now(timezone.utc).isoformat()

        # Build the stored dict value
        link_value: dict = {"id": platform_user_id}
        if profile:
            if profile.get("username"):
                link_value["username"] = str(profile["username"])
            if profile.get("display_name"):
                link_value["display_name"] = str(profile["display_name"])

        result = await users_collection.update_one(
            {"_id": query_value},
            {
                "$set": {
                    f"platform_links.{platform}": link_value,
                    f"platform_links_connected_at.{platform}": now,
                }
            },
        )

        if result.matched_count == 0:
            raise ValueError("User not found")

        return {
            "status": "linked",
            "platform": platform,
            "platform_user_id": platform_user_id,
            "connected_at": now,
        }

    @staticmethod
    async def unlink_account(
        user_id: str, platform: str, use_object_id: bool = False
    ) -> dict:
        """
        Unlink a platform account from a GAIA user.

        Args:
            user_id: GAIA user ID (string representation of MongoDB _id)
            platform: Platform name
            use_object_id: Deprecated - no longer used

        Returns:
            Result dict with status

        Raises:
            ValueError: If user not found
        """
        result = await users_collection.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$unset": {
                    f"platform_links.{platform}": "",
                    f"platform_links_connected_at.{platform}": "",
                }
            },
        )

        if result.matched_count == 0:
            raise ValueError("User not found")

        return {"status": "disconnected", "platform": platform}

    @staticmethod
    async def get_linked_platforms(user_id: str) -> dict:
        """
        Get all linked platforms for a user.

        Only returns platforms where the stored value is a dict with a non-empty "id" key.
        Legacy string/int values are skipped.

        Args:
            user_id: GAIA user ID (string representation of MongoDB _id)

        Returns:
            Dict mapping platform name to connection details
        """
        user = await users_collection.find_one({"_id": ObjectId(user_id)})

        if not user:
            return {}

        platform_links = user.get("platform_links", {})
        connected_at = user.get("platform_links_connected_at", {})

        result = {}
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
