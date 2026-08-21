"""Tests for the browser session registry — ownership writes, reads, teardown.

The registry is the authorization source for live-view access: a session must
be registered before a user can be granted a takeover token, and the entry's
TTL bounds an orphaned entry. These tests pin the round-trip and the
fail-closed behavior when Redis cannot write.
"""

from typing import Any

import pytest

from app.services.browser import registry as reg
from app.services.browser.registry import SessionRegistryEntry


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


async def test_register_success_does_not_log_warning(
    fake_redis: _FakeRedis, fake_log: _FakeLog
) -> None:
    ok = await reg.register_session("s6", "user-6")
    assert ok is True
    assert fake_log.warning_calls == []


async def test_register_failure_logs_warning_with_message_and_session_id(
    monkeypatch: pytest.MonkeyPatch, fake_log: _FakeLog
) -> None:
    failing = _FakeRedis(fail_writes=True)
    monkeypatch.setattr(reg, "redis_cache", failing)
    ok = await reg.register_session("s7", "user-7")
    assert ok is False
    assert len(fake_log.warning_calls) == 1
    message, kwargs = fake_log.warning_calls[0]
    assert message == "[BROWSER] browser session registry write failed"
    assert kwargs == {"session_id": "s7"}


async def test_register_sets_wide_event_context_with_operation_and_session_id(
    fake_redis: _FakeRedis, fake_log: _FakeLog
) -> None:
    await reg.register_session("s8", "user-8")
    assert len(fake_log.set_calls) == 1
    assert fake_log.set_calls[0] == {
        "browser": {"session_id": "s8", "operation": "registry_register"}
    }


async def test_get_session_entry_calls_redis_get_with_exact_key_and_model(
    fake_redis: _FakeRedis,
) -> None:
    await reg.register_session("s9", "user-9")
    fake_redis.get_calls.clear()
    await reg.get_session_entry("s9")
    assert len(fake_redis.get_calls) == 1
    call = fake_redis.get_calls[0]
    assert call["key"] == "browser:sess:s9"
    assert call["model"] is SessionRegistryEntry


async def test_unregister_calls_redis_delete_with_exact_key(fake_redis: _FakeRedis) -> None:
    await reg.register_session("s10", "user-10")
    await reg.unregister_session("s10")
    assert fake_redis.delete_calls == ["browser:sess:s10"]


async def test_unregister_sets_wide_event_context_with_operation_and_session_id(
    fake_redis: _FakeRedis, fake_log: _FakeLog
) -> None:
    await reg.unregister_session("s11")
    assert len(fake_log.set_calls) == 1
    assert fake_log.set_calls[0] == {
        "browser": {"session_id": "s11", "operation": "registry_unregister"}
    }


async def test_unregister_does_not_touch_other_sessions(fake_redis: _FakeRedis) -> None:
    await reg.register_session("s12", "user-12")
    await reg.register_session("s13", "user-13")
    await reg.unregister_session("s12")
    assert await reg.session_owner("s12") is None
    assert await reg.session_owner("s13") == "user-13"
