"""Persistent bash tool — run shell commands in the user's E2B sandbox."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import posixpath
import time
from typing import Annotated
import uuid

from e2b import CommandExitException, TimeoutException
from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import tool
from prometheus_client import Counter

from app.agents.tools.coding._artifacts import publish_artifact
from app.agents.tools.coding._context import (
    get_session_id,
    get_user_id,
    safe_emit,
    sh_quote,
)
from app.agents.workspace.paths import (
    INLINE_ARTIFACT_MAX_BYTES,
    WORKSPACE_ROOT,
    detect_content_type,
    is_inlineable_content_type,
    is_under_workspace,
    runs_log_dir,
    session_artifacts,
    session_dir,
)
from app.constants.log_tags import LogTag
from app.constants.sandbox import (
    BASH_DEFAULT_TIMEOUT_SECONDS,
    BASH_MAX_COMMAND_LENGTH,
    BASH_MAX_TIMEOUT_SECONDS,
    WORKSPACE_TMP_SUFFIX,
)
from app.decorators import with_doc, with_rate_limiting
from app.services.sandbox import (
    SandboxAcquisitionError,
    acquire_sandbox,
)
from app.services.storage import FsOps, fs_timer
from app.services.storage.metrics import _register_once
from app.templates.docstrings.coding_tools_docs import BASH_TOOL
from app.utils.output_limiter import truncate_head_tail
from shared.py.wide_events import log

MAX_TIMEOUT_SECONDS = 600
DEFAULT_TIMEOUT_SECONDS = 120
MAX_COMMAND_LENGTH = 16_000

# Bucketed bash exit code counter (fs-metrics-coverage contract). Mirrors
# shell semantics: 0=success, 1-126=generic failure, 127=not found,
# 128-254=killed by signal, 255=catch-all, "timeout"=our deadline.
_BASH_EXIT_CODE_TOTAL = _register_once(
    "tool_bash_exit_code_total",
    lambda: Counter(
        name="tool_bash_exit_code_total",
        documentation="Bucketed bash tool exit codes",
        labelnames=("exit_code",),
    ),
)


def _bucket_exit_code(code: int | None, timed_out: bool) -> str:
    """Map a raw exit code (or timeout flag) to the bucket label string."""
    if timed_out:
        return "timeout"
    if code is None:
        # Treat unknown as catch-all rather than skipping — the agent saw
        # *some* outcome, we just couldn't read the exit code attribute.
        return "255"
    if code == 0:
        return "0"
    if code == 127:
        return "127"
    if code == 255:
        return "255"
    if 1 <= code <= 126:
        return "1-126"
    if 128 <= code <= 254:
        return "128-254"
    return "255"


def _record_bash_exit_code(code: int | None, *, timed_out: bool) -> None:
    """Increment the exit-code counter once per command completion. Non-fatal."""
    try:
        _BASH_EXIT_CODE_TOTAL.labels(exit_code=_bucket_exit_code(code, timed_out=timed_out)).inc()
    except Exception as e:
        log.warning(
            "[metrics] bash exit_code inc failed",
            error_type=type(e).__name__,
        )


def _emit_bash_error(run_id: str, chunk: str, return_message: str, session_id: str | None) -> str:
    """Emit a terminal error event for a bash run and return the error string."""
    safe_emit(
        {
            "bash_data": {
                "id": run_id,
                "status": "error",
                "exit_code": None,
                "stream": "stderr",
                "chunk": chunk,
            }
        },
        session_id=session_id,
    )
    return return_message


def _resolve_cwd(cwd: str, session_id: str | None) -> tuple[str, str | None]:
    """Resolve the working directory for a bash run.

    Returns (cwd, error). error is non-None when the LLM-supplied cwd
    escapes the workspace, in which case the caller returns it. Any non-empty
    resolved cwd is guaranteed to be inside the workspace.
    """
    if session_id and (not cwd or cwd == WORKSPACE_ROOT):
        return session_dir(session_id), None
    if cwd:
        # A relative cwd joins to the session dir (or /workspace), mirroring
        # canonical_path, so `cwd="scratch"` means the session's scratch.
        if not cwd.startswith("/"):
            base = session_dir(session_id) if session_id else WORKSPACE_ROOT
            cwd = posixpath.join(base, cwd)
        # Normalize BEFORE the containment check — otherwise `/workspace/../etc`
        # starts with `/workspace/`, slips past, and the shell resolves the
        # `..` to escape — a gate against reaching host config (`/etc/gaia`).
        normalized = posixpath.normpath(cwd)
        if not is_under_workspace(normalized):
            return cwd, f"Error: cwd must be under {WORKSPACE_ROOT}"
        return normalized, None
    return cwd, None


@tool
@with_rate_limiting("bash_execution")
@with_doc(BASH_TOOL)
async def bash(
    config: RunnableConfig,
    command: Annotated[str, "Shell command to run inside /workspace"],
    cwd: Annotated[
        str,
        "Working directory; defaults to your session root (holds artifacts/, scratch/, user-uploaded/)",
    ] = "",
    # Agent-facing tool parameter: the e2b server-side command deadline (see
    # _run_foreground). A local asyncio.timeout context manager can't replace it
    # — it would cancel our coroutine without killing the remote command.
    timeout: Annotated[
        int, "Seconds before kill"
    ] = BASH_DEFAULT_TIMEOUT_SECONDS,  # NOSONAR python:S7483
    background: Annotated[bool, "Run detached; returns pid + log path"] = False,
) -> str:
    """Run a shell command in the user's persistent coding sandbox."""

    log.set(tool={"name": "bash", "action": "execute"})

    if not command or not command.strip():
        return "Error: command cannot be empty"
    if len(command) > BASH_MAX_COMMAND_LENGTH:
        return f"Error: command exceeds {BASH_MAX_COMMAND_LENGTH} characters"

    timeout = max(1, min(timeout, BASH_MAX_TIMEOUT_SECONDS))
    run_id = uuid.uuid4().hex[:12]

    try:
        user_id = get_user_id(config)
    except ValueError as e:
        return f"Error: {e}"

    session_id = get_session_id(config)
    cwd, cwd_error = _resolve_cwd(cwd, session_id)
    if cwd_error:
        return cwd_error

    safe_emit(
        {
            "bash_data": {
                "id": run_id,
                "command": command,
                "cwd": cwd or WORKSPACE_ROOT,
                "status": "starting",
            }
        },
        session_id=session_id,
    )

    try:
        async with fs_timer(FsOps.TOOL_BASH), acquire_sandbox(user_id) as sbx:
            if cwd:
                # Session dirs are created on demand, so a resolved cwd may
                # not exist yet. `make_dir` creates parents and no-ops if it
                # already exists.
                with contextlib.suppress(Exception):
                    await sbx.files.make_dir(cwd)
            if background:
                return await _run_background(sbx, run_id, command, cwd, session_id)
            result = await _run_foreground(sbx, run_id, command, cwd, timeout, session_id)
            # A bash command can create artifacts many ways (cat, python, mv,
            # curl -o, …), not just the write tool. Enumerate the session's
            # artifacts/ from the sandbox itself and push in real time.
            if session_id:
                async with fs_timer(FsOps.TOOL_BASH_PUBLISH):
                    await _publish_artifacts(sbx, user_id, session_id)
            return result
    except SandboxAcquisitionError as e:
        return _emit_bash_error(run_id, str(e), f"Error: sandbox unavailable ({e})", session_id)
    except Exception as e:
        # acquire_sandbox already evicted the sandbox if it died; surface it.
        log.error(f"{LogTag.SANDBOX} bash tool failed", error_type=type(e).__name__, exc_info=True)
        return _emit_bash_error(run_id, str(e), f"Error executing command: {e}", session_id)


