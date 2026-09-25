"""The executor's join on a detached browser job: the lease it holds, what it returns, and when it hands delivery back.

The lease is the whole "who speaks the result" invariant: while it is held the
worker stays quiet, so every exit from this tool — answer, timeout, dead worker,
cancelled turn — has to drop it or the user is told nothing at all.
"""

import asyncio
from typing import Any

from langchain_core.runnables.config import RunnableConfig
import pytest

from app.agents.tools import browser_tool as tool_mod
from app.agents.tools.browser_tool import wait_for_browser_task
from app.constants.browser import (
    BROWSER_JOB_JOINER_REFRESH_SECONDS,
    BrowserSessionStatus,
)
from app.constants.log_tags import LogTag
from app.schemas.browser import (
    AgentGuidanceRequest,
    BrowserResultSnapshot,
    PendingAgentGuidance,
)
from app.schemas.browser_job import BrowserJobState, BrowserJobStatus
from app.services.browser.job_runner import agent_result_message
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.unit

UI_CONFIG: RunnableConfig = {
    "configurable": {"user_id": "u1", "thread_id": "c1", "stream_id": "s1"}
}

RUNNING = BrowserJobState(job_id="job-1", status=BrowserJobStatus.RUNNING, task="book a table")
DONE = BrowserJobState(
    job_id="job-1",
    status=BrowserJobStatus.DONE,
    task="book a table",
    agent_message="Booked the table.\n\nTell the user.",
    result=BrowserResultSnapshot(
        status=BrowserSessionStatus.COMPLETED, success=True, summary="Booked the table."
    ),
)


class Joiner:
    """What the join did to the job store, in order."""

    def __init__(self) -> None:
        self.taken: list[tuple[str, str]] = []
        self.refreshed: list[tuple[str, str]] = []
        #: The fake clock's reading at each refresh.
        self.refreshed_at: list[float] = []
        #: Every id the join looked anything up by.
        self.asked_conversations: list[str] = []
        self.asked_jobs: list[str] = []
        self.dropped: list[str] = []
        self.polls = 0
        self.slept = 0.0
        #: Set once the poll loop is genuinely running, so a cancel lands mid-wait.
        self.polling = asyncio.Event()


def _install(
    monkeypatch: pytest.MonkeyPatch,
    *,
    slots: list[str | None],
    states: list[BrowserJobState | None],
    real_sleep: bool = False,
    guidance: PendingAgentGuidance | None = None,
) -> Joiner:
    """Script the slot and the state one answer per poll; the last answer repeats forever."""
    j = Joiner()

    async def _slot(conversation_id: str) -> str | None:
        j.asked_conversations.append(conversation_id)
        return slots[min(j.polls, len(slots) - 1)]

    async def _state(job_id: str) -> BrowserJobState | None:
        j.asked_jobs.append(job_id)
        answer = states[min(j.polls, len(states) - 1)]
        j.polls += 1
        if j.polls >= 2:
            j.polling.set()
        return answer

    async def _take(job_id: str, stream_id: str) -> None:
        j.taken.append((job_id, stream_id))

    async def _refresh(job_id: str, stream_id: str) -> None:
        j.refreshed.append((job_id, stream_id))
        j.refreshed_at.append(j.slept)

    async def _drop(job_id: str) -> None:
        j.dropped.append(job_id)

    async def _sleep(seconds: float) -> None:
        j.slept += seconds

    async def _guidance(job_id: str) -> PendingAgentGuidance | None:
        j.asked_jobs.append(job_id)
        return guidance

    monkeypatch.setattr(tool_mod, "get_guidance_request", _guidance)
    monkeypatch.setattr(tool_mod, "get_conversation_slot", _slot)
    monkeypatch.setattr(tool_mod, "get_job_state", _state)
    monkeypatch.setattr(tool_mod, "take_joiner_lease", _take)
    monkeypatch.setattr(tool_mod, "refresh_joiner_lease", _refresh)
    monkeypatch.setattr(tool_mod, "drop_joiner_lease", _drop)
    if not real_sleep:
        monkeypatch.setattr(tool_mod.asyncio, "sleep", _sleep)
    return j


