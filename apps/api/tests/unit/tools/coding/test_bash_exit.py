"""bash_tool — exit-code bucketing, run-log persistence, _run_foreground, and
the background/artifact/error-event contracts.

Layer 3. The original bug: commands.run raises CommandExitException on any
non-zero exit, and the old code let it propagate → every failing command (grep
no-match, failing test) was reported as "Error executing command" with the exit
code/output lost. These assert the exit code + stdout + stderr are surfaced
normally, plus the exact contracts around them: exit-code bucket labels,
metric recording, run-log persistence, streaming events, error paths, the
background-command wrapper, the NUL-delimited artifact enumeration, and the
inline-body decode gates.
"""

from __future__ import annotations

import asyncio
import base64
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock, call, patch

from e2b import CommandExitException, TimeoutException
import pytest

from app.agents.tools.coding import bash_tool
from app.agents.tools.coding.bash_tool import (
    _bucket_exit_code,
    _decode_inline,
    _emit_bash_error,
    _persist_run_log,
    _publish_artifacts,
    _record_bash_exit_code,
    _run_background,
    _run_foreground,
    bash,
)
from app.agents.workspace.paths import (
    INLINE_ARTIFACT_MAX_BYTES,
    WORKSPACE_ROOT,
    runs_log_dir,
    session_dir,
)
from app.constants.log_tags import LogTag
from app.constants.sandbox import BASH_MAX_COMMAND_LENGTH
from app.services.sandbox import SandboxAcquisitionError
from app.services.storage import FsOps

CONFIG = {"configurable": {"user_id": "u1", "conversation_id": "c1"}}


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


# --- _emit_bash_error: exact terminal event + the message it returns ---

def test_emit_bash_error_exact_event_and_return() -> None:
    with patch.object(bash_tool, "safe_emit") as emit:
        msg = _emit_bash_error("rid1", "boom chunk", "Error executing command: boom", "conv1")
    assert msg == "Error executing command: boom"
    emit.assert_called_once_with(
        {
            "bash_data": {
                "id": "rid1",
                "status": "error",
                "exit_code": None,
                "stream": "stderr",
                "chunk": "boom chunk",
            }
        },
        session_id="conv1",
    )


def test_emit_bash_error_without_session_and_empty_chunk() -> None:
    with patch.object(bash_tool, "safe_emit") as emit:
        msg = _emit_bash_error("rid1", "", "Error: sandbox unavailable — nope", None)
    assert msg == "Error: sandbox unavailable — nope"
    emit.assert_called_once_with(
        {
            "bash_data": {
                "id": "rid1",
                "status": "error",
                "exit_code": None,
                "stream": "stderr",
                "chunk": "",
            }
        },
        session_id=None,
    )


# --- _decode_inline: size/type gates, exact decode, replace-mode, ValueError ---

@pytest.mark.parametrize(
    ("body_b64", "size_bytes", "content_type", "expected"),
    [
        ("", 10, "text/plain", None),  # empty body
        ("aGVsbG8=", 0, "text/plain", None),  # zero size
        ("aGVsbG8=", -1, "text/plain", None),  # negative size
        (  # above the 64 KB inline cap
            "aGVsbG8=",
            INLINE_ARTIFACT_MAX_BYTES + 1,
            "text/plain",
            None,
        ),
        ("aGVsbG8=", 5, None, None),  # unknown content type
        ("aGVsbG8=", 5, "application/pdf", None),  # non-inlineable type
        ("aGVsbG8=", 1, "text/plain", "hello"),  # size 1 still inlines
    ],
)
def test_decode_inline_gates(
    body_b64: str, size_bytes: int, content_type: str | None, expected: str | None
) -> None:
    assert _decode_inline(body_b64, size_bytes, content_type) == expected


def test_decode_inline_exact_body() -> None:
    body = "hello world!\n"
    b64 = base64.b64encode(body.encode()).decode()
    assert _decode_inline(b64, len(body.encode()), "text/plain") == body