async def _publish_artifacts(sbx: object, user_id: str, session_id: str) -> None:
    """Enumerate the session's artifacts/ in the sandbox and push each file as a real-time event.

    Used to be N+1 sandbox round-trips (one find plus one base64 per
    artifact, 6 for a 5-artifact turn); now a single find -exec streams
    path/size/base64 for every artifact in one round-trip.
    """
    artifacts_root = session_artifacts(session_id)
    # NUL-delimited fields AND records (desync-proof, filenames can't contain
    # NUL). Each artifact emits <path>\0<size>\0<mtime>\0<base64>\0. Real
    # mtime is required so the forwarder's dedup skips unchanged files.
    max_inline = INLINE_ARTIFACT_MAX_BYTES
    enumerate_cmd = (
        f"find {sh_quote(artifacts_root)} -type f "
        f"! -name '*{WORKSPACE_TMP_SUFFIX}' "
        f"-printf '%P\\0%s\\0%T@\\0' "
        f"-exec sh -c '"
        f'  s=$(stat -c%s "$0"); '
        f'  if [ "$s" -le {max_inline} ]; then base64 -w0 "$0" 2>/dev/null; fi; '
        f'  printf "\\0"'
        f"' {{}} \\; 2>/dev/null"
    )
    try:
        res = await sbx.commands.run(enumerate_cmd, timeout=15)  # type: ignore[attr-defined]  # e2b sandbox SDK ships no type stubs
    except Exception:
        return

    stdout = getattr(res, "stdout", "") or ""
    fields = stdout.split("\0")
    # Last element after the trailing NUL is the empty tail — discard. Group
    # the remainder in 4-tuples (path, size, mtime, body); a partial trailing
    # group means find was interrupted mid-record and we skip it.
    for i in range(0, len(fields) - (len(fields) % 4), 4):
        rel = fields[i]
        size_str = fields[i + 1]
        mtime_str = fields[i + 2]
        body_b64 = fields[i + 3]
        if not rel:
            continue
        try:
            size_bytes = int(size_str) if size_str else 0
        except ValueError:
            size_bytes = 0
        try:
            mtime = float(mtime_str) if mtime_str else time.time()
        except ValueError:
            mtime = time.time()
        inline_body = _decode_inline(body_b64, size_bytes, detect_content_type(rel))
        # Same shared publisher write/edit use — one owner of the event shape.
        await publish_artifact(user_id, session_id, rel, size_bytes, mtime, inline_body)


