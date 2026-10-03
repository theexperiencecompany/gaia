"""The one telling of a browser job's ending: what lands in the executor inbox, and when nothing does.

Real code over fakeredis: the job store and the executor inbox.
"""

import pytest

from app.agents.core.background.executor_channel import ExecutorInbox
from app.constants.agents import AgentTag
from app.constants.browser import BrowserSessionStatus
from app.constants.log_tags import LogTag
from app.schemas.browser import BrowserResultSnapshot
from app.schemas.browser_job import (
    BrowserJobFinished,
    BrowserJobRequest,
    BrowserJobState,
    BrowserJobStatus,
    BrowserJobStopped,
)
from app.services.browser.job_teller import end_job, ending_message
from app.services.browser.jobs import done_state, landed_wake, landed_wakes, put_job_state
from tests.helpers import captured_wide_event

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("fake_redis")]

FINISHED = BrowserJobFinished(
    result=BrowserResultSnapshot(
        status=BrowserSessionStatus.COMPLETED, success=True, summary="Booked."
    )
)


async def _queued(job_id: str, conversation_id: str, *, in_background: bool = True) -> None:
    request = BrowserJobRequest(
        job_id=job_id,
        tool_call_id="call-1",
        user_id="u1",
        conversation_id=conversation_id,
        task="book",
        in_background=in_background,
    )
    await put_job_state(BrowserJobState.of(request, BrowserJobStatus.QUEUED))


async def test_each_ending_lands_as_its_own_entry_under_its_tag() -> None:
    """An inbox entry is retired by its id: two endings sharing one would retire each other."""
    await _queued("job-1", "conv-1")
    await _queued("job-2", "conv-1")

    await end_job("job-1", FINISHED)
    await end_job("job-2", BrowserJobStopped())

    result, stopped = await ExecutorInbox("conv-1").read()
    assert (result.tag, stopped.tag) == (AgentTag.BROWSER_RESULT, AgentTag.BROWSER_STOPPED)
    assert (result.text, stopped.text) == (
        ending_message("job-1", FINISHED),
        ending_message("job-2", BrowserJobStopped()),
    )
    assert result.id and stopped.id
    assert result.id != stopped.id


async def test_an_ending_for_a_job_nobody_queued_is_recorded_told_to_nobody_and_said() -> None:
    async with captured_wide_event() as event:
        recorded = await end_job("job-x", FINISHED)

    assert recorded is FINISHED
    assert await done_state("job-x") == FINISHED
    [warning] = event["warnings"]
    assert warning["msg"] == (
        f"{LogTag.BROWSER} Browser job ending recorded for a job with no state; nothing told"
    )
    assert warning["browser"] == {"job_id": "job-x", "ending": "finished"}


async def test_a_result_is_recorded_to_be_woken_for_and_a_stop_is_not() -> None:
    """A worker that dies between landing a result and waking a run must not strand it."""
    await _queued("job-1", "conv-1")
    await _queued("job-2", "conv-1")

    await end_job("job-1", FINISHED)
    await end_job("job-2", BrowserJobStopped())

    [entry, _notice] = await ExecutorInbox("conv-1").read()
    [wake] = await landed_wakes()
    assert (wake.job_id, wake.conversation_id, wake.user_id, wake.entry_id) == (
        "job-1",
        "conv-1",
        "u1",
        entry.id,
    )
    assert wake.landed_at > 0
    assert await landed_wake("job-2") is None


async def test_a_headless_result_is_never_woken_for() -> None:
    await _queued("job-1", "conv-1", in_background=False)

    await end_job("job-1", FINISHED)

    assert await landed_wakes() == []
