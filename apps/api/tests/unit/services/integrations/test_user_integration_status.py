"""Tests for the OAuth callbacks' reconnect lookup and what a new connection sets off."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch, sentinel

import pytest

from app.constants.integrations import INTEGRATION_STATUS_UPDATE_EVENT, IntegrationStatus
from app.constants.log_tags import LogTag
from app.constants.scouts import LEARN_SCOUT_TASK
from app.constants.waits import WaitCondition
from app.db.repositories.errors import RepositoryError
from app.services.briefing.scouts.lifecycle import SCOUT_INTEGRATION_HOOKS
from app.services.integrations.user_integration_status import (
    publish_connected,
    reconnect_or_unknown,
    update_user_integration_status,
)
from app.utils.redis_utils import RedisPoolManager

MODULE = "app.services.integrations.user_integration_status"
LIFECYCLE = "app.services.briefing.scouts.lifecycle"
HOOKS = "app.services.integrations.hook_registry"


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
            result = await reconnect_or_unknown(_raise(RepositoryError("down")), "gmail")

        assert result is None
        log.warning.assert_called_once()
        assert log.warning.call_args.args == (
            f"{LogTag.INTEGRATION} Could not tell whether the connect is a reconnect",
        )
        assert log.warning.call_args.kwargs == {
            "integration_id": "gmail",
            "error_type": "RepositoryError",
        }

    async def test_any_other_failure_still_raises(self) -> None:
        with pytest.raises(RuntimeError, match="bug"):
            await reconnect_or_unknown(_raise(RuntimeError("bug")), "gmail")


@contextmanager
def _connect_seams(
    get_pool: AsyncMock, enqueue: AsyncMock, *, report: AsyncMock | None = None
) -> Iterator[AsyncMock]:
    """Stub Redis, the ARQ enqueue and the page push; the integration hooks run for real."""
    broadcast = AsyncMock()
    with (
        patch(f"{MODULE}.schedule_user_integrations_sync", MagicMock()),
        patch.object(RedisPoolManager, "get_pool", get_pool),
        patch(f"{LIFECYCLE}.enqueue_worker_job", enqueue),
        patch(f"{MODULE}.websocket_manager.broadcast_to_user", broadcast),
        patch(f"{MODULE}.report_wait_met", report or AsyncMock()),
    ):
        yield broadcast


class TestPublishConnected:
    async def test_a_scout_learn_that_cannot_be_queued_is_logged_and_the_connect_stands(
        self,
    ) -> None:
        down = AsyncMock(side_effect=ConnectionError("down"))
        with (
            _connect_seams(down, AsyncMock()) as broadcast,
            patch(f"{HOOKS}.log") as log,
        ):
            await publish_connected("user-1", "linear")

        log.warning.assert_called_once_with(
            f"{LogTag.INTEGRATION} An integration connect hook failed",
            hook=SCOUT_INTEGRATION_HOOKS.name,
            integration_id="linear",
            error="down",
            error_type="ConnectionError",
        )
        broadcast.assert_awaited_once()

    async def test_a_new_connection_queues_that_users_scout_for_that_integration(self) -> None:
        enqueue = AsyncMock()
        with _connect_seams(AsyncMock(return_value=sentinel.pool), enqueue):
            await publish_connected("user-1", "linear")

        enqueue.assert_awaited_once_with(
            sentinel.pool,
            LEARN_SCOUT_TASK,
            "user-1",
            "linear",
            _job_id=f"{LEARN_SCOUT_TASK}:user-1:linear",
        )

    async def test_a_connect_meets_everything_waiting_on_that_integration(self) -> None:
        report = AsyncMock()
        with _connect_seams(AsyncMock(), AsyncMock(), report=report):
            await publish_connected("user-1", "gmail")

        report.assert_awaited_once_with("user-1", WaitCondition.INTEGRATION_CONNECTED, "gmail")

    async def test_a_connect_continues_the_conversations_waiting_on_it(self) -> None:
        with (
            patch(f"{MODULE}.schedule_user_integrations_sync"),
            patch(f"{MODULE}.websocket_manager.announce", AsyncMock()) as announce,
            patch(f"{MODULE}.continue_after_connect", AsyncMock()) as carry_on,
            patch(f"{MODULE}.report_wait_met", AsyncMock()),
        ):
            await publish_connected("user-1", "gmail")

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
            await publish_connected("user-1", "gmail")

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
            updated = await update_user_integration_status(
                "user-1", "gmail", IntegrationStatus.EXPIRED
            )

        assert updated is True
        announce.assert_awaited_once_with(
            "user-1",
            {"type": INTEGRATION_STATUS_UPDATE_EVENT, "data": {"integration_id": "gmail"}},
        )
        carry_on.assert_not_awaited()
