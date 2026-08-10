"""Unit tests for PlatformLinkService.

The service now delegates persistence to ``user_repository`` (link/unlink/lookup
behaviour against real Mongo is covered by the UserRepository contract tests).
These tests mock the repository singleton and cover the service's own logic:
conflict detection, profile assembly, the legacy dict it returns to bot consumers,
and the get_linked_platforms filtering.
"""

from unittest.mock import AsyncMock, patch

from bson import ObjectId
import pytest

from app.models.user_models import UserDocument
from app.services.platform_link_service import Platform, PlatformLinkService


def _user(**fields) -> UserDocument:
    return UserDocument.model_validate({"email": "test@example.com", **fields})


@pytest.fixture
def mock_repo():
    with patch("app.services.platform_link_service.user_repository") as repo:
        repo.get_by_platform_id = AsyncMock(return_value=None)
        repo.get = AsyncMock(return_value=None)
        repo.link_platform = AsyncMock()
        repo.unlink_platform = AsyncMock()
        repo.list_platform_user_ids = AsyncMock(return_value=[])
        yield repo


@pytest.fixture
def sample_user_id():
    return str(ObjectId())


class TestPlatform:
    def test_is_valid_known_platform(self):
        assert all(Platform.is_valid(p) for p in ("discord", "slack", "telegram", "whatsapp"))

    def test_is_valid_unknown_platform(self):
        assert Platform.is_valid("twitch") is False
        assert Platform.is_valid("") is False

    def test_values_returns_all_platforms(self):
        assert set(Platform.values()) == {"discord", "slack", "telegram", "whatsapp"}


class TestGetUserByPlatformId:
    async def test_finds_user_returns_legacy_dict(self, mock_repo, sample_user_id):
        mock_repo.get_by_platform_id.return_value = _user(
            id=sample_user_id, platform_links={"discord": {"id": "discord123"}}
        )

        result = await PlatformLinkService.get_user_by_platform_id("discord", "discord123")

        assert result is not None
        assert result["email"] == "test@example.com"
        assert result["_id"] == sample_user_id  # string id for bot consumers
        mock_repo.get_by_platform_id.assert_awaited_once_with("discord", "discord123")

    async def test_returns_none_when_not_found(self, mock_repo):
        mock_repo.get_by_platform_id.return_value = None
        assert await PlatformLinkService.get_user_by_platform_id("slack", "nope") is None


