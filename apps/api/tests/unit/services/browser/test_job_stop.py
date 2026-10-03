"""A stop: what it settles, what it aborts, and what it reports the job came to.

Real code over fakeredis, ARQ's keys included; no worker runs.
"""

from unittest.mock import AsyncMock

from arq.constants import abort_jobs_ss, in_progress_key_prefix
import fakeredis.aioredis
import pytest

from app.agents.core.background.executor_channel import ExecutorInbox
from app.constants.agents import NON_WAKING_TAGS, AgentTag
from app.constants.browser import BrowserSessionStatus, BrowserStopOutcome, HandoffStatus
from app.constants.chat import ConversationSource
from app.schemas.browser import BrowserResultSnapshot, NewHandoff
from app.schemas.browser_job import BrowserJobFinished, BrowserJobState, BrowserJobStatus
from app.services.browser import job_stop
from app.services.browser.handoff import create_pending_handoff, get_handoff
from app.services.browser.jobs import (
    job_cancel_requested,
    put_job_state,
    record_ending,
    set_job_wait,
    set_latest_job,
)
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def arq(
    fake_redis: fakeredis.aioredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> fakeredis.aioredis.FakeRedis:
    """ARQ's pool on the same fake Redis."""
    monkeypatch.setattr(job_stop.RedisPoolManager, "get_pool", AsyncMock(return_value=fake_redis))
    return fake_redis


def _state(
    status: BrowserJobStatus, *, job_id: str = "job-1", in_background: bool = True
) -> BrowserJobState:
    return BrowserJobState(
        job_id=job_id,
        status=status,
        task="t",
        conversation_id="conv-1",
        user_id="u1",
        in_background=in_background,
    )


async def _job(status: BrowserJobStatus, *, in_background: bool = True) -> None:
    await set_latest_job("conv-1", "job-1")
    await put_job_state(_state(status, in_background=in_background))


_FINISHED = BrowserJobFinished(
    result=BrowserResultSnapshot(status=BrowserSessionStatus.COMPLETED, success=True, summary="ok")
)


async def test_a_stop_settles_the_handoff_the_run_waits_on_and_aborts_the_running_task(
    arq: fakeredis.aioredis.FakeRedis,
) -> None:
    await _job(BrowserJobStatus.RUNNING)
    await create_pending_handoff(
        "h1",
        NewHandoff(
            job_id="job-1",
            user_id="u1",
            conversation_id="conv-1",
            reason="Sign in",
            reply_to="conv-1",
        ),
    )
    await set_job_wait("job-1", "h1")
    await arq.set(f"{in_progress_key_prefix}job-1", "1")

    async with captured_wide_event() as event:
        assert await job_stop.stop_browser_job("conv-1") == "job-1"

    assert event["browser"] == {"stopped_job": "job-1", "stop_settled": "h1", "stop_aborted": True}
    assert await job_cancel_requested("job-1")
    record = await get_handoff("h1")
    assert record is not None
    assert record.status is HandoffStatus.CANCELLED
    assert await arq.zscore(abort_jobs_ss, "job-1") is not None


async def test_a_queued_job_is_flagged_but_never_aborted(arq: fakeredis.aioredis.FakeRedis) -> None:
    """ARQ drops an aborted job unrun, with no ending at all; the queued job reads its flag at its start."""
    await _job(BrowserJobStatus.QUEUED)

    async with captured_wide_event() as event:
        assert await job_stop.stop_browser_job("conv-1") == "job-1"

    assert event["browser"] == {"stopped_job": "job-1", "stop_settled": None, "stop_aborted": False}
    assert await job_cancel_requested("job-1")
    assert await arq.zscore(abort_jobs_ss, "job-1") is None


async def test_a_finished_or_unknown_job_is_not_stopped() -> None:
    assert await job_stop.stop_browser_job("conv-1") is None
    # A pointer outliving its job's state names nothing to stop.
    await set_latest_job("conv-1", "job-gone")
    assert await job_stop.stop_browser_job("conv-1") is None
    await _job(BrowserJobStatus.RUNNING)
    await record_ending("job-1", _FINISHED)

    assert await job_stop.stop_browser_job("conv-1") is None
    assert not await job_cancel_requested("job-1")


async def test_a_stop_that_comes_after_the_runs_own_end_reports_it_ended_and_changes_nothing(
    arq: fakeredis.aioredis.FakeRedis,
) -> None:
    """The run recorded its result first: that answer is told, and the stop says so."""
    await _job(BrowserJobStatus.RUNNING)
    await record_ending("job-1", _FINISHED)
    await arq.set(f"{in_progress_key_prefix}job-1", "1")

    async with captured_wide_event() as event:
        assert await job_stop.stop_job("job-1") is BrowserStopOutcome.ALREADY_ENDED

    assert event["browser"] == {"stopped_job": "job-1", "stop_lost": "finished"}
    assert not await job_cancel_requested("job-1")
    assert await arq.zscore(abort_jobs_ss, "job-1") is None


async def test_a_stop_in_the_requesters_dm_reaches_the_task_they_started_in_a_group() -> None:
    """Its updates and handoffs come to the DM, so a plain "stop" there must reach it (Greptile)."""
    await put_job_state(_state(BrowserJobStatus.RUNNING, job_id="job-g"))
    await set_latest_job("conv-group", "job-g")
    await set_latest_job("telegram:u1", "job-g")

    requester = job_stop.requester_chat("u1", ConversationSource.TELEGRAM)

    stopped = await job_stop.stop_chat_jobs("conv-dm", requester)

    assert stopped == {"job-g": BrowserStopOutcome.STOPPED}
    assert await job_cancel_requested("job-g")
    # A web chat has no requester chat: it controls its own conversation's job, and only that.
    assert job_stop.requester_chat("u1", ConversationSource.WEB) is None
    assert job_stop.requester_chat("u1", None) is None
    # A turn that names no user has no chat of the user's to reach.
    assert job_stop.requester_chat(None, ConversationSource.TELEGRAM) is None
    assert job_stop.chat_job_keys("conv-web", None) == ["conv-web"]


async def test_a_stopped_background_job_tells_its_thread_without_waking_anyone() -> None:
    """The stop answered the user; the thread still has to learn the job ended, or a later run reports it."""
    await _job(BrowserJobStatus.RUNNING)

    await job_stop.stop_job("job-1")

    [notice] = await ExecutorInbox("conv-1").read()
    assert notice.tag is AgentTag.BROWSER_STOPPED
    assert notice.tag in NON_WAKING_TAGS
    assert "job-1" in notice.text


async def test_a_stopped_headless_job_lands_nothing_in_the_inbox() -> None:
    """Its blocked tool call reads the stop itself; an inbox entry would tell it a second time."""
    await _job(BrowserJobStatus.RUNNING, in_background=False)

    await job_stop.stop_job("job-1")

    assert await job_cancel_requested("job-1")
    assert await ExecutorInbox("conv-1").read() == []


async def test_a_stop_that_lost_lands_nothing_either() -> None:
    await _job(BrowserJobStatus.RUNNING)
    await record_ending("job-1", _FINISHED)

    await job_stop.stop_job("job-1")

    assert await ExecutorInbox("conv-1").read() == []


async def test_a_job_that_ended_is_not_one_the_chat_still_controls() -> None:
    await _job(BrowserJobStatus.RUNNING)
    assert [job.job_id for job in await job_stop.running_chat_jobs("conv-1", None)] == ["job-1"]

    await record_ending("job-1", _FINISHED)

    assert await job_stop.running_chat_jobs("conv-1", None) == []
