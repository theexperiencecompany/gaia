"""Tests for the OAuth callbacks' reconnect lookup."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from pymongo.errors import PyMongoError
import pytest

from app.constants.integrations import INTEGRATION_STATUS_UPDATE_EVENT
from app.constants.log_tags import LogTag
from app.constants.waits import WaitCondition
from app.services.integrations import user_integration_status
from app.services.integrations.user_integration_status import reconnect_or_unknown

MODULE = "app.services.integrations.user_integration_status"


async def _answer(value: bool) -> bool:
    return value


async def _raise(error: Exception) -> bool:
    raise error


class TestReconnectOrUnknown:
    @pytest.mark.parametrize("connected_before", [True, False])
    async def test_an_answer_is_passed_through(self, connected_before: bool) -> None:
        assert await reconnect_or_unknown(_answer(connected_before), "gmail") is connected_before

    async def test_a_mongo_failure_is_unknown_and_names_the_integration(self) -> None:
        with patch(f"{MODULE}.log") as log:
            result = await reconnect_or_unknown(_raise(PyMongoError("down")), "gmail")

        assert result is None
        log.warning.assert_called_once()
        assert log.warning.call_args.args == (
            f"{LogTag.INTEGRATION} Could not tell whether the connect is a reconnect",
        )
        assert log.warning.call_args.kwargs == {
            "integration_id": "gmail",
            "error_type": "PyMongoError",
        }

    async def test_any_other_failure_still_raises(self) -> None:
        with pytest.raises(RuntimeError, match="bug"):
            await reconnect_or_unknown(_raise(RuntimeError("bug")), "gmail")


class TestPublishConnected:
    async def test_a_connect_meets_everything_waiting_on_that_integration(self) -> None:
        with (
            patch(f"{MODULE}.schedule_user_integrations_sync"),
            patch(f"{MODULE}.websocket_manager.broadcast_to_user", AsyncMock()),
            patch(f"{MODULE}.report_wait_met", AsyncMock()) as report,
        ):
            await user_integration_status.publish_connected("user-1", "gmail")

        report.assert_awaited_once_with("user-1", WaitCondition.INTEGRATION_CONNECTED, "gmail")

    async def test_a_connect_continues_the_conversations_waiting_on_it(self) -> None:
        with (
            patch(f"{MODULE}.schedule_user_integrations_sync"),
            patch(f"{MODULE}.websocket_manager.announce", AsyncMock()) as announce,
            patch(f"{MODULE}.continue_after_connect", AsyncMock()) as carry_on,
            patch(f"{MODULE}.report_wait_met", AsyncMock()),
        ):
            await user_integration_status.publish_connected("user-1", "gmail")

        carry_on.assert_awaited_once_with("user-1", "gmail")
        announce.assert_awaited_once_with(
            "user-1",
            {"type": INTEGRATION_STATUS_UPDATE_EVENT, "data": {"integration_id": "gmail"}},
        )

    async def test_a_failed_continue_is_logged_and_still_meets_the_wait(self) -> None:
        with (
            patch(f"{MODULE}.schedule_user_integrations_sync"),
            patch(f"{MODULE}.websocket_manager.announce", AsyncMock()),
            patch(
                f"{MODULE}.continue_after_connect", AsyncMock(side_effect=RuntimeError("log down"))
            ),
            patch(f"{MODULE}.report_wait_met", AsyncMock()) as report,
            patch(f"{MODULE}.log") as log,
        ):
            await user_integration_status.publish_connected("user-1", "gmail")

        log.error.assert_called_once_with(
            f"{LogTag.INTEGRATION} Failed to continue conversations waiting on the connect",
            integration_id="gmail",
            error="log down",
            error_type="RuntimeError",
        )
        report.assert_awaited_once_with("user-1", WaitCondition.INTEGRATION_CONNECTED, "gmail")


class TestUpdateUserIntegrationStatus:
    async def test_a_status_other_than_connected_only_tells_open_clients(self) -> None:
        with (
            patch(f"{MODULE}.user_integration_repository.set_status", AsyncMock(return_value=True)),
            patch(f"{MODULE}.websocket_manager.announce", AsyncMock()) as announce,
            patch(f"{MODULE}.continue_after_connect", AsyncMock()) as carry_on,
        ):
            updated = await user_integration_status.update_user_integration_status(
                "user-1", "gmail", "expired"
            )

        assert updated is True
        announce.assert_awaited_once_with(
            "user-1",
            {"type": INTEGRATION_STATUS_UPDATE_EVENT, "data": {"integration_id": "gmail"}},
        )
        carry_on.assert_not_awaited()