async def test_nothing_running_returns_at_once_without_taking_a_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lease taken on nothing would be dropped anyway, but the model must hear that there is no run rather than wait out a timeout."""
    j = _install(monkeypatch, slots=[None], states=[None])

    out = await wait_for_browser_task.ainvoke({}, config=UI_CONFIG)

    assert out == "No browser task is running."
    assert j.taken == []
    assert j.polls == 0


async def test_the_finished_runs_own_guidance_is_returned_verbatim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The worker already shaped the answer; re-deriving it here would give the same run two different voices."""
    j = _install(monkeypatch, slots=["job-1"], states=[RUNNING, RUNNING, DONE])

    out = await wait_for_browser_task.ainvoke({}, config=UI_CONFIG)

    assert out == DONE.agent_message
    assert j.taken == [("job-1", "s1")]


async def test_collecting_the_result_hands_nothing_back_to_the_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dropped lease is what tells the worker its result has been spoken; a leaked one is a silent double-delivery guard that never lifts."""
    j = _install(monkeypatch, slots=["job-1"], states=[DONE])

    await wait_for_browser_task.ainvoke({}, config=UI_CONFIG)

    assert j.dropped == ["job-1"]


async def test_a_job_whose_slot_died_is_reported_as_not_completed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the worker holds the slot: a RUNNING state with no slot is a worker that died, and waiting out the timeout would strand the turn."""
    j = _install(monkeypatch, slots=["job-1", None], states=[RUNNING])

    out = await wait_for_browser_task.ainvoke({}, config=UI_CONFIG)

    assert out == agent_result_message(
        BrowserResultSnapshot(
            status=BrowserSessionStatus.FAILED,
            success=False,
            summary="the browser worker stopped unexpectedly",
        )
    )
    assert "Do not run the browser again" in out
    assert j.dropped == ["job-1"]


async def test_a_run_that_outlasts_the_wait_is_left_to_the_worker_to_deliver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    j = _install(monkeypatch, slots=["job-1"], states=[RUNNING])

    out = await wait_for_browser_task.ainvoke({"timeout": 1}, config=UI_CONFIG)

    assert out == (
        "The browser task is still running; it will be delivered to the user when it finishes."
    )
    assert j.dropped == ["job-1"]
    assert j.slept == pytest.approx(1.0)


async def test_a_cancelled_turn_releases_the_lease_on_the_way_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A turn stopped mid-wait must not keep suppressing the worker's delivery: the run is still going and someone has to report it."""
    j = _install(monkeypatch, slots=["job-1"], states=[RUNNING], real_sleep=True)
    monkeypatch.setattr(tool_mod, "BROWSER_JOB_POLL_INTERVAL_SECONDS", 0.001)

    task: asyncio.Task[Any] = asyncio.create_task(
        wait_for_browser_task.ainvoke({"timeout": 600}, config=UI_CONFIG)
    )
    await j.polling.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert j.dropped == ["job-1"]


async def test_a_turn_with_no_stream_still_joins_on_the_conversations_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The lease's value names the waiting turn; a missing stream id makes it anonymous, not absent."""
    j = _install(monkeypatch, slots=["job-1"], states=[DONE])

    out = await wait_for_browser_task.ainvoke(
        {}, config={"configurable": {"user_id": "u1", "thread_id": "c1"}}
    )

    assert out == DONE.agent_message
    assert j.taken == [("job-1", "")]


STUCK = PendingAgentGuidance(
    handoff_id="h-1",
    request=AgentGuidanceRequest(
        reason="The booking form rejects every date.",
        task="book a table",
        url="https://example.test/book",
        title="Book",
    ),
)


