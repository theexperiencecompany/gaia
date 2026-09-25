"""Tests for the browser session registry — ownership writes, reads, teardown.

The registry is the authorization source for live-view access: a session must
be registered before a user can be granted a takeover token, and the entry's
TTL bounds an orphaned entry. These tests pin the round-trip and the
fail-closed behavior when Redis cannot write.
"""

from typing import Any

import fakeredis
import pytest

from app.services.browser import registry as reg
from app.services.browser.registry import SessionRegistryEntry
from tests.helpers import captured_wide_event


class _FakeRedis:
    def __init__(self, *, fail_writes: bool = False) -> None:
        self.store: dict[str, object] = {}
        self.fail_writes = fail_writes
        self.set_calls: list[dict[str, Any]] = []
        self.get_calls: list[dict[str, Any]] = []
        self.delete_calls: list[str] = []

    async def set(self, key: str, value: object, ttl: int = 3600, model: object = None) -> bool:
        self.set_calls.append({"key": key, "value": value, "ttl": ttl, "model": model})
        if self.fail_writes:
            return False
        self.store[key] = value
        return True

    async def get(self, key: str, model: object = None) -> object:
        self.get_calls.append({"key": key, "model": model})
        return self.store.get(key)

    async def delete(self, key: str) -> None:
        self.delete_calls.append(key)
        self.store.pop(key, None)


class _FakeLog:
    def __init__(self) -> None:
        self.set_calls: list[dict[str, Any]] = []
        self.warning_calls: list[tuple[str, dict[str, Any]]] = []

    def set(self, **kwargs: Any) -> None:
        self.set_calls.append(kwargs)

    def warning(self, message: str, /, **kwargs: Any) -> None:
        self.warning_calls.append((message, kwargs))


@pytest.fixture
def fake_log(monkeypatch: pytest.MonkeyPatch) -> _FakeLog:
    fl = _FakeLog()
    monkeypatch.setattr(reg, "log", fl)
    return fl


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


async def test_register_calls_redis_set_with_exact_key_ttl_and_model(
    fake_redis: _FakeRedis,
) -> None:
    await reg.register_session("s5", "user-5", live_ws="ws://live/5")
    assert len(fake_redis.set_calls) == 1
    call = fake_redis.set_calls[0]
    assert call["key"] == "browser:sess:s5"
    assert call["ttl"] == 7200
    assert call["model"] is SessionRegistryEntry
    entry = call["value"]
    assert isinstance(entry, SessionRegistryEntry)
    assert entry.owner == "user-5"
    assert entry.live_ws == "ws://live/5"


async def test_unregister_does_not_touch_other_sessions(fake_redis: _FakeRedis) -> None:
    await reg.register_session("s12", "user-12")
    await reg.register_session("s13", "user-13")
    await reg.unregister_session("s12")
    assert await reg.session_owner("s12") is None
    assert await reg.session_owner("s13") == "user-13"


async def test_an_entry_read_back_through_redis_is_a_typed_registry_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Real serialization, not the dict fake above: the entry crosses Redis as
    # JSON, and only the read's model turns it back into something with .owner.
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(reg.redis_cache, "redis", client)

    await reg.register_session("s20", "user-20", live_ws="ws://live/20")
    entry = await reg.get_session_entry("s20")

    assert entry == SessionRegistryEntry(owner="user-20", live_ws="ws://live/20")
    assert await reg.session_owner("s20") == "user-20"


async def test_registering_tags_the_wide_event_with_the_session_and_operation(
    fake_redis: _FakeRedis,
) -> None:
    async with captured_wide_event() as event:
        await reg.register_session("s21", "user-21")

    assert event["browser"] == {"session_id": "s21", "operation": "registry_register"}


async def test_unregistering_tags_the_wide_event_with_the_session_and_operation(
    fake_redis: _FakeRedis,
) -> None:
    async with captured_wide_event() as event:
        await reg.unregister_session("s22")

    assert event["browser"] == {"session_id": "s22", "operation": "registry_unregister"}


async def test_a_failed_ownership_write_is_a_warning_naming_the_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reg, "redis_cache", _FakeRedis(fail_writes=True))

    async with captured_wide_event() as event:
        await reg.register_session("s23", "user-23")

    [warning] = event["warnings"]
    assert "registry write failed" in warning["msg"]
    assert warning["session_id"] == "s23"


async def test_a_successful_ownership_write_raises_no_warning(fake_redis: _FakeRedis) -> None:
    async with captured_wide_event() as event:
        await reg.register_session("s24", "user-24")

    assert "warnings" not in event
