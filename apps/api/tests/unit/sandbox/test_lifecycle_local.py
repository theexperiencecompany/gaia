"""Layer 3 — the local-sandbox routing branch of `acquire_sandbox`.

Covers what the E2B-path siblings don't: when ENV=selfhost runs without an
E2B key, `acquire_sandbox` must yield a `LocalDockerSandbox` and bypass every
piece of E2B machinery (pool entries, Mongo records, mount script, canary,
pause scheduling) — while any other configuration keeps the E2B path byte-for-
byte unchanged. The local sandbox itself is mocked; its behavior is covered by
`test_local_sandbox.py` (hermetic) and `test_local_sandbox_docker.py` (live).
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest

from app.services.sandbox import lifecycle
from app.services.sandbox.local_sandbox import LocalDockerSandbox


def _uid() -> str:
    return f"u-{uuid.uuid4().hex}"


def _fake_local_sandbox(alive: bool = True) -> Any:
    sbx = MagicMock(spec=LocalDockerSandbox)
    sbx.user_id = "u"
    sbx.container_name = "gaia-sandbox-u"
    sbx.sandbox_id = "gaia-sandbox-u"
    sbx.ensure_started = AsyncMock()
    sbx.is_running = AsyncMock(return_value=alive)
    sbx.kill = AsyncMock()
    return sbx


@contextmanager
def _selfhost_no_key() -> Iterator[None]:
    """Settings flipped to 'self-host with NO resolvable E2B credential'."""
    with (
        patch.object(lifecycle.settings, "ENV", "selfhost"),
        patch.object(lifecycle, "_resolved_e2b_api_key", AsyncMock(return_value=None)),
    ):
        yield


# --------------------------------------------------------------------------
# routing
# --------------------------------------------------------------------------


async def test_use_local_sandbox_requires_selfhost_and_no_resolvable_key() -> None:
    """The backend switch reads the credential seam, not the env var: a key
    stored in Settings (or env) keeps self-host on real E2B."""
    with (
        patch.object(lifecycle.settings, "ENV", "selfhost"),
        patch.object(lifecycle, "_resolved_e2b_api_key", AsyncMock(return_value="k")),
    ):
        assert await lifecycle.use_local_sandbox() is False

    with (
        patch.object(lifecycle.settings, "ENV", "selfhost"),
        patch.object(lifecycle, "_resolved_e2b_api_key", AsyncMock(return_value=None)),
    ):
        assert await lifecycle.use_local_sandbox() is True

    with patch.object(lifecycle.settings, "ENV", "production"):
        assert await lifecycle.use_local_sandbox() is False


async def test_selfhost_without_an_e2b_key_yields_the_local_sandbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uid = _uid()
    sbx = _fake_local_sandbox()
    e2b_acquire = AsyncMock()
    try:
        monkeypatch.setattr(lifecycle, "get_local_sandbox", lambda u: sbx)
        with _selfhost_no_key(), patch.object(lifecycle, "_acquire_or_create", e2b_acquire):
            async with lifecycle.acquire_sandbox(uid) as yielded:
                assert yielded is sbx
                sbx.ensure_started.assert_awaited_once()
        # Not one byte of the E2B machinery may run in local mode.
        e2b_acquire.assert_not_awaited()
    finally:
        lifecycle.pop_local_sandbox(uid)


async def test_selfhost_with_an_e2b_key_stays_on_the_e2b_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.sandbox.pool import PooledSandbox

    uid = _uid()
    sbx_e2b = AsyncMock()
    entry = PooledSandbox(sandbox=sbx_e2b)
    with (
        patch.object(lifecycle.settings, "ENV", "selfhost"),
        patch.object(lifecycle, "_acquire_or_create", AsyncMock(return_value=entry)),
        patch.object(lifecycle, "e2b_sandbox_repository", AsyncMock()),
        patch.object(lifecycle, "_schedule_pause"),
    ):
        async with lifecycle.acquire_sandbox(uid) as yielded:
            # The E2B path yields entry.sandbox (the live handle), not the
            # PooledSandbox wrapper.
            assert yielded is sbx_e2b


async def test_production_without_a_key_stays_on_the_e2b_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Only selfhost routes to Docker-exec; a misconfigured production instance
    # must fail loudly on the E2B path, not silently fall back to containers.
    uid = _uid()
    error = AsyncMock(side_effect=lifecycle.SandboxAcquisitionError("E2B_API_KEY"))
    with (
        patch.object(lifecycle.settings, "ENV", "production"),
        patch.object(lifecycle, "_resolved_e2b_api_key", AsyncMock(return_value=None)),
        patch.object(lifecycle, "_acquire_or_create", error),
    ):
        with pytest.raises(lifecycle.SandboxAcquisitionError, match="E2B_API_KEY"):
            async with lifecycle.acquire_sandbox(uid):
                pass  # pragma: no cover — never reached


async def test_an_empty_user_id_is_rejected_before_any_local_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get_local = MagicMock()
    monkeypatch.setattr(lifecycle, "get_local_sandbox", get_local)
    with _selfhost_no_key():
        with pytest.raises(lifecycle.SandboxAcquisitionError, match="user_id"):
            async with lifecycle.acquire_sandbox(""):
                pass  # pragma: no cover
    get_local.assert_not_called()


# --------------------------------------------------------------------------
# failure semantics inside the local branch
# --------------------------------------------------------------------------


async def test_a_tool_failure_with_a_live_container_keeps_the_cached_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uid = _uid()
    sbx = _fake_local_sandbox(alive=True)
    monkeypatch.setattr(lifecycle, "get_local_sandbox", lambda u: sbx)
    pop = MagicMock()
    monkeypatch.setattr(lifecycle, "pop_local_sandbox", pop)
    try:
        with _selfhost_no_key():
            with pytest.raises(RuntimeError, match="tool blew up"):
                async with lifecycle.acquire_sandbox(uid):
                    raise RuntimeError("tool blew up")
        sbx.kill.assert_not_awaited()
        pop.assert_not_called()
    finally:
        lifecycle.pop_local_sandbox(uid)


async def test_a_tool_failure_with_a_dead_container_evicts_and_kills(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uid = _uid()
    # The container died underneath the tool op → the handle must be evicted
    # and killed so the next acquire provisions a fresh container.
    sbx = _fake_local_sandbox(alive=False)
    monkeypatch.setattr(lifecycle, "get_local_sandbox", lambda u: sbx)
    pop = MagicMock(return_value=sbx)
    monkeypatch.setattr(lifecycle, "pop_local_sandbox", pop)
    with _selfhost_no_key():
        with pytest.raises(RuntimeError, match="container died"):
            async with lifecycle.acquire_sandbox(uid):
                raise RuntimeError("container died")
    sbx.is_running.assert_awaited_once()
    pop.assert_called_once_with(uid)
    sbx.kill.assert_awaited_once()


async def test_the_per_user_lock_is_released_after_a_failed_local_acquire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.sandbox.pool import get_sandbox_pool

    uid = _uid()
    sbx = _fake_local_sandbox()
    sbx.ensure_started = AsyncMock(side_effect=RuntimeError("daemon down"))
    monkeypatch.setattr(lifecycle, "get_local_sandbox", lambda u: sbx)
    with _selfhost_no_key():
        with pytest.raises(RuntimeError, match="daemon down"):
            async with lifecycle.acquire_sandbox(uid):
                pass  # pragma: no cover
    lock = await get_sandbox_pool().get_lock(uid)
    assert not lock.locked(), "a leaked lock would deadlock this user's next tool call"


async def test_concurrent_local_acquires_for_one_user_serialize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uid = _uid()
    sbx = _fake_local_sandbox()
    monkeypatch.setattr(lifecycle, "get_local_sandbox", lambda u: sbx)
    order: list[str] = []

    async def worker(tag: str) -> None:
        async with lifecycle.acquire_sandbox(uid):
            order.append(f"enter-{tag}")
            await asyncio.sleep(0.02)
            order.append(f"exit-{tag}")

    with _selfhost_no_key():
        await asyncio.gather(worker("a"), worker("b"))
    assert order[0].removeprefix("enter-") == order[1].removeprefix("exit-"), (
        f"same-user local acquires must serialize, got {order}"
    )
