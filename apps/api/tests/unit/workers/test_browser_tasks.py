"""The ARQ tasks of a browser job: the slot a run holds, the one telling of its ending, and the reaper.

Real code over fakeredis: the task bodies, the job store, the executor inbox, the
feed and ARQ's own keys. The run itself (execute_browser_job) is stood in for by
one that ends the job the way the real run does, and waking an executor run (a
graph run) is recorded rather than started.
"""

import asyncio
import json
from time import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from arq.constants import in_progress_key_prefix
import fakeredis.aioredis
import pytest

from app.agents.core.background.executor_channel import ExecutorInbox
from app.agents.core.background.executor_queue import hold_run_alive
from app.constants.agents import NON_WAKING_TAGS, AgentTag
from app.constants.browser import (
    BROWSER_JOB_DEATH_CONFIRM_SECONDS,
    BROWSER_JOB_LIVE_KEY,
    BROWSER_JOB_QUEUE,
    BROWSER_JOB_SLOT_TAKEN_SUMMARY,
    BROWSER_JOB_SUSPECT_KEY,
    BROWSER_JOB_WAKE_GRACE_SECONDS,
    BROWSER_JOB_WAKE_KEY,
    BROWSER_JOB_WORKER_LOST_SUMMARY,
    BrowserRunFailure,
    BrowserSessionStatus,
)
from app.constants.cache import EXECUTOR_BUSY_PREFIX, EXECUTOR_INBOX_PREFIX
from app.constants.hil import HIL_PAUSED_LOCK_TTL_SECONDS
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
    hold_job_alive,
    job_alive,
    landed_wake,
    landed_wakes,
    live_job_ids,
    put_job_state,
    record_ending,
    release_job_alive,
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
        #: Whether the job's worker lease was held while the run ran.
        self.leased: list[bool] = []


@pytest.fixture
def world(fake_redis: fakeredis.aioredis.FakeRedis, monkeypatch: pytest.MonkeyPatch) -> World:
    w = World()

    async def _execute(request: BrowserJobRequest) -> BrowserResultSnapshot:
        """End the job as the real run does: its result card records the ending, told with it."""
        w.ran.append(request)
        w.heartbeat_alive.append(
            any(task.get_name() == "browser_job_heartbeat" for task in asyncio.all_tasks())
        )
        w.leased.append(await job_alive(request.job_id))
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
    # Held while it ran, the evidence the reaper reads; given back once it ended.
    assert world.leased == [True]
    assert await job_alive("job-1") is False
    assert event["user"] == {"id": "u1"}
    assert event["platform"] == "telegram"
    assert event["browser"] == {
        "job_id": "job-1",
        "conversation_id": "conv-9",
        "source_category": None,
    }


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
    assert warning["msg"] == (
        f"{LogTag.BROWSER} Browser job result landed but nobody can be woken: user not found"
    )
    assert warning["browser"] == {"job_id": "job-1", "conversation_id": "conv-9"}
    # Nobody ever can be: the sweep is not asked to try again.
    assert await landed_wakes() == []