def test_decode_inline_at_max_size_boundary_is_inlined() -> None:
    body = "x" * INLINE_ARTIFACT_MAX_BYTES
    b64 = base64.b64encode(body.encode()).decode()
    assert _decode_inline(b64, INLINE_ARTIFACT_MAX_BYTES, "text/plain") == body


def test_decode_inline_invalid_base64_returns_none() -> None:
    # '!' is outside the base64 alphabet → b64decode raises ValueError
    assert _decode_inline("not base64!", 10, "text/plain") is None


def test_decode_inline_undecodable_utf8_uses_replacement_chars() -> None:
    # b"\xff\xfe" is not valid UTF-8; errors="replace" must yield U+FFFD, not raise
    b64 = base64.b64encode(b"\xff\xfe").decode()
    assert _decode_inline(b64, 2, "text/plain") == "\ufffd\ufffd"


# --- _run_background: exact wrapped command, pid parse, event, error paths ---

async def test_run_background_exact_wrapped_command_and_args() -> None:
    run = AsyncMock(return_value=SimpleNamespace(stdout="42", stderr=""))
    sbx = _sbx_with_run(run)
    with patch.object(bash_tool, "safe_emit"):
        await _run_background(sbx, "rid9", "sleep 100", "", None)
    run.assert_awaited_once_with(
        "mkdir -p '/workspace/.gaia/runs' && "
        "nohup bash -c 'sleep 100' > '/workspace/.gaia/runs/rid9.log' 2>&1 "
        "& echo $!",
        cwd=WORKSPACE_ROOT,
        timeout=10,
    )


async def test_run_background_pid_stripped_event_and_return() -> None:
    run = AsyncMock(return_value=SimpleNamespace(stdout="  42\n", stderr=""))
    sbx = _sbx_with_run(run)
    emitted: list[tuple[dict, str | None]] = []

    def capture(event: dict, *, session_id: str | None = None) -> None:
        emitted.append((event, session_id))

    with patch.object(bash_tool, "safe_emit", side_effect=capture):
        out = await _run_background(sbx, "rid9", "sleep 100", "/workspace/scratch", "conv1")
    assert out == (
        "Started in background. pid=42, log_path=/workspace/.gaia/runs/rid9.log\n"
        'Tail the log via bash("tail -f /workspace/.gaia/runs/rid9.log")'
    )
    assert emitted == [
        (
            {
                "bash_data": {
                    "id": "rid9",
                    "status": "background_started",
                    "pid": "42",
                    "log_path": "/workspace/.gaia/runs/rid9.log",
                }
            },
            "conv1",
        )
    ]


async def test_run_background_cwd_passthrough() -> None:
    run = AsyncMock(return_value=SimpleNamespace(stdout="7", stderr=""))
    sbx = _sbx_with_run(run)
    with patch.object(bash_tool, "safe_emit"):
        await _run_background(sbx, "rid9", "cmd", "/workspace/scratch", None)
    run.assert_awaited_once_with(ANY, cwd="/workspace/scratch", timeout=10)


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (
            SimpleNamespace(stdout="", stderr="log write failed"),
            "Error: failed to start background command (stderr: log write failed)",
        ),
        (
            SimpleNamespace(stdout="  \n", stderr="nohup: command not found"),
            "Error: failed to start background command (stderr: nohup: command not found)",
        ),
        # stdout attr missing entirely → getattr default ""
        (
            SimpleNamespace(stderr="boom"),
            "Error: failed to start background command (stderr: boom)",
        ),
        # neither attr present — the stderr default must yield "" not None/"XXXX"
        (
            SimpleNamespace(),
            "Error: failed to start background command (stderr: )",
        ),
    ],
)
async def test_run_background_empty_pid_returns_error(
    result: SimpleNamespace, expected: str
) -> None:
    sbx = _sbx_with_run(AsyncMock(return_value=result))
    with patch.object(bash_tool, "safe_emit") as emit:
        out = await _run_background(sbx, "rid9", "cmd", "", None)
    assert out == expected
    emit.assert_not_called()


# --- _publish_artifacts: exact find command, NUL parsing, per-record publish ---

