"""The worker job that picks a chat, todo or workflow back up once the user did what GAIA asked."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from arq import Retry
import pytest
import time_machine

from app.constants.agents import AgentTag
from app.constants.log_tags import LogTag
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


def _wait(
    waiter: WaiterKind = WaiterKind.CHAT,
    waiter_id: str = "conv-1",
    *,
    condition: WaitCondition = WaitCondition.INTEGRATION_CONNECTED,
    subject_name: str = "Gmail",
    stream_id: str | None = "stream-1",
) -> WaitDocument:
    return WaitDocument(
        id="w1",
        user_id=USER,
        condition=condition,
        subject_id="gmail" if condition is WaitCondition.INTEGRATION_CONNECTED else "wf-9",
        subject_name=subject_name,
        waiter=waiter,
        waiter_id=waiter_id,
        stream_id=stream_id,
        # Half a minute past, so waited_minutes must be floored to stay an int.
        created_at=NOW - timedelta(hours=72, minutes=5, seconds=30),
    )


@dataclass
class Seams:
    user: MagicMock
    pool: MagicMock
    claim: AsyncMock
    restore: AsyncMock
    require_owner: AsyncMock
    unblock: AsyncMock
    deliver: AsyncMock
    enqueue: AsyncMock
    queue_workflow: AsyncMock
    capture: MagicMock


@pytest.fixture
def seams() -> Iterator[Seams]:
    user = MagicMock(user_id=USER)
    pool = MagicMock()
    with (
        time_machine.travel(NOW, tick=False),
        patch(f"{MODULE}.wait_repository.claim", AsyncMock(return_value=_wait())) as claim,
        patch(f"{MODULE}.wait_repository.restore", AsyncMock()) as restore,
        patch(f"{MODULE}.require_owner", AsyncMock(return_value=user)) as require_owner,
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
        yield Seams(
            user=user,
            pool=pool,
            claim=claim,
            restore=restore,
            require_owner=require_owner,
            unblock=unblock,
            deliver=deliver,
            enqueue=enqueue,
            queue_workflow=queue_workflow,
            capture=capture,
        )


class TestResumeWaiter:
    async def test_a_chat_is_told_what_was_done_and_how_long_ago_it_asked(
        self, seams: Seams
    ) -> None:
        await resume_waiter({}, USER, "w1")

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

    async def test_a_todo_gets_a_run_woken_by_the_wait_not_a_scheduled_one(
        self, seams: Seams
    ) -> None:
        seams.claim.return_value = _wait(WaiterKind.TODO, "todo-1")
        await resume_waiter({}, USER, "w1")

        pool, task, todo_id, origin = seams.enqueue.await_args.args
        assert (pool, task, todo_id) == (seams.pool, EXECUTE_TRACKED_TODO_TASK, "todo-1")
        assert isinstance(origin, TriggerOrigin)
        assert origin.trigger_name == WAIT_MET_TRIGGER
        assert str(origin.payload["message"]).startswith("The user just connected Gmail.")
        seams.deliver.assert_not_awaited()

    async def test_a_workflow_gets_a_run_carrying_the_news(self, seams: Seams) -> None:
        seams.claim.return_value = _wait(WaiterKind.WORKFLOW, "wf-1")
        await resume_waiter({}, USER, "w1")

        workflow_id, user_id = seams.queue_workflow.await_args.args
        assert (workflow_id, user_id) == ("wf-1", USER)
        context = seams.queue_workflow.await_args.kwargs["context"]
        assert context[WAIT_MET_CONTEXT_KEY].startswith("The user just connected Gmail.")

    async def test_a_failed_resume_puts_the_wait_back_and_retries_with_backoff(
        self, seams: Seams
    ) -> None:
        wait = _wait(WaiterKind.WORKFLOW, "wf-1")
        seams.claim.return_value = wait
        seams.queue_workflow.return_value = False

        with pytest.raises(Retry) as retry:
            await resume_waiter({"job_try": 3}, USER, "w1")

        assert isinstance(retry.value.__cause__, WorkflowNotQueuedError)
        assert "wf-1" in str(retry.value.__cause__)
        assert retry.value.defer_score == 120_000
        seams.restore.assert_awaited_once_with(wait)
        seams.capture.assert_not_called()

    async def test_a_resume_that_succeeds_leaves_the_wait_taken(self, seams: Seams) -> None:
        await resume_waiter({}, USER, "w1")

        seams.restore.assert_not_awaited()

    async def test_a_connect_lifts_the_asking_runs_block_on_the_integration(
        self, seams: Seams
    ) -> None:
        await resume_waiter({}, USER, "w1")

        seams.unblock.assert_awaited_once_with("stream-1", "gmail")

    async def test_a_configured_trigger_blocks_nothing_and_names_the_workflow(
        self, seams: Seams
    ) -> None:
        seams.claim.return_value = _wait(
            condition=WaitCondition.WORKFLOW_TRIGGER_CONFIGURED, subject_name="PR digest"
        )
        await resume_waiter({}, USER, "w1")

        seams.unblock.assert_not_awaited()
        entry = seams.deliver.await_args.args[2]
        assert entry.startswith(
            'The user just finished setting up the trigger of the workflow "PR digest".'
        )

    async def test_the_job_claims_the_wait_it_was_queued_for_as_its_owner(
        self, seams: Seams
    ) -> None:
        await resume_waiter({}, USER, "w1")

        seams.claim.assert_awaited_once_with("w1", user_id=USER)
        seams.require_owner.assert_awaited_once_with(USER)

    async def test_a_wait_already_picked_up_or_expired_resumes_nothing(self, seams: Seams) -> None:
        seams.claim.return_value = None

        await resume_waiter({}, USER, "w1")

        seams.deliver.assert_not_awaited()
        seams.capture.assert_not_called()

    async def test_a_first_failed_try_waits_the_base_delay_and_says_why(self, seams: Seams) -> None:
        seams.claim.return_value = _wait(WaiterKind.WORKFLOW, "wf-1")
        seams.queue_workflow.return_value = False

        with patch(f"{MODULE}.log") as log, pytest.raises(Retry) as retry:
            await resume_waiter({}, USER, "w1")

        assert retry.value.defer_score == 30_000
        log.warning.assert_called_once_with(
            f"{LogTag.AGENT} Resuming a waiter failed; the wait is back on file and retrying",
            waiter="workflow",
            waiter_id="wf-1",
            error_type="WorkflowNotQueuedError",
            error="wf-1",
            defer_seconds=30.0,
        )

    async def test_a_cancelled_resume_puts_the_wait_back_and_stays_cancelled(
        self, seams: Seams
    ) -> None:
        wait = _wait()
        seams.claim.return_value = wait
        seams.deliver.side_effect = asyncio.CancelledError

        with pytest.raises(asyncio.CancelledError):
            await resume_waiter({}, USER, "w1")

        seams.restore.assert_awaited_once_with(wait)
