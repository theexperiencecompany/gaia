"""The account tools through the real tool, the real lifecycle service and match_account.

The account repository, Composio, the trigger registries and analytics are the mocked seams.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from functools import partial
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import ValidationError
import pytest

from app.agents.tools.integration_account_tools import (
    disconnect_integration,
    rename_integration_account,
    set_primary_integration_account,
)
from app.models.integration_models import IntegrationAccount, UserIntegrationDocument
from app.services.analytics_service import AnalyticsEvents
from tests.integration_account_factories import (
    make_integration_account,
    make_integration_record,
    with_nickname,
)

USER_ID = "user-1"
CONFIG = {"metadata": {"user_id": USER_ID}}
LIFECYCLE = "app.services.integrations.integration_account_lifecycle"
TOOLS = "app.agents.tools.integration_account_tools"

_record = partial(make_integration_record, user_id=USER_ID, integration_id="googlecalendar")


@dataclass(frozen=True)
class Seams:
    get_record: AsyncMock
    save: AsyncMock
    name: AsyncMock
    capture: MagicMock
    workflow_triggers: AsyncMock
    revoke: AsyncMock
    disconnect_all: AsyncMock
    disconnect_one_connection: AsyncMock
    tool_capture: MagicMock


async def _persist(
    user_id: str,
    integration_id: str,
    accounts: list[IntegrationAccount],
    primary_account_id: str | None,
) -> UserIntegrationDocument:
    return make_integration_record(
        *accounts, user_id=user_id, integration_id=integration_id, primary=primary_account_id
    )


@pytest.fixture
def seams() -> Iterator[Seams]:
    with (
        patch(f"{LIFECYCLE}.get_account_record", AsyncMock(return_value=None)) as get_record,
        patch(f"{LIFECYCLE}.save_accounts", AsyncMock(side_effect=_persist)) as save,
        patch(f"{LIFECYCLE}.set_account_nickname", AsyncMock()) as name,
        patch(f"{LIFECYCLE}.capture_event") as capture,
        patch(f"{LIFECYCLE}.TriggerService") as trigger_service,
        patch(f"{LIFECYCLE}.resync_subscriptions_for_trigger_names", AsyncMock()),
        patch(f"{LIFECYCLE}.get_composio_service") as composio,
        patch(f"{LIFECYCLE}.disconnect_integration", AsyncMock()) as disconnect_all,
        patch(
            f"{TOOLS}.integration_connection_service.disconnect_integration", AsyncMock()
        ) as disconnect_one_connection,
        patch(f"{TOOLS}.capture_event") as tool_capture,
        patch("app.agents.tools.core.mutations.log"),
    ):
        name.side_effect = lambda _u, _i, account_id, nickname: with_nickname(
            get_record.return_value, account_id, nickname
        )
        trigger_service.resync_user_workflow_triggers = AsyncMock()
        composio.return_value.delete_connected_account = AsyncMock()
        yield Seams(
            get_record=get_record,
            save=save,
            name=name,
            capture=capture,
            workflow_triggers=trigger_service.resync_user_workflow_triggers,
            revoke=composio.return_value.delete_connected_account,
            disconnect_all=disconnect_all,
            disconnect_one_connection=disconnect_one_connection,
            tool_capture=tool_capture,
        )


def _two_calendars() -> UserIntegrationDocument:
    return _record(
        make_integration_account("ca_1", label="Google Calendar account 1"),
        make_integration_account(
            "ca_2", label="Google Calendar account 2", identity={"email": "me@gmail.com"}
        ),
    )


async def _rename(account: str, name: str, config: dict[str, object] = CONFIG) -> str:
    return await rename_integration_account.ainvoke(
        {"integration_id": "googlecalendar", "account": account, "name": name}, config=config
    )


class TestRenameIntegrationAccount:
    async def test_a_generic_account_gets_the_name_given(self, seams: Seams) -> None:
        seams.get_record.return_value = _two_calendars()

        result = await _rename("Google Calendar account 2", "Personal")

        assert result == "Renamed Google Calendar account 2 to Personal."
        seams.name.assert_awaited_once_with(USER_ID, "googlecalendar", "ca_2", "Personal")
        # One account is written in place, never the whole list another rename may be writing.
        seams.save.assert_not_awaited()
        seams.capture.assert_called_once_with(
            USER_ID,
            AnalyticsEvents.INTEGRATION_ACCOUNT_RENAMED,
            {"integration_id": "googlecalendar", "cleared": False},
        )

    async def test_the_account_can_be_named_by_its_identity(self, seams: Seams) -> None:
        seams.get_record.return_value = _two_calendars()

        result = await _rename("ME@gmail.com", "Personal")

        assert result == "Renamed Google Calendar account 2 to Personal."

    async def test_an_empty_name_clears_it_and_says_what_shows_instead(self, seams: Seams) -> None:
        seams.get_record.return_value = _record(
            make_integration_account("ca_1", label="work@acme.com", nickname="Work")
        )

        result = await _rename("Work", "")

        assert result == "Cleared the name; the account shows as work@acme.com again."
        seams.name.assert_awaited_once_with(USER_ID, "googlecalendar", "ca_1", None)

    async def test_an_unknown_account_lists_the_real_names_and_changes_nothing(
        self, seams: Seams
    ) -> None:
        seams.get_record.return_value = _two_calendars()

        result = await _rename("Work", "Office")

        assert result == (
            "Error: No googlecalendar account is named 'Work' "
            "Fix: Use one of: Google Calendar account 1, Google Calendar account 2"
        )
        seams.name.assert_not_awaited()
        seams.capture.assert_not_called()

    async def test_an_integration_with_no_accounts_is_refused(self, seams: Seams) -> None:
        result = await _rename("Work", "Office")

        assert result == (
            "Error: The user has no connected googlecalendar accounts "
            "Fix: Check the integration_id against the connected integrations list"
        )
        seams.get_record.assert_awaited_once_with(USER_ID, "googlecalendar")

    async def test_an_integration_without_accounts_support_is_refused(self, seams: Seams) -> None:
        result = await rename_integration_account.ainvoke(
            {"integration_id": "deepwiki", "account": "x", "name": "y"}, config=CONFIG
        )

        assert result == "Error: This integration does not support multiple accounts"
        seams.get_record.assert_not_awaited()

    async def test_a_run_without_a_user_is_refused(self, seams: Seams) -> None:
        result = await _rename("Work", "Office", config={"metadata": {}})

        assert result == "Error: user authentication required."
        seams.get_record.assert_not_awaited()

    async def test_a_name_over_the_limit_is_rejected_before_anything_runs(
        self, seams: Seams
    ) -> None:
        with pytest.raises(ValidationError):
            await _rename("Google Calendar account 2", "x" * 61)

        seams.get_record.assert_not_awaited()


def _work_and_personal() -> UserIntegrationDocument:
    return _record(
        make_integration_account("ca_1", label="me@gmail.com", nickname="Personal"),
        make_integration_account("ca_2", label="work@acme.com"),
        primary="ca_1",
    )


class TestSetPrimaryIntegrationAccount:
    async def test_the_named_account_becomes_primary(self, seams: Seams) -> None:
        seams.get_record.return_value = _work_and_personal()

        result = await set_primary_integration_account.ainvoke(
            {"integration_id": "googlecalendar", "account": "WORK@acme.com"}, config=CONFIG
        )

        assert result == "work@acme.com is now the primary googlecalendar account."
        seams.save.assert_awaited_once_with(
            USER_ID, "googlecalendar", seams.get_record.return_value.accounts, "ca_2"
        )
        seams.workflow_triggers.assert_awaited_once()
        seams.name.assert_not_awaited()

    async def test_an_expired_account_cannot_become_primary(self, seams: Seams) -> None:
        seams.get_record.return_value = _record(
            make_integration_account("ca_1"), make_integration_account("ca_2", "expired")
        )

        result = await set_primary_integration_account.ainvoke(
            {"integration_id": "googlecalendar", "account": "ca_2@acme.com"}, config=CONFIG
        )

        assert result == "Error: Reconnect this account before making it primary"
        seams.save.assert_not_awaited()

    async def test_an_unknown_account_lists_the_real_names(self, seams: Seams) -> None:
        seams.get_record.return_value = _work_and_personal()

        result = await set_primary_integration_account.ainvoke(
            {"integration_id": "googlecalendar", "account": "School"}, config=CONFIG
        )

        assert result == (
            "Error: No googlecalendar account is named 'School' "
            "Fix: Use one of: Personal, work@acme.com"
        )
        seams.save.assert_not_awaited()


async def _disconnect(integration_id: str, account: str | None = None) -> str:
    args: dict[str, object] = {"integration_id": integration_id}
    if account is not None:
        args["account"] = account
    return await disconnect_integration.ainvoke(args, config=CONFIG)


class TestDisconnectIntegration:
    async def test_the_named_account_is_revoked_and_the_rest_stay(self, seams: Seams) -> None:
        seams.get_record.return_value = _work_and_personal()

        result = await _disconnect("googlecalendar", "Personal")

        assert result == "Disconnected Personal. The primary account is work@acme.com."
        seams.revoke.assert_awaited_once_with("ca_1")
        seams.save.assert_awaited_once()
        assert seams.save.await_args.args[2:] == (
            [seams.get_record.return_value.accounts[1]],
            "ca_2",
        )
        seams.disconnect_all.assert_not_awaited()

    async def test_with_several_accounts_and_none_named_nothing_is_removed(
        self, seams: Seams
    ) -> None:
        seams.get_record.return_value = _work_and_personal()

        result = await _disconnect("googlecalendar")

        assert result == (
            "Error: The user has 2 googlecalendar accounts Fix: Pass account as one of: "
            "Personal, work@acme.com, or ask the user which one"
        )
        seams.revoke.assert_not_awaited()
        seams.disconnect_all.assert_not_awaited()

    async def test_the_only_account_goes_without_being_named_and_disconnects_it(
        self, seams: Seams
    ) -> None:
        seams.get_record.return_value = _record(make_integration_account("ca_1"))

        result = await _disconnect("googlecalendar")

        assert result == (
            "Disconnected ca_1@acme.com, the only googlecalendar account, "
            "so googlecalendar is no longer connected."
        )
        seams.disconnect_all.assert_awaited_once_with(USER_ID, "googlecalendar")
        seams.revoke.assert_not_awaited()

    async def test_an_unknown_account_removes_nothing(self, seams: Seams) -> None:
        seams.get_record.return_value = _work_and_personal()

        result = await _disconnect("googlecalendar", "School")

        assert result.startswith("Error: No googlecalendar account is named 'School'")
        seams.revoke.assert_not_awaited()

    async def test_a_single_connection_integration_is_disconnected_whole(
        self, seams: Seams
    ) -> None:
        result = await _disconnect("deepwiki")

        assert result == "Disconnected deepwiki."
        seams.disconnect_one_connection.assert_awaited_once_with(USER_ID, "deepwiki")
        seams.tool_capture.assert_called_once_with(
            USER_ID, AnalyticsEvents.INTEGRATION_DISCONNECTED, {"integration_id": "deepwiki"}
        )
        seams.get_record.assert_not_awaited()

    async def test_a_single_connection_integration_takes_no_account(self, seams: Seams) -> None:
        result = await _disconnect("deepwiki", "Work")

        assert result == (
            "Error: deepwiki has one connection, not separate accounts "
            "Fix: Omit account to disconnect it"
        )
        seams.disconnect_one_connection.assert_not_awaited()

    async def test_an_unknown_integration_says_so(self, seams: Seams) -> None:
        seams.disconnect_one_connection.side_effect = ValueError("Integration nope not found")

        result = await _disconnect("nope")

        assert result == "Error: Integration nope not found Fix: Check the integration_id"
        seams.tool_capture.assert_not_called()
