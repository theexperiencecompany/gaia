"""The browser job store: the per-conversation slot, the durable state, the joiner lease, the cancel flag."""

from typing import Any

import pytest

from app.constants.browser import (
    BROWSER_JOB_CANCEL_PREFIX,
    BROWSER_JOB_JOINER_LEASE_SECONDS,
    BROWSER_JOB_JOINER_PREFIX,
    BROWSER_JOB_LOCK_PREFIX,
    BROWSER_JOB_LOCK_TTL_SECONDS,
    BROWSER_JOB_STATE_PREFIX,
    BROWSER_JOB_TTL_SECONDS,
    BrowserSessionStatus,
)
from app.schemas.browser import BrowserResultSnapshot
from app.schemas.browser_job import BrowserJobState, BrowserJobStatus
from app.services.browser import jobs as jobs_mod


class _FakeRedisClient:
    """In-memory stand-in for the raw client, with the SET NX and TTL semantics the slot lease relies on."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.expire_calls: list[tuple[str, int]] = []

    async def set(
        self, name: str, value: str, *, ex: int | None = None, nx: bool = False
    ) -> bool | None:
        if nx and name in self.store:
            return None
        self.store[name] = value
        if ex is not None:
            self.ttls[name] = ex
        return True

    async def get(self, name: str) -> str | None:
        return self.store.get(name)

    async def delete(self, *names: str) -> int:
        removed = 0
        for name in names:
            removed += 1 if self.store.pop(name, None) is not None else 0
            self.ttls.pop(name, None)
        return removed

    async def exists(self, *names: str) -> int:
        return sum(1 for name in names if name in self.store)

    async def expire(self, name: str, time: int) -> bool:
        self.expire_calls.append((name, time))
        if name not in self.store:
            return False
        self.ttls[name] = time
        return True


class _FakeRedisCache:
    """redis_cache stand-in: model-level get/set/delete over the same store the raw client sees."""

    def __init__(self) -> None:
        self.client = _FakeRedisClient()
        self.models: dict[str, Any] = {}
        self.set_calls: list[tuple[str, int | None, type[Any] | None]] = []

    async def get(self, key: str, model: type[Any] | None = None) -> Any:
        return self.models.get(key)

    async def set(
        self, key: str, value: object, ttl: int = 3600, model: type[Any] | None = None
    ) -> bool:
        self.set_calls.append((key, ttl, model))
        self.models[key] = value
        return True

    async def delete(self, key: str) -> None:
        self.models.pop(key, None)
        await self.client.delete(key)


@pytest.fixture
def fake_cache(monkeypatch: pytest.MonkeyPatch) -> _FakeRedisCache:
    fake = _FakeRedisCache()
    monkeypatch.setattr(jobs_mod, "redis_cache", fake)
    return fake


@pytest.mark.unit
async def test_a_second_claim_names_the_job_already_holding_the_slot(
    fake_cache: _FakeRedisCache,
) -> None:
    assert await jobs_mod.claim_conversation_slot("conv-1", "job-1") is None
    assert await jobs_mod.claim_conversation_slot("conv-1", "job-2") == "job-1"
    assert fake_cache.client.store[f"{BROWSER_JOB_LOCK_PREFIX}conv-1"] == "job-1"


@pytest.mark.unit
async def test_the_slot_lease_is_written_with_the_lock_ttl(fake_cache: _FakeRedisCache) -> None:
    await jobs_mod.claim_conversation_slot("conv-1", "job-1")
    assert (
        fake_cache.client.ttls[f"{BROWSER_JOB_LOCK_PREFIX}conv-1"] == BROWSER_JOB_LOCK_TTL_SECONDS
    )


@pytest.mark.unit
async def test_get_conversation_slot_reports_the_holder_and_nothing_when_free(
    fake_cache: _FakeRedisCache,
) -> None:
    assert await jobs_mod.get_conversation_slot("conv-1") is None
    await jobs_mod.claim_conversation_slot("conv-1", "job-1")
    assert await jobs_mod.get_conversation_slot("conv-1") == "job-1"


@pytest.mark.unit
async def test_releasing_with_the_wrong_job_id_leaves_the_slot_held(
    fake_cache: _FakeRedisCache,
) -> None:
    await jobs_mod.claim_conversation_slot("conv-1", "job-1")
    await jobs_mod.release_conversation_slot("conv-1", "job-2")
    assert await jobs_mod.get_conversation_slot("conv-1") == "job-1"
    await jobs_mod.release_conversation_slot("conv-1", "job-1")
    assert await jobs_mod.get_conversation_slot("conv-1") is None


@pytest.mark.unit
async def test_heartbeating_with_the_wrong_job_id_does_not_extend_the_lease(
    fake_cache: _FakeRedisCache,
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
    fake_cache: _FakeRedisCache,
) -> None:
    assert await jobs_mod.get_job_state("nope") is None


@pytest.mark.unit
async def test_job_state_round_trips_with_its_result(fake_cache: _FakeRedisCache) -> None:
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
        (f"{BROWSER_JOB_STATE_PREFIX}job-1", BROWSER_JOB_TTL_SECONDS, BrowserJobState)
    ]
    loaded = await jobs_mod.get_job_state("job-1")
    assert loaded is not None
    assert loaded.result is not None
    assert loaded.result.summary == "booked"


@pytest.mark.unit
async def test_the_joiner_lease_is_held_only_between_take_and_drop(
    fake_cache: _FakeRedisCache,
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
    fake_cache: _FakeRedisCache,
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
    fake_cache: _FakeRedisCache,
) -> None:
    assert await jobs_mod.job_cancel_requested("job-1") is False
    await jobs_mod.request_job_cancel("job-1")
    assert await jobs_mod.job_cancel_requested("job-1") is True
    assert await jobs_mod.job_cancel_requested("job-2") is False
    assert fake_cache.client.ttls[f"{BROWSER_JOB_CANCEL_PREFIX}job-1"] == BROWSER_JOB_TTL_SECONDS
