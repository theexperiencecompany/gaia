"""Which account a call means: status derivation, primary choice, name matching, primary resolution."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.error_codes import INTEGRATION_NOT_CONNECTED
from app.models.integration_models import (
    IntegrationAccount,
    IntegrationAccountStatus,
    UserIntegrationDocument,
)
from app.services.integrations.integration_accounts import (
    derive_status,
    event_account_name,
    match_account,
    pick_primary,
    primary_connected_account_id,
)
from app.services.triggers.base import primary_account_for_trigger
from app.utils.errors import AppError
from app.utils.exceptions import TriggerRegistrationError

USER_ID = "u1"


def _account(
    account_id: str,
    status: IntegrationAccountStatus = "connected",
    *,
    nickname: str | None = None,
    identity: dict[str, str] | None = None,
) -> IntegrationAccount:
    return IntegrationAccount(
        connected_account_id=account_id,
        label=f"{account_id}@acme.com",
        nickname=nickname,
        identity=identity or {},
        status=status,
    )


def _record(*accounts: IntegrationAccount, primary: str | None = "ca_1") -> UserIntegrationDocument:
    return UserIntegrationDocument(
        user_id=USER_ID,
        integration_id="gmail",
        accounts=list(accounts),
        primary_account_id=primary,
    )


@pytest.fixture
def repo() -> Iterator[MagicMock]:
    with patch(
        "app.services.integrations.integration_accounts.user_integration_repository"
    ) as repository:
        repository.get_for_user = AsyncMock(return_value=None)
        yield repository


class TestDeriveStatus:
    def test_one_live_account_keeps_the_integration_connected(self) -> None:
        assert derive_status([_account("a", "expired"), _account("b")]) == "connected"

    def test_every_account_dead_expires_the_integration(self) -> None:
        assert derive_status([_account("a", "expired"), _account("b", "expired")]) == "expired"

    def test_no_accounts_is_still_pending(self) -> None:
        assert derive_status([]) == "created"


class TestPickPrimary:
    def test_the_current_primary_survives_while_it_exists(self) -> None:
        assert pick_primary([_account("a"), _account("b")], "b") == "b"

    def test_a_gone_primary_falls_to_the_oldest_live_account(self) -> None:
        accounts = [_account("a", "expired"), _account("b"), _account("c")]

        assert pick_primary(accounts, "gone") == "b"

    def test_with_nothing_live_the_oldest_account_holds_the_slot(self) -> None:
        """The user still needs one account to reconnect and default to."""
        assert pick_primary([_account("a", "expired"), _account("b", "expired")], None) == "a"

    def test_no_accounts_no_primary(self) -> None:
        assert pick_primary([], "a") is None


class TestMatchAccount:
    @pytest.mark.parametrize("name", ["Work", "ca_1@acme.com", "boss@corp.com", "  WORK "])
    def test_label_nickname_and_identity_values_all_name_the_account(self, name: str) -> None:
        record = _record(
            _account("ca_1", nickname="Work", identity={"email": "boss@corp.com"}),
            _account("ca_2"),
        )

        account = match_account(record, name)

        assert account is not None
        assert account.connected_account_id == "ca_1"

    def test_an_unknown_name_matches_nothing(self) -> None:
        assert match_account(_record(_account("ca_1")), "someone@else.com") is None


class TestPrimaryConnectedAccountId:
    async def test_it_is_the_primary_of_the_toolkits_integration(self, repo: MagicMock) -> None:
        repo.get_for_user.return_value = _record(_account("ca_1"), _account("ca_2"), primary="ca_2")

        assert await primary_connected_account_id(USER_ID, "GMAIL") == "ca_2"
        repo.get_for_user.assert_awaited_once_with(USER_ID, "gmail")

    async def test_no_accounts_is_the_reconnect_error(self, repo: MagicMock) -> None:
        with pytest.raises(AppError) as exc:
            await primary_connected_account_id(USER_ID, "GMAIL")

        assert exc.value.status_code == 403
        assert exc.value.code == INTEGRATION_NOT_CONNECTED
        assert exc.value.public == {"toolkit": "GMAIL"}

    async def test_an_expired_primary_is_named_in_the_reconnect_error(
        self, repo: MagicMock
    ) -> None:
        """Another account may still work, but the default cannot quietly switch to it."""
        repo.get_for_user.return_value = _record(_account("ca_1", "expired"), _account("ca_2"))

        with pytest.raises(AppError) as exc:
            await primary_connected_account_id(USER_ID, "GMAIL")

        assert exc.value.code == INTEGRATION_NOT_CONNECTED
        assert "ca_1@acme.com" in exc.value.why

    async def test_an_unknown_toolkit_is_a_server_error(self, repo: MagicMock) -> None:
        with pytest.raises(AppError) as exc:
            await primary_connected_account_id(USER_ID, "NOT_A_TOOLKIT")

        assert exc.value.status_code == 500
        repo.get_for_user.assert_not_awaited()


class TestEventAccountName:
    async def test_an_event_on_one_of_several_accounts_names_it(self, repo: MagicMock) -> None:
        repo.get_for_user.return_value = _record(
            _account("ca_1"), _account("ca_2", nickname="Personal")
        )

        name = await event_account_name(USER_ID, "GMAIL_NEW_GMAIL_MESSAGE", "ca_2")

        assert name == "Personal"
        repo.get_for_user.assert_awaited_once_with(USER_ID, "gmail")

    async def test_a_single_account_needs_no_name(self, repo: MagicMock) -> None:
        repo.get_for_user.return_value = _record(_account("ca_1"))

        assert await event_account_name(USER_ID, "GMAIL_NEW_GMAIL_MESSAGE", "ca_1") is None

    async def test_an_untracked_account_is_not_guessed(self, repo: MagicMock) -> None:
        repo.get_for_user.return_value = _record(_account("ca_1"), _account("ca_2"))

        assert await event_account_name(USER_ID, "GMAIL_NEW_GMAIL_MESSAGE", "ca_gone") is None

    async def test_a_trigger_of_no_known_integration_is_not_looked_up(
        self, repo: MagicMock
    ) -> None:
        assert await event_account_name(USER_ID, "WEATHER_ALERT", "ca_1") is None
        repo.get_for_user.assert_not_awaited()


class TestPrimaryAccountForTrigger:
    async def test_workflow_triggers_register_on_the_slugs_integration_primary(self) -> None:
        with patch(
            "app.services.triggers.base.primary_connected_account_id",
            AsyncMock(return_value="ca_primary"),
        ) as resolve:
            account = await primary_account_for_trigger(USER_ID, "GITHUB_COMMIT_EVENT")

        assert account == "ca_primary"
        resolve.assert_awaited_once_with(USER_ID, "GITHUB")

    async def test_a_slug_no_integration_owns_fails_registration(self) -> None:
        with pytest.raises(TriggerRegistrationError):
            await primary_account_for_trigger(USER_ID, "WEATHER_ALERT")
