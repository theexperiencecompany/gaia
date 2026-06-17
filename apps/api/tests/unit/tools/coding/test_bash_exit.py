"""Layer 3 — bash _run_foreground: non-zero exits are RESULTS, not tool errors.

The bug: commands.run raises CommandExitException on any non-zero exit, and the
old code let it propagate → every failing command (grep no-match, failing test)
was reported as "Error executing command" with the exit code/output lost. These
assert the exit code + stdout + stderr are surfaced normally.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from e2b import CommandExitException, TimeoutException
import pytest

from app.agents.tools.coding.bash_tool import _run_foreground

pytestmark = pytest.mark.unit


def _sbx_with_run(run_mock: AsyncMock) -> AsyncMock:
    sbx = AsyncMock()
    sbx.commands = SimpleNamespace(run=run_mock)
    sbx.files = AsyncMock()  # _persist_run_log calls files.write
    return sbx


async def test_zero_exit_returns_exit_code_and_streams() -> None:
    run = AsyncMock(return_value=SimpleNamespace(exit_code=0, stdout="done", stderr=""))
    out = await _run_foreground(_sbx_with_run(run), "rid", "echo done", "/workspace", 60, None)
    assert "exit_code: 0" in out
    assert "done" in out


async def test_nonzero_exit_is_surfaced_as_result_not_error() -> None:
    # grep-style: exit 1, real stdout/stderr. Must be a normal result.
    run = AsyncMock(
        side_effect=CommandExitException(
            stdout="partial out", stderr="grep: no match", exit_code=1, error=None
        )
    )
    out = await _run_foreground(_sbx_with_run(run), "rid", "grep x f", "/workspace", 60, None)
    assert "exit_code: 1" in out, "a non-zero exit must report its code, not raise"
    assert "partial out" in out
    assert "grep: no match" in out
    assert "Error executing command" not in out


@pytest.mark.parametrize("code", [1, 2, 127, 137, 255])
async def test_various_nonzero_exit_codes_surface(code: int) -> None:
    run = AsyncMock(
        side_effect=CommandExitException(stdout="", stderr="boom", exit_code=code, error=None)
    )
    out = await _run_foreground(_sbx_with_run(run), "rid", "cmd", "/workspace", 60, None)
    assert f"exit_code: {code}" in out


async def test_command_timeout_propagates() -> None:
    # A command-deadline TimeoutException must propagate (the bash() wrapper /
    # acquire_sandbox decide eviction), not be swallowed as a normal result.
    run = AsyncMock(side_effect=TimeoutException("exceeding 'timeout'"))
    with pytest.raises(TimeoutException):
        await _run_foreground(_sbx_with_run(run), "rid", "sleep 999", "/workspace", 1, None)
