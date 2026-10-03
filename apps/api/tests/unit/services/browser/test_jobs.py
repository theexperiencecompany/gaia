"""The browser job store: owner-checked leases, the one telling of a result, and the wait for it to be free."""

import asyncio

import fakeredis.aioredis
import pytest

from app.constants.browser import (
    BROWSER_JOB_JOINER_LEASE_SECONDS,
    BROWSER_JOB_LOCK_TTL_SECONDS,
    JobEnding,
    ResultSpeaker,
)
from app.schemas.browser_job import BrowserJobState, BrowserJobStatus
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
    assert await jobs_mod.get_conversation_slot("conv-1") == "job-1"
    await jobs_mod.release_conversation_slot("conv-1", "job-1")
    assert await jobs_mod.get_conversation_slot("conv-1") is None


async def test_the_result_is_told_once_by_whoever_claims_it_first() -> None:
    joiner, worker = ResultSpeaker.JOINER, ResultSpeaker.WORKER
    assert await jobs_mod.claim_result_delivery("job-1", joiner) is joiner
    assert await jobs_mod.claim_result_delivery("job-1", worker) is joiner
    # The losing claim changed nothing: the first claimer still holds it.
    assert await jobs_mod.claim_result_delivery("job-1", worker) is joiner
    # Another job's result is its own to tell.
    assert await jobs_mod.claim_result_delivery("job-2", worker) is worker


async def test_a_turn_drops_only_its_own_join(redis: fakeredis.aioredis.FakeRedis) -> None:
    """A stale turn dropping another turn's lease would hand the result to the worker while that turn still waits."""
    await jobs_mod.take_joiner_lease("job-1", "stream-a")
    # A lease, not a flag: a turn whose API died lets it lapse.
    assert await redis.ttl("browser:job:joiner:job-1") > 0

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


async def test_messages_for_a_job_are_taken_once_in_order() -> None:
    await jobs_mod.post_job_message("job-1", "use the blue one")
    await jobs_mod.post_job_message("job-1", "then the big one")
    await jobs_mod.post_job_message("job-1", "no, the small one")
    assert await jobs_mod.job_messages_waiting("job-1") is True
    assert await jobs_mod.take_job_messages("job-1") == [
        "use the blue one",
        "then the big one",
        "no, the small one",
    ]
    assert await jobs_mod.job_messages_waiting("job-1") is False
    assert await jobs_mod.take_job_messages("job-1") == []


