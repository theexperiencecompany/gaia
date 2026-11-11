"""cancel_all_work: one stop reaches every kind of work a conversation has running."""

from collections.abc import Iterator
from unittest.mock import AsyncMock

import fakeredis.aioredis
import pytest

from app.agents.core.background.executor_channel import ExecutorInbox
from app.agents.core.background.work_cancel import cancel_all_work
from app.constants.agents import AgentTag
from app.constants.browser import BrowserStopOutcome
from app.constants.cache import EXECUTOR_BUSY_PREFIX
from app.core.stream_manager import stream_manager
from app.core.websocket_manager import websocket_manager
from app.models.work_cancel_models import WorkCancelled
from app.services.browser import job_stop
from app.services.browser.jobs import job_cancel_requested
from tests.work_cancel_fakes import (
    APPROVAL,
    BROWSER_JOB,
    EXECUTOR_STREAM,
    EXECUTOR_TASK,
    LEDGER_APPROVAL,
    SUBAGENT_STREAM,
    ApprovalSeams,
    approval_seams,
    seed_live_work,
)

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("fake_redis")]

CONVERSATION = "conv-stop"
USER = "user-1"


@pytest.fixture
def pending_approvals() -> Iterator[ApprovalSeams]:
    yield from approval_seams(pending=True)


@pytest.fixture
def no_approvals() -> Iterator[ApprovalSeams]:
    yield from approval_seams(pending=False)


@pytest.fixture(autouse=True)
def no_arq(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job_stop, "_abort_if_started", AsyncMock(return_value=True))


@pytest.fixture
def broadcast(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    mock = AsyncMock()
    monkeypatch.setattr(websocket_manager, "broadcast_to_user", mock)
    return mock


async def test_one_stop_cancels_the_run_its_inbox_subagents_approvals_and_browser_job(
    fake_redis: fakeredis.aioredis.FakeRedis,
    pending_approvals: ApprovalSeams,
    broadcast: AsyncMock,
) -> None:
    await seed_live_work(CONVERSATION, USER)

    work = await cancel_all_work(CONVERSATION, USER, None)

    assert work == WorkCancelled(
        executor_stopped=True,
        executor_task_id=EXECUTOR_TASK,
        pending_tasks=1,
        subagent_ids=["s1"],
        approval_ids=[APPROVAL, LEDGER_APPROVAL],
        browser_jobs={BROWSER_JOB: BrowserStopOutcome.STOPPED},
    )
    assert await stream_manager.is_cancelled(EXECUTOR_STREAM)
    assert await stream_manager.is_cancelled(SUBAGENT_STREAM)
    assert await fake_redis.get(f"{EXECUTOR_BUSY_PREFIX}{CONVERSATION}") is None
    assert await job_cancel_requested(BROWSER_JOB)
    pending_approvals.barrier.assert_awaited_once_with(CONVERSATION, USER)
    pending_approvals.ledger.assert_awaited_once_with(CONVERSATION, USER)
    broadcast.assert_awaited_once()


async def test_the_next_run_is_told_the_work_was_stopped_and_what_to_do_instead(
    no_approvals: ApprovalSeams, broadcast: AsyncMock
) -> None:
    await seed_live_work(CONVERSATION, USER)

    await cancel_all_work(CONVERSATION, USER, None, redirect="do gmail instead")

    entries = [(entry.tag, entry.text) for entry in await ExecutorInbox(CONVERSATION).read()]
    assert [tag for tag, _ in entries] == [
        AgentTag.BROWSER_STOPPED,
        AgentTag.EXECUTOR_INTERRUPTED,
        AgentTag.USER_INTERJECTION,
    ]
    assert entries[-1][1] == "do gmail instead"


async def test_approvals_close_even_when_no_run_holds_the_lock(
    pending_approvals: ApprovalSeams, broadcast: AsyncMock
) -> None:
    """A parked approval outlives the busy lock; left pending, Approve revives the stopped work."""
    work = await cancel_all_work(CONVERSATION, USER, None)

    assert work.approval_ids == [APPROVAL, LEDGER_APPROVAL]
    pending_approvals.barrier.assert_awaited_once_with(CONVERSATION, USER)


async def test_an_idle_conversation_returns_an_empty_summary_and_touches_nothing(
    fake_redis: fakeredis.aioredis.FakeRedis,
    no_approvals: ApprovalSeams,
    broadcast: AsyncMock,
) -> None:
    work = await cancel_all_work(CONVERSATION, USER, None)

    assert work == WorkCancelled()
    assert not work.stopped_anything
    assert await ExecutorInbox(CONVERSATION).read() == []
    assert await fake_redis.keys("*") == []
    broadcast.assert_not_awaited()


async def test_a_second_stop_finds_nothing_left(
    no_approvals: ApprovalSeams, broadcast: AsyncMock
) -> None:
    await seed_live_work(CONVERSATION, USER)
    await cancel_all_work(CONVERSATION, USER, None)

    again = await cancel_all_work(CONVERSATION, USER, None)

    assert again.executor_stopped is False
    assert again.pending_tasks == 0
    assert again.browser_jobs == {}
