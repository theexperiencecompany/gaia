"""bash_tool — exit-code bucketing, run-log persistence, and _run_foreground.

Layer 3. The original bug: commands.run raises CommandExitException on any
non-zero exit, and the old code let it propagate → every failing command (grep
no-match, failing test) was reported as "Error executing command" with the exit
code/output lost. These assert the exit code + stdout + stderr are surfaced
normally, plus the exact contracts around them: exit-code bucket labels,
metric recording, run-log persistence, streaming events, and error paths.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock, call, patch

from e2b import CommandExitException, TimeoutException
import pytest

from app.agents.tools.coding import bash_tool
from app.agents.tools.coding.bash_tool import (
    _bucket_exit_code,
    _persist_run_log,
    _record_bash_exit_code,
    _run_foreground,
)
from app.agents.workspace.paths import WORKSPACE_ROOT, runs_log_dir


def _sbx_with_run(run_mock: AsyncMock) -> AsyncMock:
    sbx = AsyncMock()
    sbx.commands = SimpleNamespace(run=run_mock)
    sbx.files = AsyncMock()  # _persist_run_log calls files.write
    return sbx


# --- _bucket_exit_code: every branch and boundary maps to the exact label ---

@pytest.mark.parametrize(
    ("code", "timed_out", "expected"),
    [
        (0, False, "0"),
        (1, False, "1-126"),
        (126, False, "1-126"),
        (127, False, "127"),
        (128, False, "128-254"),
        (254, False, "128-254"),
        (255, False, "255"),
        (None, False, "255"),
        (-1, False, "255"),
        (256, False, "255"),
        (1_000, False, "255"),
        (None, True, "timeout"),
        (0, True, "timeout"),
        (137, True, "timeout"),
    ],
)
def test_bucket_exit_code_exact_labels(code: int | None, timed_out: bool, expected: str) -> None:
    assert _bucket_exit_code(code, timed_out=timed_out) == expected


# --- _record_bash_exit_code: exact counter label + non-fatal failure path ---

def test_record_bash_exit_code_labels_exact_bucket() -> None:
    counter = MagicMock()
    with patch.object(bash_tool, "_BASH_EXIT_CODE_TOTAL", counter):
        _record_bash_exit_code(127, timed_out=False)
    counter.labels.assert_called_once_with(exit_code="127")
    counter.labels.return_value.inc.assert_called_once_with()


def test_record_bash_exit_code_timeout_bucket() -> None:
    counter = MagicMock()
    with patch.object(bash_tool, "_BASH_EXIT_CODE_TOTAL", counter):
        _record_bash_exit_code(None, timed_out=True)
    counter.labels.assert_called_once_with(exit_code="timeout")
    counter.labels.return_value.inc.assert_called_once_with()


def test_record_bash_exit_code_metric_failure_is_non_fatal() -> None:
    counter = MagicMock()
    counter.labels.side_effect = RuntimeError("prometheus broken")
    with patch.object(bash_tool, "_BASH_EXIT_CODE_TOTAL", counter):
        with patch.object(bash_tool, "log") as mock_log:
            _record_bash_exit_code(1, timed_out=False)  # must not raise
    mock_log.warning.assert_called_once_with(
        "[metrics] bash exit_code inc failed", error_type="RuntimeError"
    )


# --- _persist_run_log: exact path + body, and the silent-failure contract ---

async def test_persist_run_log_writes_full_body_to_run_log() -> None:
    sbx = AsyncMock()
    await _persist_run_log(sbx, "abc123", "stdout line", "stderr line")
    sbx.files.write.assert_awaited_once_with(
        f"{runs_log_dir()}/abc123.log", "stdout line\n---STDERR---\nstderr line"
    )


async def test_persist_run_log_with_empty_streams() -> None:
    sbx = AsyncMock()
    await _persist_run_log(sbx, "abc123", "", "")
    sbx.files.write.assert_awaited_once_with(f"{runs_log_dir()}/abc123.log", "\n---STDERR---\n")


async def test_persist_run_log_swallows_write_failure() -> None:
    sbx = AsyncMock()
    sbx.files.write.side_effect = RuntimeError("sandbox died")
    await _persist_run_log(sbx, "abc123", "out", "")  # must not raise


# --- _run_foreground: exact return strings, stream events, deps' args ---

async def test_full_result_return_string_and_dep_args() -> None:
    run = AsyncMock(return_value=SimpleNamespace(exit_code=0, stdout="done", stderr="warn"))
    sbx = _sbx_with_run(run)
    with patch.object(bash_tool, "safe_emit"), patch.object(
        bash_tool, "_record_bash_exit_code"
    ) as record:
        out = await _run_foreground(sbx, "rid1", "echo done", "/workspace", 60, None)
    assert out == "exit_code: 0\n\nstdout:\ndone\n\nstderr:\nwarn"
    record.assert_called_once_with(0, timed_out=False)
    run.assert_awaited_once_with(
        "echo done", cwd="/workspace", on_stdout=ANY, on_stderr=ANY, timeout=60
    )
    sbx.files.write.assert_awaited_once_with(
        f"{runs_log_dir()}/rid1.log", "done\n---STDERR---\nwarn"
    )


async def test_streams_chunks_and_exited_event_in_order() -> None:
    emitted: list[tuple[dict, str | None]] = []

    def capture(event: dict, *, session_id: str | None = None) -> None:
        emitted.append((event, session_id))

    def _run_side_effect(
        command: str,
        cwd: str | None = None,
        on_stdout=None,
        on_stderr=None,
        timeout: int | None = None,
    ) -> SimpleNamespace:
        on_stdout("first chunk")
        on_stderr("warn line")
        return SimpleNamespace(exit_code=2, stdout="", stderr="")

    sbx = _sbx_with_run(AsyncMock(side_effect=_run_side_effect))
    with patch.object(bash_tool, "safe_emit", side_effect=capture), patch.object(
        bash_tool, "_persist_run_log"
    ):
        await _run_foreground(sbx, "rid1", "cmd", "/workspace", 60, "conv1")

    assert emitted == [
        (
            {
                "bash_data": {
                    "id": "rid1",
                    "status": "running",
                    "stream": "stdout",
                    "chunk": "first chunk",
                }
            },
            "conv1",
        ),
        (
            {
                "bash_data": {
                    "id": "rid1",
                    "status": "running",
                    "stream": "stderr",
                    "chunk": "warn line",
                }
            },
            "conv1",
        ),
        ({"bash_data": {"id": "rid1", "status": "exited", "exit_code": 2}}, "conv1"),
    ]


async def test_empty_cwd_falls_back_to_workspace_root() -> None:
    run = AsyncMock(return_value=SimpleNamespace(exit_code=0, stdout="", stderr=""))
    sbx = _sbx_with_run(run)
    with patch.object(bash_tool, "safe_emit"), patch.object(
        bash_tool, "_record_bash_exit_code"
    ), patch.object(bash_tool, "_persist_run_log"):
        out = await _run_foreground(sbx, "rid", "pwd", "", 60, None)
    assert out == "exit_code: 0"
    run.assert_awaited_once_with(
        "pwd", cwd=WORKSPACE_ROOT, on_stdout=ANY, on_stderr=ANY, timeout=60
    )


async def test_output_truncated_via_head_tail_seam() -> None:
    run = AsyncMock(
        return_value=SimpleNamespace(exit_code=0, stdout="long out", stderr="long err")
    )
    sbx = _sbx_with_run(run)
    with patch.object(bash_tool, "safe_emit"), patch.object(
        bash_tool, "truncate_head_tail", side_effect=lambda s: f"[{s}]"
    ) as trunc:
        out = await _run_foreground(sbx, "rid", "cmd", "/workspace", 60, None)
    assert trunc.call_args_list == [call("long out"), call("long err")]
    assert out == "exit_code: 0\n\nstdout:\n[long out]\n\nstderr:\n[long err]"


async def test_stdout_only_result() -> None:
    run = AsyncMock(return_value=SimpleNamespace(exit_code=0, stdout="done", stderr=""))
    sbx = _sbx_with_run(run)
    with patch.object(bash_tool, "safe_emit"), patch.object(
        bash_tool, "_record_bash_exit_code"
    ), patch.object(bash_tool, "_persist_run_log"):
        out = await _run_foreground(sbx, "rid", "cmd", "/workspace", 60, None)
    assert out == "exit_code: 0\n\nstdout:\ndone"


async def test_stderr_only_result() -> None:
    run = AsyncMock(return_value=SimpleNamespace(exit_code=3, stdout="", stderr="boom"))
    sbx = _sbx_with_run(run)
    with patch.object(bash_tool, "safe_emit"), patch.object(
        bash_tool, "_record_bash_exit_code"
    ), patch.object(bash_tool, "_persist_run_log"):
        out = await _run_foreground(sbx, "rid", "cmd", "/workspace", 60, None)
    assert out == "exit_code: 3\n\nstderr:\nboom"


async def test_result_without_exit_code_attr_records_none() -> None:
    run = AsyncMock(return_value=SimpleNamespace(stdout="x", stderr=""))
    sbx = _sbx_with_run(run)
    with patch.object(bash_tool, "safe_emit"), patch.object(
        bash_tool, "_record_bash_exit_code"
    ) as record, patch.object(bash_tool, "_persist_run_log"):
        out = await _run_foreground(sbx, "rid", "cmd", "/workspace", 60, None)
    assert out == "exit_code: None\n\nstdout:\nx"
    record.assert_called_once_with(None, timed_out=False)


async def test_result_without_stream_attrs_falls_back_to_empty() -> None:
    # The SDK result may lack stdout/stderr entirely; the getattr defaults must
    # yield empty streams (no section in the return), never raise or leak the
    # default into the output.
    run = AsyncMock(return_value=SimpleNamespace(exit_code=0))
    sbx = _sbx_with_run(run)
    with patch.object(bash_tool, "safe_emit"), patch.object(
        bash_tool, "_record_bash_exit_code"
    ) as record, patch.object(bash_tool, "_persist_run_log"):
        out = await _run_foreground(sbx, "rid", "cmd", "/workspace", 60, None)
    assert out == "exit_code: 0"
    record.assert_called_once_with(0, timed_out=False)


async def test_command_exit_exception_surfaces_result_and_records() -> None:
    # grep-style: exit 1, real stdout/stderr. Must be a normal result.
    run = AsyncMock(
        side_effect=CommandExitException(
            stdout="partial out", stderr="grep: no match", exit_code=1, error=None
        )
    )
    sbx = _sbx_with_run(run)
    with patch.object(bash_tool, "safe_emit"), patch.object(
        bash_tool, "_record_bash_exit_code"
    ) as record, patch.object(bash_tool, "_persist_run_log"):
        out = await _run_foreground(sbx, "rid", "grep x f", "/workspace", 60, None)
    assert out == "exit_code: 1\n\nstdout:\npartial out\n\nstderr:\ngrep: no match"
    assert "Error executing command" not in out
    record.assert_called_once_with(1, timed_out=False)


async def test_command_exit_exception_with_missing_streams() -> None:
    run = AsyncMock(
        side_effect=CommandExitException(stdout=None, stderr=None, exit_code=2, error=None)
    )
    sbx = _sbx_with_run(run)
    with patch.object(bash_tool, "safe_emit"), patch.object(
        bash_tool, "_record_bash_exit_code"
    ) as record, patch.object(bash_tool, "_persist_run_log"):
        out = await _run_foreground(sbx, "rid", "cmd", "/workspace", 60, None)
    assert out == "exit_code: 2"
    record.assert_called_once_with(2, timed_out=False)


@pytest.mark.parametrize("code", [1, 2, 127, 137, 255])
async def test_various_nonzero_exit_codes_surface(code: int) -> None:
    run = AsyncMock(
        side_effect=CommandExitException(stdout="", stderr="boom", exit_code=code, error=None)
    )
    sbx = _sbx_with_run(run)
    with patch.object(bash_tool, "safe_emit"), patch.object(
        bash_tool, "_record_bash_exit_code"
    ), patch.object(bash_tool, "_persist_run_log"):
        out = await _run_foreground(sbx, "rid", "cmd", "/workspace", 60, None)
    assert out == f"exit_code: {code}\n\nstderr:\nboom"


@pytest.mark.parametrize(
    "exc",
    [TimeoutException("exceeding 'timeout'"), TimeoutError("deadline"), asyncio.CancelledError()],
)
async def test_timeout_like_errors_record_timeout_bucket_and_propagate(exc: BaseException) -> None:
    # A command-deadline TimeoutException must propagate (the bash() wrapper /
    # acquire_sandbox decide eviction), not be swallowed as a normal result —
    # but the metric bucket must still record it as a timeout.
    run = AsyncMock(side_effect=exc)
    sbx = _sbx_with_run(run)
    with patch.object(bash_tool, "safe_emit"), patch.object(
        bash_tool, "_record_bash_exit_code"
    ) as record, patch.object(bash_tool, "_persist_run_log"):
        with pytest.raises(type(exc)):
            await _run_foreground(sbx, "rid", "sleep 999", "/workspace", 1, None)
    record.assert_called_once_with(None, timed_out=True)


async def test_other_errors_record_unknown_bucket_and_propagate() -> None:
    run = AsyncMock(side_effect=RuntimeError("sandbox connection lost"))
    sbx = _sbx_with_run(run)
    with patch.object(bash_tool, "safe_emit"), patch.object(
        bash_tool, "_record_bash_exit_code"
    ) as record, patch.object(bash_tool, "_persist_run_log"):
        with pytest.raises(RuntimeError, match="sandbox connection lost"):
            await _run_foreground(sbx, "rid", "cmd", "/workspace", 60, None)
    record.assert_called_once_with(None, timed_out=False)
