"""The ARQ tasks of a browser job: the slot a run holds, the one telling of its ending, and the reaper.

Real code over fakeredis: the task bodies, the job store, the executor inbox, the
feed and ARQ's own keys. The run itself (execute_browser_job) is stood in for by
one that ends the job the way the real run does, and waking an executor run (a
graph run) is recorded rather than started.
"""

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from arq.constants import in_progress_key_prefix
import fakeredis.aioredis
import pytest

from app.agents.core.background.executor_channel import ExecutorInbox
from app.constants.agents import NON_WAKING_TAGS, AgentTag
from app.constants.browser import (
    BROWSER_JOB_LIVE_KEY,
    BROWSER_JOB_QUEUE,
    BROWSER_JOB_SLOT_TAKEN_SUMMARY,
    BROWSER_JOB_WORKER_LOST_SUMMARY,
    BrowserRunFailure,
    BrowserSessionStatus,
)
from app.constants.log_tags import LogTag
from app.schemas.browser import BrowserResultSnapshot
from app.schemas.browser_job import (
    BrowserJobFinished,
    BrowserJobRequest,
    BrowserJobState,
    BrowserJobStatus,
    BrowserJobStopped,
)
from app.services.browser.job_events import JOB_TERMINAL_FRAME, read_job_events
from app.services.browser.job_teller import end_job
from app.services.browser.jobs import (
    claim_conversation_slot,
    done_state,
    get_conversation_slot,
    live_job_ids,
    put_job_state,
    record_ending,
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
    "in_background": True,
    "stream_id": "s1",
}
DONE = BrowserResultSnapshot(
    status=BrowserSessionStatus.COMPLETED, success=True, summary="Booked the table."
)


class World:
    def __init__(self) -> None:
        self.ran: list[BrowserJobRequest] = []
        #: Each executor run woken to tell a landed ending: (conversation, user).
        self.woken: list[tuple[str, object]] = []
        self.users: dict[str, object] = {"u1": MagicMock(user_id="u1")}
        #: Whether the heartbeat that holds the slot was alive while the run ran.
        self.heartbeat_alive: list[bool] = []


@pytest.fixture
def world(fake_redis: fakeredis.aioredis.FakeRedis, monkeypatch: pytest.MonkeyPatch) -> World:
    w = World()

    async def _execute(request: BrowserJobRequest) -> BrowserResultSnapshot:
        """End the job as the real run does: its result card records the ending, told with it."""
        w.ran.append(request)
        w.heartbeat_alive.append(
            any(task.get_name() == "browser_job_heartbeat" for task in asyncio.all_tasks())
        )
        await end_job(request.job_id, BrowserJobFinished(result=DONE))
        return DONE

    async def _wake(conversation_id: str, user: object) -> None:
        w.woken.append((conversation_id, user))

    async def _user(user_id: str) -> object | None:
        return w.users.get(user_id)

    monkeypatch.setattr(tasks_mod, "execute_browser_job", _execute)
    monkeypatch.setattr(tasks_mod, "wake_executor_for_inbox", _wake)
    monkeypatch.setattr(tasks_mod, "load_user_context", _user)
    monkeypatch.setattr(tasks_mod.RedisPoolManager, "get_pool", AsyncMock(return_value=fake_redis))
    return w


async def _queued(payload: dict[str, Any] = PAYLOAD) -> BrowserJobRequest:
    """Queue the job as browser_task does: its state first, so a stop or the reaper can find it."""
    request = BrowserJobRequest.model_validate(payload)
    await put_job_state(BrowserJobState.of(request, BrowserJobStatus.QUEUED))
    return request


async def _inbox_tags() -> list[AgentTag]:
    return [entry.tag for entry in await ExecutorInbox("conv-9").read()]