async def test_publish_artifacts_exact_enumerate_command() -> None:
    run = AsyncMock(return_value=SimpleNamespace(stdout=""))
    sbx = _sbx_with_run(run)
    with patch.object(bash_tool, "publish_artifact") as publish:
        await _publish_artifacts(sbx, "user1", "conv1")
    run.assert_awaited_once_with(
        "find '/workspace/sessions/conv1/artifacts' -type f "
        "! -name '*.gaia-tmp' "
        "-printf '%P\\0%s\\0%T@\\0' "
        "-exec sh -c '"
        '  s=$(stat -c%s "$0"); '
        f'  if [ "$s" -le {INLINE_ARTIFACT_MAX_BYTES} ]; then base64 -w0 "$0" 2>/dev/null; fi; '
        '  printf "\\0"'
        "' {} \\; 2>/dev/null",
        timeout=15,
    )
    publish.assert_not_called()


async def test_publish_artifacts_single_record_exact_publish_args() -> None:
    body = "hello world!\n"
    b64 = base64.b64encode(body.encode()).decode()
    stdout = "notes.md\0" + "17\0" + "1700000000.5\0" + b64 + "\0"
    sbx = _sbx_with_run(AsyncMock(return_value=SimpleNamespace(stdout=stdout)))
    with patch.object(bash_tool, "publish_artifact") as publish:
        await _publish_artifacts(sbx, "user1", "conv1")
    publish.assert_awaited_once_with("user1", "conv1", "notes.md", 17, 1700000000.5, body)


async def test_publish_artifacts_multiple_records_in_order() -> None:
    stdout = (
        "a.txt\0" + "3\0" + "1.0\0" + base64.b64encode(b"abc").decode() + "\0"
        "b.py\0" + "4\0" + "2.5\0" + base64.b64encode(b"def\n").decode() + "\0"
    )
    sbx = _sbx_with_run(AsyncMock(return_value=SimpleNamespace(stdout=stdout)))
    with patch.object(bash_tool, "publish_artifact") as publish:
        await _publish_artifacts(sbx, "user1", "conv1")
    assert publish.await_args_list == [
        call("user1", "conv1", "a.txt", 3, 1.0, "abc"),
        call("user1", "conv1", "b.py", 4, 2.5, "def\n"),
    ]


async def test_publish_artifacts_empty_rel_record_skipped_not_breaking() -> None:
    # A pathless record must be skipped without dropping the records after it —
    # continue, not break, through the NUL field groups.
    stdout = (
        "\0" + "10\0" + "1.0\0" + base64.b64encode(b"x" * 10).decode() + "\0"
        "ok.txt\0" + "9\0" + "1.5\0" + "ZGF0YQ==" + "\0"
    )
    sbx = _sbx_with_run(AsyncMock(return_value=SimpleNamespace(stdout=stdout)))
    with patch.object(bash_tool, "publish_artifact") as publish:
        await _publish_artifacts(sbx, "user1", "conv1")
    publish.assert_awaited_once_with("user1", "conv1", "ok.txt", 9, 1.5, "data")


async def test_publish_artifacts_partial_trailing_record_skipped() -> None:
    # find died mid-record: 7 NUL fields (a full record + 2 partial) — the
    # trailing group (7 % 4 = 3 fields) must be dropped, not published.
    stdout = "a.txt\0" + "3\0" + "1.0\0" + "YQ==" + "\0" + "partial\0" + "1\0"
    sbx = _sbx_with_run(AsyncMock(return_value=SimpleNamespace(stdout=stdout)))
    with patch.object(bash_tool, "publish_artifact") as publish:
        await _publish_artifacts(sbx, "user1", "conv1")
    publish.assert_awaited_once_with("user1", "conv1", "a.txt", 3, 1.0, "a")