async def test_a_lease_another_run_took_between_the_read_and_the_write_is_left_to_it(
    redis: fakeredis.aioredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The check and the write are one transaction: a heartbeat must never re-arm, nor a release free, a newer run's lease."""
    await jobs_mod.claim_conversation_slot("conv-1", "job-1")
    real_pipeline = redis.pipeline

    def _raced(*args: object, **kwargs: object) -> object:
        pipe = real_pipeline(*args, **kwargs)
        read = pipe.get

        async def _read_then_lose_it(key: str) -> object:
            value = await read(key)
            await redis.set(key, "job-2")
            return value

        pipe.get = _read_then_lose_it
        return pipe

    monkeypatch.setattr(redis, "pipeline", _raced)

    assert await jobs_mod.heartbeat_conversation_slot("conv-1", "job-1") is False
    await jobs_mod.release_conversation_slot("conv-1", "job-1")
    assert await redis.get("browser:job:lock:conv-1") == "job-2"


async def test_a_turns_join_is_re_armed_only_by_that_turn(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    await jobs_mod.take_joiner_lease("job-1", "stream-a")
    await redis.expire("browser:job:joiner:job-1", 1)

    await jobs_mod.refresh_joiner_lease("job-1", "stream-b")
    assert await redis.ttl("browser:job:joiner:job-1") == 1

    await jobs_mod.refresh_joiner_lease("job-1", "stream-a")
    assert await redis.ttl("browser:job:joiner:job-1") > 1


async def test_a_claim_whose_process_died_lapses_and_frees_the_result(
    redis: fakeredis.aioredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nobody drops a dead API's lease: the worker waits only until it expires."""
    monkeypatch.setattr(jobs_mod, "BROWSER_JOB_JOINER_LEASE_SECONDS", 1)
    await jobs_mod.take_joiner_lease("job-1", "stream-a")
    await redis.pexpire("browser:job:joiner:job-1", 50)

    await asyncio.wait_for(jobs_mod.await_result_unclaimed("job-1"), timeout=3)


async def test_a_joiners_telling_lapses_with_its_lease_until_its_run_keeps_it(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """A turn whose process died after collecting told nobody: its claim must lapse so the worker tells it."""
    key = "browser:job:delivered:job-1"
    await jobs_mod.claim_result_delivery("job-1", ResultSpeaker.JOINER)
    assert 0 < await redis.ttl(key) <= BROWSER_JOB_JOINER_LEASE_SECONDS

    await redis.expire(key, 1)
    await jobs_mod.keep_result_claim("job-1")
    assert await redis.ttl(key) > 1

    await jobs_mod.settle_result_claim("job-1", told=True)
    assert await redis.ttl(key) > BROWSER_JOB_JOINER_LEASE_SECONDS
    # The worker's telling is final from the start.
    await jobs_mod.claim_result_delivery("job-2", ResultSpeaker.WORKER)
    assert await redis.ttl("browser:job:delivered:job-2") > BROWSER_JOB_JOINER_LEASE_SECONDS


async def test_everything_the_job_store_writes_lapses_with_the_job(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    await jobs_mod.claim_conversation_slot("conv-1", "job-1")
    await jobs_mod.set_latest_job("conv-1", "job-1")
    await jobs_mod.put_job_state(
        BrowserJobState(job_id="job-1", status=BrowserJobStatus.RUNNING, task="t")
    )
    await jobs_mod.take_joiner_lease("job-1", "stream-a")
    await jobs_mod.hold_result_for_run("job-1", "stream-b")
    await jobs_mod.claim_result_delivery("job-1", ResultSpeaker.WORKER)
    await jobs_mod.record_ending("job-1", JobEnding.STOPPED)
    await jobs_mod.set_job_wait("job-1", "h1")
    await jobs_mod.post_job_message("job-1", "hi")
    await jobs_mod.drop_joiner_lease("job-1", "stream-a")

    keys = await redis.keys("browser:job:*")
    # The join's lease is gone, dropped; its release signal stays behind for a waiting worker.
    assert len(keys) == 9
    assert all([await redis.ttl(key) > 0 for key in keys])
    # The job's own record lives as long as the job can, not the cache's default hour.
    assert await redis.ttl("browser:job:job-1") > 3600
    state = await jobs_mod.get_job_state("job-1")
    assert state is not None
    assert state.status is BrowserJobStatus.RUNNING
    assert await jobs_mod.get_job_wait("job-1") == "h1"
    await jobs_mod.clear_job_wait("job-1")
    assert await jobs_mod.get_job_wait("job-1") is None


@pytest.mark.parametrize(
    ("first", "then"),
    [(JobEnding.FINISHED, JobEnding.STOPPED), (JobEnding.STOPPED, JobEnding.FINISHED)],
)
async def test_a_job_ends_once_whoever_records_first(first: JobEnding, then: JobEnding) -> None:
    """A stop and the run's end raced in every round: each read one record and acted on another."""
    assert await jobs_mod.job_ending("job-1") is None

    assert await jobs_mod.record_ending("job-1", first) is first
    assert await jobs_mod.record_ending("job-1", then) is first

    assert await jobs_mod.job_ending("job-1") is first
    assert await jobs_mod.job_cancel_requested("job-1") is (first is JobEnding.STOPPED)


async def test_a_latest_job_pointer_goes_back_only_while_the_job_that_never_ran_holds_it(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    assert await jobs_mod.set_latest_job("discord:u1", "job-new") is None
    await jobs_mod.restore_latest_job("discord:u1", "job-new", "job-old")
    assert await jobs_mod.get_latest_job("discord:u1") == "job-old"
    # Put back for as long as a job lives, like any pointer.
    assert await redis.ttl("browser:job:latest:discord:u1") > 3600

    assert await jobs_mod.set_latest_job("discord:u1", "job-newer") == "job-old"
    await jobs_mod.restore_latest_job("discord:u1", "job-new", "job-old")
    assert await jobs_mod.get_latest_job("discord:u1") == "job-newer"

    await jobs_mod.set_latest_job("c1", "job-new")
    await jobs_mod.restore_latest_job("c1", "job-new", None)
    assert await jobs_mod.get_latest_job("c1") is None
