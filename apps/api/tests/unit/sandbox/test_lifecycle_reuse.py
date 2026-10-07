"""Layer 3 — _reuse_cached_entry: conditional set_timeout (#7) + health/canary evict.

Patches the surrounding probes so each test isolates one branch. Asserts on the
real set_timeout call count and real pool state.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch
import uuid

from e2b import NotFoundException, SandboxState
import pytest

from app.constants.sandbox import SANDBOX_LAB_LIFETIME_SECONDS, SANDBOX_LIFETIME_SECONDS
from app.services.sandbox import lifecycle, pool as pool_module
from app.services.sandbox.pool import PooledSandbox, get_sandbox_pool


def _healthy_entry() -> PooledSandbox:
    sbx = AsyncMock()
    sbx.set_timeout = AsyncMock()
    return PooledSandbox(sandbox=sbx, last_canary_ts="x")


def _seed(entry: PooledSandbox) -> str:
    user_id = f"u-{uuid.uuid4().hex}"
    get_sandbox_pool().put(user_id, entry)
    return user_id


def _patch_probes_healthy() -> tuple[Any, Any, Any, Any]:
    return (
        patch.object(lifecycle, "_health_probe", AsyncMock(return_value=True)),
        patch.object(lifecycle, "_ensure_mounted", AsyncMock()),
        patch.object(lifecycle, "_verify_canary_or_die", AsyncMock(return_value=True)),
        patch.object(lifecycle, "_ensure_watcher", AsyncMock()),
    )


async def _reuse(entry: PooledSandbox) -> tuple[str, PooledSandbox | None]:
    user_id = _seed(entry)
    try:
        return user_id, await lifecycle._reuse_cached_entry(user_id, {}, "gaia-coder")
    finally:
        get_sandbox_pool().evict(user_id)


async def test_set_timeout_refreshed_when_window_elapsed() -> None:
    entry = _healthy_entry()
    entry.timeout_refreshed_at = time.monotonic() - (SANDBOX_LIFETIME_SECONDS // 2 + 5)
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
    repo = AsyncMock()
    with (
        patch.object(lifecycle, "_health_probe", AsyncMock(return_value=False)),
        patch.object(
            lifecycle.AsyncSandbox, "get_info", AsyncMock(side_effect=NotFoundException("gone"))
        ),
        patch.object(lifecycle, "_stop_watcher", AsyncMock()),
        patch.object(lifecycle, "e2b_sandbox_repository", repo),
    ):
        user_id = _seed(entry)
        result = await lifecycle._reuse_cached_entry(user_id, {}, "gaia-coder")
        assert result is None, "an unhealthy cached handle must not be reused"
        assert get_sandbox_pool().get(user_id) is None, "it must be evicted"
        entry.sandbox.set_timeout.assert_not_awaited()
        # Evicting in-memory is not enough — Mongo must also record the
        # sandbox as dead, or a stale doc lets _acquire_or_create resume a
        # sandbox_id that no longer exists (the 404-on-resume bug).
        repo.mark_dead.assert_awaited_once()


async def test_stale_canary_is_evicted() -> None:
    entry = _healthy_entry()
    repo = AsyncMock()
    with (
        patch.object(lifecycle, "_health_probe", AsyncMock(return_value=True)),
        patch.object(lifecycle, "_ensure_mounted", AsyncMock()),
        patch.object(lifecycle, "_verify_canary_or_die", AsyncMock(return_value=False)),
        patch.object(lifecycle, "_stop_watcher", AsyncMock()),
        patch.object(lifecycle, "e2b_sandbox_repository", repo),
    ):
        user_id = _seed(entry)
        result = await lifecycle._reuse_cached_entry(user_id, {}, "gaia-coder")
        assert result is None, "a stale-canary (stale FS) sandbox must be recreated"
        assert get_sandbox_pool().get(user_id) is None
        repo.mark_dead.assert_awaited_once()


async def test_returns_none_when_no_cached_entry() -> None:
    missing = f"u-{uuid.uuid4().hex}"
    get_sandbox_pool().evict(missing)
    assert await lifecycle._reuse_cached_entry(missing, {}, "gaia-coder") is None


def _control_plane(state: SandboxState) -> object:
    """Patch E2B's control plane to report the sandbox in the given state."""
    return patch.object(
        lifecycle.AsyncSandbox, "get_info", AsyncMock(return_value=SimpleNamespace(state=state))
    )


