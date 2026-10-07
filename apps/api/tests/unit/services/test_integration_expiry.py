"""The connected -> expired transition of one account (app/services/integrations/integration_expiry.py).

Persistence is mocked at the repository, so the real save path — and with it
the integration status derived from the account set — runs under test.
"""

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.notifications import CHANNEL_TYPE_INAPP
from app.models.integration_models import (
    IntegrationAccount,
    IntegrationAccountStatus,
    UserIntegrationDocument,
)
from app.models.notification.notification_models import ActionStyle, NotificationType
from app.services.integrations.integration_expiry import (
    AccountExpired,
    _expiry_body,
    announce_account_expiry,
    expire_account,
)

MODULE = "app.services.integrations.integration_expiry"
ACCOUNTS_MODULE = "app.services.integrations.integration_accounts"

USER_ID = "507f1f77bcf86cd799439011"
INTEGRATION_ID = "notion"
GENERIC_LEAD = "GAIA lost access to your Notion account and can no longer use it."


def _account(account_id: str, status: IntegrationAccountStatus = "connected") -> IntegrationAccount:
    return IntegrationAccount(
        connected_account_id=account_id, label=f"{account_id}@acme.com", status=status
    )


def _record(*accounts: IntegrationAccount, primary: str = "ca_1") -> UserIntegrationDocument:
    return UserIntegrationDocument(
        user_id=USER_ID,
        integration_id=INTEGRATION_ID,
        status="connected",
        accounts=list(accounts),
        primary_account_id=primary,
    )


@pytest.fixture
def repo(fake_redis: object) -> Iterator[MagicMock]:
    """Mock the user_integrations repository; saves echo back the document they would write."""

    async def save(user_id: str, integration_id: str, **fields: object) -> UserIntegrationDocument:
        fields.pop("expired_reason", None)
        return UserIntegrationDocument(user_id=user_id, integration_id=integration_id, **fields)

    with patch(f"{ACCOUNTS_MODULE}.user_integration_repository") as repository:
        repository.get_for_user = AsyncMock(return_value=None)
        repository.save_accounts = AsyncMock(side_effect=save)
        yield repository


@pytest.fixture(autouse=True)
def vfs_sync() -> Iterator[MagicMock]:
    with patch(f"{MODULE}.schedule_user_integrations_sync") as sync:
        yield sync


def _saved_accounts(repo: MagicMock) -> dict[str, str]:
    accounts = repo.save_accounts.await_args.kwargs["accounts"]
    return {a.connected_account_id: a.status for a in accounts}


class TestNoOpGuards:
    async def test_it_never_fabricates_a_record_for_an_integration_the_user_never_added(
        self, repo: MagicMock
    ) -> None:
        outcome = await expire_account(USER_ID, INTEGRATION_ID, "ca_1", trigger="webhook")

        assert outcome is None
        repo.save_accounts.assert_not_awaited()

    async def test_an_account_gaia_does_not_track_changes_nothing(self, repo: MagicMock) -> None:
        """A superseded or legacy account dying must not mark a live integration expired."""
        repo.get_for_user.return_value = _record(_account("ca_1"))

        outcome = await expire_account(USER_ID, INTEGRATION_ID, "ca_gone", trigger="webhook")

        assert outcome is None
        repo.save_accounts.assert_not_awaited()

    async def test_an_already_expired_account_does_not_expire_again(self, repo: MagicMock) -> None:
        repo.get_for_user.return_value = _record(_account("ca_1", status="expired"))

        outcome = await expire_account(USER_ID, INTEGRATION_ID, "ca_1", trigger="webhook")

        assert outcome is None
        repo.save_accounts.assert_not_awaited()