async def test_publish_artifacts_unparseable_size_and_mtime_fall_back() -> None:
    b64 = base64.b64encode(b"data").decode()
    stdout = (
        "bad.txt\0" + "not-a-size\0" + "not-a-time\0" + b64 + "\0"
        "ok.txt\0" + "9\0" + "1.5\0" + "ZGF0YQ==" + "\0"
    )
    sbx = _sbx_with_run(AsyncMock(return_value=SimpleNamespace(stdout=stdout)))
    with patch.object(bash_tool, "time") as fake_time:
        fake_time.time.return_value = 1234.0
        with patch.object(bash_tool, "publish_artifact") as publish:
            await _publish_artifacts(sbx, "user1", "conv1")
    assert publish.await_args_list == [
        # size fell back to 0 → the inline gate (size > 0) blocks the body
        call("user1", "conv1", "bad.txt", 0, 1234.0, None),
        call("user1", "conv1", "ok.txt", 9, 1.5, "data"),
    ]


async def test_publish_artifacts_empty_size_field_yields_zero_size_no_inline() -> None:
    # Empty size field → 0 without int(); size 0 then gates the inline body off
    stdout = "e.txt\0" + "\0" + "1.0\0" + base64.b64encode(b"data").decode() + "\0"
    sbx = _sbx_with_run(AsyncMock(return_value=SimpleNamespace(stdout=stdout)))
    with patch.object(bash_tool, "publish_artifact") as publish:
        await _publish_artifacts(sbx, "user1", "conv1")
    publish.assert_awaited_once_with("user1", "conv1", "e.txt", 0, 1.0, None)


async def test_publish_artifacts_empty_mtime_field_uses_now() -> None:
    stdout = "e.txt\0" + "9\0" + "\0" + base64.b64encode(b"data").decode() + "\0"
    sbx = _sbx_with_run(AsyncMock(return_value=SimpleNamespace(stdout=stdout)))
    with patch.object(bash_tool, "time") as fake_time:
        fake_time.time.return_value = 99.0
        with patch.object(bash_tool, "publish_artifact") as publish:
            await _publish_artifacts(sbx, "user1", "conv1")
    publish.assert_awaited_once_with("user1", "conv1", "e.txt", 9, 99.0, "data")


async def test_publish_artifacts_large_or_binary_body_not_inlined() -> None:
    # find's sh -c only base64s files ≤ the cap, so a big file has an empty
    # body field → inline_body must be None (side panel falls back to fetch)
    stdout = "big.bin\0" + "99999\0" + "1.0\0" + "\0"
    sbx = _sbx_with_run(AsyncMock(return_value=SimpleNamespace(stdout=stdout)))
    with patch.object(bash_tool, "publish_artifact") as publish:
        await _publish_artifacts(sbx, "user1", "conv1")
    publish.assert_awaited_once_with("user1", "conv1", "big.bin", 99999, 1.0, None)


async def test_publish_artifacts_run_failure_is_silent() -> None:
    sbx = _sbx_with_run(AsyncMock(side_effect=RuntimeError("sandbox died")))
    with patch.object(bash_tool, "publish_artifact") as publish:
        await _publish_artifacts(sbx, "user1", "conv1")  # must not raise
    publish.assert_not_called()


async def test_publish_artifacts_missing_stdout_is_silent() -> None:
    sbx = _sbx_with_run(AsyncMock(return_value=SimpleNamespace()))
    with patch.object(bash_tool, "publish_artifact") as publish:
        await _publish_artifacts(sbx, "user1", "conv1")
    publish.assert_not_called()


# --- bash tool (through @tool + @with_rate_limiting + @with_doc) --------------
# The tool's own guards and orchestration: input validation, cwd gate, sandbox
# acquisition, foreground/background dispatch, artifact publish, error paths.

@pytest.mark.parametrize("command", ["", "   ", "\n\t"])
async def test_bash_empty_command_returns_error(command: str) -> None:
    with patch.object(bash_tool, "acquire_sandbox") as acq:
        out = await bash.ainvoke({"command": command}, config=CONFIG)
    assert out == "Error: command cannot be empty"
    acq.assert_not_called()


async def test_bash_overlong_command_returns_error() -> None:
    command = "x" * (BASH_MAX_COMMAND_LENGTH + 1)
    with patch.object(bash_tool, "acquire_sandbox") as acq:
        out = await bash.ainvoke({"command": command}, config=CONFIG)
    assert out == f"Error: command exceeds {BASH_MAX_COMMAND_LENGTH} characters"
    acq.assert_not_called()