async def test_a_run_waiting_on_guidance_comes_back_at_once_with_what_it_needs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The run is parked until the executor answers, so polling it to the timeout would burn the whole wait on a question already asked."""
    _install(monkeypatch, slots=["job-1"], states=[RUNNING], guidance=STUCK)

    out = await wait_for_browser_task.ainvoke({"timeout": 600}, config=UI_CONFIG)

    assert "STUCK" in out
    assert "The booking form rejects every date." in out
    assert "guide_browser_task" in out


async def test_asking_for_guidance_keeps_this_turns_claim_on_the_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The executor is coming straight back; a dropped lease would let the worker decide nobody is joined and narrate the run itself."""
    j = _install(monkeypatch, slots=["job-1"], states=[RUNNING], guidance=STUCK)

    await wait_for_browser_task.ainvoke({"timeout": 600}, config=UI_CONFIG)

    assert j.dropped == []


WORKER_DIED = agent_result_message(
    BrowserResultSnapshot(
        status=BrowserSessionStatus.FAILED,
        success=False,
        summary="the browser worker stopped unexpectedly",
    )
)


async def test_a_join_with_no_timeout_waits_the_documented_ten_minutes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The schema promises the model a 600 s default; the raw coroutine is what that default is read from."""
    j = _install(monkeypatch, slots=["job-1"], states=[RUNNING])

    out = await wait_for_browser_task.coroutine(config=UI_CONFIG)

    assert out == tool_mod._STILL_RUNNING
    assert j.slept == pytest.approx(600.0)


async def test_a_long_wait_re_arms_the_lease_on_the_refresh_cadence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The lease outlives a refresh interval by a margin only; a late or missing refresh lets the worker speak over this turn."""
    j = _install(monkeypatch, slots=["job-1"], states=[RUNNING])

    await wait_for_browser_task.ainvoke({"timeout": 20}, config=UI_CONFIG)

    step = BROWSER_JOB_JOINER_REFRESH_SECONDS
    assert j.refreshed_at == pytest.approx([step, 2 * step, 3 * step, 4 * step])
    assert set(j.refreshed) == {("job-1", "s1")}


async def test_the_join_follows_its_own_conversations_job_throughout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    j = _install(monkeypatch, slots=["job-1"], states=[RUNNING, RUNNING, DONE])

    await wait_for_browser_task.ainvoke({}, config=UI_CONFIG)

    assert set(j.asked_conversations) == {"c1"}
    assert set(j.asked_jobs) == {"job-1"}


async def test_a_finished_run_that_left_no_answer_is_reported_as_not_completed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A DONE state with no message is a worker that died mid-write; an empty reply would read as success."""
    done_silent = DONE.model_copy(update={"agent_message": None})
    _install(monkeypatch, slots=["job-1"], states=[done_silent])

    out = await wait_for_browser_task.ainvoke({}, config=UI_CONFIG)

    assert out == WORKER_DIED


async def test_a_queued_job_whose_enqueue_lease_lapsed_is_still_waited_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A QUEUED job never had a worker; a missing slot says nothing about it, and a worker still booting will run it."""
    queued = BrowserJobState(job_id="job-1", status=BrowserJobStatus.QUEUED, task="book a table")
    _install(monkeypatch, slots=["job-1", None], states=[queued, queued, DONE])

    out = await wait_for_browser_task.ainvoke({}, config=UI_CONFIG)

    assert out == DONE.agent_message


async def test_a_lost_worker_is_a_warning_naming_the_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, slots=["job-1", None], states=[RUNNING])

    async with captured_wide_event() as event:
        await wait_for_browser_task.ainvoke({}, config=UI_CONFIG)

    (warning,) = [w for w in event["warnings"] if "browser" in w]
    assert warning["msg"].startswith(LogTag.BROWSER)
    assert warning["browser"] == {"job_id": "job-1"}


async def test_a_join_that_gave_up_waiting_says_so_on_the_wide_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A timed-out join hands delivery to the worker; the event is how a missing follow-up is traced to it."""
    _install(monkeypatch, slots=["job-1"], states=[RUNNING])

    async with captured_wide_event() as event:
        await wait_for_browser_task.ainvoke({"timeout": 1}, config=UI_CONFIG)

    assert event["browser"] == {"job_id": "job-1", "join": "timed_out_still_running"}