async def test_a_finished_background_run_is_told_once_by_the_executor_run_it_wakes(
    world: World,
) -> None:
    """The worker narrated the result and the executor reported it too: one run, two answers."""
    await _queued()

    async with captured_wide_event() as event:
        status = await asyncio.wait_for(
            tasks_mod.run_browser_job({}, PAYLOAD | {"conversation_source": "telegram"}), timeout=2
        )

    assert status == BrowserSessionStatus.COMPLETED.value
    [entry] = await ExecutorInbox("conv-9").read()
    assert entry.tag is AgentTag.BROWSER_RESULT
    assert entry.text.startswith("The browser task you started (job job-1) has ended.")
    assert "Booked the table." in entry.text
    assert world.woken == [("conv-9", world.users["u1"])]
    assert await get_conversation_slot("conv-9") is None
    assert world.heartbeat_alive == [True]
    assert event["user"] == {"id": "u1"}
    assert event["platform"] == "telegram"


async def test_a_stopped_run_wakes_nobody_and_leaves_only_the_stops_notice(world: World) -> None:
    """The stop already answered the user; a woken run would answer them a second time."""
    await _queued()
    await end_job("job-1", BrowserJobStopped())

    await tasks_mod.run_browser_job({}, PAYLOAD)

    assert world.woken == []
    assert await _inbox_tags() == [AgentTag.BROWSER_STOPPED]
    assert AgentTag.BROWSER_STOPPED in NON_WAKING_TAGS


async def test_a_headless_run_lands_nothing_and_wakes_nobody(world: World) -> None:
    """Its tool call blocks for the ending and returns it: that is its one telling."""
    await _queued(PAYLOAD | {"in_background": False})

    await tasks_mod.run_browser_job({}, PAYLOAD | {"in_background": False})

    assert isinstance(await done_state("job-1"), BrowserJobFinished)
    assert await _inbox_tags() == []
    assert world.woken == []


async def test_a_job_whose_user_is_gone_lands_its_result_but_wakes_nobody(world: World) -> None:
    world.users.clear()
    await _queued()

    async with captured_wide_event() as event:
        await tasks_mod.run_browser_job({}, PAYLOAD)

    assert await _inbox_tags() == [AgentTag.BROWSER_RESULT]
    assert world.woken == []
    [warning] = event["warnings"]
    assert "user not found" in warning["msg"]


