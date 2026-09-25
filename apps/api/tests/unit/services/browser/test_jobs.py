"""The browser job store: the per-conversation slot, the durable state, the joiner lease, the cancel flag."""

import pytest

from app.constants.browser import (
    BROWSER_JOB_CANCEL_PREFIX,
    BROWSER_JOB_JOINER_LEASE_SECONDS,
    BROWSER_JOB_JOINER_PREFIX,
    BROWSER_JOB_LOCK_PREFIX,
    BROWSER_JOB_LOCK_TTL_SECONDS,
    BROWSER_JOB_STATE_PREFIX,
    BrowserSessionStatus,
)
from app.schemas.browser import BrowserResultSnapshot
from app.schemas.browser_job import BrowserJobState, BrowserJobStatus
from app.services.browser import jobs as jobs_mod
from app.services.browser.job_lifetime import browser_job_ttl_seconds
from tests._harness.redis_fakes import FakeRedisCache


@pytest.fixture
def fake_cache(monkeypatch: pytest.MonkeyPatch) -> FakeRedisCache:
    fake = FakeRedisCache()
    monkeypatch.setattr(jobs_mod, "redis_cache", fake)
    return fake


@pytest.mark.unit
async def test_a_second_claim_names_the_job_already_holding_the_slot(
    fake_cache: FakeRedisCache,
) -> None:
    assert await jobs_mod.claim_conversation_slot("conv-1", "job-1") is None
    assert await jobs_mod.claim_conversation_slot("conv-1", "job-2") == "job-1"
    assert fake_cache.client.store[f"{BROWSER_JOB_LOCK_PREFIX}conv-1"] == "job-1"


@pytest.mark.unit
async def test_the_slot_lease_is_written_with_the_lock_ttl(fake_cache: FakeRedisCache) -> None:
    await jobs_mod.claim_conversation_slot("conv-1", "job-1")
    assert (
        fake_cache.client.ttls[f"{BROWSER_JOB_LOCK_PREFIX}conv-1"] == BROWSER_JOB_LOCK_TTL_SECONDS
    )


@pytest.mark.unit
async def test_get_conversation_slot_reports_the_holder_and_nothing_when_free(
    fake_cache: FakeRedisCache,
) -> None:
    assert await jobs_mod.get_conversation_slot("conv-1") is None
    await jobs_mod.claim_conversation_slot("conv-1", "job-1")
    assert await jobs_mod.get_conversation_slot("conv-1") == "job-1"


@pytest.mark.unit
async def test_releasing_with_the_wrong_job_id_leaves_the_slot_held(
    fake_cache: FakeRedisCache,
) -> None:
    await jobs_mod.claim_conversation_slot("conv-1", "job-1")
    await jobs_mod.release_conversation_slot("conv-1", "job-2")
    assert await jobs_mod.get_conversation_slot("conv-1") == "job-1"
    await jobs_mod.release_conversation_slot("conv-1", "job-1")
    assert await jobs_mod.get_conversation_slot("conv-1") is None


@pytest.mark.unit
async def test_heartbeating_with_the_wrong_job_id_does_not_extend_the_lease(
    fake_cache: FakeRedisCache,
) -> None:
    await jobs_mod.claim_conversation_slot("conv-1", "job-1")
    await jobs_mod.heartbeat_conversation_slot("conv-1", "job-2")
    assert fake_cache.client.expire_calls == []
    await jobs_mod.heartbeat_conversation_slot("conv-1", "job-1")
    assert fake_cache.client.expire_calls == [
        (f"{BROWSER_JOB_LOCK_PREFIX}conv-1", BROWSER_JOB_LOCK_TTL_SECONDS)
    ]


@pytest.mark.unit
async def test_get_job_state_on_an_unknown_job_is_none_not_a_default_state(
    fake_cache: FakeRedisCache,
) -> None:
    assert await jobs_mod.get_job_state("nope") is None