async def test_bash_command_at_exact_max_length_is_allowed() -> None:
    # The limit is `>` not `>=`: exactly BASH_MAX_COMMAND_LENGTH chars pass
    command = "x" * BASH_MAX_COMMAND_LENGTH
    sbx = AsyncMock()
    acq, timer = _sandbox_context(sbx)
    with (
        patch.object(bash_tool, "acquire_sandbox", return_value=acq),
        patch.object(bash_tool, "fs_timer", return_value=timer),
        patch.object(bash_tool, "safe_emit"),
        patch.object(bash_tool, "_run_foreground", return_value="exit_code: 0") as fg,
        patch.object(bash_tool, "_publish_artifacts"),
    ):
        out = await bash.ainvoke({"command": command}, config=CONFIG)
    assert out == "exit_code: 0"
    fg.assert_awaited_once()
    assert fg.await_args.args[2] == command


async def test_bash_missing_user_id_returns_error() -> None:
    with patch.object(bash_tool, "get_user_id", side_effect=ValueError("no user here")):
        out = await bash.ainvoke({"command": "pwd"}, config=CONFIG)
    assert out == "Error: no user here"


@pytest.mark.parametrize(
    ("cwd", "expected"),
    [
        ("/etc", "Error: cwd must be under /workspace (got '/etc')"),
        # normalized climb-out is reported at its joined (pre-normpath) form
        (
            "/workspace/../etc",
            "Error: cwd must be under /workspace (got '/workspace/../etc')",
        ),
        (
            "../../..",
            "Error: cwd must be under /workspace (got '/workspace/sessions/c1/../../..')",
        ),
    ],
)
async def test_bash_escaping_cwd_rejected_before_sandbox(cwd: str, expected: str) -> None:
    with patch.object(bash_tool, "acquire_sandbox") as acq:
        out = await bash.ainvoke({"command": "pwd", "cwd": cwd}, config=CONFIG)
    assert out == expected
    acq.assert_not_called()


def _sandbox_context(sbx: AsyncMock) -> tuple[AsyncMock, AsyncMock]:
    acq = AsyncMock()
    acq.__aenter__.return_value = sbx
    timer = AsyncMock()
    timer.__aenter__.return_value = None
    return acq, timer


async def test_bash_foreground_exact_args_events_and_artifacts() -> None:
    sbx = AsyncMock()
    acq, timer = _sandbox_context(sbx)
    emitted: list[tuple[dict, str | None]] = []

    def capture(event: dict, *, session_id: str | None = None) -> None:
        emitted.append((event, session_id))

    with (
        patch.object(bash_tool, "acquire_sandbox", return_value=acq) as acq_mock,
        patch.object(bash_tool, "fs_timer", return_value=timer) as fs_timer_mock,
        patch.object(bash_tool, "safe_emit", side_effect=capture),
        patch.object(bash_tool, "_run_foreground", return_value="exit_code: 0\n\nstdout:\ndone") as fg,
        patch.object(bash_tool, "_publish_artifacts") as publish,
        patch.object(bash_tool, "log") as mock_log,
    ):
        out = await bash.ainvoke(
            {"command": "echo done", "cwd": "/workspace/scratch"}, config=CONFIG
        )

    run_id = emitted[0][0]["bash_data"]["id"]
    assert len(run_id) == 12 and all(c in "0123456789abcdef" for c in run_id)
    assert out == "exit_code: 0\n\nstdout:\ndone"
    assert emitted == [
        (
            {
                "bash_data": {
                    "id": run_id,
                    "command": "echo done",
                    "cwd": "/workspace/scratch",
                    "status": "starting",
                }
            },
            "c1",
        )
    ]
    mock_log.set.assert_called_once_with(tool={"name": "bash", "action": "execute"})
    acq_mock.assert_called_once_with("u1")
    sbx.files.make_dir.assert_awaited_once_with("/workspace/scratch")
    fg.assert_awaited_once_with(sbx, run_id, "echo done", "/workspace/scratch", 300, "c1")
    publish.assert_awaited_once_with(sbx, "u1", "c1")
    assert fs_timer_mock.call_args_list == [call(FsOps.TOOL_BASH), call(FsOps.TOOL_BASH_PUBLISH)]


