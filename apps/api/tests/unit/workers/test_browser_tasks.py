"""The ARQ task behind a browser job: the terminal state it writes, the slot it holds, and who speaks the result."""

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.constants.browser import (
    BROWSER_JOB_HEARTBEAT_SECONDS,
    BROWSER_JOB_JOINER_LEASE_SECONDS,
    BROWSER_JOB_JOINER_REFRESH_SECONDS,
    BROWSER_TASK_EVENT,
    BrowserSessionStatus,
)
from app.schemas.browser import BrowserResultSnapshot
from app.schemas.browser_job import BrowserJobRequest, BrowserJobState, BrowserJobStatus
from app.services.browser.job_events import JOB_TERMINAL_FRAME
from app.services.browser.job_runner import agent_result_message
from app.workers.tasks import browser_tasks as tasks_mod
from shared.py.wide_events import log, log_context

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
        self.narrated: list[tuple[str, str, str, object]] = []
        self.claims: list[tuple[str, str]] = []
        self.loaded_users: list[str] = []
        self.delivered: list[dict[str, Any]] = []
        self.ran: list[BrowserJobRequest] = []
        self.reads: list[tuple[str, str, int]] = []
        #: The job's card feed, as a test sets it up before the run.
        self.feed: list[dict[str, Any]] = []
        self.slept: float = 0.0


def _install(
    monkeypatch: pytest.MonkeyPatch,
    *,
    result: BrowserResultSnapshot | None = None,
    lease: list[bool] | None = None,
    narration: str = "Booked it for you.",
    missing_user: bool = False,
    slot_holder: str | None = None,
) -> Worker:
    """Wire every seam of the task to a recorder; the lease answers one entry per poll."""
    w = Worker()
    lease_answers = iter(lease or [])

    async def _execute(request: BrowserJobRequest) -> BrowserResultSnapshot:
        w.ran.append(request)
        return result or DONE

    async def _put_state(state: BrowserJobState) -> None:
        w.states.append(state)

    async def _publish(job_id: str, payload: dict[str, Any]) -> None:
        w.frames.append((job_id, payload))

    async def _heartbeat(conversation_id: str, job_id: str) -> None:
        w.heartbeats.append((conversation_id, job_id))

    async def _release(conversation_id: str, job_id: str) -> None:
        w.released.append((conversation_id, job_id))

    async def _claim(conversation_id: str, job_id: str) -> str | None:
        w.claims.append((conversation_id, job_id))
        return slot_holder

    async def _lease_held(job_id: str) -> bool:
        # The lease is this job's; nobody ever joins on another id.
        return next(lease_answers, False) if job_id == PAYLOAD["job_id"] else False

    async def _load_user(user_id: str) -> object | None:
        w.loaded_users.append(user_id)
        return None if missing_user else MagicMock(user_id=user_id)

    async def _narrate(text: str, msg_type: str, conversation_id: str, user: object) -> str:
        w.narrated.append((text, msg_type, conversation_id, user))
        return narration

    async def _deliver(**kwargs: Any) -> None:
        w.delivered.append(kwargs)

    async def _read_events(job_id: str, cursor: str, block_ms: int) -> list[tuple[str, Any]]:
        w.reads.append((job_id, cursor, block_ms))
        return [(f"1-{i}", frame) for i, frame in enumerate(w.feed)]

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
    monkeypatch.setattr(tasks_mod, "claim_conversation_slot", _claim)
    monkeypatch.setattr(tasks_mod, "joiner_lease_held", _lease_held)
    monkeypatch.setattr(tasks_mod, "load_user_context", _load_user)
    monkeypatch.setattr(tasks_mod, "narrate_executor_result", _narrate)
    monkeypatch.setattr(tasks_mod, "deliver_message_to_conversation", _deliver)
    monkeypatch.setattr(tasks_mod, "read_job_events", _read_events)
    monkeypatch.setattr(tasks_mod.asyncio, "sleep", _sleep)
    return w


async def _run_logged(payload: dict[str, Any] = PAYLOAD) -> dict[str, Any]:
    """Run the job inside the worker_task boundary arq_task opens, and return its wide event."""
    async with log_context("run_browser_job"):
        await tasks_mod.run_browser_job({}, payload)
        return dict(log.get())


# ---------------------------------------------------------------------------
# what the job leaves behind
# ---------------------------------------------------------------------------


async def test_the_jobs_event_names_its_user_platform_conversation_and_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one queryable record of a background browser run; without these it cannot be tied to anyone."""
    _install(monkeypatch)
    payload = {**PAYLOAD, "conversation_source": "telegram", "source_category": "chat"}

    event = await _run_logged(payload)

    assert event["user"] == {"id": "u1"}
    assert event["platform"] == "telegram"
    assert {
        key: event["browser"][key] for key in ("job_id", "conversation_id", "source_category")
    } == {
        "job_id": "job-1",
        "conversation_id": "conv-9",
        "source_category": "chat",
    }


async def test_the_run_retakes_its_conversations_slot_before_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The enqueuer's lease went unrefreshed through the queue wait and may have expired."""
    w = _install(monkeypatch)

    await tasks_mod.run_browser_job({}, PAYLOAD)

    assert w.claims == [("conv-9", "job-1")]