@pytest.mark.unit
async def test_job_state_round_trips_with_its_result(fake_cache: FakeRedisCache) -> None:
    state = BrowserJobState(
        job_id="job-1",
        status=BrowserJobStatus.DONE,
        task="book a table",
        result=BrowserResultSnapshot(
            status=BrowserSessionStatus.COMPLETED, success=True, summary="booked"
        ),
    )
    await jobs_mod.put_job_state(state)
    assert fake_cache.set_calls == [
        (f"{BROWSER_JOB_STATE_PREFIX}job-1", browser_job_ttl_seconds(), BrowserJobState)
    ]
    loaded = await jobs_mod.get_job_state("job-1")
    assert loaded is not None
    assert loaded.result is not None
    assert loaded.result.summary == "booked"


@pytest.mark.unit
@pytest.mark.usefixtures("fake_redis")
async def test_a_stored_job_state_loads_back_as_a_typed_state_through_real_redis() -> None:
    """Redis holds JSON; the worker and the API both read the state back as a model, never a raw dict."""
    await jobs_mod.put_job_state(
        BrowserJobState(job_id="job-1", status=BrowserJobStatus.RUNNING, task="book a table")
    )

    loaded = await jobs_mod.get_job_state("job-1")

    assert isinstance(loaded, BrowserJobState)
    assert loaded.status is BrowserJobStatus.RUNNING
    assert loaded.task == "book a table"


@pytest.mark.unit
async def test_the_joiner_lease_is_held_only_between_take_and_drop(
    fake_cache: FakeRedisCache,
) -> None:
    assert await jobs_mod.joiner_lease_held("job-1") is False
    await jobs_mod.take_joiner_lease("job-1", "stream-1")
    assert await jobs_mod.joiner_lease_held("job-1") is True
    assert (
        fake_cache.client.ttls[f"{BROWSER_JOB_JOINER_PREFIX}job-1"]
        == BROWSER_JOB_JOINER_LEASE_SECONDS
    )
    await jobs_mod.drop_joiner_lease("job-1")
    assert await jobs_mod.joiner_lease_held("job-1") is False


@pytest.mark.unit
async def test_a_foreign_stream_cannot_refresh_another_turns_joiner_lease(
    fake_cache: FakeRedisCache,
) -> None:
    await jobs_mod.take_joiner_lease("job-1", "stream-1")
    fake_cache.client.expire_calls.clear()
    await jobs_mod.refresh_joiner_lease("job-1", "stream-other")
    assert fake_cache.client.expire_calls == []
    await jobs_mod.refresh_joiner_lease("job-1", "stream-1")
    assert fake_cache.client.expire_calls == [
        (f"{BROWSER_JOB_JOINER_PREFIX}job-1", BROWSER_JOB_JOINER_LEASE_SECONDS)
    ]


@pytest.mark.unit
async def test_cancel_is_requested_per_job_and_unset_for_every_other_job(
    fake_cache: FakeRedisCache,
) -> None:
    assert await jobs_mod.job_cancel_requested("job-1") is False
    await jobs_mod.request_job_cancel("job-1")
    assert await jobs_mod.job_cancel_requested("job-1") is True
    assert await jobs_mod.job_cancel_requested("job-2") is False
    assert fake_cache.client.ttls[f"{BROWSER_JOB_CANCEL_PREFIX}job-1"] == browser_job_ttl_seconds()


@pytest.mark.unit
async def test_a_conversations_running_job_is_the_one_a_stop_cancels(
    fake_cache: FakeRedisCache,
) -> None:
    """A stop arrives naming a conversation, never a job id: the slot is the only way back to the run."""
    await jobs_mod.claim_conversation_slot("conv-1", "job-1")

    assert await jobs_mod.cancel_conversation_browser_job("conv-1") == "job-1"
    assert await jobs_mod.job_cancel_requested("job-1") is True


@pytest.mark.unit
async def test_a_stop_with_no_browser_run_cancels_nothing(fake_cache: FakeRedisCache) -> None:
    """Every stop in every conversation reaches here; one without a browser run must be silent, not an error."""
    assert await jobs_mod.cancel_conversation_browser_job("conv-1") is None
    assert fake_cache.client.store == {}
