"""The ARQ task behind a browser job: the slot it holds, and who tells the user the result.

Real code over fakeredis: the task body, the job store and the feed. The run itself
(execute_browser_job) and the narration (an LLM call) are stood in for.
"""

import asyncio
from typing import Any
from unittest.mock import MagicMock

import fakeredis.aioredis
import pytest

from app.constants.browser import (
    BROWSER_JOB_SLOT_TAKEN_SUMMARY,
    BROWSER_TASK_EVENT,
    BrowserSessionStatus,
    ResultSpeaker,
)
from app.constants.comms import SILENCE_TAG
from app.schemas.browser import BrowserResultSnapshot, BrowserStepSnapshot
from app.schemas.browser_job import BrowserJobRequest
from app.services.browser.job_events import publish_job_event
from app.services.browser.jobs import (
    claim_conversation_slot,
    claim_result_delivery,
    get_conversation_slot,
    get_job_state,
    hold_result_for_run,
    release_result_hold,
    request_job_cancel,
)
from app.workers.tasks import browser_tasks as tasks_mod

pytestmark = pytest.mark.unit

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
STEP = {BROWSER_TASK_EVENT: BrowserStepSnapshot(index=1, goal="open").model_dump(mode="json")}


class World:
    def __init__(self) -> None:
        self.ran: list[BrowserJobRequest] = []
        self.narrated: list[str] = []
        self.delivered: list[dict[str, Any]] = []
        self.narration = "Booked it for you."


@pytest.fixture
def world(fake_redis: fakeredis.aioredis.FakeRedis, monkeypatch: pytest.MonkeyPatch) -> World:
    w = World()

    async def _execute(request: BrowserJobRequest) -> BrowserResultSnapshot:
        w.ran.append(request)
        await publish_job_event(request.job_id, STEP)
        return DONE

    async def _narrate(
        text: str, msg_type: str, conversation_id: str, user: object, *, preamble: str
    ) -> str:
        w.narrated.append(text)
        return w.narration

    async def _deliver(**kwargs: Any) -> None:
        w.delivered.append(kwargs)

    async def _user(user_id: str) -> object:
        return MagicMock(user_id=user_id)

    monkeypatch.setattr(tasks_mod, "execute_browser_job", _execute)
    monkeypatch.setattr(tasks_mod, "narrate_executor_result", _narrate)
    monkeypatch.setattr(tasks_mod, "deliver_message_to_conversation", _deliver)
    monkeypatch.setattr(tasks_mod, "load_user_context", _user)
    return w


async def test_an_unjoined_result_is_told_at_once_with_the_runs_cards(world: World) -> None:
    """Nobody holds the result, so the worker tells it now, not after a guessed grace, from the run's own message."""
    status = await asyncio.wait_for(tasks_mod.run_browser_job({}, PAYLOAD), timeout=2)

    assert status == BrowserSessionStatus.COMPLETED.value
    (delivery,) = world.delivered
    assert delivery["conversation_id"] == "conv-9"
    assert delivery["text"] == "Booked it for you."
    assert [entry["data"]["kind"] for entry in delivery["tool_data"]] == ["step"]
    assert world.narrated[0].startswith("Booked the table.")
    assert await get_conversation_slot("conv-9") is None


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


async def test_a_stopped_job_is_not_narrated_a_second_time(world: World) -> None:
    """The stop already told the user."""
    await request_job_cancel("job-1")

    await tasks_mod.run_browser_job({}, PAYLOAD)

    assert world.delivered == []


async def test_a_job_whose_conversation_another_run_took_never_runs(world: World) -> None:
    """One browser per conversation: a job that queued past its lease while another started ends on its own card."""
    await claim_conversation_slot("conv-9", "job-other")

    status = await tasks_mod.run_browser_job({}, PAYLOAD)

    assert status == BrowserSessionStatus.FAILED.value
    assert world.ran == []
    state = await get_job_state("job-1")
    assert state is not None
    assert state.result is not None
    assert state.result.summary == BROWSER_JOB_SLOT_TAKEN_SUMMARY
    assert await get_conversation_slot("conv-9") == "job-other"


@pytest.mark.parametrize("narration", ["", f"<{SILENCE_TAG}>nothing new</{SILENCE_TAG}>"])
async def test_a_narration_that_is_no_reply_is_not_delivered(world: World, narration: str) -> None:
    world.narration = narration

    await tasks_mod.run_browser_job({}, PAYLOAD)

    assert world.delivered == []


async def test_one_failed_heartbeat_does_not_end_the_runs_hold_on_its_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A heartbeat that died on one Redis error would let the slot lapse under a live run."""
    beats: list[str] = []
    third_beat = asyncio.Event()

    async def _beat(conversation_id: str, job_id: str) -> bool:
        beats.append(job_id)
        if len(beats) == 1:
            raise ConnectionError("redis blinked")
        if len(beats) == 3:
            third_beat.set()
        return True

    monkeypatch.setattr(tasks_mod, "heartbeat_conversation_slot", _beat)
    monkeypatch.setattr(tasks_mod, "BROWSER_JOB_HEARTBEAT_SECONDS", 0)
    heartbeat = asyncio.create_task(tasks_mod._heartbeat(BrowserJobRequest.model_validate(PAYLOAD)))

    await asyncio.wait_for(third_beat.wait(), timeout=2)
    heartbeat.cancel()