class TestOneAccountOfSeveral:
    async def test_only_the_named_account_dies_and_the_integration_stays_connected(
        self, repo: MagicMock
    ) -> None:
        repo.get_for_user.return_value = _record(_account("ca_1"), _account("ca_2"))

        outcome = await expire_account(
            USER_ID, INTEGRATION_ID, "ca_2", trigger="webhook", reason="token_expired"
        )

        assert outcome is not None
        assert _saved_accounts(repo) == {"ca_1": "connected", "ca_2": "expired"}
        assert repo.save_accounts.await_args.kwargs["status"] == "connected"
        assert repo.save_accounts.await_args.kwargs["primary_account_id"] == "ca_1"
        assert outcome.integration_expired is False
        assert outcome.was_primary is False
        assert outcome.stops_workflows is False

    async def test_no_account_named_means_the_primary(self, repo: MagicMock) -> None:
        """The tool path runs unpinned calls as the primary, so that is what died."""
        repo.get_for_user.return_value = _record(_account("ca_1"), _account("ca_2"), primary="ca_2")

        outcome = await expire_account(USER_ID, INTEGRATION_ID, None, trigger="tool_execution")

        assert outcome is not None
        assert _saved_accounts(repo) == {"ca_1": "connected", "ca_2": "expired"}
        assert outcome.was_primary is True

    async def test_a_dead_primary_halts_workflows_even_with_another_account_alive(
        self, repo: MagicMock
    ) -> None:
        """Workflow triggers are registered on the primary only."""
        repo.get_for_user.return_value = _record(_account("ca_1"), _account("ca_2"))

        outcome = await expire_account(USER_ID, INTEGRATION_ID, "ca_1", trigger="webhook")

        assert outcome is not None
        assert outcome.integration_expired is False
        assert outcome.stops_workflows is True

    async def test_the_last_live_account_takes_the_integration_with_it(
        self, repo: MagicMock
    ) -> None:
        repo.get_for_user.return_value = _record(
            _account("ca_1"), _account("ca_2", status="expired")
        )

        outcome = await expire_account(
            USER_ID, INTEGRATION_ID, "ca_1", trigger="webhook", reason="refresh_token_revoked"
        )

        assert outcome is not None
        assert repo.save_accounts.await_args.kwargs["status"] == "expired"
        assert repo.save_accounts.await_args.kwargs["expired_reason"] == "refresh_token_revoked"
        assert outcome.integration_expired is True

    async def test_the_workspace_is_resynced(self, repo: MagicMock, vfs_sync: MagicMock) -> None:
        repo.get_for_user.return_value = _record(_account("ca_1"))

        await expire_account(USER_ID, INTEGRATION_ID, "ca_1", trigger="webhook")

        vfs_sync.assert_called_once_with(USER_ID)


@pytest.fixture
def announce_seams() -> Iterator[dict[str, MagicMock]]:
    with (
        patch(f"{MODULE}.websocket_manager") as ws,
        patch(f"{MODULE}.notification_service") as notifications,
    ):
        ws.broadcast_to_user = AsyncMock()
        notifications.create_notification = AsyncMock()
        yield {"ws": ws, "notify": notifications}


def _expired(*, count: int = 1, integration_expired: bool = True) -> AccountExpired:
    return AccountExpired(
        account=_account("ca_1", status="expired"),
        account_count=count,
        was_primary=True,
        integration_expired=integration_expired,
    )