class TestLinkAccount:
    async def test_link_new_account(self, mock_repo, sample_user_id):
        mock_repo.get.return_value = _user(id=sample_user_id, platform_links={})
        mock_repo.link_platform.return_value = _user(id=sample_user_id)

        result = await PlatformLinkService.link_account(sample_user_id, "discord", "discord456")

        assert result.status == "linked"
        assert result.platform_user_id == "discord456"
        assert result.is_new_link is True

    async def test_link_with_profile_builds_link_value(self, mock_repo, sample_user_id):
        mock_repo.get.return_value = _user(id=sample_user_id, platform_links={})
        mock_repo.link_platform.return_value = _user(id=sample_user_id)

        await PlatformLinkService.link_account(
            sample_user_id,
            "discord",
            "discord456",
            profile={"username": "TestUser#1234", "display_name": "Test User"},
        )

        _, kwargs_platform, link_value, _connected = mock_repo.link_platform.call_args[0]
        assert kwargs_platform == "discord"
        assert link_value == {
            "id": "discord456",
            "username": "TestUser#1234",
            "display_name": "Test User",
        }

    async def test_raises_on_empty_platform_user_id(self, mock_repo, sample_user_id):
        with pytest.raises(ValueError, match="platform_user_id must not be empty"):
            await PlatformLinkService.link_account(sample_user_id, "discord", "  ")

    async def test_raises_when_linked_to_other_user(self, mock_repo, sample_user_id):
        mock_repo.get_by_platform_id.return_value = _user(id=str(ObjectId()))

        with pytest.raises(ValueError, match="already linked to another GAIA user"):
            await PlatformLinkService.link_account(sample_user_id, "discord", "discord123")

    async def test_raises_on_different_platform_id_already_linked(self, mock_repo, sample_user_id):
        mock_repo.get.return_value = _user(
            id=sample_user_id, platform_links={"discord": {"id": "existing_id"}}
        )

        with pytest.raises(ValueError, match="already has a different discord account linked"):
            await PlatformLinkService.link_account(sample_user_id, "discord", "new_id")

    async def test_raises_on_user_not_found(self, mock_repo, sample_user_id):
        mock_repo.get.return_value = None
        mock_repo.link_platform.return_value = None

        with pytest.raises(ValueError, match="User not found"):
            await PlatformLinkService.link_account(sample_user_id, "discord", "discord456")

    async def test_same_platform_id_relink_is_not_new(self, mock_repo, sample_user_id):
        mock_repo.get.return_value = _user(
            id=sample_user_id, platform_links={"discord": {"id": "discord123"}}
        )
        mock_repo.link_platform.return_value = _user(id=sample_user_id)

        result = await PlatformLinkService.link_account(sample_user_id, "discord", "discord123")

        assert result.status == "linked"
        assert result.is_new_link is False

    async def test_stringifies_platform_user_id(self, mock_repo, sample_user_id):
        mock_repo.get.return_value = _user(id=sample_user_id, platform_links={})
        mock_repo.link_platform.return_value = _user(id=sample_user_id)

        result = await PlatformLinkService.link_account(sample_user_id, "telegram", 12345)

        assert result.platform_user_id == "12345"

    async def test_legacy_non_dict_link_ignored(self, mock_repo, sample_user_id):
        mock_repo.get.return_value = _user(
            id=sample_user_id, platform_links={"discord": "legacy_string"}
        )
        mock_repo.link_platform.return_value = _user(id=sample_user_id)

        result = await PlatformLinkService.link_account(sample_user_id, "discord", "new_id")

        assert result.status == "linked"


class TestUnlinkAccount:
    async def test_unlinks_successfully(self, mock_repo, sample_user_id):
        mock_repo.unlink_platform.return_value = _user(id=sample_user_id)

        result = await PlatformLinkService.unlink_account(sample_user_id, "discord")

        assert result.status == "disconnected"
        assert result.platform == "discord"
        mock_repo.unlink_platform.assert_awaited_once_with(sample_user_id, "discord")

    async def test_raises_on_user_not_found(self, mock_repo, sample_user_id):
        mock_repo.unlink_platform.return_value = None

        with pytest.raises(ValueError, match="User not found"):
            await PlatformLinkService.unlink_account(sample_user_id, "discord")


class TestGetLinkedPlatforms:
    async def test_returns_linked_platforms(self, mock_repo, sample_user_id):
        mock_repo.get.return_value = _user(
            id=sample_user_id,
            platform_links={"discord": {"id": "discord123", "username": "TestUser#1234"}},
            platform_links_connected_at={"discord": "2024-01-01T00:00:00Z"},
        )

        result = await PlatformLinkService.get_linked_platforms(sample_user_id)

        assert result["discord"]["platformUserId"] == "discord123"
        assert result["discord"]["username"] == "TestUser#1234"
        assert result["discord"]["connectedAt"] == "2024-01-01T00:00:00Z"

    async def test_returns_empty_when_user_not_found(self, mock_repo):
        mock_repo.get.return_value = None
        assert await PlatformLinkService.get_linked_platforms(str(ObjectId())) == {}

    async def test_skips_legacy_and_idless_values(self, mock_repo, sample_user_id):
        mock_repo.get.return_value = _user(
            id=sample_user_id,
            platform_links={
                "discord": "legacy_string",
                "slack": {"id": "slack123"},
                "telegram": {"username": "no_id"},
                "whatsapp": {"id": ""},
            },
        )

        result = await PlatformLinkService.get_linked_platforms(sample_user_id)

        assert set(result) == {"slack"}

    async def test_no_platform_links_returns_empty(self, mock_repo, sample_user_id):
        mock_repo.get.return_value = _user(id=sample_user_id)
        assert await PlatformLinkService.get_linked_platforms(sample_user_id) == {}
