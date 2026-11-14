"""cancel_named_work and stop_unlogged_work: a Stop reaches exactly the work it covers, and what the log never held."""

from collections.abc import Iterator
from unittest.mock import AsyncMock

import fakeredis.aioredis
import pytest

from app.agents.core.background.executor_channel import ExecutorInbox
from app.agents.core.background.executor_progress import progress_key
from app.agents.core.background.work_cancel import cancel_named_work, stop_unlogged_work
from app.constants.agents import AgentTag
from app.constants.browser import BrowserStopOutcome
from app.constants.cache import EXECUTOR_BUSY_PREFIX, EXECUTOR_BUSY_TTL
from app.core.stream_manager import stream_manager
from app.models.work_cancel_models import WorkCancelled
from app.services.browser import job_stop
from app.services.browser.jobs import job_cancel_requested
from tests.helpers import captured_wide_event
from tests.work_cancel_fakes import (
    APPROVAL,
    BROWSER_JOB,
    EXECUTOR_STREAM,
    EXECUTOR_TASK,
    LEDGER_APPROVAL,
    SUBAGENT_STREAM,
    ApprovalSeams,
    approval_seams,
    claim_subagent,
    seed_live_work,
)

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("fake_redis")]

CONVERSATION = "conv-stop"
USER = "user-1"
LOCK = f"{EXECUTOR_STREAM}:{EXECUTOR_TASK}"


@pytest.fixture
def pending_approvals() -> Iterator[ApprovalSeams]:
    yield from approval_seams(pending=True)


@pytest.fixture
def no_approvals() -> Iterator[ApprovalSeams]:
    yield from approval_seams(pending=False)


@pytest.fixture(autouse=True)
def no_arq(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job_stop, "_abort_if_started", AsyncMock(return_value=True))


APPROVALS = [APPROVAL, LEDGER_APPROVAL]


async def test_a_stops_cancel_reaches_the_named_run_its_queued_work_and_its_approvals(
    fake_redis: fakeredis.aioredis.FakeRedis,
    pending_approvals: ApprovalSeams,
) -> None:
    await seed_live_work(CONVERSATION)

    work = await cancel_named_work(
        CONVERSATION, USER, [EXECUTOR_TASK, "queued-task"], approval_ids=APPROVALS
    )

    assert work == WorkCancelled(
        executor_stopped=True,
        executor_task_id=EXECUTOR_TASK,
        pending_task_ids=["queued-task"],
        approval_ids=APPROVALS,
    )
    assert await stream_manager.is_cancelled(EXECUTOR_STREAM)
    assert await fake_redis.get(f"{EXECUTOR_BUSY_PREFIX}{CONVERSATION}") is None
    # Neither the subagent an earlier turn left running nor the browser job is named.
    assert not await stream_manager.is_cancelled(SUBAGENT_STREAM)
    assert not await job_cancel_requested(BROWSER_JOB)
    pending_approvals.ledger.assert_awaited_once_with(CONVERSATION, USER, APPROVALS)


async def test_the_rest_of_a_stop_reaches_the_subagents_and_browser_job_no_run_holds(
    no_approvals: ApprovalSeams,
) -> None:
    await seed_live_work(CONVERSATION)

    work = await stop_unlogged_work(CONVERSATION, None)

    assert work == WorkCancelled(
        subagent_ids=["s1"], browser_jobs={BROWSER_JOB: BrowserStopOutcome.STOPPED}
    )
    assert await stream_manager.is_cancelled(SUBAGENT_STREAM)
    assert await job_cancel_requested(BROWSER_JOB)
    assert not await stream_manager.is_cancelled(EXECUTOR_STREAM)


async def test_the_next_run_is_told_the_work_was_stopped_and_what_to_do_instead(
    no_approvals: ApprovalSeams,
) -> None:
    await seed_live_work(CONVERSATION)

    await cancel_named_work(
        CONVERSATION, USER, [EXECUTOR_TASK], approval_ids=[], redirect="do gmail instead"
    )

    entries = [(entry.tag, entry.text) for entry in await ExecutorInbox(CONVERSATION).read()]
    assert [tag for tag, _ in entries][-2:] == [
        AgentTag.EXECUTOR_INTERRUPTED,
        AgentTag.USER_INTERJECTION,
    ]
    assert entries[-1][1] == "do gmail instead"


async def test_approvals_close_even_when_no_run_holds_the_lock(
    pending_approvals: ApprovalSeams,
) -> None:
    """A parked approval outlives the busy lock; left pending, Approve revives the stopped work."""
    work = await cancel_named_work(CONVERSATION, USER, ["paused-task"], approval_ids=APPROVALS)

    assert work.approval_ids == APPROVALS
    pending_approvals.ledger.assert_awaited_once_with(CONVERSATION, USER, APPROVALS)


async def test_a_cancel_naming_no_approvals_touches_neither_store(
    fake_redis: fakeredis.aioredis.FakeRedis,
    pending_approvals: ApprovalSeams,
) -> None:
    work = await cancel_named_work(CONVERSATION, USER, ["gone-task"], approval_ids=[])

    assert work == WorkCancelled()
    assert not work.stopped_anything
    pending_approvals.ledger.assert_not_awaited()
    assert await ExecutorInbox(CONVERSATION).read() == []
    assert await fake_redis.keys("*") == []


async def test_the_stopped_runs_progress_is_dropped(
    fake_redis: fakeredis.aioredis.FakeRedis, no_approvals: ApprovalSeams
) -> None:
    await seed_live_work(CONVERSATION)
    await fake_redis.set(progress_key(CONVERSATION, LOCK), "{}")

    await cancel_named_work(CONVERSATION, USER, [EXECUTOR_TASK], approval_ids=[])

    assert await fake_redis.get(progress_key(CONVERSATION, LOCK)) is None


async def test_the_subagents_the_stopped_run_dispatched_are_counted_as_stopped(
    fake_redis: fakeredis.aioredis.FakeRedis, no_approvals: ApprovalSeams
) -> None:
    await fake_redis.set(f"{EXECUTOR_BUSY_PREFIX}{CONVERSATION}", LOCK, ex=EXECUTOR_BUSY_TTL)
    own = await claim_subagent(CONVERSATION, "own", dispatched_by=EXECUTOR_STREAM)

    work = await cancel_named_work(CONVERSATION, USER, [EXECUTOR_TASK], approval_ids=[])

    assert work.subagent_ids == ["own"]
    assert await stream_manager.is_cancelled(own)


async def test_the_stop_is_recorded_on_the_wide_event(no_approvals: ApprovalSeams) -> None:
    await seed_live_work(CONVERSATION)

    async with captured_wide_event() as event:
        await cancel_named_work(CONVERSATION, USER, [EXECUTOR_TASK, "queued-task"], approval_ids=[])

    assert event["work_cancel"] == {
        "conversation_id": CONVERSATION,
        "executor_stopped": True,
        "pending": 1,
        "subagents": 0,
        "approvals": 0,
        "browser_jobs": 0,
    }


async def test_naming_only_queued_work_spares_the_run(pending_approvals: ApprovalSeams) -> None:
    await seed_live_work(CONVERSATION)

    work = await cancel_named_work(CONVERSATION, USER, ["queued-task"], approval_ids=[])

    assert work == WorkCancelled(executor_spared=True, pending_task_ids=["queued-task"])
    assert not await stream_manager.is_cancelled(EXECUTOR_STREAM)
    pending_approvals.ledger.assert_not_awaited()
