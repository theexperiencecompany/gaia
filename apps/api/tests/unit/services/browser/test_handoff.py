"""Tests for the Redis handoff bridge — one-time resolution, ownership, timeout."""

import pytest

from app.constants.browser import HandoffDecision, HandoffStatus
from app.services.browser import handoff as handoff_mod


@pytest.fixture
def fake_redis(monkeypatch):
    store: dict[str, dict] = {}

    async def _get(key, model=None):
        return store.get(key)

    async def _set(key, value, ttl=None, model=None):
        store[key] = value
        return True

    monkeypatch.setattr(handoff_mod, "get_cache", _get)
    monkeypatch.setattr(handoff_mod, "set_cache", _set)
    return store


async def test_continue(fake_redis):
    await handoff_mod.create_pending_handoff("h1", "user-1")
    status = await handoff_mod.resolve_handoff("h1", HandoffDecision.CONTINUE, "user-1")
    assert status == HandoffStatus.COMPLETED


async def test_cancel(fake_redis):
    await handoff_mod.create_pending_handoff("h2", "user-1")
    status = await handoff_mod.resolve_handoff("h2", HandoffDecision.CANCEL, "user-1")
    assert status == HandoffStatus.CANCELLED


async def test_resolution_is_one_time(fake_redis):
    await handoff_mod.create_pending_handoff("h3", "user-1")
    first = await handoff_mod.resolve_handoff("h3", HandoffDecision.CONTINUE, "user-1")
    second = await handoff_mod.resolve_handoff("h3", HandoffDecision.CANCEL, "user-1")
    assert first == HandoffStatus.COMPLETED
    assert second == HandoffStatus.COMPLETED


async def test_unknown_returns_none(fake_redis):
    assert await handoff_mod.resolve_handoff("missing", HandoffDecision.CONTINUE, "u") is None


async def test_ownership_enforced(fake_redis):
    await handoff_mod.create_pending_handoff("h4", "owner")
    with pytest.raises(PermissionError):
        await handoff_mod.resolve_handoff("h4", HandoffDecision.CONTINUE, "intruder")


async def test_await_returns_when_resolved(fake_redis):
    await handoff_mod.create_pending_handoff("h5", "user-1")
    await handoff_mod.resolve_handoff("h5", HandoffDecision.CONTINUE, "user-1")
    assert await handoff_mod.await_handoff("h5", timeout_seconds=5) == HandoffStatus.COMPLETED


async def test_await_times_out(fake_redis, monkeypatch):
    monkeypatch.setattr(handoff_mod, "HANDOFF_POLL_INTERVAL_SECONDS", 0.001)
    await handoff_mod.create_pending_handoff("h6", "user-1")
    assert await handoff_mod.await_handoff("h6", timeout_seconds=0) == HandoffStatus.TIMEOUT
