"""The executor's join on a detached browser job: what it returns, and who tells the user the result.

Real code over fakeredis: the job store, its feed and the join; nothing else is scripted.
"""

import asyncio

import fakeredis.aioredis
from langchain_core.runnables.config import RunnableConfig
import pytest

from app.agents.tools import browser_tool as tool_mod
from app.agents.tools.browser_tool import wait_for_browser_task
from app.constants.browser import (
    BROWSER_JOB_DELIVERED_PREFIX,
    BrowserSessionStatus,
    ResultSpeaker,
)
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.schemas.browser import AgentGuidanceRequest, BrowserResultSnapshot, PendingAgentGuidance
from app.schemas.browser_job import BrowserJobState, BrowserJobStatus
from app.services.browser import job_events as job_events_mod
from app.services.browser.agent_guidance import put_guidance_request
from app.services.browser.job_events import JOB_TERMINAL_FRAME, publish_job_event
from app.services.browser.jobs import (
    claim_conversation_slot,
    claim_result_delivery,
    joiner_lease_held,
    put_job_state,
    set_latest_job,
)
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.unit

CONFIG: RunnableConfig = {"configurable": {"user_id": "u1", "thread_id": "c1", "stream_id": "s1"}}
ANSWER = "Booked the table.\n\nTell the user."
JOINER_KEY = "browser:job:joiner:job-1"
STEP_CARD: dict[str, object] = {
    "tool_data": {"tool_name": "browser_task_data", "data": {"step": 1}}
}
RESULT = BrowserResultSnapshot(
    status=BrowserSessionStatus.COMPLETED, success=True, summary="Booked the table."
)


@pytest.fixture(autouse=True)
async def job(fake_redis: fakeredis.aioredis.FakeRedis, monkeypatch: pytest.MonkeyPatch) -> None:
    """Start a running job in conversation c1, from stream s1."""
    await set_latest_job("c1", "job-1")
    await claim_conversation_slot("c1", "job-1")
    await put_job_state(_state(BrowserJobStatus.RUNNING))


def _state(status: BrowserJobStatus) -> BrowserJobState:
    done = status is BrowserJobStatus.DONE
    return BrowserJobState(
        job_id="job-1",
        status=status,
        task="book a table",
        relay_stream_id="s1",
        agent_message=ANSWER if done else "",
        result=RESULT if done else None,
    )


async def _forget_who_told() -> None:
    """Forget who told the result, so another join can collect the same finished run."""
    await redis_cache.client.delete(f"{BROWSER_JOB_DELIVERED_PREFIX}job-1")


async def _finish() -> None:
    await put_job_state(_state(BrowserJobStatus.DONE))
    await publish_job_event("job-1", JOB_TERMINAL_FRAME)


async def _join(timeout: int = 5) -> str:
    return await wait_for_browser_task.ainvoke({"timeout": timeout}, config=CONFIG)


