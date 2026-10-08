"""Promoting, renaming and removing one of a user's accounts on a Composio integration.

The account repository, Composio client, trigger registries and analytics are
the mocked seams; every decision in between is the real lifecycle service.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from functools import partial
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from tests.integration_account_factories import make_integration_account, make_integration_record

from app.models.integration_models import (
    IntegrationAccount,
    UserIntegrationDocument,
)
from app.services.analytics_service import AnalyticsEvents
from app.services.integrations.integration_account_lifecycle import (
    composio_integration,
    remove_account,
    update_account,
)
from app.utils.errors import AppError

USER_ID = "u1"
LIFECYCLE = "app.services.integrations.integration_account_lifecycle"
GMAIL_WORKFLOW_TRIGGERS = ["gmail_new_message", "gmail_poll_inbox"]


_record = partial(make_integration_record, user_id=USER_ID, integration_id="gmail")


async def _persist(
    user_id: str,
    integration_id: str,
    accounts: list[IntegrationAccount],
    primary_account_id: str | None,
) -> UserIntegrationDocument:
    return UserIntegrationDocument(
        user_id=user_id,
        integration_id=integration_id,
        accounts=accounts,
        primary_account_id=primary_account_id,
    )


@dataclass(frozen=True)
class Seams:
    get_record: AsyncMock
    save: AsyncMock
    capture: MagicMock
    workflow_triggers: AsyncMock
    subscriptions: AsyncMock
    composio: MagicMock
    disconnect: AsyncMock


@pytest.fixture
def seams() -> Iterator[Seams]:
    composio = MagicMock()
    composio.delete_connected_account = AsyncMock()
    with (
        patch(f"{LIFECYCLE}.get_account_record", AsyncMock(return_value=None)) as get_record,
        patch(f"{LIFECYCLE}.save_accounts", AsyncMock(side_effect=_persist)) as save,
        patch(f"{LIFECYCLE}.capture_event") as capture,
        patch(f"{LIFECYCLE}.TriggerService") as trigger_service,
        patch(f"{LIFECYCLE}.resync_subscriptions_for_trigger_names", AsyncMock()) as subscriptions,
        patch(f"{LIFECYCLE}.get_composio_service", return_value=composio),
        patch(f"{LIFECYCLE}.disconnect_integration", AsyncMock()) as disconnect,
    ):
        trigger_service.resync_user_workflow_triggers = AsyncMock()
        yield Seams(
            get_record=get_record,
            save=save,
            capture=capture,
            workflow_triggers=trigger_service.resync_user_workflow_triggers,
            subscriptions=subscriptions,
            composio=composio,
            disconnect=disconnect,
        )


def _assert_triggers_resynced(seams: Seams) -> None:
    seams.workflow_triggers.assert_awaited_once_with(USER_ID, GMAIL_WORKFLOW_TRIGGERS)
    seams.subscriptions.assert_awaited_once_with(USER_ID, set(GMAIL_WORKFLOW_TRIGGERS))


class TestComposioIntegration:
    def test_a_non_composio_integration_is_refused(self) -> None:
        with pytest.raises(AppError) as exc:
            composio_integration("deepwiki")

        assert exc.value == AppError(
            message="This integration does not support multiple accounts",
            status_code=404,
            meta={"integration_id": "deepwiki"},
        )


class TestUpdateAccount:
    @pytest.mark.parametrize("record", [None, _record()], ids=["no_record", "no_accounts"])
    async def test_an_integration_without_accounts_is_404(
        self, seams: Seams, record: UserIntegrationDocument | None
    ) -> None:
        seams.get_record.return_value = record

        with pytest.raises(AppError) as exc:
            await update_account(
                USER_ID, "gmail", "ca_1", nickname=None, rename=False, make_primary=False
            )

        assert exc.value == AppError(
            message="This integration has no connected accounts",
            status_code=404,
            meta={"integration_id": "gmail"},
        )
        seams.get_record.assert_awaited_once_with(USER_ID, "gmail")

    async def test_with_no_change_requested_the_record_comes_back_unsaved(
        self, seams: Seams
    ) -> None:
        record = _record(make_integration_account("ca_1"))
        seams.get_record.return_value = record

        result = await update_account(
            USER_ID, "gmail", "ca_1", nickname=None, rename=False, make_primary=False
        )

        assert result is record
        seams.get_record.assert_awaited_once_with(USER_ID, "gmail")
        seams.save.assert_not_awaited()

    async def test_an_unknown_account_is_404(self, seams: Seams) -> None:
        seams.get_record.return_value = _record(make_integration_account("ca_1"))

        with pytest.raises(AppError) as exc:
            await update_account(
                USER_ID, "gmail", "ca_nope", nickname="Work", rename=True, make_primary=False
            )

        assert exc.value == AppError(
            message="Account not found on this integration",
            status_code=404,
            meta={"integration_id": "gmail", "account": "ca_nope"},
        )
        seams.save.assert_not_awaited()

    async def test_an_expired_account_cannot_become_primary(self, seams: Seams) -> None:
        seams.get_record.return_value = _record(
            make_integration_account("ca_1"), make_integration_account("ca_2", "expired")
        )

        with pytest.raises(AppError) as exc:
            await update_account(
                USER_ID, "gmail", "ca_2", nickname=None, rename=False, make_primary=True
            )

        assert exc.value == AppError(
            message="Reconnect this account before making it primary",
            status_code=409,
            meta={"integration_id": "gmail"},
        )
        seams.save.assert_not_awaited()
        seams.workflow_triggers.assert_not_awaited()

    async def test_promoting_an_account_saves_it_primary_and_moves_the_triggers(
        self, seams: Seams
    ) -> None:
        record = _record(make_integration_account("ca_1"), make_integration_account("ca_2"))
        seams.get_record.return_value = record

        result = await update_account(
            USER_ID, "gmail", "ca_2", nickname=None, rename=False, make_primary=True
        )

        assert result.primary_account_id == "ca_2"
        assert seams.get_record.await_args_list == [call(USER_ID, "gmail")] * 2
        seams.save.assert_awaited_once_with(USER_ID, "gmail", record.accounts, "ca_2")
        _assert_triggers_resynced(seams)
        seams.capture.assert_called_once_with(
            USER_ID,
            AnalyticsEvents.INTEGRATION_PRIMARY_CHANGED,
            {"integration_id": "gmail", "account_count": 2},
        )

    async def test_renaming_a_secondary_account_keeps_the_primary(self, seams: Seams) -> None:
        seams.get_record.return_value = _record(
            make_integration_account("ca_1"), make_integration_account("ca_2"), primary="ca_2"
        )

        result = await update_account(
            USER_ID, "gmail", "ca_1", nickname="  Work  ", rename=True, make_primary=False
        )

        assert [(a.connected_account_id, a.nickname) for a in result.accounts] == [
            ("ca_1", "Work"),
            ("ca_2", None),
        ]
        assert result.primary_account_id == "ca_2"
        assert seams.get_record.await_args_list == [call(USER_ID, "gmail")] * 2
        seams.workflow_triggers.assert_not_awaited()


class TestRemoveAccount:
    async def test_removing_a_secondary_account_keeps_the_primary_and_its_triggers(
        self, seams: Seams
    ) -> None:
        seams.get_record.return_value = _record(
            make_integration_account("ca_1"),
            make_integration_account("ca_2"),
            make_integration_account("ca_3"),
            primary="ca_3",
        )

        result = await remove_account(USER_ID, "gmail", "ca_1")

        assert result is not None
        assert [a.connected_account_id for a in result.accounts] == ["ca_2", "ca_3"]
        assert result.primary_account_id == "ca_3"
        seams.get_record.assert_awaited_once_with(USER_ID, "gmail")
        seams.composio.delete_connected_account.assert_awaited_once_with("ca_1")
        seams.workflow_triggers.assert_not_awaited()
        seams.subscriptions.assert_not_awaited()
        seams.capture.assert_called_once_with(
            USER_ID,
            AnalyticsEvents.INTEGRATION_ACCOUNT_REMOVED,
            {"integration_id": "gmail", "account_count": 2},
        )

    async def test_removing_the_primary_hands_it_on_and_moves_the_triggers(
        self, seams: Seams
    ) -> None:
        seams.get_record.return_value = _record(
            make_integration_account("ca_1"), make_integration_account("ca_2")
        )

        result = await remove_account(USER_ID, "gmail", "ca_1")

        assert result is not None
        assert result.primary_account_id == "ca_2"
        _assert_triggers_resynced(seams)

    async def test_removing_the_last_account_disconnects_the_integration(
        self, seams: Seams
    ) -> None:
        seams.get_record.return_value = _record(make_integration_account("ca_1"))

        result = await remove_account(USER_ID, "gmail", "ca_1")

        assert result is None
        seams.disconnect.assert_awaited_once_with(USER_ID, "gmail")
        seams.save.assert_not_awaited()
        seams.capture.assert_called_once_with(
            USER_ID,
            AnalyticsEvents.INTEGRATION_ACCOUNT_REMOVED,
            {"integration_id": "gmail", "account_count": 0},
        )