async def test_the_running_job_beats_on_its_own_slot(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    beat = asyncio.Event()
    beats: list[tuple[str, str]] = []
    release = asyncio.Event()

    async def _beat(conversation_id: str, job_id: str) -> bool:
        beats.append((conversation_id, job_id))
        beat.set()
        return True

    async def _execute(request: BrowserJobRequest) -> BrowserResultSnapshot:
        await release.wait()
        return DONE

    monkeypatch.setattr(tasks_mod, "heartbeat_conversation_slot", _beat)
    monkeypatch.setattr(tasks_mod, "BROWSER_JOB_HEARTBEAT_SECONDS", 0)
    monkeypatch.setattr(tasks_mod, "execute_browser_job", _execute)
    running = asyncio.create_task(tasks_mod.run_browser_job({}, PAYLOAD))

    await asyncio.wait_for(beat.wait(), timeout=2)
    release.set()
    await asyncio.wait_for(running, timeout=2)

    assert set(beats) == {("conv-9", "job-1")}


async def test_a_job_whose_conversation_another_run_took_never_runs_and_says_so(
    world: World,
) -> None:
    """One browser per conversation: a job that queued past its lease while another started ends on its own card."""
    await _queued()
    await claim_conversation_slot("conv-9", "job-other")

    async with captured_wide_event() as event:
        status = await tasks_mod.run_browser_job({}, PAYLOAD)

    [warning] = event["warnings"]
    assert "slot was taken" in warning["msg"]
    assert warning["browser"] == {"job_id": "job-1", "slot_holder": "job-other"}
    assert status == BrowserSessionStatus.FAILED.value
    assert world.ran == []
    ending = await done_state("job-1")
    assert isinstance(ending, BrowserJobFinished)
    assert ending.result.summary == BROWSER_JOB_SLOT_TAKEN_SUMMARY
    assert await _inbox_tags() == [AgentTag.BROWSER_RESULT]
    assert world.woken == [("conv-9", world.users["u1"])]
    assert await get_conversation_slot("conv-9") == "job-other"


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


async def _feed(job_id: str = "job-1") -> list[dict[str, object]]:
    return [payload for _, payload in await read_job_events(job_id, "0-0")]


async def test_a_job_whose_worker_died_is_ended_and_told_once(
    world: World, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    """ARQ never retries a browser job: with its worker gone the card spun and the user heard nothing, forever."""
    request = await _queued()
    await put_job_state(BrowserJobState.of(request, BrowserJobStatus.RUNNING))
    # ARQ still marks it in progress for hours; its heartbeat stopped with the worker.
    await fake_redis.set(f"{in_progress_key_prefix}job-1", "1")

    async with captured_wide_event() as event:
        assert await tasks_mod.reap_browser_jobs({}) == "reaped=1"
        assert await tasks_mod.reap_browser_jobs({}) == "reaped=0"

    ending = await done_state("job-1")
    assert isinstance(ending, BrowserJobFinished)
    assert ending.result.summary == BROWSER_JOB_WORKER_LOST_SUMMARY
    assert await _inbox_tags() == [AgentTag.BROWSER_RESULT]
    assert world.woken == [("conv-9", world.users["u1"])]
    feed = await _feed()
    assert feed[-1] == JOB_TERMINAL_FRAME
    assert BROWSER_JOB_WORKER_LOST_SUMMARY in json.dumps(feed[-2])
    [warning] = event["warnings"]
    assert warning["reason"] == BrowserRunFailure.WORKER_LOST.value
    assert await live_job_ids() == []


async def test_a_job_still_waiting_for_a_worker_or_still_beating_is_left_alone(
    world: World, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    """A long queue wait and a long handoff are both a live job: reaping either would end a run the user is in."""
    await _queued()
    await fake_redis.zadd(BROWSER_JOB_QUEUE, {"job-1": 1})
    beating = await _queued(PAYLOAD | {"job_id": "job-2", "conversation_id": "conv-8"})
    await put_job_state(BrowserJobState.of(beating, BrowserJobStatus.RUNNING))
    await fake_redis.set(f"{in_progress_key_prefix}job-2", "1")
    await claim_conversation_slot("conv-8", "job-2")

    assert await tasks_mod.reap_browser_jobs({}) == "reaped=0"

    assert await done_state("job-1") is None
    assert await done_state("job-2") is None
    assert sorted(await live_job_ids()) == ["job-1", "job-2"]


async def test_a_headless_job_whose_worker_died_unblocks_its_caller_without_an_inbox_entry(
    world: World,
) -> None:
    """Its tool call follows the feed: closing it is what lets a workflow go on."""
    await _queued(PAYLOAD | {"in_background": False})

    assert await tasks_mod.reap_browser_jobs({}) == "reaped=1"

    assert isinstance(await done_state("job-1"), BrowserJobFinished)
    assert (await _feed())[-1] == JOB_TERMINAL_FRAME
    assert await _inbox_tags() == []
    assert world.woken == []


async def test_a_job_that_ended_or_expired_is_forgotten_by_the_reaper(
    world: World, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    request = await _queued()
    await record_ending("job-1", BrowserJobStopped())
    # A RUNNING write landing after the ending puts the ended job back in view.
    await put_job_state(BrowserJobState.of(request, BrowserJobStatus.RUNNING))
    # A job whose state expired leaves its id behind with nothing to read.
    await fake_redis.sadd(BROWSER_JOB_LIVE_KEY, "job-gone")

    assert await tasks_mod.reap_browser_jobs({}) == "reaped=0"

    assert await live_job_ids() == []
    assert world.woken == []