async def test_a_run_that_ends_while_joined_is_collected_at_its_end_and_told_by_this_turn(
    fake_redis: fakeredis.aioredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Woken by the run's own frames, never a beat: each re-arms this turn's claim, and the last one ends the wait."""
    monkeypatch.setattr(job_events_mod, "BROWSER_JOB_FEED_WAIT_MS", 60_000)
    re_armed = asyncio.Event()
    refresh = tool_mod.refresh_joiner_lease

    async def _refresh(job_id: str, stream_id: str) -> None:
        await refresh(job_id, stream_id)
        re_armed.set()

    monkeypatch.setattr(tool_mod, "refresh_joiner_lease", _refresh)
    joining = asyncio.create_task(_join(timeout=600))
    for _ in range(50):
        await asyncio.sleep(0)
    assert await fake_redis.get(JOINER_KEY) == "s1"
    await fake_redis.expire(JOINER_KEY, 1)

    await publish_job_event("job-1", STEP_CARD)
    await asyncio.wait_for(re_armed.wait(), timeout=2)
    assert await fake_redis.ttl(JOINER_KEY) > 1
    await _finish()

    assert await asyncio.wait_for(joining, timeout=2) == ANSWER
    assert await claim_result_delivery("job-1", ResultSpeaker.WORKER) is ResultSpeaker.JOINER
    assert await joiner_lease_held("job-1") is False


async def test_a_join_cut_off_mid_wait_lets_go_of_the_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The worker stays silent while the claim is held: a cancelled turn keeping it would lose the result."""
    parked = asyncio.Event()

    # Parked on an event rather than the fake's XREAD: a fakeredis connection cut off
    # mid-command answers the next command with the stale reply, where redis-py disconnects.
    async def _park(job_id: str, cursor: str) -> list[tuple[str, dict[str, object]]]:
        parked.set()
        await asyncio.Event().wait()
        return []

    monkeypatch.setattr(tool_mod, "read_job_events", _park)
    joining = asyncio.create_task(_join(timeout=600))
    await asyncio.wait_for(parked.wait(), timeout=2)
    assert await joiner_lease_held("job-1") is True

    joining.cancel()
    with pytest.raises(asyncio.CancelledError):
        await joining

    assert await joiner_lease_held("job-1") is False


async def test_a_join_from_another_turn_carries_the_runs_cards_onto_its_own_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The message that speaks the result shows the run; the turn that relayed it live already has the cards."""
    published: list[tuple[str, dict[str, object]]] = []

    async def _publish(stream_id: str, card: dict[str, object]) -> None:
        published.append((stream_id, card))

    monkeypatch.setattr(tool_mod, "publish_to_stream", _publish)
    await publish_job_event("job-1", STEP_CARD)
    await _finish()

    assert await _join() == ANSWER
    assert published == []

    await _forget_who_told()
    later_turn: RunnableConfig = {
        "configurable": {"user_id": "u1", "thread_id": "c1", "stream_id": "s2"}
    }
    assert await wait_for_browser_task.ainvoke({"timeout": 5}, config=later_turn) == ANSWER
    assert published == [("s2", STEP_CARD)]

    await _forget_who_told()
    no_stream: RunnableConfig = {"configurable": {"user_id": "u1", "thread_id": "c1"}}
    assert await wait_for_browser_task.ainvoke({"timeout": 5}, config=no_stream) == ANSWER
    assert published == [("s2", STEP_CARD)]


async def test_a_result_the_worker_already_told_is_not_told_again() -> None:
    await _finish()
    await claim_result_delivery("job-1", ResultSpeaker.WORKER)

    joined = await _join()

    assert joined.startswith("The browser task already finished, and the user was told")
    assert ANSWER in joined


async def test_a_run_asking_for_guidance_comes_back_at_once_and_keeps_the_claim() -> None:
    request = AgentGuidanceRequest(reason="The hours are not on this page.", task="book a table")
    await put_guidance_request("job-1", PendingAgentGuidance(handoff_id="h1", request=request))

    joined = await _join()

    assert "The hours are not on this page." in joined
    # This turn answers and comes straight back: the worker must not speak meanwhile.
    assert await joiner_lease_held("job-1") is True


async def test_a_running_job_that_lost_its_worker_is_reported_failed() -> None:
    await claim_conversation_slot("c-other", "job-x")
    await tool_mod.release_conversation_slot("c1", "job-1")

    async with captured_wide_event() as event:
        joined = await _join()

    assert joined == tool_mod._WORKER_LOST
    assert await joiner_lease_held("job-1") is False
    [warning] = event["warnings"]
    assert warning["msg"] == f"{LogTag.BROWSER} Browser job lost its worker"
    assert warning["browser"] == {"job_id": "job-1"}


async def test_a_queued_job_with_no_worker_yet_is_still_waited_for() -> None:
    """The enqueuer never heartbeats the slot, so its lapse says nothing until a worker has picked the job up."""
    await put_job_state(_state(BrowserJobStatus.QUEUED))
    await tool_mod.release_conversation_slot("c1", "job-1")

    assert await _join(timeout=0) == tool_mod._STILL_RUNNING


async def test_a_run_that_outlasts_the_wait_is_left_for_the_worker_to_tell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A clock that stands still: a wait of no time at all is already over.
    monkeypatch.setattr(tool_mod, "monotonic", lambda: 100.0)

    async with captured_wide_event() as event:
        joined = await asyncio.wait_for(_join(timeout=0), timeout=2)

    assert joined == tool_mod._STILL_RUNNING
    assert await joiner_lease_held("job-1") is False
    assert event["browser"] == {"job_id": "job-1", "join": "timed_out_still_running"}


async def test_with_no_job_in_the_conversation_nothing_is_joined(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    await fake_redis.flushall()

    assert await _join() == tool_mod._NOTHING_RUNNING
    assert await joiner_lease_held("job-1") is False
