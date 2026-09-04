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
from app.models.payment_models import PlanType
from app.models.platform_models import (
    DisconnectPlatformResponse,
    InitiatePlatformConnectResponse,
    PendingPlatformRegistrationDocument,
)
from app.models.user_models import UserDocument
from app.services.analytics_service import AnalyticsEvents
from app.services.platform_link_service import (
    Platform,
    PlatformLinkService,
    disconnect_platform_account,
    reap_abandoned_imessage_registrations,
    register_pending_imessage_number,
    start_platform_connect,
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

    async def test_a_pending_number_that_differs_is_released_too(
        self, mock_repo, mock_pending_repo, sample_user_id
    ):
        """A re-run of connect registers a second number while the first stays
        linked. Deleting that pending record without releasing its number
        stranded the seat where even the sweep could not find it."""
        mock_repo.get.return_value = _user(
            id=sample_user_id, platform_links={"imessage": {"id": "+15551234567"}}
        )
        mock_repo.unlink_platform.return_value = _user(id=sample_user_id)
        mock_pending_repo.get_for_user.return_value = _pending(sample_user_id, "+15559999999")

        with patch(
            "app.services.platform_link_service.unregister_shared_user",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_unregister:
            await PlatformLinkService.unlink_account(sample_user_id, "imessage")

        assert sorted(call.args[0] for call in mock_unregister.await_args_list) == [
            "+15551234567",
            "+15559999999",
        ]
        # Scoped to this user and platform, not a bare collection scan.
        mock_pending_repo.get_for_user.assert_awaited_once_with(sample_user_id, "imessage")
        mock_pending_repo.delete_for_user.assert_awaited_once_with(sample_user_id, "imessage")

    async def test_a_number_photon_would_not_release_stays_tracked_for_the_sweep(
        self, mock_repo, mock_pending_repo, sample_user_id
    ):
        """The sweep only scans pending records. Deleting the record after a
        failed release left the linked number registered on Photon with nothing
        in GAIA referencing it, so it could never be retried."""
        mock_repo.get.return_value = _user(
            id=sample_user_id, platform_links={"imessage": {"id": "+15551234567"}}
        )
        mock_repo.unlink_platform.return_value = _user(id=sample_user_id)

        with (
            patch(
                "app.services.platform_link_service.unregister_shared_user",
                new_callable=AsyncMock,
                side_effect=_photon_down(),
            ),
            patch("app.services.platform_link_service.log") as mock_log,
        ):
            result = await PlatformLinkService.unlink_account(sample_user_id, "imessage")

        assert result.status == "disconnected"
        mock_pending_repo.delete_for_user.assert_not_awaited()
        mock_pending_repo.record.assert_awaited_once()
        recorded = mock_pending_repo.record.await_args.kwargs
        assert recorded["user_id"] == sample_user_id
        assert recorded["platform"] == "imessage"
        assert recorded["platform_user_id"] == "+15551234567"
        # Timezone-aware, or the sweep's TTL comparison silently drifts by the
        # host's offset.
        assert recorded["created_at"].tzinfo is UTC
        # One stranded number fits on the record, so nothing is unrecoverable
        # and the error must stay quiet.
        mock_log.error.assert_not_called()

    async def test_a_pending_record_for_the_linked_number_is_released_once(
        self, mock_repo, mock_pending_repo, sample_user_id
    ):
        """The linked number is usually also the pending one; releasing it twice
        would hand Photon a second delete for a seat it no longer holds."""
        mock_repo.get.return_value = _user(
            id=sample_user_id, platform_links={"imessage": {"id": "+15551234567"}}
        )
        mock_repo.unlink_platform.return_value = _user(id=sample_user_id)
        mock_pending_repo.get_for_user.return_value = _pending(sample_user_id, "+15551234567")

        with patch(
            "app.services.platform_link_service.unregister_shared_user",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_unregister:
            await PlatformLinkService.unlink_account(sample_user_id, "imessage")

        assert mock_unregister.await_count == 1
        assert mock_unregister.await_args.args[0] == "+15551234567"

    async def test_a_second_unreleasable_number_is_named_rather_than_dropped(
        self, mock_repo, mock_pending_repo, sample_user_id
    ):
        """Only one number fits on the pending record. The other cannot be
        retried by the sweep, so it has to be shouted about rather than lost."""
        mock_repo.get.return_value = _user(
            id=sample_user_id, platform_links={"imessage": {"id": "+15551234567"}}
        )
        mock_repo.unlink_platform.return_value = _user(id=sample_user_id)
        mock_pending_repo.get_for_user.return_value = _pending(sample_user_id, "+15559999999")

        with (
            patch(
                "app.services.platform_link_service.unregister_shared_user",
                new_callable=AsyncMock,
                side_effect=_photon_down(),
            ),
            patch("app.services.platform_link_service.log") as mock_log,
        ):
            await PlatformLinkService.unlink_account(sample_user_id, "imessage")

        # The pending record keeps the first, so the sweep can retry it.
        assert mock_pending_repo.record.await_args.kwargs["platform_user_id"] == "+15559999999"
        mock_pending_repo.delete_for_user.assert_not_awaited()
        # The second is unrecoverable and must not vanish quietly. Every field
        # is asserted: an operator chasing these by hand has only this line.
        assert mock_log.error.call_count == 1
        assert (
            mock_log.error.call_args.args[0]
            == "imessage seats left registered with nothing tracking them"
        )
        assert mock_log.error.call_args.kwargs == {
            "user": {"id": sample_user_id},
            "provider": "imessage",
            "stranded": 1,
            # The number itself, not just how many: the pending record holds
            # only the first, so this line is the sole trace of the second.
            "untracked": ["+15551234567"],
            "fix": "release these numbers on Photon by hand; the sweep cannot see them",
        }

    async def test_a_user_with_neither_a_link_nor_a_pending_record_calls_photon_never(
        self, mock_repo, mock_pending_repo, sample_user_id
    ):
        mock_repo.get.return_value = _user(id=sample_user_id)
        mock_repo.unlink_platform.return_value = _user(id=sample_user_id)
        mock_pending_repo.get_for_user.return_value = None

        with patch(
            "app.services.platform_link_service.unregister_shared_user", new_callable=AsyncMock
        ) as mock_unregister:
            await PlatformLinkService.unlink_account(sample_user_id, "imessage")

        mock_unregister.assert_not_awaited()
        mock_pending_repo.delete_for_user.assert_awaited_once_with(sample_user_id, "imessage")

    async def test_a_non_imessage_unlink_still_clears_its_pending_record(
        self, mock_repo, mock_pending_repo, sample_user_id
    ):
        # The early return for other platforms must not skip the cleanup.
        mock_repo.get.return_value = _user(
            id=sample_user_id, platform_links={"discord": {"id": "d1"}}
        )
        mock_repo.unlink_platform.return_value = _user(id=sample_user_id)

        await PlatformLinkService.unlink_account(sample_user_id, "discord")

        mock_pending_repo.delete_for_user.assert_awaited_once_with(sample_user_id, "discord")
        mock_pending_repo.record.assert_not_awaited()

    async def test_each_release_is_attributed_to_the_user_unlinking(
        self, mock_repo, mock_pending_repo, sample_user_id
    ):
        """The release helper is handed the user id, not just the number.

        It is what the audit line and the failure warning are keyed on — a
        release that cannot say whose seat it freed is unauditable.
        """
        mock_repo.get.return_value = _user(
            id=sample_user_id, platform_links={"imessage": {"id": "+15551234567"}}
        )
        mock_repo.unlink_platform.return_value = _user(id=sample_user_id)
        mock_pending_repo.get_for_user.return_value = _pending(sample_user_id, "+15559999999")

        with patch(
            "app.services.platform_link_service._release_imessage_number",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_release:
            await PlatformLinkService.unlink_account(sample_user_id, "imessage")

        assert sorted(call.args for call in mock_release.await_args_list) == [
            (sample_user_id, "+15551234567"),
            (sample_user_id, "+15559999999"),
        ]

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


PLAN_PATCH = "app.services.platform_link_service.payment_service.get_cached_plan_type"


class TestStartPlatformConnect:
    async def test_unsupported_platform_error_names_the_valid_platforms(self):
        with pytest.raises(AppError) as exc_info:
            await start_platform_connect("user-1", "twitch")

        error = exc_info.value
        assert error.status_code == 400
        assert error.message == "Unsupported platform 'twitch'"
        assert error.fix == "Use one of: discord, slack, telegram, whatsapp, imessage"

    async def test_discord_oauth_builds_state_and_url(self):
        with (
            patch("app.services.platform_link_service.settings") as mock_settings,
            patch(
                "app.services.platform_link_service.create_oauth_state",
                new_callable=AsyncMock,
                return_value="state123",
            ) as mock_state,
        ):
            mock_settings.DISCORD_OAUTH_CLIENT_ID = "client_123"
            mock_settings.DISCORD_OAUTH_REDIRECT_URI = "http://localhost/callback"

            result = await start_platform_connect("user-1", "discord")

        # Every kwarg: a state filed under the wrong user or integration is a
        # callback that can never be redeemed.
        mock_state.assert_awaited_once_with(
            user_id="user-1",
            redirect_path="/settings?section=linked-accounts",
            integration_id="discord",
        )
        assert result == InitiatePlatformConnectResponse(
            auth_url=(
                "https://discord.com/api/oauth2/authorize"
                "?client_id=client_123"
                "&redirect_uri=http%3A//localhost/callback"
                "&response_type=code&scope=identify&state=state123"
            ),
            auth_type="oauth",
        )
        # OAuth responses explicitly carry no instructions and no action link —
        # the manual-flow fields must be present-and-None, never defaulted away.
        assert result.model_fields_set == {"auth_url", "auth_type", "instructions", "action_link"}

    async def test_slack_oauth_builds_state_and_url(self):
        with (
            patch("app.services.platform_link_service.settings") as mock_settings,
            patch(
                "app.services.platform_link_service.create_oauth_state",
                new_callable=AsyncMock,
                return_value="slack_state",
            ) as mock_state,
        ):
            mock_settings.DISCORD_OAUTH_CLIENT_ID = None
            mock_settings.SLACK_OAUTH_CLIENT_ID = "client_slack"
            mock_settings.SLACK_OAUTH_REDIRECT_URI = "http://localhost/slack/cb"

            result = await start_platform_connect("user-1", "slack")

        mock_state.assert_awaited_once_with(
            user_id="user-1",
            redirect_path="/settings?section=linked-accounts",
            integration_id="slack",
        )
        assert result == InitiatePlatformConnectResponse(
            auth_url=(
                "https://slack.com/oauth/v2/authorize"
                "?client_id=client_slack"
                "&redirect_uri=http%3A//localhost/slack/cb"
                "&user_scope=identity.basic&state=slack_state"
            ),
            auth_type="oauth",
        )
        assert result.model_fields_set == {"auth_url", "auth_type", "instructions", "action_link"}

    async def test_unconfigured_discord_is_501_even_when_slack_oauth_exists(self):
        """An unconfigured platform must raise, not fall into the other
        platform's OAuth branch — the and/or gate keeps each flow its own."""
        with patch("app.services.platform_link_service.settings") as mock_settings:
            mock_settings.DISCORD_OAUTH_CLIENT_ID = None
            mock_settings.SLACK_OAUTH_CLIENT_ID = "client_slack"

            with pytest.raises(AppError) as exc_info:
                await start_platform_connect("user-1", "discord")

        error = exc_info.value
        assert error.status_code == 501
        assert error.message == "discord connect is not configured"
        assert error.fix == (
            "Connect this platform from the GAIA settings page once OAuth is set up"
        )

    async def test_unconfigured_slack_is_501_even_when_discord_oauth_exists(self):
        with patch("app.services.platform_link_service.settings") as mock_settings:
            mock_settings.DISCORD_OAUTH_CLIENT_ID = "client_123"
            mock_settings.SLACK_OAUTH_CLIENT_ID = None

            with pytest.raises(AppError) as exc_info:
                await start_platform_connect("user-1", "slack")

        error = exc_info.value
        assert error.status_code == 501
        assert error.message == "slack connect is not configured"

    async def test_telegram_falls_back_to_the_default_bot_username(self):
        with patch("app.services.platform_link_service.settings") as mock_settings:
            mock_settings.TELEGRAM_BOT_USERNAME = None

            result = await start_platform_connect("user-1", "telegram")

        assert result.auth_url is None
        assert result.instructions == (
            "Open Telegram and message @gaia_bot with /auth to link your account."
        )
        assert result.action_link == "https://t.me/gaia_bot"
        # auth_url is explicitly None for a manual flow, not just defaulted.
        assert result.model_fields_set == {"auth_url", "auth_type", "instructions", "action_link"}

    async def test_whatsapp_manual_flow_builds_the_wa_me_link(self):
        with patch("app.services.platform_link_service.settings") as mock_settings:
            mock_settings.WHATSAPP_PHONE_NUMBER = "15551234567"

            result = await start_platform_connect("user-1", "whatsapp")

        assert result.auth_url is None
        assert result.instructions == (
            "Open WhatsApp and send /auth to the GAIA WhatsApp number to link your account."
        )
        assert result.action_link == "https://wa.me/15551234567"
        assert result.model_fields_set == {"auth_url", "auth_type", "instructions", "action_link"}

    async def test_imessage_without_phone_is_a_422_carrying_photon_context(self):
        """The why/fix are the only explanation the caller gets for why a phone
        is mandatory — they must arrive intact, not defaulted away."""
        with (
            patch(PLAN_PATCH, new_callable=AsyncMock, return_value=PlanType.PRO),
            pytest.raises(AppError) as exc_info,
        ):
            await start_platform_connect("user-1", "imessage", phone=None)

        error = exc_info.value
        assert error.status_code == 422
        assert error.message == (
            "A phone number in E.164 format (e.g. +15551234567) is required for iMessage."
        )
        assert error.why == "Photon's shared pool delivers only to allowlisted numbers"
        assert error.fix == "Pass a phone number in E.164 format (e.g. +15551234567)"


class TestDisconnectPlatformAccount:
    async def test_success_clears_bot_cache_and_audits(self, sample_user_id):
        link_entry = {"platformUserId": "DISC999"}
        unlink_result = DisconnectPlatformResponse(status="disconnected", platform="discord")
        with (
            patch(
                "app.services.platform_link_service.PlatformLinkService.get_linked_platforms",
                new_callable=AsyncMock,
                return_value={"discord": link_entry},
            ) as mock_get,
            patch(
                "app.services.platform_link_service.PlatformLinkService.unlink_account",
                new_callable=AsyncMock,
                return_value=unlink_result,
            ) as mock_unlink,
            patch("app.services.platform_link_service.redis_cache") as mock_cache,
            patch("app.services.platform_link_service.capture_context_event") as mock_capture,
            patch("app.services.platform_link_service.log") as mock_log,
        ):
            mock_cache.client = AsyncMock()
            result = await disconnect_platform_account(sample_user_id, "discord")

        assert result is unlink_result
        # The id is what scopes the lookup — a None here would silently match nothing.
        mock_get.assert_awaited_once_with(sample_user_id)
        mock_unlink.assert_awaited_once_with(sample_user_id, "discord")
        mock_cache.client.delete.assert_awaited_once_with("bot_user:discord:DISC999")
        mock_log.audit.assert_called_once_with(
            "platform account unlinked",
            actor=sample_user_id,
            provider="discord",
        )
        mock_capture.assert_called_once_with(
            AnalyticsEvents.INTEGRATION_DISCONNECTED, {"integration_id": "discord"}
        )

    async def test_never_linked_platform_is_a_404_not_a_silent_noop(self, sample_user_id):
        with (
            patch(
                "app.services.platform_link_service.PlatformLinkService.get_linked_platforms",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "app.services.platform_link_service.PlatformLinkService.unlink_account",
                new_callable=AsyncMock,
            ) as mock_unlink,
            pytest.raises(AppError) as exc_info,
        ):
            await disconnect_platform_account(sample_user_id, "discord")

        error = exc_info.value
        assert error.status_code == 404
        assert error.message == "No discord account is linked"
        assert error.fix == "Check account/linked-accounts for what is actually connected"
        mock_unlink.assert_not_awaited()

    async def test_unlink_rejection_is_audited_and_reraised_as_404(self, sample_user_id):
        with (
            patch(
                "app.services.platform_link_service.PlatformLinkService.get_linked_platforms",
                new_callable=AsyncMock,
                return_value={"discord": {"platformUserId": "DISC999"}},
            ),
            patch(
                "app.services.platform_link_service.PlatformLinkService.unlink_account",
                new_callable=AsyncMock,
                side_effect=ValueError("boom"),
            ) as mock_unlink,
            patch("app.services.platform_link_service.log") as mock_log,
            pytest.raises(AppError) as exc_info,
        ):
            await disconnect_platform_account(sample_user_id, "discord")

        error = exc_info.value
        assert error.status_code == 404
        assert error.message == "boom"
        mock_unlink.assert_awaited_once_with(sample_user_id, "discord")
        # Whole audit line, every field: this is the trace an operator reconciles
        # a rejected unlink against.
        mock_log.audit.assert_called_once_with(
            "platform account unlink rejected",
            actor=sample_user_id,
            provider="discord",
            reason="unlink_failed",
            error_type="ValueError",
        )
