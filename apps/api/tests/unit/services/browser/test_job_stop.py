"""A stop: what it settles, what it aborts, and what it reports the job came to.

Real code over fakeredis, ARQ's keys included; no worker runs.
"""

from unittest.mock import AsyncMock

from arq.constants import abort_jobs_ss, in_progress_key_prefix
import fakeredis.aioredis
import pytest

from app.constants.browser import BrowserSessionStatus, BrowserStopOutcome, HandoffStatus
from app.schemas.browser import BrowserResultSnapshot, NewHandoff
from app.schemas.browser_job import BrowserJobState, BrowserJobStatus
from app.services.browser import job_stop
from app.services.browser.handoff import create_pending_handoff, get_handoff
from app.services.browser.job_events import JOB_TERMINAL_FRAME, publish_job_event
from app.services.browser.jobs import (
    job_cancel_requested,
    put_job_state,
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


async def _job(status: BrowserJobStatus, result: BrowserResultSnapshot | None = None) -> None:
    await set_latest_job("conv-1", "job-1")
    await put_job_state(BrowserJobState(job_id="job-1", status=status, task="t", result=result))


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
    await _job(BrowserJobStatus.DONE)

    assert await job_stop.stop_browser_job("conv-1") is None
    assert not await job_cancel_requested("job-1")


@pytest.mark.parametrize(
    ("status", "outcome"),
    [
        (BrowserSessionStatus.CANCELLED, BrowserStopOutcome.STOPPED),
        (BrowserSessionStatus.COMPLETED, BrowserStopOutcome.ALREADY_ENDED),
    ],
)
async def test_the_stop_reports_how_the_job_really_ended(
    status: BrowserSessionStatus, outcome: BrowserStopOutcome
) -> None:
    result = BrowserResultSnapshot(status=status, success=False, summary="x")
    await _job(BrowserJobStatus.DONE, result)
    await publish_job_event("job-1", JOB_TERMINAL_FRAME)

    assert await job_stop.confirm_stopped("job-1", within_seconds=1) is outcome


async def test_a_job_that_never_ends_is_reported_unconfirmed() -> None:
    await _job(BrowserJobStatus.RUNNING)

    assert (
        await job_stop.confirm_stopped("job-1", within_seconds=0.05)
        is BrowserStopOutcome.UNCONFIRMED
    )
