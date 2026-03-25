"""Unit tests for PlatformLinkService."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bson import ObjectId

from app.services.platform_link_service import Platform, PlatformLinkService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_users_collection():
    with patch("app.services.platform_link_service.users_collection") as mock_col:
        yield mock_col


@pytest.fixture
def sample_user_id():
    return str(ObjectId())


@pytest.fixture
def sample_user_doc(sample_user_id):
    return {
        "_id": ObjectId(sample_user_id),
        "email": "test@example.com",
        "platform_links": {
            "discord": {"id": "discord123", "username": "TestUser#1234"},
        },
        "platform_links_connected_at": {
            "discord": "2024-01-01T00:00:00Z",
        },
    }


# ---------------------------------------------------------------------------
# Platform enum
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPlatform:
    def test_is_valid_known_platform(self):
        assert Platform.is_valid("discord") is True
        assert Platform.is_valid("slack") is True
        assert Platform.is_valid("telegram") is True
        assert Platform.is_valid("whatsapp") is True

    def test_is_valid_unknown_platform(self):
        assert Platform.is_valid("twitch") is False
        assert Platform.is_valid("") is False

    def test_values_returns_all_platforms(self):
        values = Platform.values()
        assert "discord" in values
        assert "slack" in values
        assert "telegram" in values
        assert "whatsapp" in values
        assert len(values) == 4


# ---------------------------------------------------------------------------
# PlatformLinkService.get_user_by_platform_id
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetUserByPlatformId:
    async def test_finds_user(self, mock_users_collection, sample_user_doc):
        mock_users_collection.find_one = AsyncMock(return_value=sample_user_doc)

        result = await PlatformLinkService.get_user_by_platform_id(
            "discord", "discord123"
        )

        assert result is not None
        assert result["email"] == "test@example.com"
        mock_users_collection.find_one.assert_awaited_once_with(
            {"platform_links.discord.id": "discord123"}
        )

    async def test_returns_none_when_not_found(self, mock_users_collection):
        mock_users_collection.find_one = AsyncMock(return_value=None)

        result = await PlatformLinkService.get_user_by_platform_id(
            "slack", "nonexistent"
        )

        assert result is None


# ---------------------------------------------------------------------------
# PlatformLinkService.is_authenticated
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIsAuthenticated:
    async def test_returns_true_when_linked(
        self, mock_users_collection, sample_user_doc
    ):
        mock_users_collection.find_one = AsyncMock(return_value=sample_user_doc)

        result = await PlatformLinkService.is_authenticated("discord", "discord123")

        assert result is True

    async def test_returns_false_when_not_linked(self, mock_users_collection):
        mock_users_collection.find_one = AsyncMock(return_value=None)

        result = await PlatformLinkService.is_authenticated("discord", "unknown")

        assert result is False


# ---------------------------------------------------------------------------
# PlatformLinkService.link_account
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLinkAccount:
    async def test_link_new_account(self, mock_users_collection, sample_user_id):
        user_doc = {
            "_id": ObjectId(sample_user_id),
            "platform_links": {},
        }
        mock_users_collection.find_one = AsyncMock(
            side_effect=[None, user_doc]  # first: no existing link, second: user lookup
        )
        mock_users_collection.update_one = AsyncMock(
            return_value=MagicMock(matched_count=1)
        )

        result = await PlatformLinkService.link_account(
            sample_user_id, "discord", "discord456"
        )

        assert result["status"] == "linked"
        assert result["platform"] == "discord"
        assert result["platform_user_id"] == "discord456"
        assert "connected_at" in result

    async def test_link_with_profile(self, mock_users_collection, sample_user_id):
        user_doc = {
            "_id": ObjectId(sample_user_id),
            "platform_links": {},
        }
        mock_users_collection.find_one = AsyncMock(side_effect=[None, user_doc])
        mock_users_collection.update_one = AsyncMock(
            return_value=MagicMock(matched_count=1)
        )

        result = await PlatformLinkService.link_account(
            sample_user_id,
            "discord",
            "discord456",
            profile={"username": "TestUser#1234", "display_name": "Test User"},
        )

        assert result["status"] == "linked"
        # Verify the update call includes profile data
        update_call = mock_users_collection.update_one.call_args
        set_data = update_call[0][1]["$set"]
        link_value = set_data["platform_links.discord"]
        assert link_value["id"] == "discord456"
        assert link_value["username"] == "TestUser#1234"
        assert link_value["display_name"] == "Test User"

    async def test_raises_on_empty_platform_user_id(
        self, mock_users_collection, sample_user_id
    ):
        with pytest.raises(ValueError, match="platform_user_id must not be empty"):
            await PlatformLinkService.link_account(sample_user_id, "discord", "  ")

    async def test_raises_on_already_linked_to_other_user(
        self, mock_users_collection, sample_user_id
    ):
        other_user_id = str(ObjectId())
        mock_users_collection.find_one = AsyncMock(
            return_value={"_id": ObjectId(other_user_id)}
        )

        with pytest.raises(ValueError, match="already linked to another GAIA user"):
            await PlatformLinkService.link_account(
                sample_user_id, "discord", "discord123"
            )

    async def test_raises_on_different_platform_id_already_linked(
        self, mock_users_collection, sample_user_id
    ):
        user_doc = {
            "_id": ObjectId(sample_user_id),
            "platform_links": {
                "discord": {"id": "existing_discord_id"},
            },
        }
        # First call: no existing user with the new platform ID
        # Second call: user lookup returns user with existing different link
        mock_users_collection.find_one = AsyncMock(side_effect=[None, user_doc])

        with pytest.raises(
            ValueError, match="already has a different discord account linked"
        ):
            await PlatformLinkService.link_account(
                sample_user_id, "discord", "new_discord_id"
            )

    async def test_raises_on_user_not_found(
        self, mock_users_collection, sample_user_id
    ):
        mock_users_collection.find_one = AsyncMock(
            side_effect=[None, None]  # no existing link, no user
        )
        mock_users_collection.update_one = AsyncMock(
            return_value=MagicMock(matched_count=0)
        )

        with pytest.raises(ValueError, match="User not found"):
            await PlatformLinkService.link_account(
                sample_user_id, "discord", "discord456"
            )

    async def test_same_platform_id_re_link_succeeds(
        self, mock_users_collection, sample_user_id
    ):
        """Re-linking the same platform ID to the same user should succeed."""
        user_doc = {
            "_id": ObjectId(sample_user_id),
            "platform_links": {
                "discord": {"id": "discord123"},
            },
        }
        # First call: existing with same user_id
        mock_users_collection.find_one = AsyncMock(
            side_effect=[
                {"_id": ObjectId(sample_user_id)},  # same user owns it
                user_doc,
            ]
        )
        mock_users_collection.update_one = AsyncMock(
            return_value=MagicMock(matched_count=1)
        )

        result = await PlatformLinkService.link_account(
            sample_user_id, "discord", "discord123"
        )

        assert result["status"] == "linked"

    async def test_strips_and_stringifies_platform_user_id(
        self, mock_users_collection, sample_user_id
    ):
        user_doc = {
            "_id": ObjectId(sample_user_id),
            "platform_links": {},
        }
        mock_users_collection.find_one = AsyncMock(side_effect=[None, user_doc])
        mock_users_collection.update_one = AsyncMock(
            return_value=MagicMock(matched_count=1)
        )

        result = await PlatformLinkService.link_account(
            sample_user_id,
            "telegram",
            12345,  # int input
        )

        assert result["platform_user_id"] == "12345"

    async def test_legacy_current_link_non_dict_ignored(
        self, mock_users_collection, sample_user_id
    ):
        """Legacy string value for current_link should not trigger duplicate check."""
        user_doc = {
            "_id": ObjectId(sample_user_id),
            "platform_links": {
                "discord": "legacy_string_value",  # legacy format
            },
        }
        mock_users_collection.find_one = AsyncMock(side_effect=[None, user_doc])
        mock_users_collection.update_one = AsyncMock(
            return_value=MagicMock(matched_count=1)
        )

        result = await PlatformLinkService.link_account(
            sample_user_id, "discord", "new_discord_id"
        )

        assert result["status"] == "linked"


# ---------------------------------------------------------------------------
# PlatformLinkService.unlink_account
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUnlinkAccount:
    async def test_unlinks_successfully(self, mock_users_collection, sample_user_id):
        mock_users_collection.update_one = AsyncMock(
            return_value=MagicMock(matched_count=1)
        )

        result = await PlatformLinkService.unlink_account(sample_user_id, "discord")

        assert result["status"] == "disconnected"
        assert result["platform"] == "discord"

    async def test_raises_on_user_not_found(
        self, mock_users_collection, sample_user_id
    ):
        mock_users_collection.update_one = AsyncMock(
            return_value=MagicMock(matched_count=0)
        )

        with pytest.raises(ValueError, match="User not found"):
            await PlatformLinkService.unlink_account(sample_user_id, "discord")

    async def test_uses_unset_operation(self, mock_users_collection, sample_user_id):
        mock_users_collection.update_one = AsyncMock(
            return_value=MagicMock(matched_count=1)
        )

        await PlatformLinkService.unlink_account(sample_user_id, "slack")

        call_args = mock_users_collection.update_one.call_args
        unset_data = call_args[0][1]["$unset"]
        assert "platform_links.slack" in unset_data
        assert "platform_links_connected_at.slack" in unset_data


# ---------------------------------------------------------------------------
# PlatformLinkService.get_linked_platforms
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetLinkedPlatforms:
    async def test_returns_linked_platforms(
        self, mock_users_collection, sample_user_doc
    ):
        mock_users_collection.find_one = AsyncMock(return_value=sample_user_doc)

        result = await PlatformLinkService.get_linked_platforms(
            str(sample_user_doc["_id"])
        )

        assert "discord" in result
        assert result["discord"]["platformUserId"] == "discord123"
        assert result["discord"]["username"] == "TestUser#1234"
        assert result["discord"]["connectedAt"] == "2024-01-01T00:00:00Z"

    async def test_returns_empty_when_user_not_found(self, mock_users_collection):
        mock_users_collection.find_one = AsyncMock(return_value=None)

        result = await PlatformLinkService.get_linked_platforms(str(ObjectId()))

        assert result == {}

    async def test_skips_legacy_string_values(self, mock_users_collection):
        user_doc = {
            "_id": ObjectId(),
            "platform_links": {
                "discord": "legacy_string",
                "slack": {"id": "slack123"},
            },
            "platform_links_connected_at": {},
        }
        mock_users_collection.find_one = AsyncMock(return_value=user_doc)

        result = await PlatformLinkService.get_linked_platforms(str(user_doc["_id"]))

        assert "discord" not in result
        assert "slack" in result

    async def test_skips_dict_without_id(self, mock_users_collection):
        user_doc = {
            "_id": ObjectId(),
            "platform_links": {
                "discord": {"username": "TestUser#1234"},  # no "id" key
            },
            "platform_links_connected_at": {},
        }
        mock_users_collection.find_one = AsyncMock(return_value=user_doc)

        result = await PlatformLinkService.get_linked_platforms(str(user_doc["_id"]))

        assert "discord" not in result

    async def test_skips_dict_with_empty_id(self, mock_users_collection):
        user_doc = {
            "_id": ObjectId(),
            "platform_links": {
                "discord": {"id": ""},
            },
            "platform_links_connected_at": {},
        }
        mock_users_collection.find_one = AsyncMock(return_value=user_doc)

        result = await PlatformLinkService.get_linked_platforms(str(user_doc["_id"]))

        assert "discord" not in result

    async def test_no_platform_links_key(self, mock_users_collection):
        user_doc = {
            "_id": ObjectId(),
        }
        mock_users_collection.find_one = AsyncMock(return_value=user_doc)

        result = await PlatformLinkService.get_linked_platforms(str(user_doc["_id"]))

        assert result == {}

    async def test_includes_display_name(self, mock_users_collection):
        user_doc = {
            "_id": ObjectId(),
            "platform_links": {
                "telegram": {
                    "id": "tg123",
                    "username": "testuser",
                    "display_name": "Test User",
                },
            },
            "platform_links_connected_at": {
                "telegram": "2024-06-01T00:00:00Z",
            },
        }
        mock_users_collection.find_one = AsyncMock(return_value=user_doc)

        result = await PlatformLinkService.get_linked_platforms(str(user_doc["_id"]))

        assert result["telegram"]["displayName"] == "Test User"
        assert result["telegram"]["platform"] == "telegram"
