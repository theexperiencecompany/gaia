"""The worker job that picks a chat, todo or workflow back up once the user did what GAIA asked."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import time_machine

from app.constants.agents import AgentTag
from app.constants.todos import EXECUTE_TRACKED_TODO_TASK
from app.constants.waits import WAIT_MET_CONTEXT_KEY, WAIT_MET_TRIGGER, WaitCondition, WaiterKind
from app.models.trigger_subscription_models import TriggerOrigin
from app.models.wait_models import WaitDocument
from app.workers.tasks.wait_tasks import WorkflowNotQueuedError, resume_waiter
from shared.py.analytics import UserId
from shared.py.analytics.catalog.agents import WaitResumed

MODULE = "app.workers.tasks.wait_tasks"
USER = "6812f0b3c9a14e2b7d5a91cc"
NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)


def _wait_json(
    waiter: WaiterKind = WaiterKind.CHAT,
    waiter_id: str = "conv-1",
    *,
    condition: WaitCondition = WaitCondition.INTEGRATION_CONNECTED,
    subject_name: str = "Gmail",
    stream_id: str | None = "stream-1",
) -> str:
    return WaitDocument(
        id="w1",
        user_id=USER,
        condition=condition,
        subject_id="gmail" if condition is WaitCondition.INTEGRATION_CONNECTED else "wf-9",
        subject_name=subject_name,
        waiter=waiter,
        waiter_id=waiter_id,
        stream_id=stream_id,
        created_at=NOW - timedelta(hours=72, minutes=5),
    ).model_dump_json()


@pytest.fixture
def seams():
    user = MagicMock(user_id=USER)
    pool = MagicMock()
    with (
        time_machine.travel(NOW, tick=False),
        patch(f"{MODULE}.require_owner", AsyncMock(return_value=user)),
        patch(f"{MODULE}.unblock_integration", AsyncMock()) as unblock,
        patch(f"{MODULE}.deliver_to_executor", AsyncMock()) as deliver,
        patch(f"{MODULE}.RedisPoolManager.get_pool", AsyncMock(return_value=pool)),
        patch(f"{MODULE}.enqueue_worker_job", AsyncMock()) as enqueue,
        patch(
            f"{MODULE}.WorkflowQueueService.queue_workflow_execution",
            AsyncMock(return_value=True),
        ) as queue_workflow,
        patch(f"{MODULE}.capture") as capture,
    ):
        yield MagicMock(
            user=user,
            pool=pool,
            unblock=unblock,
            deliver=deliver,
            enqueue=enqueue,
            queue_workflow=queue_workflow,
            capture=capture,
        )


class TestResumeWaiter:
    async def test_a_chat_is_told_what_was_done_and_how_long_ago_it_asked(self, seams) -> None:
        await resume_waiter({}, _wait_json())

        conversation_id, user, entry = seams.deliver.await_args.args
        assert (conversation_id, user) == ("conv-1", seams.user)
        assert seams.deliver.await_args.kwargs == {"tag": AgentTag.WAIT_MET}
        assert entry.startswith("The user just connected Gmail.")
        assert "72h5m ago" in entry
        assert "only read and search" in entry
        seams.capture.assert_called_once_with(
            UserId(USER),
            WaitResumed(
                condition="integration_connected", waiter="chat", waited_minutes=72 * 60 + 5
            ),
        )

    async def test_a_todo_gets_a_run_woken_by_the_wait_not_a_scheduled_one(self, seams) -> None:
        await resume_waiter({}, _wait_json(WaiterKind.TODO, "todo-1"))

        pool, task, todo_id, origin = seams.enqueue.await_args.args
        assert (pool, task, todo_id) == (seams.pool, EXECUTE_TRACKED_TODO_TASK, "todo-1")
        assert isinstance(origin, TriggerOrigin)
        assert origin.trigger_name == WAIT_MET_TRIGGER
        assert str(origin.payload["message"]).startswith("The user just connected Gmail.")
        seams.deliver.assert_not_awaited()

    async def test_a_workflow_gets_a_run_carrying_the_news(self, seams) -> None:
        await resume_waiter({}, _wait_json(WaiterKind.WORKFLOW, "wf-1"))

        workflow_id, user_id = seams.queue_workflow.await_args.args
        assert (workflow_id, user_id) == ("wf-1", USER)
        context = seams.queue_workflow.await_args.kwargs["context"]
        assert context[WAIT_MET_CONTEXT_KEY].startswith("The user just connected Gmail.")

    async def test_a_workflow_run_that_cannot_be_queued_fails_the_job(self, seams) -> None:
        seams.queue_workflow.return_value = False

        with pytest.raises(WorkflowNotQueuedError):
            await resume_waiter({}, _wait_json(WaiterKind.WORKFLOW, "wf-1"))

        seams.capture.assert_not_called()

    async def test_a_connect_lifts_the_asking_runs_block_on_the_integration(self, seams) -> None:
        await resume_waiter({}, _wait_json())

        seams.unblock.assert_awaited_once_with("stream-1", "gmail")

    async def test_a_configured_trigger_blocks_nothing_and_names_the_workflow(self, seams) -> None:
        await resume_waiter(
            {},
            _wait_json(
                condition=WaitCondition.WORKFLOW_TRIGGER_CONFIGURED, subject_name="PR digest"
            ),
        )

        seams.unblock.assert_not_awaited()
        entry = seams.deliver.await_args.args[2]
        assert entry.startswith(
            'The user just finished setting up the trigger of the workflow "PR digest".'
        )