def _decode_inline(body_b64: str, size_bytes: int, content_type: str | None) -> str | None:
    """Decode the inline body if the file is small + textual, else None."""
    if not body_b64:
        return None
    if size_bytes <= 0 or size_bytes > INLINE_ARTIFACT_MAX_BYTES:
        return None
    if not is_inlineable_content_type(content_type):
        return None
    try:
        return base64.b64decode(body_b64).decode("utf-8", errors="replace")
    except ValueError:
        return None


async def _persist_run_log(sbx: object, run_id: str, stdout: str, stderr: str) -> None:
    """Write the full foreground output to /workspace/.gaia/runs/{run_id}.log.

    The bash docstring promises this; it lets the agent re-read output that
    was truncated in the tool return value.
    """
    log_path = f"{runs_log_dir()}/{run_id}.log"
    body = stdout + "\n---STDERR---\n" + stderr
    # Native write auto-creates the runs/ parent and takes the body as data —
    # no base64 round-trip, no shell.
    with contextlib.suppress(Exception):
        await sbx.files.write(log_path, body)  # type: ignore[attr-defined]  # e2b sandbox SDK ships no type stubs


async def _run_foreground(
    sbx: object,
    run_id: str,
    command: str,
    cwd: str,
    timeout: int,
    session_id: str | None,
) -> str:
    """Run a command synchronously and stream stdout/stderr chunks."""

    def _on_stdout(chunk: str) -> None:
        safe_emit(
            {
                "bash_data": {
                    "id": run_id,
                    "status": "running",
                    "stream": "stdout",
                    "chunk": chunk,
                }
            },
            session_id=session_id,
        )

    def _on_stderr(chunk: str) -> None:
        safe_emit(
            {
                "bash_data": {
                    "id": run_id,
                    "status": "running",
                    "stream": "stderr",
                    "chunk": chunk,
                }
            },
            session_id=session_id,
        )

    try:
        # `timeout` is the e2b server-side deadline; a local asyncio.timeout
        # would only cancel our coroutine, not the remote command.
        result = await sbx.commands.run(  # type: ignore[attr-defined]  # e2b SDK ships no stubs  # NOSONAR python:S7483
            command,
            cwd=cwd or WORKSPACE_ROOT,
            on_stdout=_on_stdout,
            on_stderr=_on_stderr,
            timeout=timeout,
        )
        exit_code = getattr(result, "exit_code", None)
        stdout = getattr(result, "stdout", "") or ""
        stderr = getattr(result, "stderr", "") or ""
    except CommandExitException as e:
        # A non-zero exit (grep no-match, failing test, linter) is a normal
        # command outcome, not a tool failure — the SDK raises instead of
        # returning, so translate it back into a result we report normally.
        exit_code, stdout, stderr = e.exit_code, e.stdout or "", e.stderr or ""
    except (TimeoutException, TimeoutError, asyncio.CancelledError):
        _record_bash_exit_code(None, timed_out=True)
        raise
    except Exception:
        _record_bash_exit_code(None, timed_out=False)
        raise

    _record_bash_exit_code(exit_code, timed_out=False)

    await _persist_run_log(sbx, run_id, stdout, stderr)

    safe_emit(
        {
            "bash_data": {
                "id": run_id,
                "status": "exited",
                "exit_code": exit_code,
            }
        },
        session_id=session_id,
    )

    parts: list[str] = [f"exit_code: {exit_code}"]
    if stdout:
        parts.append("stdout:\n" + truncate_head_tail(stdout))
    if stderr:
        parts.append("stderr:\n" + truncate_head_tail(stderr))
    return "\n\n".join(parts)


async def _run_background(
    sbx: object,
    run_id: str,
    command: str,
    cwd: str,
    session_id: str | None,
) -> str:
    """Detach a long-running command and return its pid + log path."""
    log_path = f"{runs_log_dir()}/{run_id}.log"
    wrapped = (
        f"mkdir -p {sh_quote(runs_log_dir())} && "
        f"nohup bash -c {sh_quote(command)} > {sh_quote(log_path)} 2>&1 "
        "& echo $!"
    )
    result = await sbx.commands.run(  # type: ignore[attr-defined]  # e2b sandbox SDK ships no type stubs
        wrapped, cwd=cwd or WORKSPACE_ROOT, timeout=10
    )
    pid = (getattr(result, "stdout", "") or "").strip()
    if not pid:
        return (
            f"Error: failed to start background command (stderr: {getattr(result, 'stderr', '')})"
        )
    safe_emit(
        {
            "bash_data": {
                "id": run_id,
                "status": "background_started",
                "pid": pid,
                "log_path": log_path,
            }
        },
        session_id=session_id,
    )
    return (
        f"Started in background. pid={pid}, log_path={log_path}\n"
        f'Tail the log via bash("tail -f {log_path}")'
    )
