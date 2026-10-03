"""The browser job store: owner-checked leases, and the one ending of record, told with it or not at all."""

from uuid import uuid4

import fakeredis.aioredis
import pytest

from app.agents.core.background.executor_channel import ExecutorInbox
from app.constants.agents import AgentTag
from app.constants.browser import BROWSER_JOB_LOCK_TTL_SECONDS, BrowserSessionStatus
from app.models.agent_models import InboxEntry
from app.schemas.browser import BrowserResultSnapshot
from app.schemas.browser_job import (
    BrowserJobEnding,
    BrowserJobFinished,
    BrowserJobState,
    BrowserJobStatus,
    BrowserJobStopped,
)
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


_FINISHED = BrowserJobFinished(
    result=BrowserResultSnapshot(status=BrowserSessionStatus.COMPLETED, success=True, summary="ok")
)


def _state(job_id: str = "job-1") -> BrowserJobState:
    return BrowserJobState(
        job_id=job_id,
        status=BrowserJobStatus.RUNNING,
        task="t",
        conversation_id="conv-1",
        user_id="u1",
        in_background=True,
    )


async def test_everything_the_job_store_writes_lapses_with_the_job(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    await jobs_mod.claim_conversation_slot("conv-1", "job-1")
    await jobs_mod.set_latest_job("conv-1", "job-1")
    await jobs_mod.put_job_state(_state())
    await jobs_mod.record_ending("job-1", BrowserJobStopped())
    await jobs_mod.set_job_wait("job-1", "h1")
    await jobs_mod.post_job_message("job-1", "hi")

    keys = await redis.keys("browser:job:*")
    assert len(keys) == 6
    assert all([await redis.ttl(key) > 0 for key in keys])
    # The job's own record lives as long as the job can, not the cache's default hour.
    assert await redis.ttl("browser:job:job-1") > 3600
    assert await redis.ttl("browser:job:ending:job-1") > 3600
    state = await jobs_mod.get_job_state("job-1")
    assert state is not None
    assert state.status is BrowserJobStatus.RUNNING
    assert await jobs_mod.get_job_wait("job-1") == "h1"
    await jobs_mod.clear_job_wait("job-1")
    assert await jobs_mod.get_job_wait("job-1") is None


@pytest.mark.parametrize(
    ("first", "then"),
    [(_FINISHED, BrowserJobStopped()), (BrowserJobStopped(), _FINISHED)],
)
async def test_a_job_ends_once_whoever_records_first(
    first: BrowserJobEnding, then: BrowserJobEnding
) -> None:
    """A stop and the run's end raced in every round: each read one record and acted on another."""
    assert await jobs_mod.done_state("job-1") is None

    assert await jobs_mod.record_ending("job-1", first) is first
    assert await jobs_mod.record_ending("job-1", then) == first

    assert await jobs_mod.done_state("job-1") == first
    assert await jobs_mod.job_cancel_requested("job-1") is isinstance(first, BrowserJobStopped)


def _landing(text: str) -> jobs_mod.InboxLanding:
    entry = InboxEntry(id=str(uuid4()), text=text, tag=AgentTag.BROWSER_RESULT)
    return jobs_mod.InboxLanding(ExecutorInbox("conv-1"), entry)


async def test_an_ending_lands_in_the_inbox_once_and_only_with_the_record_that_won() -> None:
    """Two writers each told the ending in turn: the executor reported one browser run twice."""
    await jobs_mod.record_ending("job-1", _FINISHED, _landing("first"))
    await jobs_mod.record_ending("job-1", BrowserJobStopped(), _landing("second"))

    assert [entry.text for entry in await ExecutorInbox("conv-1").read()] == ["first"]


async def test_an_ending_is_recorded_and_landed_in_one_transaction(
    redis: fakeredis.aioredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A landing that failed after the record left an ending nobody would ever tell."""
    real_pipeline = redis.pipeline

    def _failing_landing(*args: object, **kwargs: object) -> object:
        pipe = real_pipeline(*args, **kwargs)

        def _refuse(*_args: object, **_kwargs: object) -> object:
            raise ConnectionError("redis went away")

        pipe.rpush = _refuse
        return pipe

    monkeypatch.setattr(redis, "pipeline", _failing_landing)

    with pytest.raises(ConnectionError):
        await jobs_mod.record_ending("job-1", _FINISHED, _landing("told"))

    assert await jobs_mod.done_state("job-1") is None


async def test_an_ending_recorded_between_the_read_and_the_write_wins(
    redis: fakeredis.aioredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The read and the write are one transaction: a stop landing between them is not overwritten."""
    real_pipeline = redis.pipeline
    raced = {"done": False}

    def _raced(*args: object, **kwargs: object) -> object:
        pipe = real_pipeline(*args, **kwargs)
        read = pipe.get

        async def _read_then_stop(key: str) -> object:
            value = await read(key)
            if not raced["done"]:
                raced["done"] = True
                await redis.set(key, BrowserJobStopped().model_dump_json())
            return value

        pipe.get = _read_then_stop
        return pipe

    monkeypatch.setattr(redis, "pipeline", _raced)

    recorded = await jobs_mod.record_ending("job-1", _FINISHED, _landing("told"))

    assert recorded == BrowserJobStopped()
    assert await ExecutorInbox("conv-1").read() == []


async def test_a_job_leaves_the_reapers_view_when_it_ends() -> None:
    await jobs_mod.put_job_state(_state())
    assert await jobs_mod.live_job_ids() == ["job-1"]

    await jobs_mod.record_ending("job-1", BrowserJobStopped())

    assert await jobs_mod.live_job_ids() == []


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
