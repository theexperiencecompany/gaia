"""The ARQ task behind a browser job: the terminal state it writes, the slot it holds, and who speaks the result."""

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.constants.browser import (
    BROWSER_JOB_HEARTBEAT_SECONDS,
    BROWSER_JOB_JOINER_LEASE_SECONDS,
    BROWSER_JOB_JOINER_REFRESH_SECONDS,
    BrowserSessionStatus,
)
from app.schemas.browser import BrowserResultSnapshot
from app.schemas.browser_job import BrowserJobRequest, BrowserJobState, BrowserJobStatus
from app.services.browser.job_events import JOB_TERMINAL_FRAME
from app.services.browser.job_runner import agent_result_message
from app.workers.tasks import browser_tasks as tasks_mod

pytestmark = pytest.mark.unit

#: Captured before the task module's sleep is faked out, so a test can still
#: hand the event loop back to a task it wants to see run.
_real_sleep = asyncio.sleep

PAYLOAD: dict[str, Any] = {
    "job_id": "job-1",
    "user_id": "u1",
    "conversation_id": "conv-9",
    "task": "book a table",
    "stream_id": "s1",
}

DONE = BrowserResultSnapshot(
    status=BrowserSessionStatus.COMPLETED, success=True, summary="Booked the table."
)


class Worker:
    """Everything the task did to the world, captured for assertion."""

    def __init__(self) -> None:
        self.states: list[BrowserJobState] = []
        self.frames: list[tuple[str, dict[str, Any]]] = []
        self.heartbeats: list[tuple[str, str]] = []
        self.released: list[tuple[str, str]] = []
        self.narrated: list[tuple[str, str, str]] = []
        self.delivered: list[dict[str, Any]] = []
        self.ran: list[BrowserJobRequest] = []
        self.slept: float = 0.0


def _install(
    monkeypatch: pytest.MonkeyPatch,
    *,
    result: BrowserResultSnapshot | None = None,
    run_error: Exception | None = None,
    lease: list[bool] | None = None,
    narration: str = "Booked it for you.",
    missing_user: bool = False,
) -> Worker:
    """Wire every seam of the task to a recorder; the lease answers one entry per poll."""
    w = Worker()
    lease_answers = iter(lease or [])

    async def _execute(request: BrowserJobRequest) -> BrowserResultSnapshot:
        w.ran.append(request)
        if run_error is not None:
            raise run_error
        return result or DONE

    async def _put_state(state: BrowserJobState) -> None:
        w.states.append(state)

    async def _publish(job_id: str, payload: dict[str, Any]) -> None:
        w.frames.append((job_id, payload))

    async def _heartbeat(conversation_id: str, job_id: str) -> None:
        w.heartbeats.append((conversation_id, job_id))

    async def _release(conversation_id: str, job_id: str) -> None:
        w.released.append((conversation_id, job_id))

    async def _lease_held(job_id: str) -> bool:
        return next(lease_answers, False)

    async def _load_user(user_id: str) -> object | None:
        return None if missing_user else MagicMock(user_id=user_id)

    async def _narrate(text: str, msg_type: str, conversation_id: str, _user: object) -> str:
        w.narrated.append((text, msg_type, conversation_id))
        return narration

    async def _deliver(**kwargs: Any) -> None:
        w.delivered.append(kwargs)

    async def _sleep(seconds: float) -> None:
        if seconds == BROWSER_JOB_HEARTBEAT_SECONDS:
            # The heartbeat parks here for the whole test and is cancelled with
            # the run; only the delivery wait's sleeps are virtual.
            await _real_sleep(BROWSER_JOB_HEARTBEAT_SECONDS)
        w.slept += seconds

    monkeypatch.setattr(tasks_mod, "execute_browser_job", _execute)
    monkeypatch.setattr(tasks_mod, "put_job_state", _put_state)
    monkeypatch.setattr(tasks_mod, "publish_job_event", _publish)
    monkeypatch.setattr(tasks_mod, "heartbeat_conversation_slot", _heartbeat)
    monkeypatch.setattr(tasks_mod, "release_conversation_slot", _release)
    monkeypatch.setattr(tasks_mod, "joiner_lease_held", _lease_held)
    monkeypatch.setattr(tasks_mod, "load_user_context", _load_user)
    monkeypatch.setattr(tasks_mod, "narrate_executor_result", _narrate)
    monkeypatch.setattr(tasks_mod, "deliver_message_to_conversation", _deliver)
    monkeypatch.setattr(tasks_mod.asyncio, "sleep", _sleep)
    return w


# ---------------------------------------------------------------------------
# what the job leaves behind
# ---------------------------------------------------------------------------