async def test_a_run_whose_slot_another_job_took_says_so_on_its_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, slot_holder="job-other")

    event = await _run_logged()

    [warning] = event["warnings"]
    assert "without its conversation slot" in warning["msg"]
    assert warning["browser"] == {"job_id": "job-1", "slot_holder": "job-other"}


async def test_a_run_that_still_holds_its_own_slot_warns_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, slot_holder="job-1")

    event = await _run_logged()

    assert "warnings" not in event


async def test_a_long_run_keeps_refreshing_its_own_conversations_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without the heartbeat the slot lease lapses mid-run and a joiner reads the live job as dead."""
    w = _install(monkeypatch)
    sleeps: list[float] = []

    async def _no_wait(seconds: float) -> None:
        sleeps.append(seconds)
        await _real_sleep(0)

    async def _runs_until_heartbeat(request: BrowserJobRequest) -> BrowserResultSnapshot:
        for _ in range(50):
            if w.heartbeats:
                break
            await _real_sleep(0)
        return DONE

    monkeypatch.setattr(tasks_mod.asyncio, "sleep", _no_wait)
    monkeypatch.setattr(tasks_mod, "execute_browser_job", _runs_until_heartbeat)

    await tasks_mod.run_browser_job({}, PAYLOAD)

    assert w.heartbeats[0] == ("conv-9", "job-1")
    # The first wait is the heartbeat's, before its first refresh: one interval, not a spin.
    assert sleeps[0] == BROWSER_JOB_HEARTBEAT_SECONDS


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


async def test_a_result_the_joiner_collected_is_recorded_as_delivered_by_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, lease=[True, False])

    event = await _run_logged()

    assert event["browser"]["delivered_by"] == "joiner"


async def test_an_unjoined_result_is_narrated_from_the_runs_own_message_for_its_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The comms voice rewrites exactly what the run said, as a result, in the job's conversation, for the job's user."""
    w = _install(monkeypatch, lease=[])

    event = await _run_logged()

    [(text, msg_type, conversation_id, user)] = w.narrated
    assert (text, msg_type, conversation_id) == (agent_result_message(DONE), "result", "conv-9")
    assert user.user_id == "u1"
    assert w.loaded_users == ["u1"]
    assert event["browser"]["delivered_by"] == "worker"


async def test_an_unjoined_result_lands_in_the_jobs_conversation_labelled_with_the_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w = _install(monkeypatch, lease=[])

    await tasks_mod.run_browser_job({}, PAYLOAD)

    [delivery] = w.delivered
    assert delivery["conversation_id"] == "conv-9"
    assert delivery["user"].user_id == "u1"
    assert "job-1" in delivery["origin"]


async def test_the_wait_for_a_joiner_is_bounded_by_its_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unjoined result must not sit unspoken: the wait ends one refresh after the lease could last."""
    w = _install(monkeypatch, lease=[])

    await tasks_mod.run_browser_job({}, PAYLOAD)

    assert w.slept == BROWSER_JOB_JOINER_LEASE_SECONDS + BROWSER_JOB_JOINER_REFRESH_SECONDS


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

    event = await _run_logged()

    assert w.delivered == []
    [warning] = event["warnings"]
    assert "narration was empty" in warning["msg"]
    assert warning["browser"] == {"job_id": "job-1"}


async def test_a_job_whose_user_is_gone_is_not_delivered_anywhere(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w = _install(monkeypatch, lease=[], missing_user=True)

    event = await _run_logged()

    assert w.delivered == []
    [warning] = event["warnings"]
    assert "user not found" in warning["msg"]
    assert warning["browser"] == {"job_id": "job-1"}


# ---------------------------------------------------------------------------
# the cards a follow-up carries
# ---------------------------------------------------------------------------

CARD_FRAME: dict[str, Any] = {
    "tool_data": {
        "tool_name": BROWSER_TASK_EVENT,
        "data": {"kind": "result", "summary": "Booked the table."},
        "timestamp": "2026-09-19T00:00:00+00:00",
    }
}


async def test_the_whole_feed_is_drained_without_blocking_on_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """From 0-0 so the first card is included, and without a BLOCK: the run is over, so waiting for a frame that will never come would hang the job."""
    w = _install(monkeypatch, lease=[])
    w.feed = [CARD_FRAME]

    await tasks_mod.run_browser_job({}, PAYLOAD)

    assert w.reads == [("job-1", "0-0", 0)]


async def test_a_run_with_no_cards_still_delivers_its_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w = _install(monkeypatch, lease=[])

    await tasks_mod.run_browser_job({}, PAYLOAD)

    assert w.delivered[0]["tool_data"] == []
    assert w.delivered[0]["text"] == "Booked it for you."