async def test_bash_cwd_workspace_root_resolves_to_session_dir() -> None:
    # cwd == WORKSPACE_ROOT is the explicit "default to my session" spelling
    sbx = AsyncMock()
    acq, timer = _sandbox_context(sbx)
    with (
        patch.object(bash_tool, "acquire_sandbox", return_value=acq),
        patch.object(bash_tool, "fs_timer", return_value=timer),
        patch.object(bash_tool, "safe_emit"),
        patch.object(bash_tool, "_run_foreground", return_value="exit_code: 0") as fg,
        patch.object(bash_tool, "_publish_artifacts"),
    ):
        await bash.ainvoke({"command": "pwd", "cwd": WORKSPACE_ROOT}, config=CONFIG)
    sbx.files.make_dir.assert_awaited_once_with(session_dir("c1"))
    assert fg.await_args.args[3] == session_dir("c1")


async def test_bash_make_dir_failure_is_swallowed() -> None:
    # The session dir is created on demand; if that fails the command must
    # still run — make_dir is best-effort (contextlib.suppress(Exception)).
    sbx = AsyncMock()
    sbx.files.make_dir.side_effect = RuntimeError("sandbox fs broken")
    acq, timer = _sandbox_context(sbx)
    with (
        patch.object(bash_tool, "acquire_sandbox", return_value=acq),
        patch.object(bash_tool, "fs_timer", return_value=timer),
        patch.object(bash_tool, "safe_emit"),
        patch.object(bash_tool, "_run_foreground", return_value="exit_code: 0") as fg,
        patch.object(bash_tool, "_publish_artifacts"),
    ):
        out = await bash.ainvoke(
            {"command": "pwd", "cwd": "/workspace/scratch"}, config=CONFIG
        )
    assert out == "exit_code: 0"
    fg.assert_awaited_once()


async def test_bash_no_cwd_without_session_skips_make_dir() -> None:
    # A session-id-less invocation keeps cwd "" — nothing to create, and
    # _run_foreground's own `cwd or WORKSPACE_ROOT` fallback handles it.
    sbx = AsyncMock()
    acq, timer = _sandbox_context(sbx)
    with (
        patch.object(bash_tool, "acquire_sandbox", return_value=acq),
        patch.object(bash_tool, "fs_timer", return_value=timer),
        patch.object(bash_tool, "safe_emit"),
        patch.object(bash_tool, "get_session_id", return_value=None),
        patch.object(bash_tool, "_run_foreground", return_value="exit_code: 0") as fg,
        patch.object(bash_tool, "_publish_artifacts"),
    ):
        await bash.ainvoke({"command": "pwd"}, config=CONFIG)
    sbx.files.make_dir.assert_not_called()
    assert fg.await_args.args[3] == ""


@pytest.mark.parametrize(
    ("timeout", "expected"),
    [
        (9999, 1800),  # clamped to BASH_MAX_TIMEOUT_SECONDS
        (0, 1),  # floored at 1
        (5, 5),  # in range passes through
    ],
)
async def test_bash_timeout_clamped(timeout: int, expected: int) -> None:
    sbx = AsyncMock()
    acq, timer = _sandbox_context(sbx)
    with (
        patch.object(bash_tool, "acquire_sandbox", return_value=acq),
        patch.object(bash_tool, "fs_timer", return_value=timer),
        patch.object(bash_tool, "safe_emit"),
        patch.object(bash_tool, "_run_foreground", return_value="exit_code: 0") as fg,
        patch.object(bash_tool, "_publish_artifacts"),
    ):
        await bash.ainvoke({"command": "sleep 1", "timeout": timeout}, config=CONFIG)
    assert fg.await_args.args[4] == expected