async def test_the_finished_run_is_written_where_a_joiner_reads_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The join tool and a restarted API have only this state to answer "is it done, and what did it say?"."""
    w = _install(monkeypatch)

    await tasks_mod.run_browser_job({}, PAYLOAD)

    assert w.states[-1] == BrowserJobState(
        job_id="job-1",
        status=BrowserJobStatus.DONE,
        task="book a table",
        agent_message=agent_result_message(DONE),
        result=DONE,
    )


async def test_the_payload_crossing_the_queue_is_validated_into_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w = _install(monkeypatch)

    await tasks_mod.run_browser_job({}, PAYLOAD)

    assert w.ran == [BrowserJobRequest.model_validate(PAYLOAD)]


async def test_the_feed_is_closed_so_a_relay_stops_without_re_reading_the_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w = _install(monkeypatch)

    await tasks_mod.run_browser_job({}, PAYLOAD)

    assert w.frames == [("job-1", JOB_TERMINAL_FRAME)]


async def test_the_conversations_slot_is_released_when_the_run_ends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w = _install(monkeypatch)

    await tasks_mod.run_browser_job({}, PAYLOAD)

    assert w.released == [("conv-9", "job-1")]


async def test_a_run_that_blows_up_still_frees_the_conversation_and_reports_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A wedged slot would refuse every later browser task in this conversation, and silence would leave the user waiting on a run that is already dead."""
    w = _install(monkeypatch, run_error=RuntimeError("the host vanished"))
    fake_log = MagicMock()
    monkeypatch.setattr(tasks_mod, "log", fake_log)

    await tasks_mod.run_browser_job({}, PAYLOAD)

    assert w.released == [("conv-9", "job-1")]
    assert w.states[-1].status is BrowserJobStatus.DONE
    assert w.states[-1].result is not None
    assert w.states[-1].result.status is BrowserSessionStatus.FAILED
    assert "the host vanished" in w.states[-1].result.summary
    assert len(w.delivered) == 1
    fake_log.error.assert_called_once()


async def test_the_slot_lease_is_refreshed_for_as_long_as_the_run_lasts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing else holds the slot: without the heartbeat a run that legitimately sits inside a handoff loses it within the lease's two minutes."""
    w = _install(monkeypatch)
    intervals: list[float] = []

    async def _sleep(seconds: float) -> None:
        intervals.append(seconds)
        if len(w.heartbeats) >= 3:
            raise asyncio.CancelledError

    monkeypatch.setattr(tasks_mod.asyncio, "sleep", _sleep)

    with pytest.raises(asyncio.CancelledError):
        await tasks_mod._heartbeat(BrowserJobRequest.model_validate(PAYLOAD))

    assert w.heartbeats == [("conv-9", "job-1")] * 3
    assert intervals == [BROWSER_JOB_HEARTBEAT_SECONDS] * 4


async def test_the_heartbeat_stops_with_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """A heartbeat outliving its run would hold the conversation's slot against a job that is already finished."""
    spawned: list[Any] = []
    _install(monkeypatch)
    real_spawn = tasks_mod.spawn_background_task

    def _spawn(coro: Any, **kwargs: Any) -> Any:
        task = real_spawn(coro, **kwargs)
        spawned.append((task, kwargs.get("name")))
        return task

    monkeypatch.setattr(tasks_mod, "spawn_background_task", _spawn)

    await tasks_mod.run_browser_job({}, PAYLOAD)
    await _real_sleep(0)

    assert [name for _, name in spawned] == ["browser_job_heartbeat"]
    assert spawned[0][0].cancelled()


# ---------------------------------------------------------------------------
# exactly one party speaks the result
# ---------------------------------------------------------------------------


async def test_a_joiner_that_collects_the_result_keeps_the_worker_quiet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The executor took the lease and dropped it as it collected; delivering here too would say the same thing twice."""
    w = _install(monkeypatch, lease=[True, True, False])

    await tasks_mod.run_browser_job({}, PAYLOAD)

    assert w.delivered == []
    assert w.narrated == []


async def test_a_turn_that_ended_first_gets_the_result_as_a_follow_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nobody is waiting, so the run's own answer has to reach the user as a message — in the conversation's own voice."""
    w = _install(monkeypatch, lease=[])

    await tasks_mod.run_browser_job({}, PAYLOAD)

    assert w.narrated == [(agent_result_message(DONE), "result", "conv-9")]
    assert len(w.delivered) == 1
    assert w.delivered[0]["conversation_id"] == "conv-9"
    assert w.delivered[0]["text"] == "Booked it for you."
    assert "job-1" in w.delivered[0]["origin"]


async def test_the_wait_for_a_joiner_is_bounded_by_its_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unjoined result must not sit unspoken: the wait ends one refresh after the lease could last."""
    w = _install(monkeypatch, lease=[])

    await tasks_mod.run_browser_job({}, PAYLOAD)

    assert (
        BROWSER_JOB_JOINER_LEASE_SECONDS
        <= w.slept
        <= BROWSER_JOB_JOINER_LEASE_SECONDS + BROWSER_JOB_JOINER_REFRESH_SECONDS
    )


async def test_a_joiner_that_never_collects_does_not_cost_the_user_the_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stuck executor holds the lease forever; dropping the result then would leave the user with a run nobody ever reported."""
    w = _install(monkeypatch, lease=[True] * 500)

    await tasks_mod.run_browser_job({}, PAYLOAD)

    assert len(w.delivered) == 1


async def test_nothing_is_delivered_when_the_narration_comes_back_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """narrate_executor_result degrades to "" when comms is unavailable; an empty bot message is worse than none."""
    w = _install(monkeypatch, lease=[], narration="")

    await tasks_mod.run_browser_job({}, PAYLOAD)

    assert w.delivered == []


async def test_a_job_whose_user_is_gone_is_not_delivered_anywhere(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w = _install(monkeypatch, lease=[], missing_user=True)
    fake_log = MagicMock()
    monkeypatch.setattr(tasks_mod, "log", fake_log)

    await tasks_mod.run_browser_job({}, PAYLOAD)

    assert w.delivered == []
    fake_log.warning.assert_called_once()
