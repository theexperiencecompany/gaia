"""The local-sandbox routing branch of acquire_sandbox.

When ENV selfhost runs without an E2B key, acquire_sandbox yields a local
Docker sandbox and bypasses all E2B machinery, while any other configuration
keeps the E2B path unchanged. The sandbox itself is mocked here; hermetic and
live coverage live in the sibling suites.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest
from tests.helpers import captured_wide_event

from app.constants.sandbox import CODE_EXECUTION_DISABLED_MESSAGE
from app.services.sandbox import lifecycle
from app.services.sandbox.errors import CodeExecutionDisabledError
from app.services.sandbox.local_sandbox import LocalDockerSandbox
from app.services.storage.metrics import FsOps, flush_fs_metrics, peek_fs_metrics


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
def _selfhost_no_key(*, local_code_sandbox: bool = True) -> Iterator[None]:
    """Flip settings to self-host with NO resolvable E2B credential."""
    with (
        patch.object(lifecycle.settings, "ENV", "selfhost"),
        patch.object(lifecycle.settings, "LOCAL_CODE_SANDBOX", local_code_sandbox),
        patch.object(lifecycle, "_resolved_e2b_api_key", AsyncMock(return_value=None)),
    ):
        yield


# --------------------------------------------------------------------------
# routing
# --------------------------------------------------------------------------


async def test_use_local_sandbox_requires_selfhost_and_no_resolvable_key() -> None:
    """Read the credential seam, not the env var, to pick the backend."""
    with (
        patch.object(lifecycle.settings, "ENV", "selfhost"),
        patch.object(lifecycle, "_resolved_e2b_api_key", AsyncMock(return_value="k")),
    ):
        assert await lifecycle.use_local_sandbox() is False

    with _selfhost_no_key():
        assert await lifecycle.use_local_sandbox() is True

    with (
        patch.object(lifecycle.settings, "ENV", "production"),
        patch.object(lifecycle.settings, "LOCAL_CODE_SANDBOX", True),
    ):
        assert await lifecycle.use_local_sandbox() is False


async def test_selfhost_without_the_opt_in_refuses_code_execution_with_the_fix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get_local = MagicMock()
    monkeypatch.setattr(lifecycle, "get_local_sandbox", get_local)
    with _selfhost_no_key(local_code_sandbox=False):
        with pytest.raises(CodeExecutionDisabledError) as refused:
            async with lifecycle.acquire_sandbox(_uid()):
                pass  # pragma: no cover — never reached
    assert str(refused.value) == CODE_EXECUTION_DISABLED_MESSAGE
    assert "gaia up --code-sandbox" in CODE_EXECUTION_DISABLED_MESSAGE
    # No Docker call may be attempted without the socket the opt-in mounts.
    get_local.assert_not_called()


async def test_an_e2b_key_runs_code_without_the_local_opt_in() -> None:
    with (
        patch.object(lifecycle.settings, "ENV", "selfhost"),
        patch.object(lifecycle.settings, "LOCAL_CODE_SANDBOX", False),
        patch.object(lifecycle, "_resolved_e2b_api_key", AsyncMock(return_value="k")),
    ):
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
        patch.object(lifecycle, "_resolved_e2b_api_key", AsyncMock(return_value="test-e2b-key")),
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


async def test_local_acquires_for_different_users_do_not_block_each_other(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sbx = _fake_local_sandbox()
    monkeypatch.setattr(lifecycle, "get_local_sandbox", lambda u: sbx)
    second_entered = asyncio.Event()

    async def first() -> None:
        async with lifecycle.acquire_sandbox(_uid()):
            await second_entered.wait()

    async def second() -> None:
        async with lifecycle.acquire_sandbox(_uid()):
            second_entered.set()

    with _selfhost_no_key():
        await asyncio.wait_for(asyncio.gather(first(), second()), timeout=5)


async def test_a_local_acquire_records_its_sandbox_and_timing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uid = _uid()
    sbx = _fake_local_sandbox()
    monkeypatch.setattr(lifecycle, "get_local_sandbox", lambda u: sbx if u == uid else None)
    flush_fs_metrics()

    with _selfhost_no_key():
        async with captured_wide_event() as event:
            async with lifecycle.acquire_sandbox(uid) as yielded:
                assert yielded is sbx

    assert event["sandbox"] == {
        "operation": "acquire",
        "source": "local_docker",
        "sandbox_id": "gaia-sandbox-u",
    }
    assert peek_fs_metrics()[FsOps.SBX_ACQUIRE]["count"] == 1


async def test_a_dead_container_is_recorded_unhealthy_and_a_failed_kill_hides_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uid = _uid()
    sbx = _fake_local_sandbox(alive=False)
    sbx.kill = AsyncMock(side_effect=RuntimeError("rm failed"))
    monkeypatch.setattr(lifecycle, "get_local_sandbox", lambda u: sbx)
    monkeypatch.setattr(lifecycle, "pop_local_sandbox", MagicMock(return_value=sbx))

    with _selfhost_no_key():
        async with captured_wide_event() as event:
            with pytest.raises(RuntimeError, match="container died"):
                async with lifecycle.acquire_sandbox(uid):
                    raise RuntimeError("container died")

    assert event["sandbox"]["health_ok"] is False
    sbx.kill.assert_awaited_once()
