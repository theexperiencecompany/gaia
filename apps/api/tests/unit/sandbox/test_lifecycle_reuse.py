"""Layer 3 — _reuse_cached_entry: conditional set_timeout (#7) + health/canary evict.

Patches the surrounding probes so each test isolates one branch. Asserts on the
real set_timeout call count and real pool state.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch
import uuid

import pytest

from app.constants.sandbox import SANDBOX_TIMEOUT_REFRESH_SECONDS
from app.services.sandbox import lifecycle
from app.services.sandbox.pool import PooledSandbox, get_sandbox_pool

pytestmark = pytest.mark.unit


def _healthy_entry() -> PooledSandbox:
    sbx = AsyncMock()
    sbx.set_timeout = AsyncMock()
    return PooledSandbox(sandbox=sbx, last_canary_ts="x")


def _seed(entry: PooledSandbox) -> str:
    user_id = f"u-{uuid.uuid4().hex}"
    get_sandbox_pool().put(user_id, entry)
    return user_id


def _patch_probes_healthy():
    return (
        patch.object(lifecycle, "_health_probe", AsyncMock(return_value=True)),
        patch.object(lifecycle, "_ensure_mounted", AsyncMock()),
        patch.object(lifecycle, "_verify_canary_or_die", AsyncMock(return_value=True)),
        patch.object(lifecycle, "_ensure_watcher", AsyncMock()),
    )


async def _reuse(entry: PooledSandbox):
    user_id = _seed(entry)
    try:
        return user_id, await lifecycle._reuse_cached_entry(user_id, {})
    finally:
        get_sandbox_pool().evict(user_id)


async def test_set_timeout_refreshed_when_window_elapsed() -> None:
    entry = _healthy_entry()
    entry.timeout_refreshed_at = time.monotonic() - (SANDBOX_TIMEOUT_REFRESH_SECONDS + 5)
    p1, p2, p3, p4 = _patch_probes_healthy()
    with p1, p2, p3, p4:
        _, result = await _reuse(entry)
    assert result is entry
    entry.sandbox.set_timeout.assert_awaited_once()
    assert entry.timeout_refreshed_at > time.monotonic() - 5, "refresh clock must advance"


async def test_set_timeout_skipped_when_recently_refreshed() -> None:
    entry = _healthy_entry()
    entry.timeout_refreshed_at = time.monotonic()  # just refreshed
    p1, p2, p3, p4 = _patch_probes_healthy()
    with p1, p2, p3, p4:
        _, result = await _reuse(entry)
    assert result is entry
    entry.sandbox.set_timeout.assert_not_awaited()  # no wasted round-trip in a rapid turn


async def test_unhealthy_cached_handle_is_evicted() -> None:
    entry = _healthy_entry()
    with (
        patch.object(lifecycle, "_health_probe", AsyncMock(return_value=False)),
        patch.object(lifecycle, "_stop_watcher", AsyncMock()),
    ):
        user_id = _seed(entry)
        result = await lifecycle._reuse_cached_entry(user_id, {})
        assert result is None, "an unhealthy cached handle must not be reused"
        assert get_sandbox_pool().get(user_id) is None, "it must be evicted"
        entry.sandbox.set_timeout.assert_not_awaited()


async def test_stale_canary_is_evicted() -> None:
    entry = _healthy_entry()
    with (
        patch.object(lifecycle, "_health_probe", AsyncMock(return_value=True)),
        patch.object(lifecycle, "_ensure_mounted", AsyncMock()),
        patch.object(lifecycle, "_verify_canary_or_die", AsyncMock(return_value=False)),
        patch.object(lifecycle, "_stop_watcher", AsyncMock()),
    ):
        user_id = _seed(entry)
        result = await lifecycle._reuse_cached_entry(user_id, {})
        assert result is None, "a stale-canary (stale FS) sandbox must be recreated"
        assert get_sandbox_pool().get(user_id) is None


async def test_returns_none_when_no_cached_entry() -> None:
    missing = f"u-{uuid.uuid4().hex}"
    get_sandbox_pool().evict(missing)
    assert await lifecycle._reuse_cached_entry(missing, {}) is None
