"""The executor's join on a detached browser job: what it returns, and who tells the user the result.

Real code over fakeredis: the job store, its feed and the join; nothing else is scripted.
"""

import asyncio

import fakeredis.aioredis
from langchain_core.runnables.config import RunnableConfig
import pytest

from app.agents.tools import browser_tool as tool_mod
from app.agents.tools.browser_tool import wait_for_browser_task
from app.constants.browser import BrowserSessionStatus, ResultSpeaker
from app.schemas.browser import AgentGuidanceRequest, BrowserResultSnapshot, PendingAgentGuidance
from app.schemas.browser_job import BrowserJobState, BrowserJobStatus
from app.services.browser.agent_guidance import put_guidance_request
from app.services.browser.job_events import JOB_TERMINAL_FRAME, publish_job_event
from app.services.browser.jobs import (
    claim_conversation_slot,
    claim_result_delivery,
    joiner_lease_held,
    put_job_state,
    set_latest_job,
)

pytestmark = pytest.mark.unit

CONFIG: RunnableConfig = {"configurable": {"user_id": "u1", "thread_id": "c1", "stream_id": "s1"}}
ANSWER = "Booked the table.\n\nTell the user."
RESULT = BrowserResultSnapshot(
    status=BrowserSessionStatus.COMPLETED, success=True, summary="Booked the table."
)


@pytest.fixture(autouse=True)
async def job(fake_redis: fakeredis.aioredis.FakeRedis, monkeypatch: pytest.MonkeyPatch) -> None:
    """Start a running job in conversation c1, from stream s1."""
    # The beat a join re-arms its lease on, shortened so a timeout case is quick.
    monkeypatch.setattr(tool_mod, "BROWSER_JOB_JOINER_REFRESH_SECONDS", 0.05)
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


async def _finish() -> None:
    await put_job_state(_state(BrowserJobStatus.DONE))
    await publish_job_event("job-1", JOB_TERMINAL_FRAME)


async def _join(timeout: int = 5) -> str:
    return await wait_for_browser_task.ainvoke({"timeout": timeout}, config=CONFIG)


async def test_a_run_that_ends_while_joined_is_collected_at_its_end_and_told_by_this_turn() -> None:
    joining = asyncio.create_task(_join(timeout=600))
    for _ in range(50):
        await asyncio.sleep(0)
    assert await joiner_lease_held("job-1") is True

    await _finish()

    assert await asyncio.wait_for(joining, timeout=2) == ANSWER
    assert await claim_result_delivery("job-1", ResultSpeaker.WORKER) is ResultSpeaker.JOINER
    assert await joiner_lease_held("job-1") is False


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

    joined = await _join()

    assert "BROWSER TASK DID NOT COMPLETE" in joined
    assert await joiner_lease_held("job-1") is False


async def test_a_run_that_outlasts_the_wait_is_left_for_the_worker_to_tell() -> None:
    joined = await _join(timeout=0)

    assert joined == tool_mod._STILL_RUNNING
    assert await joiner_lease_held("job-1") is False


async def test_with_no_job_in_the_conversation_nothing_is_joined(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    await fake_redis.flushall()

    assert await _join() == tool_mod._NOTHING_RUNNING
    assert await joiner_lease_held("job-1") is False
