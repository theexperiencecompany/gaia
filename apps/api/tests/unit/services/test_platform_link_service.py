"""Unit tests for PlatformLinkService.

The service now delegates persistence to ``user_repository`` (link/unlink/lookup
behaviour against real Mongo is covered by the UserRepository contract tests).
These tests mock the repository singleton and cover the service's own logic:
conflict detection, profile assembly, the legacy dict it returns to bot consumers,
and the get_linked_platforms filtering.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, call, patch

from bson import ObjectId
import pytest

from app.constants.platform_links import IMESSAGE_PENDING_REGISTRATION_TTL
from app.models.platform_models import PendingPlatformRegistrationDocument
from app.models.user_models import UserDocument
from app.services.platform_link_service import (
    Platform,
    PlatformLinkService,
    reap_abandoned_imessage_registrations,
    register_pending_imessage_number,
)
from app.utils.errors import AppError, create_error


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


NOW = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


def _pending(
    user_id: str, phone: str, created_at: datetime = NOW
) -> PendingPlatformRegistrationDocument:
    return PendingPlatformRegistrationDocument(
        id="pending-1",
        user_id=user_id,
        platform=Platform.IMESSAGE.value,
        platform_user_id=phone,
        created_at=created_at,
    )


@pytest.fixture(autouse=True)
def mock_pending_repo(sample_user_id):
    with patch(
        "app.services.platform_link_service.pending_platform_registration_repository"
    ) as repo:
        repo.get_for_user = AsyncMock(return_value=None)
        repo.record = AsyncMock(return_value=_pending(sample_user_id, "+15551234567"))
        repo.find_older_than = AsyncMock(return_value=[])
        repo.delete_for_user = AsyncMock(return_value=0)
        repo.delete_by_platform_user_id = AsyncMock(return_value=0)
        yield repo


def _photon_down() -> AppError:
    return create_error(
        message="Could not disconnect your number from iMessage",
        why="Photon returned HTTP 500 for DELETE /users/pu-1/",
        status_code=502,
    )


class TestPlatform:
    def test_is_valid_known_platform(self):
        assert all(Platform.is_valid(p) for p in ("discord", "slack", "telegram", "whatsapp"))

    def test_is_valid_unknown_platform(self):
        assert Platform.is_valid("twitch") is False
        assert Platform.is_valid("") is False

    def test_values_returns_all_platforms(self):
        assert set(Platform.values()) == {"discord", "imessage", "slack", "telegram", "whatsapp"}


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

    async def test_imessage_link_clears_the_pending_registration(
        self, mock_repo, mock_pending_repo, sample_user_id
    ):
        mock_repo.get.return_value = _user(id=sample_user_id, platform_links={})
        mock_repo.link_platform.return_value = _user(id=sample_user_id)
        mock_pending_repo.get_for_user.return_value = _pending(sample_user_id, "+15551234567")

        with patch(
            "app.services.platform_link_service.unregister_shared_user", new_callable=AsyncMock
        ) as mock_unregister:
            await PlatformLinkService.link_account(sample_user_id, "imessage", "+15551234567")

        mock_pending_repo.get_for_user.assert_awaited_once_with(sample_user_id, "imessage")
        mock_pending_repo.delete_for_user.assert_awaited_once_with(sample_user_id, "imessage")
        mock_unregister.assert_not_awaited()

    async def test_imessage_link_from_another_number_releases_the_pending_one(
        self, mock_repo, mock_pending_repo, sample_user_id
    ):
        """They registered one number and texted /auth from another — release the stale one."""
        mock_repo.get.return_value = _user(id=sample_user_id, platform_links={})
        mock_repo.link_platform.return_value = _user(id=sample_user_id)
        mock_pending_repo.get_for_user.return_value = _pending(sample_user_id, "+15550000000")

        with (
            patch(
                "app.services.platform_link_service.unregister_shared_user",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_unregister,
            patch("app.services.platform_link_service.log") as mock_log,
        ):
            await PlatformLinkService.link_account(sample_user_id, "imessage", "+15551234567")

        mock_pending_repo.get_for_user.assert_awaited_once_with(sample_user_id, "imessage")
        mock_pending_repo.delete_for_user.assert_awaited_once_with(sample_user_id, "imessage")
        mock_unregister.assert_awaited_once_with("+15550000000")
        mock_log.audit.assert_called_once_with(
            "imessage number unregistered", actor=sample_user_id, provider="imessage"
        )

    async def test_non_imessage_link_leaves_pending_records_alone(
        self, mock_repo, mock_pending_repo, sample_user_id
    ):
        mock_repo.get.return_value = _user(id=sample_user_id, platform_links={})
        mock_repo.link_platform.return_value = _user(id=sample_user_id)

        await PlatformLinkService.link_account(sample_user_id, "discord", "discord456")

        mock_pending_repo.delete_for_user.assert_not_awaited()


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

    async def test_imessage_unlink_releases_photon_registration(self, mock_repo, sample_user_id):
        mock_repo.get.return_value = _user(
            id=sample_user_id, platform_links={"imessage": {"id": "+15551234567"}}
        )
        mock_repo.unlink_platform.return_value = _user(id=sample_user_id)

        with patch(
            "app.services.platform_link_service.unregister_shared_user",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_unregister:
            result = await PlatformLinkService.unlink_account(sample_user_id, "imessage")

        assert result.status == "disconnected"
        mock_unregister.assert_awaited_once_with("+15551234567")

    async def test_non_imessage_unlink_never_touches_photon(self, mock_repo, sample_user_id):
        mock_repo.get.return_value = _user(
            id=sample_user_id, platform_links={"discord": {"id": "discord123"}}
        )
        mock_repo.unlink_platform.return_value = _user(id=sample_user_id)

        with patch(
            "app.services.platform_link_service.unregister_shared_user", new_callable=AsyncMock
        ) as mock_unregister:
            await PlatformLinkService.unlink_account(sample_user_id, "discord")

        mock_unregister.assert_not_awaited()

    async def test_unlink_without_imessage_link_skips_photon(self, mock_repo, sample_user_id):
        mock_repo.get.return_value = _user(id=sample_user_id)
        mock_repo.unlink_platform.return_value = _user(id=sample_user_id)

        with patch(
            "app.services.platform_link_service.unregister_shared_user", new_callable=AsyncMock
        ) as mock_unregister:
            await PlatformLinkService.unlink_account(sample_user_id, "imessage")

        mock_unregister.assert_not_awaited()

    async def test_photon_failure_still_unlinks_and_warns(self, mock_repo, sample_user_id):
        mock_repo.get.return_value = _user(
            id=sample_user_id, platform_links={"imessage": {"id": "+15551234567"}}
        )
        mock_repo.unlink_platform.return_value = _user(id=sample_user_id)

        with (
            patch(
                "app.services.platform_link_service.unregister_shared_user",
                new_callable=AsyncMock,
                side_effect=create_error(
                    message="Could not disconnect your number from iMessage",
                    why="Photon returned HTTP 500 for DELETE /users/pu-1/",
                    status_code=502,
                ),
            ),
            patch("app.services.platform_link_service.log") as mock_log,
        ):
            result = await PlatformLinkService.unlink_account(sample_user_id, "imessage")

        assert result.status == "disconnected"
        mock_log.warning.assert_called_once()
        assert mock_log.warning.call_args.kwargs["error_type"] == "AppError"

    async def test_unlink_deletes_any_pending_registration(
        self, mock_repo, mock_pending_repo, sample_user_id
    ):
        mock_repo.get.return_value = _user(id=sample_user_id)
        mock_repo.unlink_platform.return_value = _user(id=sample_user_id)

        await PlatformLinkService.unlink_account(sample_user_id, "imessage")

        mock_pending_repo.delete_for_user.assert_awaited_once_with(sample_user_id, "imessage")


class TestRegisterPendingImessageNumber:
    async def test_records_the_pending_registration(self, mock_pending_repo, sample_user_id):
        with patch(
            "app.services.platform_link_service.unregister_shared_user", new_callable=AsyncMock
        ) as mock_unregister:
            await register_pending_imessage_number(sample_user_id, "+15551234567")

        mock_pending_repo.get_for_user.assert_awaited_once_with(sample_user_id, "imessage")
        recorded = mock_pending_repo.record.await_args.kwargs
        assert recorded["user_id"] == sample_user_id
        assert recorded["platform"] == "imessage"
        assert recorded["platform_user_id"] == "+15551234567"
        # The expiry clock the sweep measures against — a naive stamp would
        # compare against a tz-aware cutoff and blow up mid-sweep.
        assert recorded["created_at"].tzinfo is UTC
        mock_unregister.assert_not_awaited()

    async def test_swapping_numbers_releases_the_previous_one(
        self, mock_pending_repo, sample_user_id
    ):
        mock_pending_repo.get_for_user.return_value = _pending(sample_user_id, "+15550000000")

        with (
            patch(
                "app.services.platform_link_service.unregister_shared_user",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_unregister,
            patch("app.services.platform_link_service.log") as mock_log,
        ):
            await register_pending_imessage_number(sample_user_id, "+15551234567")

        mock_pending_repo.get_for_user.assert_awaited_once_with(sample_user_id, "imessage")
        mock_unregister.assert_awaited_once_with("+15550000000")
        mock_log.audit.assert_called_once_with(
            "imessage number unregistered", actor=sample_user_id, provider="imessage"
        )
        assert mock_pending_repo.record.await_args.kwargs["platform_user_id"] == "+15551234567"

    async def test_re_registering_the_same_number_keeps_it(self, mock_pending_repo, sample_user_id):
        mock_pending_repo.get_for_user.return_value = _pending(sample_user_id, "+15551234567")

        with patch(
            "app.services.platform_link_service.unregister_shared_user", new_callable=AsyncMock
        ) as mock_unregister:
            await register_pending_imessage_number(sample_user_id, "+15551234567")

        mock_unregister.assert_not_awaited()
        mock_pending_repo.record.assert_awaited_once()

    async def test_a_failed_release_still_records_the_new_number(
        self, mock_pending_repo, sample_user_id
    ):
        mock_pending_repo.get_for_user.return_value = _pending(sample_user_id, "+15550000000")

        with (
            patch(
                "app.services.platform_link_service.unregister_shared_user",
                new_callable=AsyncMock,
                side_effect=_photon_down(),
            ),
            patch("app.services.platform_link_service.log") as mock_log,
        ):
            await register_pending_imessage_number(sample_user_id, "+15551234567")

        assert mock_log.warning.call_args.kwargs["user"] == {"id": sample_user_id}
        assert mock_log.warning.call_args.args == ("imessage photon unregister failed",)
        assert mock_log.warning.call_args.kwargs["error_type"] == "AppError"
        assert (
            mock_log.warning.call_args.kwargs["error"]
            == "Could not disconnect your number from iMessage"
        )
        assert mock_pending_repo.record.await_args.kwargs["platform_user_id"] == "+15551234567"

    async def test_number_pending_on_another_account_is_a_conflict(
        self, mock_pending_repo, sample_user_id
    ):
        mock_pending_repo.record.return_value = None

        with pytest.raises(AppError) as exc_info:
            await register_pending_imessage_number(sample_user_id, "+15551234567")

        error = exc_info.value
        assert error.status_code == 409
        assert error.message == "That number is already being connected on another account"
        assert error.why == (
            "a pending imessage registration for this number belongs to a different GAIA user"
        )
        assert error.fix == (
            "finish or disconnect the other account's iMessage setup, or use a different number"
        )


class TestReapAbandonedImessageRegistrations:
    async def test_releases_and_deletes_expired_records(
        self, mock_repo, mock_pending_repo, sample_user_id
    ):
        expired = datetime(2026, 8, 14, tzinfo=UTC)
        mock_pending_repo.find_older_than.return_value = [
            _pending(sample_user_id, "+15550000001", created_at=expired),
            _pending(sample_user_id, "+15550000002", created_at=expired),
        ]

        with (
            patch(
                "app.services.platform_link_service.unregister_shared_user",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_unregister,
            patch("app.services.platform_link_service.log") as mock_log,
        ):
            reaped = await reap_abandoned_imessage_registrations(NOW)

        assert reaped == 2
        assert (
            mock_log.audit.call_args_list
            == [
                call("imessage number unregistered", actor=sample_user_id, provider="imessage"),
                call(
                    "imessage abandoned registration reaped",
                    actor=sample_user_id,
                    provider="imessage",
                ),
            ]
            * 2
        )
        assert mock_pending_repo.find_older_than.await_args.args == (
            "imessage",
            NOW - IMESSAGE_PENDING_REGISTRATION_TTL,
        )
        assert [call.args[0] for call in mock_unregister.await_args_list] == [
            "+15550000001",
            "+15550000002",
        ]
        assert [
            call.args for call in mock_pending_repo.delete_by_platform_user_id.await_args_list
        ] == [("imessage", "+15550000001"), ("imessage", "+15550000002")]

    async def test_keeps_the_record_when_photon_release_fails(
        self, mock_repo, mock_pending_repo, sample_user_id
    ):
        """A record deleted after a failed release would strand the pool seat forever."""
        mock_pending_repo.find_older_than.return_value = [
            _pending(sample_user_id, "+15550000001"),
            _pending(sample_user_id, "+15550000002"),
        ]

        with (
            patch(
                "app.services.platform_link_service.unregister_shared_user",
                new_callable=AsyncMock,
                side_effect=[_photon_down(), True],
            ),
            patch("app.services.platform_link_service.log") as mock_log,
        ):
            reaped = await reap_abandoned_imessage_registrations(NOW)

        assert reaped == 1
        mock_log.warning.assert_called_once()
        assert [
            call.args for call in mock_pending_repo.delete_by_platform_user_id.await_args_list
        ] == [("imessage", "+15550000002")]

    async def test_a_number_that_is_now_linked_is_never_released(
        self, mock_repo, mock_pending_repo, sample_user_id
    ):
        """The link landed after the record was written — releasing now kills a live link.

        Two records, linked one first: the sweep must skip it and keep going, not
        stop at the first skip and leave every later seat allocated.
        """
        mock_pending_repo.find_older_than.return_value = [
            _pending(sample_user_id, "+15551234567"),
            _pending(sample_user_id, "+15550000001"),
        ]
        mock_repo.get.return_value = _user(
            id=sample_user_id, platform_links={"imessage": {"id": "+15551234567"}}
        )

        with patch(
            "app.services.platform_link_service.unregister_shared_user",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_unregister:
            reaped = await reap_abandoned_imessage_registrations(NOW)

        assert reaped == 1
        mock_unregister.assert_awaited_once_with("+15550000001")
        # Each record is checked against ITS OWN owner's links.
        assert mock_repo.get.await_args_list == [call(sample_user_id), call(sample_user_id)]
        # The linked number's record is still retired — it is stale bookkeeping.
        assert [c.args for c in mock_pending_repo.delete_by_platform_user_id.await_args_list] == [
            ("imessage", "+15551234567"),
            ("imessage", "+15550000001"),
        ]

    async def test_reaps_nothing_when_no_record_is_expired(self, mock_repo, mock_pending_repo):
        with patch(
            "app.services.platform_link_service.unregister_shared_user", new_callable=AsyncMock
        ) as mock_unregister:
            reaped = await reap_abandoned_imessage_registrations(NOW)

        assert reaped == 0
        mock_unregister.assert_not_awaited()
        mock_pending_repo.delete_by_platform_user_id.assert_not_awaited()


class TestGetLinkedPlatforms:
    async def test_returns_linked_platforms(self, mock_repo, sample_user_id):
        mock_repo.get.return_value = _user(
            id=sample_user_id,
            platform_links={
                "discord": {
                    "id": "discord123",
                    "username": "TestUser#1234",
                    "display_name": "Test User",
                }
            },
            platform_links_connected_at={"discord": "2024-01-01T00:00:00Z"},
        )

        result = await PlatformLinkService.get_linked_platforms(sample_user_id)

        # Whole entry, keys included: the frontend reads these exact names.
        assert result == {
            "discord": {
                "platform": "discord",
                "platformUserId": "discord123",
                "username": "TestUser#1234",
                "displayName": "Test User",
                "connectedAt": "2024-01-01T00:00:00Z",
            }
        }

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
