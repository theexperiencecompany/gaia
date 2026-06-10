"""Platform Link Service

Centralized service for managing platform account linking (Discord, Slack, Telegram, WhatsApp).

Storage contract: platform_links.{platform} is always a dict with at minimum an "id" key
containing the platform user ID as a non-empty plain string. Optional keys: "username",
"display_name". Any document storing a non-dict value (legacy string/int) is treated as
unlinked.
"""

from datetime import UTC, datetime
from enum import Enum

from bson import ObjectId

from app.db.mongodb.collections import users_collection


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
    async def get_user_by_platform_id(platform: str, platform_user_id: str) -> dict | None:
        """Find a GAIA user by their platform account ID (queries the nested .id field)."""
        return await users_collection.find_one({f"platform_links.{platform}.id": platform_user_id})

    @staticmethod
    async def link_account(
        user_id: str,
        platform: str,
        platform_user_id: str,
        _use_object_id: bool = False,
        profile: dict | None = None,
    ) -> dict:
        """Link a platform account to a GAIA user.

        Stores the link as a dict {"id", "username"?, "display_name"?}. Raises
        ValueError if the id is empty, the user is not found, or either side is
        already linked to a different account.
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
            raise ValueError(f"This {platform} account is already linked to another GAIA user")

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

        now = datetime.now(UTC).isoformat()

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
    async def unlink_account(user_id: str, platform: str, _use_object_id: bool = False) -> dict:
        """Unlink a platform account from a GAIA user. Raises ValueError if the user is not found."""
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
        """Get all linked platforms for a user, mapping platform name to connection details.

        Only platforms stored as a dict with a non-empty "id" are returned;
        legacy string/int values are skipped.
        """
        # Project only the link fields: this runs on the outbound delivery hot
        # path (once per platform adapter, fanned out per notification), so
        # fetching the whole user document would pull conversations/settings/etc.
        # we never read here.
        user = await users_collection.find_one(
            {"_id": ObjectId(user_id)},
            {"platform_links": 1, "platform_links_connected_at": 1},
        )

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