@pytest.mark.regression
async def test_a_live_sandbox_that_misses_one_health_probe_is_kept() -> None:
    # A live sandbox misses the 4s /health probe about 1 in 60 times (measured
    # on E2B); killing on that miss recreated the sandbox, and the coding agent
    # running in it, every few minutes.
    entry = _healthy_entry()
    repo = AsyncMock()
    with (
        patch.object(lifecycle, "_health_probe", AsyncMock(side_effect=[False, True])),
        _control_plane(SandboxState.RUNNING),
        patch.object(lifecycle, "_ensure_mounted", AsyncMock()),
        patch.object(lifecycle, "_verify_canary_or_die", AsyncMock(return_value=True)),
        patch.object(lifecycle, "_ensure_watcher", AsyncMock()),
        patch.object(lifecycle, "e2b_sandbox_repository", repo),
    ):
        _, result = await _reuse(entry)
    assert result is entry
    entry.sandbox.kill.assert_not_awaited()
    repo.mark_dead.assert_not_awaited()


async def test_a_running_sandbox_whose_health_endpoint_stays_silent_is_evicted() -> None:
    # E2B can report a sandbox running while its envd is wedged; every command
    # would then hang to its deadline, so a second, longer miss means dead.
    entry = _healthy_entry()
    repo = AsyncMock()
    with (
        patch.object(lifecycle, "_health_probe", AsyncMock(return_value=False)),
        _control_plane(SandboxState.RUNNING),
        patch.object(lifecycle, "_stop_watcher", AsyncMock()),
        patch.object(lifecycle, "e2b_sandbox_repository", repo),
    ):
        _, result = await _reuse(entry)
    assert result is None
    repo.mark_dead.assert_awaited_once()


@pytest.mark.regression
async def test_evicting_a_dead_cached_sandbox_marks_only_that_sandbox_dead() -> None:
    # Another process may already have replaced it; marking the user's record
    # dead wholesale abandoned that replacement and created a third sandbox.
    entry = _healthy_entry()
    entry.sandbox.sandbox_id = "sbx-stale"
    repo = AsyncMock()
    with (
        patch.object(lifecycle, "_health_probe", AsyncMock(return_value=False)),
        patch.object(
            lifecycle.AsyncSandbox, "get_info", AsyncMock(side_effect=NotFoundException("gone"))
        ),
        patch.object(lifecycle, "_stop_watcher", AsyncMock()),
        patch.object(lifecycle, "e2b_sandbox_repository", repo),
    ):
        await _reuse(entry)
    assert repo.mark_dead.await_args.kwargs["sandbox_id"] == "sbx-stale"


async def test_an_agent_lab_sandbox_refreshes_to_twelve_hours_on_its_own_window() -> None:
    # Refreshing a lab sandbox back to 1h would cut its 12h lifetime short.
    entry = _healthy_entry()
    entry.template_id = "gaia-coder-8gb"
    p1, p2, p3, p4 = _patch_probes_healthy()
    with (
        p1,
        p2,
        p3,
        p4,
        patch.object(pool_module.settings, "E2B_AGENT_LAB_TEMPLATE_ID", "gaia-coder-8gb"),
    ):
        entry.timeout_refreshed_at = time.monotonic() - (SANDBOX_LIFETIME_SECONDS + 5)
        await _reuse(entry)
        entry.sandbox.set_timeout.assert_not_awaited()
        entry.timeout_refreshed_at = time.monotonic() - (SANDBOX_LAB_LIFETIME_SECONDS // 2 + 5)
        await _reuse(entry)
    entry.sandbox.set_timeout.assert_awaited_once_with(SANDBOX_LAB_LIFETIME_SECONDS)
