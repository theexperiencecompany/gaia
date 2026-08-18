"""Tests for the Redis handoff bridge — one-time resolution, ownership, timeout."""

import pytest

from app.constants.browser import HandoffDecision, HandoffStatus
from app.services.browser import handoff as handoff_mod
from app.services.browser.exceptions import BrowserHandoffNotOwned, BrowserUnavailableError


class _FakeRedisCache:
    def __init__(self) -> None:
        self.store: dict[str, object] = {}

    async def get(self, key, model=None):
        return self.store.get(key)

    async def set(self, key, value, ttl=None, model=None):
        self.store[key] = value
        return True

    async def delete(self, key):
        self.store.pop(key, None)


@pytest.fixture
def fake_redis(monkeypatch):
    fake = _FakeRedisCache()
    monkeypatch.setattr(handoff_mod, "redis_cache", fake)
    return fake.store


async def test_continue(fake_redis):
    await handoff_mod.create_pending_handoff("h1", "user-1", "conv-h1")
    status = await handoff_mod.resolve_handoff("h1", HandoffDecision.CONTINUE, "user-1")
    assert status == HandoffStatus.COMPLETED


async def test_cancel(fake_redis):
    await handoff_mod.create_pending_handoff("h2", "user-1", "conv-h2")
    status = await handoff_mod.resolve_handoff("h2", HandoffDecision.CANCEL, "user-1")
    assert status == HandoffStatus.CANCELLED


async def test_resolution_is_one_time(fake_redis):
    await handoff_mod.create_pending_handoff("h3", "user-1", "conv-h3")
    first = await handoff_mod.resolve_handoff("h3", HandoffDecision.CONTINUE, "user-1")
    second = await handoff_mod.resolve_handoff("h3", HandoffDecision.CANCEL, "user-1")
    assert first == HandoffStatus.COMPLETED
    assert second == HandoffStatus.COMPLETED


async def test_unknown_returns_none(fake_redis):
    assert await handoff_mod.resolve_handoff("missing", HandoffDecision.CONTINUE, "u") is None


async def test_ownership_enforced(fake_redis):
    await handoff_mod.create_pending_handoff("h4", "owner", "conv-h4")
    with pytest.raises(BrowserHandoffNotOwned):
        await handoff_mod.resolve_handoff("h4", HandoffDecision.CONTINUE, "intruder")


async def test_await_returns_when_resolved(fake_redis):
    await handoff_mod.create_pending_handoff("h5", "user-1", "conv-h5")
    await handoff_mod.resolve_handoff("h5", HandoffDecision.CONTINUE, "user-1")
    outcome = await handoff_mod.await_handoff("h5", timeout_seconds=5)
    assert outcome.status == HandoffStatus.COMPLETED


async def test_await_times_out(fake_redis, monkeypatch):
    monkeypatch.setattr(handoff_mod, "HANDOFF_POLL_INTERVAL_SECONDS", 0.001)
    await handoff_mod.create_pending_handoff("h6", "user-1", "conv-h6")
    outcome = await handoff_mod.await_handoff("h6", timeout_seconds=0)
    assert outcome.status == HandoffStatus.TIMEOUT


class _FailingRedisCache:
    """Redis whose writes never land — the outage case for the handoff bridge."""

    def __init__(self) -> None:
        self.store: dict[str, object] = {}

    async def get(self, key: str, model: object = None) -> object:
        return self.store.get(key)

    async def set(self, key: str, value: object, ttl: int = 3600, model: object = None) -> bool:
        return False  # every write fails

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)


async def test_persistence_failure_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    """A handoff that was never persisted can never be resolved by the awaiting
    run — fail loudly instead of stranding both sides in a silent stall."""
    fake = _FailingRedisCache()
    monkeypatch.setattr(handoff_mod, "redis_cache", fake)
    with pytest.raises(BrowserUnavailableError, match="persist handoff"):
        await handoff_mod.create_pending_handoff("h9", "user-1", "conv-h9")


async def test_resolve_persistence_failure_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settling a handoff whose status write fails must not silently drop the
    user's decision — the endpoint surfaces the storage failure instead."""

    class _FlakyRedis:
        def __init__(self) -> None:
            self.store: dict[str, object] = {}
            self.fail_writes = False

        async def get(self, key: str, model: object = None) -> object:
            return self.store.get(key)

        async def set(self, key: str, value: object, ttl: int = 3600, model: object = None) -> bool:
            if self.fail_writes:
                return False
            self.store[key] = value
            return True

        async def delete(self, key: str) -> None:
            self.store.pop(key, None)

    fake = _FlakyRedis()
    monkeypatch.setattr(handoff_mod, "redis_cache", fake)
    from app.schemas.browser import HandoffRecord

    fake.store["browser:handoff:h10"] = HandoffRecord(
        status=HandoffStatus.PENDING,
        user_id="user-1",
        conversation_id="conv-h10",
    )
    fake.store["browser:conv:conv-h10"] = "h10"
    fake.fail_writes = True
    with pytest.raises(BrowserUnavailableError, match="persist handoff"):
        await handoff_mod.resolve_handoff("h10", HandoffDecision.CONTINUE, "user-1")
