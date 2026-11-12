"""cancel_all_work: one stop reaches every kind of work a conversation has running."""

from collections.abc import Iterator
from unittest.mock import AsyncMock

import fakeredis.aioredis
import pytest

from app.agents.core.background.executor_channel import ExecutorInbox
from app.agents.core.background.executor_progress import progress_key
from app.agents.core.background.work_cancel import cancel_all_work, cancel_named_work
from app.constants.agents import AgentTag
from app.constants.browser import BrowserStopOutcome
from app.constants.cache import EXECUTOR_BUSY_PREFIX, EXECUTOR_BUSY_TTL
from app.constants.log_tags import LogTag
from app.constants.streaming import WS_EVENT_EXECUTOR_CANCELLED
from app.core.stream_manager import stream_manager
from app.core.websocket_manager import websocket_manager
from app.models.work_cancel_models import WorkCancelled
from app.services.browser import job_stop
from app.services.browser.jobs import job_cancel_requested
from tests.helpers import captured_wide_event
from tests.work_cancel_fakes import (
    APPROVAL,
    BROWSER_JOB,
    EXECUTOR_STREAM,
    EXECUTOR_TASK,
    SUBAGENT_STREAM,
    approval_seams,
    claim_subagent,
    seed_live_work,
)

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("fake_redis")]

CONVERSATION = "conv-stop"
USER = "user-1"
LOCK = f"{EXECUTOR_STREAM}:{EXECUTOR_TASK}"


@pytest.fixture
def pending_approvals() -> Iterator[AsyncMock]:
    yield from approval_seams(pending=True)


@pytest.fixture
def no_approvals() -> Iterator[AsyncMock]:
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
    pending_approvals: AsyncMock,
    broadcast: AsyncMock,
) -> None:
    await seed_live_work(CONVERSATION)

    work = await cancel_all_work(CONVERSATION, USER, None)

    assert work == WorkCancelled(
        executor_stopped=True,
        executor_task_id=EXECUTOR_TASK,
        pending_tasks=1,
        subagent_ids=["s1"],
        approval_ids=[APPROVAL],
        browser_jobs={BROWSER_JOB: BrowserStopOutcome.STOPPED},
    )
    assert await stream_manager.is_cancelled(EXECUTOR_STREAM)
    assert await stream_manager.is_cancelled(SUBAGENT_STREAM)
    assert await fake_redis.get(f"{EXECUTOR_BUSY_PREFIX}{CONVERSATION}") is None
    assert await job_cancel_requested(BROWSER_JOB)
    pending_approvals.assert_awaited_once_with(CONVERSATION, USER)
    broadcast.assert_awaited_once_with(
        USER, {"type": WS_EVENT_EXECUTOR_CANCELLED, "conversation_id": CONVERSATION}
    )


async def test_the_next_run_is_told_the_work_was_stopped_and_what_to_do_instead(
    no_approvals: AsyncMock, broadcast: AsyncMock
) -> None:
    await seed_live_work(CONVERSATION)

    await cancel_all_work(CONVERSATION, USER, None, redirect="do gmail instead")

    entries = [(entry.tag, entry.text) for entry in await ExecutorInbox(CONVERSATION).read()]
    assert [tag for tag, _ in entries] == [
        AgentTag.BROWSER_STOPPED,
        AgentTag.EXECUTOR_INTERRUPTED,
        AgentTag.USER_INTERJECTION,
    ]
    assert entries[-1][1] == "do gmail instead"


async def test_approvals_close_even_when_no_run_holds_the_lock(
    pending_approvals: AsyncMock, broadcast: AsyncMock
) -> None:
    """A parked approval outlives the busy lock; left pending, Approve revives the stopped work."""
    work = await cancel_all_work(CONVERSATION, USER, None)

    assert work.approval_ids == [APPROVAL]
    pending_approvals.assert_awaited_once_with(CONVERSATION, USER)


async def test_an_idle_conversation_returns_an_empty_summary_and_touches_nothing(
    fake_redis: fakeredis.aioredis.FakeRedis,
    no_approvals: AsyncMock,
    broadcast: AsyncMock,
) -> None:
    work = await cancel_all_work(CONVERSATION, USER, None)

    assert work == WorkCancelled()
    assert not work.stopped_anything
    assert await ExecutorInbox(CONVERSATION).read() == []
    assert await fake_redis.keys("*") == []
    broadcast.assert_not_awaited()


