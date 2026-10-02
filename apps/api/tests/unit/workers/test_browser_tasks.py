"""The ARQ task behind a browser job: the slot it holds, and who tells the user the result.

Real code over fakeredis: the task body, the job store and the feed. The run itself
(execute_browser_job) and the narration (an LLM call) are stood in for.
"""

import asyncio
from typing import Any
from unittest.mock import MagicMock

import fakeredis.aioredis
import pytest

from app.agents.prompts.comms_prompts import INTERACTIVE_DELIVERY_NOTE
from app.constants.browser import (
    BROWSER_JOB_SLOT_TAKEN_SUMMARY,
    BROWSER_TASK_EVENT,
    BrowserSessionStatus,
    ResultSpeaker,
)
from app.constants.comms import SILENCE_TAG
from app.constants.log_tags import LogTag
from app.schemas.browser import BrowserResultSnapshot, BrowserStepSnapshot
from app.schemas.browser_job import BrowserJobRequest, BrowserJobState, BrowserJobStatus
from app.services.browser.job_events import publish_job_event
from app.services.browser.jobs import (
    claim_conversation_slot,
    claim_result_delivery,
    get_conversation_slot,
    get_job_state,
    hold_result_for_run,
    put_job_state,
    release_result_hold,
    request_job_cancel,
)
from app.workers.tasks import browser_tasks as tasks_mod
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.unit

PAYLOAD: dict[str, Any] = {
    "job_id": "job-1",
    "tool_call_id": "call-1",
    "user_id": "u1",
    "conversation_id": "conv-9",
    "task": "book a table",
    "stream_id": "s1",
}
DONE = BrowserResultSnapshot(
    status=BrowserSessionStatus.COMPLETED, success=True, summary="Booked the table."
)
STEP = {BROWSER_TASK_EVENT: BrowserStepSnapshot(index=1, goal="open").model_dump(mode="json")}


class World:
    def __init__(self) -> None:
        self.ran: list[BrowserJobRequest] = []
        self.narrated: list[str] = []
        self.delivered: list[dict[str, Any]] = []
        self.narration = "Booked it for you."
        #: The arguments each narration was asked with, after the run's own message.
        self.narrate_args: list[tuple[str, str, object, str]] = []
        self.users: dict[str, object] = {}
        #: Whether the heartbeat that holds the slot was alive while the run ran.
        self.heartbeat_alive: list[bool] = []


@pytest.fixture
def world(fake_redis: fakeredis.aioredis.FakeRedis, monkeypatch: pytest.MonkeyPatch) -> World:
    w = World()
    w.users["u1"] = MagicMock(user_id="u1")

    async def _execute(request: BrowserJobRequest) -> BrowserResultSnapshot:
        w.ran.append(request)
        w.heartbeat_alive.append(
            any(task.get_name() == "browser_job_heartbeat" for task in asyncio.all_tasks())
        )
        await publish_job_event(request.job_id, STEP)
        return DONE

    async def _narrate(
        text: str, msg_type: str, conversation_id: str, user: object, *, preamble: str
    ) -> str:
        w.narrated.append(text)
        w.narrate_args.append((msg_type, conversation_id, user, preamble))
        return w.narration

    async def _deliver(**kwargs: Any) -> None:
        w.delivered.append(kwargs)

    async def _user(user_id: str) -> object | None:
        return w.users.get(user_id)

    monkeypatch.setattr(tasks_mod, "execute_browser_job", _execute)
    monkeypatch.setattr(tasks_mod, "narrate_executor_result", _narrate)
    monkeypatch.setattr(tasks_mod, "deliver_message_to_conversation", _deliver)
    monkeypatch.setattr(tasks_mod, "load_user_context", _user)
    return w


async def test_an_unjoined_result_is_told_at_once_with_the_runs_cards(world: World) -> None:
    """Nobody holds the result, so the worker tells it now, not after a guessed grace, from the run's own message."""
    async with captured_wide_event() as event:
        status = await asyncio.wait_for(
            tasks_mod.run_browser_job({}, PAYLOAD | {"conversation_source": "telegram"}), timeout=2
        )

    assert status == BrowserSessionStatus.COMPLETED.value
    (delivery,) = world.delivered
    user = world.users["u1"]
    assert (delivery["conversation_id"], delivery["user"]) == ("conv-9", user)
    assert delivery["text"] == "Booked it for you."
    assert delivery["origin"] == "browser task (job job-1)"
    assert [entry["data"]["kind"] for entry in delivery["tool_data"]] == ["step"]
    assert world.narrated[0].startswith("Booked the table.")
    assert world.narrate_args == [("result", "conv-9", user, INTERACTIVE_DELIVERY_NOTE)]
    assert await get_conversation_slot("conv-9") is None
    assert world.heartbeat_alive == [True]
    assert event["user"] == {"id": "u1"}
    assert event["platform"] == "telegram"
    assert event["browser"] == {
        "job_id": "job-1",
        "conversation_id": "conv-9",
        "source_category": None,
        "delivered_by": "worker",
    }


