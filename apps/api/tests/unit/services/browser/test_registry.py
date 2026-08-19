"""Tests for the browser session registry — ownership writes, reads, teardown.

The registry is the authorization source for live-view access: a session must
be registered before a user can be granted a takeover token, and the entry's
TTL bounds an orphaned entry. These tests pin the round-trip and the
fail-closed behavior when Redis cannot write.
"""

import pytest

from app.services.browser import registry as reg
from app.services.browser.registry import SessionRegistryEntry


class _FakeRedis:
    def __init__(self, *, fail_writes: bool = False) -> None:
        self.store: dict[str, object] = {}
        self.fail_writes = fail_writes

    async def set(self, key: str, value: object, ttl: int = 3600, model: object = None) -> bool:
        if self.fail_writes:
            return False
        self.store[key] = value
        return True

    async def get(self, key: str, model: object = None) -> object:
        return self.store.get(key)

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    r = _FakeRedis()
    monkeypatch.setattr(reg, "redis_cache", r)
    return r


async def test_register_round_trips_owner_and_live_ws(fake_redis: _FakeRedis) -> None:
    ok = await reg.register_session("s1", "user-1", live_ws="ws://live/1")
    assert ok is True
    entry = await reg.get_session_entry("s1")
    assert isinstance(entry, SessionRegistryEntry)
    assert entry.owner == "user-1"
    assert entry.live_ws == "ws://live/1"
    assert await reg.session_owner("s1") == "user-1"


async def test_register_without_live_ws(fake_redis: _FakeRedis) -> None:
    await reg.register_session("s2", "user-2")
    entry = await reg.get_session_entry("s2")
    assert entry is not None
    assert entry.live_ws is None


async def test_unknown_session_returns_none(fake_redis: _FakeRedis) -> None:
    assert await reg.get_session_entry("ghost") is None
    assert await reg.session_owner("ghost") is None


async def test_unregister_removes_entry(fake_redis: _FakeRedis) -> None:
    await reg.register_session("s3", "user-3")
    assert await reg.session_owner("s3") == "user-3"
    await reg.unregister_session("s3")
    assert await reg.session_owner("s3") is None


async def test_register_write_failure_returns_false(
    fake_redis: _FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    failing = _FakeRedis(fail_writes=True)
    monkeypatch.setattr(reg, "redis_cache", failing)
    ok = await reg.register_session("s4", "user-4")
    assert ok is False
