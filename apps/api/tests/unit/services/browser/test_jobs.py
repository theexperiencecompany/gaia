"""The browser job store: owner-checked leases, the one telling of a result, and the wait for it to be free."""

import asyncio

import fakeredis.aioredis
import pytest

from app.constants.browser import BROWSER_JOB_LOCK_TTL_SECONDS, ResultSpeaker
from app.services.browser import jobs as jobs_mod

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def redis(fake_redis: fakeredis.aioredis.FakeRedis) -> fakeredis.aioredis.FakeRedis:
    return fake_redis


async def test_a_second_claim_names_the_job_already_holding_the_slot(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    assert await jobs_mod.claim_conversation_slot("conv-1", "job-1") is None
    assert await jobs_mod.claim_conversation_slot("conv-1", "job-2") == "job-1"
    assert 0 < await redis.ttl("browser:job:lock:conv-1") <= BROWSER_JOB_LOCK_TTL_SECONDS


async def test_only_the_holder_heartbeats_or_releases_the_slot() -> None:
    """A late release from an old run must never free the slot a newer run holds."""
    await jobs_mod.claim_conversation_slot("conv-1", "job-1")

    assert await jobs_mod.heartbeat_conversation_slot("conv-1", "job-2") is False
    await jobs_mod.release_conversation_slot("conv-1", "job-2")
    assert await jobs_mod.get_conversation_slot("conv-1") == "job-1"

    assert await jobs_mod.heartbeat_conversation_slot("conv-1", "job-1") is True
    await jobs_mod.release_conversation_slot("conv-1", "job-1")
    assert await jobs_mod.get_conversation_slot("conv-1") is None


async def test_the_result_is_told_once_by_whoever_claims_it_first() -> None:
    assert (
        await jobs_mod.claim_result_delivery("job-1", ResultSpeaker.JOINER) is ResultSpeaker.JOINER
    )
    assert (
        await jobs_mod.claim_result_delivery("job-1", ResultSpeaker.WORKER) is ResultSpeaker.JOINER
    )


async def test_a_turn_drops_only_its_own_join() -> None:
    """A stale turn dropping another turn's lease would hand the result to the worker while that turn still waits."""
    await jobs_mod.take_joiner_lease("job-1", "stream-a")

    await jobs_mod.drop_joiner_lease("job-1", "stream-b")
    assert await jobs_mod.joiner_lease_held("job-1") is True

    await jobs_mod.drop_joiner_lease("job-1", "stream-a")
    assert await jobs_mod.joiner_lease_held("job-1") is False


async def test_the_worker_waits_while_a_run_or_a_join_may_speak_and_wakes_when_both_let_go() -> (
    None
):
    assert await asyncio.wait_for(jobs_mod.await_result_unclaimed("job-1"), timeout=1) is None

    await jobs_mod.hold_result_for_run("job-1", "stream-a")
    await jobs_mod.take_joiner_lease("job-1", "stream-b")
    waiting = asyncio.create_task(jobs_mod.await_result_unclaimed("job-1"))
    await jobs_mod.release_result_hold("job-1", "stream-a")
    for _ in range(50):
        await asyncio.sleep(0)
    assert not waiting.done(), "the worker spoke over a turn still joined"

    await jobs_mod.drop_joiner_lease("job-1", "stream-b")
    await asyncio.wait_for(waiting, timeout=1)


async def test_a_message_reaches_only_the_running_job_and_is_taken_once() -> None:
    assert await jobs_mod.post_conversation_message("conv-1", "hello") is None
    await jobs_mod.claim_conversation_slot("conv-1", "job-1")

    assert await jobs_mod.post_conversation_message("conv-1", "use the blue one") == "job-1"
    assert await jobs_mod.job_messages_waiting("job-1") is True
    assert await jobs_mod.take_job_messages("job-1") == ["use the blue one"]
    assert await jobs_mod.take_job_messages("job-1") == []