class TestTheAnnouncement:
    async def test_an_open_page_flips_to_the_integrations_new_status(
        self, announce_seams: dict[str, MagicMock]
    ) -> None:
        await announce_account_expiry(
            USER_ID, INTEGRATION_ID, _expired(count=2, integration_expired=False), [], None
        )

        announce_seams["ws"].broadcast_to_user.assert_awaited_once_with(
            user_id=USER_ID,
            message={
                "type": "integration_status_update",
                "data": {"integration_id": INTEGRATION_ID, "status": "connected"},
            },
        )

    async def test_a_single_account_is_announced_by_integration_name(
        self, announce_seams: dict[str, MagicMock]
    ) -> None:
        await announce_account_expiry(USER_ID, INTEGRATION_ID, _expired(), [], None)

        request = announce_seams["notify"].create_notification.await_args.args[0]
        assert request.content.title == "Notion disconnected"

    async def test_one_of_several_accounts_is_named_so_the_user_knows_which_to_reconnect(
        self, announce_seams: dict[str, MagicMock]
    ) -> None:
        await announce_account_expiry(
            USER_ID, INTEGRATION_ID, _expired(count=2, integration_expired=False), [], None
        )

        request = announce_seams["notify"].create_notification.await_args.args[0]
        assert request.content.title == "Notion (ca_1@acme.com) disconnected"

    async def test_it_is_an_in_app_warning_with_a_primary_reconnect_deep_link(
        self, announce_seams: dict[str, MagicMock]
    ) -> None:
        await announce_account_expiry(USER_ID, INTEGRATION_ID, _expired(), ["Digest"], None)

        request = announce_seams["notify"].create_notification.await_args.args[0]
        assert request.user_id == USER_ID
        assert request.type == NotificationType.WARNING
        assert [c.channel_type for c in request.channels] == [CHANNEL_TYPE_INAPP]
        (action,) = request.content.actions
        assert action.label == "Reconnect"
        assert action.style == ActionStyle.PRIMARY
        assert action.config.redirect.url == f"/integrations?id={INTEGRATION_ID}"
        assert request.metadata == {"integration_id": INTEGRATION_ID, "paused_workflows": 1}

    async def test_the_notification_carries_the_cause(
        self, announce_seams: dict[str, MagicMock]
    ) -> None:
        await announce_account_expiry(
            USER_ID, INTEGRATION_ID, _expired(), [], "refresh_token_revoked"
        )

        body = announce_seams["notify"].create_notification.await_args.args[0].content.body
        assert body.startswith("Your Notion account revoked GAIA's access.")


class TestTheBodySaysWhyTheConnectionDied:
    """expired_reason is stored for every expiry, but shown only when statable in plain language.

    Composio publishes no enum for it, and the tool-execution path puts a raw
    error sentence in the same field.
    """

    def test_a_revoked_reason_names_the_cause_instead_of_the_generic_lead(self) -> None:
        body = _expiry_body("Notion", (), "refresh_token_revoked")

        assert (
            body
            == "Your Notion account revoked GAIA's access. Reconnect to pick up where you left off."
        )

    def test_an_expired_reason_blames_the_sign_in(self) -> None:
        body = _expiry_body("Notion", (), "token_expired")

        assert (
            body
            == "The sign-in for your Notion account expired. Reconnect to pick up where you left off."
        )

    def test_a_reason_we_do_not_recognise_falls_back_to_the_generic_lead(self) -> None:
        body = _expiry_body("Notion", (), "auth_config_disabled")

        assert body.startswith(GENERIC_LEAD)
        assert "auth_config_disabled" not in body

    def test_no_reason_at_all_keeps_the_generic_lead(self) -> None:
        assert _expiry_body("Notion", (), None).startswith(GENERIC_LEAD)

    def test_a_raw_composio_tool_error_is_developer_text_and_never_reaches_the_body(self) -> None:
        raw = "Composio error 1810: connected account was revoked for user 507f1f77bcf86cd799439011"

        body = _expiry_body("Notion", (), raw)

        assert body.startswith(GENERIC_LEAD)
        assert "1810" not in body
        assert "507f1f77bcf86cd799439011" not in body

    def test_the_cause_is_stated_alongside_a_single_named_paused_workflow(self) -> None:
        body = _expiry_body("Notion", ["Morning digest"], "refresh_token_revoked")

        assert body == (
            "Your Notion account revoked GAIA's access. "
            "Your “Morning digest” workflow is paused until you reconnect."
        )

    def test_the_cause_is_stated_alongside_a_count_of_paused_workflows(self) -> None:
        body = _expiry_body("Notion", ["Morning digest", "Invoice filing"], "refresh_token_revoked")

        assert body == (
            "Your Notion account revoked GAIA's access. 2 workflows are paused until you reconnect."
        )
