"""Who a run's ask keeps waiting, and queueing every waiter once the condition is met."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.log_tags import LogTag
from app.constants.waits import RESUME_WAITER_TASK, WaitCondition, WaiterKind
from app.models.agent_config import AgentConfigurableView
from app.models.wait_models import WaitDocument, WaitKey, WaitUpdate
from app.services.wait_service import report_wait_met, wait_for_user

MODULE = "app.services.wait_service"
USER = "6812f0b3c9a14e2b7d5a91cc"
CONNECTED = WaitCondition.INTEGRATION_CONNECTED


def _wait(waiter: WaiterKind, waiter_id: str) -> WaitDocument:
    return WaitDocument(
        id="w1",
        user_id=USER,
        condition=CONNECTED,
        subject_id="gmail",
        subject_name="Gmail",
        waiter=waiter,
        waiter_id=waiter_id,
        stream_id="stream-1",
        created_at=datetime(2026, 11, 10, 9, 0, tzinfo=UTC),
    )


class TestWaitForUser:
    @pytest.mark.parametrize(
        ("run", "waiter", "waiter_id"),
        [
            (
                AgentConfigurableView(conversation_id="conv-1", execution_mode="interactive"),
                WaiterKind.CHAT,
                "conv-1",
            ),
            # The user talking about a todo in chat is still the chat waiting.
            (
                AgentConfigurableView(
                    conversation_id="conv-1", active_todo_id="todo-1", execution_mode="interactive"
                ),
                WaiterKind.CHAT,
                "conv-1",
            ),
            (
                AgentConfigurableView(
                    conversation_id="todo-conv",
                    active_todo_id="todo-1",
                    execution_mode="background",
                ),
                WaiterKind.TODO,
                "todo-1",
            ),
            (
                AgentConfigurableView(
                    conversation_id="wf-conv", workflow_id="wf-1", execution_mode="background"
                ),
                WaiterKind.WORKFLOW,
                "wf-1",
            ),
        ],
        ids=["chat", "chat-about-a-todo", "todo-run", "workflow-run"],
    )
    async def test_the_run_keeps_the_waiter_it_speaks_for(
        self, run: AgentConfigurableView, waiter: WaiterKind, waiter_id: str
    ) -> None:
        run = run.model_copy(update={"stream_id": "stream-1"})
        with patch(f"{MODULE}.wait_repository.keep", AsyncMock()) as keep:
            await wait_for_user(run, USER, CONNECTED, "gmail", "Gmail")

        keep.assert_awaited_once_with(
            WaitKey(
                user_id=USER,
                condition=CONNECTED,
                subject_id="gmail",
                waiter=waiter,
                waiter_id=waiter_id,
            ),
            WaitUpdate(subject_name="Gmail", stream_id="stream-1"),
        )

    @pytest.mark.parametrize(
        "run",
        [
            AgentConfigurableView(conversation_id="bg-conv", execution_mode="background"),
            AgentConfigurableView(conversation_id=None, execution_mode="interactive"),
        ],
        ids=["background-run-for-nobody", "no-conversation"],
    )
    async def test_a_run_speaking_for_nobody_keeps_nothing(
        self, run: AgentConfigurableView
    ) -> None:
        with patch(f"{MODULE}.wait_repository.keep", AsyncMock()) as keep:
            await wait_for_user(run, USER, CONNECTED, "gmail", "Gmail")

        keep.assert_not_awaited()


class TestReportWaitMet:
    async def test_each_waiter_gets_its_own_resume_job(self) -> None:
        waits = [_wait(WaiterKind.CHAT, "conv-1"), _wait(WaiterKind.TODO, "todo-1")]
        pool = MagicMock()
        with (
            patch(f"{MODULE}.wait_repository.take_met", AsyncMock(return_value=waits)) as take,
            patch(f"{MODULE}.RedisPoolManager.get_pool", AsyncMock(return_value=pool)),
            patch(f"{MODULE}.enqueue_worker_job", AsyncMock()) as enqueue,
        ):
            await report_wait_met(USER, CONNECTED, "gmail")

        take.assert_awaited_once_with(USER, CONNECTED, "gmail")
        assert [call.args for call in enqueue.await_args_list] == [
            (pool, RESUME_WAITER_TASK, waits[0].model_dump_json()),
            (pool, RESUME_WAITER_TASK, waits[1].model_dump_json()),
        ]

    async def test_a_condition_nobody_waited_on_queues_nothing(self) -> None:
        with (
            patch(f"{MODULE}.wait_repository.take_met", AsyncMock(return_value=[])),
            patch(f"{MODULE}.enqueue_worker_job", AsyncMock()) as enqueue,
        ):
            await report_wait_met(USER, CONNECTED, "gmail")

        enqueue.assert_not_awaited()

    async def test_a_failure_is_logged_and_never_fails_the_change_that_met_it(self) -> None:
        with (
            patch(
                f"{MODULE}.wait_repository.take_met",
                AsyncMock(side_effect=ConnectionError("mongo down")),
            ),
            patch(f"{MODULE}.log") as log,
        ):
            await report_wait_met(USER, CONNECTED, "gmail")

        log.error.assert_called_once()
        assert log.error.call_args.args == (
            f"{LogTag.AGENT} Failed to queue the waiters on a met condition",
        )
        assert log.error.call_args.kwargs["subject_id"] == "gmail"