async def test_the_running_job_beats_on_its_own_slot(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    beat = asyncio.Event()
    beats: list[tuple[str, str]] = []
    leased_at_beat: list[bool] = []
    release = asyncio.Event()

    async def _beat(conversation_id: str, job_id: str) -> bool:
        beats.append((conversation_id, job_id))
        leased_at_beat.append(await job_alive(job_id))
        beat.set()
        return True

    async def _execute(request: BrowserJobRequest) -> BrowserResultSnapshot:
        # As if the lease lapsed: only the beat can renew it before the reaper reads it.
        await release_job_alive(request.job_id)
        # The second beat after the lapse renewed the lease wholly after it.
        for _ in range(2):
            beat.clear()
            await beat.wait()
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
    assert leased_at_beat[-1] is True


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


@pytest.mark.usefixtures("fake_redis")
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


async def _running_with_no_worker(
    fake_redis: fakeredis.aioredis.FakeRedis, payload: dict[str, Any] = PAYLOAD
) -> BrowserJobRequest:
    """Queue and start a job whose worker then died: ARQ still marks it in progress for hours."""
    request = await _queued(payload)
    await put_job_state(BrowserJobState.of(request, BrowserJobStatus.RUNNING, time() - 60))
    await fake_redis.set(f"{in_progress_key_prefix}{request.job_id}", "1")
    return request


async def _suspected_long_ago(fake_redis: fakeredis.aioredis.FakeRedis, job_id: str) -> None:
    """Record that an earlier sweep found it without a worker, a full confirm window ago."""
    await fake_redis.hset(
        BROWSER_JOB_SUSPECT_KEY, job_id, str(time() - BROWSER_JOB_DEATH_CONFIRM_SECONDS - 1)
    )


async def test_a_result_landed_during_a_park_is_still_there_to_tell_when_it_ends(
    world: World, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    """An approval can wait hours: neither the answer nor the record that wakes a reader for it may lapse first."""
    await _queued()
    await fake_redis.set(f"{EXECUTOR_BUSY_PREFIX}conv-9", "s1:t1", ex=HIL_PAUSED_LOCK_TTL_SECONDS)
    await hold_run_alive("conv-9", "s1:t1", HIL_PAUSED_LOCK_TTL_SECONDS)

    await end_job("job-1", BrowserJobFinished(result=DONE))
    inbox_ttl = await fake_redis.ttl(f"{EXECUTOR_INBOX_PREFIX}conv-9")
    await fake_redis.expire(BROWSER_JOB_WAKE_KEY, 60)
    await tasks_mod.reap_browser_jobs({})

    assert inbox_ttl > HIL_PAUSED_LOCK_TTL_SECONDS - 5
    assert await landed_wake("job-1") is not None
    assert await fake_redis.ttl(BROWSER_JOB_WAKE_KEY) >= inbox_ttl - 5
    assert world.woken == []


async def test_a_job_whose_worker_died_is_ended_on_its_card_and_told_once(
    world: World, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    """ARQ never retries a browser job: with its worker gone the card spun and the user heard nothing, forever."""
    await _running_with_no_worker(fake_redis)
    await _suspected_long_ago(fake_redis, "job-1")

    async with captured_wide_event() as event:
        assert await tasks_mod.reap_browser_jobs({}) == "reaped=1 results_to_tell=0"

    ending = await done_state("job-1")
    assert isinstance(ending, BrowserJobFinished)
    assert (ending.result.summary, ending.result.success) == (
        BROWSER_JOB_WORKER_LOST_SUMMARY,
        False,
    )
    assert await _inbox_tags() == [AgentTag.BROWSER_RESULT]
    assert world.woken == [("conv-9", world.users["u1"])]
    feed = await _feed()
    assert feed[-1] == JOB_TERMINAL_FRAME
    assert BROWSER_JOB_WORKER_LOST_SUMMARY in json.dumps(feed)
    # The run's "Browser" row closes as its own end would close it, never left spinning.
    [closed] = [frame for frame in feed if "subagent_end" in frame]
    assert '"subagent_id": "browser:call-1"' in json.dumps(closed)
    [warning] = event["warnings"]
    assert warning["msg"] == f"{LogTag.BROWSER} Browser job ended by the reaper: its worker died"
    assert warning["reason"] == BrowserRunFailure.WORKER_LOST.value
    assert warning["browser"] == {"job_id": "job-1", "status": "running"}
    assert event["browser"] == {"reaped_jobs": ["job-1"], "results_to_tell": []}
    assert await live_job_ids() == []


async def test_one_sweep_without_a_worker_is_no_evidence_of_death(
    world: World, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    """ARQ hands a job over before its worker's first write: a sweep in that instant sees no lease."""
    await _running_with_no_worker(fake_redis)

    assert await tasks_mod.reap_browser_jobs({}) == "reaped=0 results_to_tell=0"
    assert await done_state("job-1") is None

    await _suspected_long_ago(fake_redis, "job-1")
    assert await tasks_mod.reap_browser_jobs({}) == "reaped=1 results_to_tell=0"


async def test_a_job_unleased_for_exactly_the_confirm_window_is_dead(
    world: World, fake_redis: fakeredis.aioredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _running_with_no_worker(fake_redis)
    await fake_redis.hset(BROWSER_JOB_SUSPECT_KEY, "job-1", "1000.0")
    monkeypatch.setattr(tasks_mod, "time", lambda: 1000.0 + BROWSER_JOB_DEATH_CONFIRM_SECONDS)

    assert await tasks_mod.reap_browser_jobs({}) == "reaped=1 results_to_tell=0"


@pytest.mark.parametrize("evidence", ["queued", "leased"])
async def test_a_job_waiting_for_a_worker_or_held_by_one_is_left_alone_and_unsuspected(
    world: World, fake_redis: fakeredis.aioredis.FakeRedis, evidence: str
) -> None:
    """A long queue wait and a long handoff are both a live job: reaping either would end a run the user is in."""
    request = await _running_with_no_worker(fake_redis)
    await _suspected_long_ago(fake_redis, "job-1")
    if evidence == "queued":
        await fake_redis.delete(f"{in_progress_key_prefix}job-1")
        await fake_redis.zadd(BROWSER_JOB_QUEUE, {request.job_id: 1})
    else:
        await hold_job_alive("job-1")

    async with captured_wide_event() as event:
        assert await tasks_mod.reap_browser_jobs({}) == "reaped=0 results_to_tell=0"

    assert event["browser"] == {"reaped_jobs": [], "results_to_tell": []}
    assert await done_state("job-1") is None
    assert await fake_redis.hget(BROWSER_JOB_SUSPECT_KEY, "job-1") is None


async def test_a_headless_job_whose_worker_died_unblocks_its_caller_without_an_inbox_entry(
    world: World, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    """Its tool call follows the feed: closing it is what lets a workflow go on."""
    await _running_with_no_worker(fake_redis, PAYLOAD | {"in_background": False})
    await _suspected_long_ago(fake_redis, "job-1")

    assert await tasks_mod.reap_browser_jobs({}) == "reaped=1 results_to_tell=0"

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

    async with captured_wide_event() as event:
        assert await tasks_mod.reap_browser_jobs({}) == "reaped=0 results_to_tell=0"

    assert event["browser"] == {"reaped_jobs": [], "results_to_tell": []}
    assert await live_job_ids() == []
    assert world.woken == []


async def test_every_dead_job_is_reaped_whatever_comes_before_it_in_the_walk(
    world: World, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    """A live or ended job ahead of a dead one in the walk must not end the sweep early."""
    await fake_redis.sadd(BROWSER_JOB_LIVE_KEY, "job-gone")
    waiting = await _queued(PAYLOAD | {"job_id": "job-0", "conversation_id": "conv-0"})
    await fake_redis.zadd(BROWSER_JOB_QUEUE, {waiting.job_id: 1})
    await _running_with_no_worker(fake_redis, PAYLOAD | {"in_background": False})
    await _suspected_long_ago(fake_redis, "job-1")

    async with captured_wide_event() as event:
        await tasks_mod.reap_browser_jobs({})

    assert event["browser"]["reaped_jobs"] == ["job-1"]
    assert await done_state("job-0") is None


async def test_a_result_whose_worker_died_before_waking_anyone_is_woken_until_it_is_read(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The landing outlived the worker that made it: without the sweep it waits for the user's next message."""
    await _queued()
    await end_job("job-1", BrowserJobFinished(result=DONE))
    [wake] = await landed_wakes()
    assert wake.job_id == "job-1"
    # Fresh, it is left to a run that may be reading the inbox right now.
    await tasks_mod.reap_browser_jobs({})
    assert world.woken == []

    later = wake.landed_at + BROWSER_JOB_WAKE_GRACE_SECONDS
    monkeypatch.setattr(tasks_mod, "time", lambda: later)
    await tasks_mod.reap_browser_jobs({})
    await tasks_mod.reap_browser_jobs({})
    assert world.woken == [("conv-9", world.users["u1"])] * 2

    # The woken run read it: nobody is woken for it again, and nothing is left to sweep.
    [entry] = await ExecutorInbox("conv-9").read()
    await ExecutorInbox("conv-9").retire(entry)
    async with captured_wide_event() as event:
        await tasks_mod.reap_browser_jobs({})

    assert world.woken == [("conv-9", world.users["u1"])] * 2
    assert event["browser"] == {"reaped_jobs": [], "results_to_tell": ["job-1"]}
    assert await landed_wakes() == []
    assert await landed_wake("job-1") is None