async def test_bash_background_dispatches_to_run_background() -> None:
    sbx = AsyncMock()
    acq, timer = _sandbox_context(sbx)
    bg_result = "Started in background. pid=7, log_path=/workspace/.gaia/runs/abc.log\n"
    with (
        patch.object(bash_tool, "acquire_sandbox", return_value=acq),
        patch.object(bash_tool, "fs_timer", return_value=timer),
        patch.object(bash_tool, "safe_emit") as emit,
        patch.object(bash_tool, "_run_foreground") as fg,
        patch.object(bash_tool, "_run_background", return_value=bg_result) as bg,
    ):
        out = await bash.ainvoke(
            {"command": "sleep 100", "cwd": "/workspace/scratch", "background": True},
            config=CONFIG,
        )
    starting_id = emit.call_args_list[0].args[0]["bash_data"]["id"]
    assert out == bg_result
    bg.assert_awaited_once_with(sbx, starting_id, "sleep 100", "/workspace/scratch", "c1")
    fg.assert_not_called()


async def test_bash_without_session_skips_artifact_publish() -> None:
    sbx = AsyncMock()
    acq, timer = _sandbox_context(sbx)
    with (
        patch.object(bash_tool, "acquire_sandbox", return_value=acq),
        patch.object(bash_tool, "fs_timer", return_value=timer),
        patch.object(bash_tool, "safe_emit") as emit,
        patch.object(bash_tool, "get_session_id", return_value=None),
        patch.object(bash_tool, "_run_foreground", return_value="exit_code: 0"),
        patch.object(bash_tool, "_publish_artifacts") as publish,
    ):
        await bash.ainvoke({"command": "pwd"}, config=CONFIG)
    publish.assert_not_called()
    assert emit.call_args_list[0].kwargs["session_id"] is None


async def test_bash_sandbox_acquisition_error_emits_terminal_event() -> None:
    emitted: list[tuple[dict, str | None]] = []

    def capture(event: dict, *, session_id: str | None = None) -> None:
        emitted.append((event, session_id))

    acq = AsyncMock()
    acq.__aenter__.side_effect = SandboxAcquisitionError("pool exhausted")
    with (
        patch.object(bash_tool, "acquire_sandbox", return_value=acq),
        patch.object(bash_tool, "safe_emit", side_effect=capture),
        patch.object(bash_tool, "log"),
    ):
        out = await bash.ainvoke({"command": "pwd"}, config=CONFIG)
    assert out == "Error: sandbox unavailable — pool exhausted"
    run_id = emitted[0][0]["bash_data"]["id"]
    assert emitted == [
        (
            {
                "bash_data": {
                    "id": run_id,
                    "command": "pwd",
                    # empty cwd + session resolves to the session root
                    "cwd": session_dir("c1"),
                    "status": "starting",
                }
            },
            "c1",
        ),
        (
            {
                "bash_data": {
                    "id": run_id,
                    "status": "error",
                    "exit_code": None,
                    "stream": "stderr",
                    "chunk": "pool exhausted",
                }
            },
            "c1",
        ),
    ]


async def test_bash_generic_failure_logs_and_emits() -> None:
    emitted: list[tuple[dict, str | None]] = []

    def capture(event: dict, *, session_id: str | None = None) -> None:
        emitted.append((event, session_id))

    sbx = AsyncMock()
    acq, timer = _sandbox_context(sbx)
    with (
        patch.object(bash_tool, "acquire_sandbox", return_value=acq),
        patch.object(bash_tool, "fs_timer", return_value=timer),
        patch.object(bash_tool, "safe_emit", side_effect=capture),
        patch.object(bash_tool, "_run_foreground", side_effect=RuntimeError("boom")),
        patch.object(bash_tool, "log") as mock_log,
    ):
        out = await bash.ainvoke({"command": "pwd"}, config=CONFIG)
    assert out == "Error executing command: boom"
    run_id = emitted[0][0]["bash_data"]["id"]
    assert emitted[1] == (
        {
            "bash_data": {
                "id": run_id,
                "status": "error",
                "exit_code": None,
                "stream": "stderr",
                "chunk": "boom",
            }
        },
        "c1",
    )
    mock_log.error.assert_called_once_with(
        f"{LogTag.SANDBOX} bash tool failed", error_type="RuntimeError", exc_info=True
    )