async def test_a_second_stop_finds_nothing_left(
    no_approvals: AsyncMock, broadcast: AsyncMock
) -> None:
    await seed_live_work(CONVERSATION)
    await cancel_all_work(CONVERSATION, USER, None)

    again = await cancel_all_work(CONVERSATION, USER, None)

    assert again.executor_stopped is False
    assert again.pending_tasks == 0
    assert again.browser_jobs == {}


async def test_the_stopped_runs_progress_is_dropped(
    fake_redis: fakeredis.aioredis.FakeRedis, no_approvals: AsyncMock, broadcast: AsyncMock
) -> None:
    await seed_live_work(CONVERSATION)
    await fake_redis.set(progress_key(CONVERSATION, LOCK), "{}")

    await cancel_all_work(CONVERSATION, USER, None)

    assert await fake_redis.get(progress_key(CONVERSATION, LOCK)) is None


async def test_the_subagents_the_stopped_run_dispatched_are_counted_as_stopped(
    fake_redis: fakeredis.aioredis.FakeRedis, no_approvals: AsyncMock, broadcast: AsyncMock
) -> None:
    """Stopping the run cancels its subagents before the sweep, which must not then miss them."""
    await fake_redis.set(f"{EXECUTOR_BUSY_PREFIX}{CONVERSATION}", LOCK, ex=EXECUTOR_BUSY_TTL)
    own = await claim_subagent(CONVERSATION, "own", dispatched_by=EXECUTOR_STREAM)

    work = await cancel_all_work(CONVERSATION, USER, None)

    assert work.subagent_ids == ["own"]
    assert await stream_manager.is_cancelled(own)


async def test_the_stop_is_recorded_on_the_wide_event(
    no_approvals: AsyncMock, broadcast: AsyncMock
) -> None:
    await seed_live_work(CONVERSATION)

    async with captured_wide_event() as event:
        await cancel_all_work(CONVERSATION, USER, None)

    assert event["work_cancel"] == {
        "conversation_id": CONVERSATION,
        "executor_stopped": True,
        "pending": 1,
        "subagents": 1,
        "approvals": 0,
        "browser_jobs": 1,
    }


async def test_a_failed_broadcast_is_a_warning_and_the_stop_still_lands(
    fake_redis: fakeredis.aioredis.FakeRedis, no_approvals: AsyncMock, broadcast: AsyncMock
) -> None:
    broadcast.side_effect = RuntimeError("rabbitmq unavailable")
    await seed_live_work(CONVERSATION)

    async with captured_wide_event() as event:
        work = await cancel_all_work(CONVERSATION, USER, None)

    assert work.executor_stopped
    assert await fake_redis.get(f"{EXECUTOR_BUSY_PREFIX}{CONVERSATION}") is None
    (warning,) = event["warnings"]
    assert warning["msg"] == f"{LogTag.TOOL} Failed to broadcast executor.cancelled"
    assert (warning["error_type"], warning["error"]) == ("RuntimeError", "rabbitmq unavailable")


class TestCancelNamedWork:
    async def test_naming_the_running_task_stops_it_closes_its_approvals_and_passes_the_redirect(
        self, pending_approvals: AsyncMock, broadcast: AsyncMock
    ) -> None:
        await seed_live_work(CONVERSATION)

        work = await cancel_named_work(
            CONVERSATION, USER, [EXECUTOR_TASK], redirect="do gmail instead"
        )

        assert work == WorkCancelled(
            executor_stopped=True,
            executor_task_id=EXECUTOR_TASK,
            approval_ids=[APPROVAL],
        )
        assert await stream_manager.is_cancelled(EXECUTOR_STREAM)
        pending_approvals.assert_awaited_once_with(CONVERSATION, USER)
        entries = await ExecutorInbox(CONVERSATION).read()
        assert [(entry.tag, entry.text) for entry in entries][-1] == (
            AgentTag.USER_INTERJECTION,
            "do gmail instead",
        )
        broadcast.assert_awaited_once_with(
            USER, {"type": WS_EVENT_EXECUTOR_CANCELLED, "conversation_id": CONVERSATION}
        )

    async def test_naming_only_queued_work_spares_the_run_and_its_approvals(
        self, pending_approvals: AsyncMock, broadcast: AsyncMock
    ) -> None:
        await seed_live_work(CONVERSATION)

        async with captured_wide_event() as event:
            work = await cancel_named_work(CONVERSATION, USER, ["queued-task"])

        assert work == WorkCancelled(executor_spared=True, pending_task_ids=["queued-task"])
        assert event["work_cancel"]["pending"] == 1
        assert not await stream_manager.is_cancelled(EXECUTOR_STREAM)
        pending_approvals.assert_not_awaited()