async def test_the_running_job_beats_on_its_own_slot(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    beat = asyncio.Event()
    beats: list[tuple[str, str]] = []

    async def _beat(conversation_id: str, job_id: str) -> bool:
        beats.append((conversation_id, job_id))
        beat.set()
        return True

    monkeypatch.setattr(tasks_mod, "heartbeat_conversation_slot", _beat)
    monkeypatch.setattr(tasks_mod, "BROWSER_JOB_HEARTBEAT_SECONDS", 0)
    await hold_result_for_run("job-1", "s1")
    running = asyncio.create_task(tasks_mod.run_browser_job({}, PAYLOAD))

    await asyncio.wait_for(beat.wait(), timeout=2)
    await release_result_hold("job-1", "s1")
    await asyncio.wait_for(running, timeout=2)

    assert set(beats) == {("conv-9", "job-1")}


async def test_the_worker_waits_for_the_run_that_started_it_and_stays_quiet_if_it_spoke(
    world: World,
) -> None:
    await hold_result_for_run("job-1", "s1")
    running = asyncio.create_task(tasks_mod.run_browser_job({}, PAYLOAD))
    for _ in range(50):
        await asyncio.sleep(0)
    assert not running.done(), "the worker spoke over the run that may still join"

    assert await claim_result_delivery("job-1", ResultSpeaker.JOINER) is ResultSpeaker.JOINER
    await release_result_hold("job-1", "s1")
    await asyncio.wait_for(running, timeout=2)

    assert world.delivered == []


async def _stopped_while_queued(job_id: str) -> None:
    """Flag a job stopped as a stop does: only one that has not ended can be."""
    await put_job_state(BrowserJobState(job_id=job_id, status=BrowserJobStatus.QUEUED, task="t"))
    assert await request_job_cancel(job_id) is True


async def test_who_told_the_result_is_on_the_jobs_event(world: World) -> None:
    await claim_result_delivery("job-1", ResultSpeaker.JOINER)
    async with captured_wide_event() as told_by_joiner:
        await tasks_mod.run_browser_job({}, PAYLOAD)
    await _stopped_while_queued("job-2")
    async with captured_wide_event() as stopped:
        await tasks_mod.run_browser_job({}, PAYLOAD | {"job_id": "job-2"})

    assert told_by_joiner["browser"]["delivered_by"] == "joiner"
    assert stopped["browser"]["delivered_by"] == "stop"


async def test_a_stopped_job_is_not_narrated_a_second_time(world: World) -> None:
    """The stop already told the user."""
    await _stopped_while_queued("job-1")

    await tasks_mod.run_browser_job({}, PAYLOAD)

    assert world.delivered == []


async def test_a_job_whose_conversation_another_run_took_never_runs(world: World) -> None:
    """One browser per conversation: a job that queued past its lease while another started ends on its own card."""
    await claim_conversation_slot("conv-9", "job-other")

    async with captured_wide_event() as event:
        status = await tasks_mod.run_browser_job({}, PAYLOAD)

    [warning] = event["warnings"]
    assert "slot was taken" in warning["msg"]
    assert warning["browser"] == {"job_id": "job-1", "slot_holder": "job-other"}

    assert status == BrowserSessionStatus.FAILED.value
    assert world.ran == []
    state = await get_job_state("job-1")
    assert state is not None
    assert state.result is not None
    assert state.result.summary == BROWSER_JOB_SLOT_TAKEN_SUMMARY
    assert await get_conversation_slot("conv-9") == "job-other"


@pytest.mark.parametrize(
    ("narration", "why", "fields"),
    [
        ("", "the narration was empty", {"job_id": "job-1"}),
        (
            f"<{SILENCE_TAG}>nothing new</{SILENCE_TAG}>",
            "the narration was a directive",
            {"job_id": "job-1", "directive": "silence"},
        ),
    ],
)
async def test_a_narration_that_is_no_reply_is_not_delivered(
    world: World, narration: str, why: str, fields: dict[str, str]
) -> None:
    world.narration = narration

    async with captured_wide_event() as event:
        await tasks_mod.run_browser_job({}, PAYLOAD)

    assert world.delivered == []
    [warning] = event["warnings"]
    assert why in warning["msg"]
    assert warning["browser"] == fields


async def test_a_job_whose_user_is_gone_is_not_delivered(world: World) -> None:
    world.users.clear()

    async with captured_wide_event() as event:
        await tasks_mod.run_browser_job({}, PAYLOAD)

    assert world.delivered == []
    assert world.narrated == []
    [warning] = event["warnings"]
    assert "user not found" in warning["msg"]
    assert warning["browser"] == {"job_id": "job-1"}


async def test_one_failed_heartbeat_does_not_end_the_runs_hold_on_its_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A heartbeat that died on one Redis error would let the slot lapse under a live run."""
    beats: list[str] = []
    third_beat = asyncio.Event()

    async def _beat(conversation_id: str, job_id: str) -> bool:
        beats.append(f"{conversation_id}/{job_id}")
        if len(beats) == 1:
            raise ConnectionError("redis blinked")
        if len(beats) == 4:
            third_beat.set()
            await asyncio.Event().wait()
        # The second and third beats find another run holds the slot now.
        return False

    monkeypatch.setattr(tasks_mod, "heartbeat_conversation_slot", _beat)
    monkeypatch.setattr(tasks_mod, "BROWSER_JOB_HEARTBEAT_SECONDS", 0)
    async with captured_wide_event() as event:
        heartbeat = asyncio.create_task(
            tasks_mod._heartbeat(BrowserJobRequest.model_validate(PAYLOAD))
        )
        await asyncio.wait_for(third_beat.wait(), timeout=2)
        heartbeat.cancel()

    assert beats == ["conv-9/job-1"] * 4
    [error] = event["errors"]
    assert "heartbeat failed" in error["msg"]
    assert (error["error_type"], error["error"], error["browser"]) == (
        "ConnectionError",
        "redis blinked",
        {"job_id": "job-1"},
    )
    warnings = [(warning["msg"], warning["browser"]) for warning in event["warnings"]]
    assert (
        warnings
        == [
            (
                f"{LogTag.BROWSER} Browser job lost its conversation slot while running",
                {"job_id": "job-1"},
            )
        ]
        * 2
    )
