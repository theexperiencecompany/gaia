"""Persistent `bash` tool — run shell commands in the user's E2B sandbox."""

from __future__ import annotations

import base64
import contextlib
import time
import uuid
from typing import Annotated

from shared.py.wide_events import log
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
from app.decorators import with_doc, with_rate_limiting
from app.services.artifact_events import publish_artifact_event, upsert_event
from app.services.sandbox import SandboxAcquisitionError, acquire_sandbox
from app.services.storage import FS_OPS, ArtifactInfo, fs_timer
from app.templates.docstrings.coding_tools_docs import BASH_TOOL
from app.utils.output_limiter import truncate_head_tail
from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import tool

MAX_TIMEOUT_SECONDS = 600
DEFAULT_TIMEOUT_SECONDS = 120
MAX_COMMAND_LENGTH = 16_000


@tool
@with_rate_limiting("bash_execution")
@with_doc(BASH_TOOL)
async def bash(
    config: RunnableConfig,
    command: Annotated[str, "Shell command to run inside /workspace"],
    cwd: Annotated[str, "Working directory; defaults to the session scratch dir"] = "",
    timeout: Annotated[int, "Seconds before kill (max 600)"] = DEFAULT_TIMEOUT_SECONDS,
    background: Annotated[bool, "Run detached; returns pid + log path"] = False,
) -> str:
    """Run a shell command in the user's persistent coding sandbox."""

    log.set(tool={"name": "bash", "action": "execute"})

    if not command or not command.strip():
        return "Error: command cannot be empty"
    if len(command) > MAX_COMMAND_LENGTH:
        return f"Error: command exceeds {MAX_COMMAND_LENGTH} characters"

    timeout = max(1, min(timeout, MAX_TIMEOUT_SECONDS))
    run_id = uuid.uuid4().hex[:12]

    try:
        user_id = get_user_id(config)
    except ValueError as e:
        return f"Error: {e}"

    session_id = get_session_id(config)
    use_session_cwd = bool(session_id) and (not cwd or cwd == WORKSPACE_ROOT)
    if use_session_cwd and session_id:
        cwd = session_dir(session_id)
    elif cwd:
        # LLM-supplied cwd must stay under /workspace. Without this gate the
        # agent could `cd /etc/gaia` (or anywhere else inside the sandbox)
        # and read host-internal config files that have no business being in
        # the agent's reach. Same-user sandbox so it's not a cross-user
        # issue, but it makes prompt-injection drift much harder to bound.
        if not is_under_workspace(cwd):
            return (
                f"Error: cwd must be under {WORKSPACE_ROOT} "
                f"(got {cwd!r})"
            )

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
        async with fs_timer(FS_OPS.TOOL_BASH), acquire_sandbox(user_id) as sbx:
            if use_session_cwd:
                # Session scratch is created host-side at chat start, but
                # silent/background runs may reach here first — make it cheap
                # and idempotent rather than failing on a missing cwd.
                with contextlib.suppress(Exception):
                    await sbx.commands.run(f"mkdir -p {sh_quote(cwd)}", timeout=10)
            if background:
                return await _run_background(sbx, run_id, command, cwd, session_id)
            result = await _run_foreground(
                sbx, run_id, command, cwd, timeout, session_id
            )
            # A bash command can create artifacts any number of ways (cat,
            # python, mv, curl -o, …), not just the write tool. Enumerate the
            # session's artifacts/ from the sandbox itself (it sees its
            # own writes instantly — no host-mount/cross-mount race) and push
            # them in real time; the chat forwarder relays them as SSE during
            # this turn. De-duped downstream by (session_id, path).
            if session_id:
                async with fs_timer(FS_OPS.TOOL_BASH_PUBLISH):
                    await _publish_artifacts(sbx, user_id, session_id)
            return result
    except SandboxAcquisitionError as e:
        safe_emit(
            {
                "bash_data": {
                    "id": run_id,
                    "status": "error",
                    "exit_code": None,
                    "stream": "stderr",
                    "chunk": str(e),
                }
            },
            session_id=session_id,
        )
        return f"Error: sandbox unavailable — {e}"
    except Exception as e:
        log.error(f"bash tool failed: {e}", exc_info=True)
        safe_emit(
            {
                "bash_data": {
                    "id": run_id,
                    "status": "error",
                    "exit_code": None,
                    "stream": "stderr",
                    "chunk": str(e),
                }
            },
            session_id=session_id,
        )
        return f"Error executing command: {e}"


async def _publish_artifacts(sbx: object, user_id: str, session_id: str) -> None:
    """Enumerate the session's ``artifacts/`` in the sandbox and push each
    file as a real-time artifact event (covers cat/python/mv/curl, etc.).

    Implementation note: this used to be N+1 sandbox round-trips (one ``find``
    plus one ``base64`` per artifact). For a turn that writes 5 artifacts that
    was 6 envd round-trips. We now collapse to a *single* ``find`` invocation
    whose ``-exec`` emits the path, size, and base64 body for every artifact in
    one stream — parsed back here in Python. One round-trip total, regardless
    of how many artifacts the turn produced.
    """
    artifacts_root = session_artifacts(session_id)
    # NUL-delimited fields AND records. Filenames cannot contain NUL bytes on
    # Linux, so this delimitation is desync-proof even when the agent creates
    # artifacts whose names contain tabs or newlines. Each artifact emits
    # exactly three NUL-terminated fields: <path>\0<size>\0<base64-body>\0.
    # The body is only emitted when small + inlineable; content-type sniff
    # happens host-side after.
    max_inline = INLINE_ARTIFACT_MAX_BYTES
    enumerate_cmd = (
        f"find {sh_quote(artifacts_root)} -type f "
        f"! -name '*.gaia-tmp' "
        f"-printf '%P\\0%s\\0' "
        f"-exec sh -c '"
        f'  s=$(stat -c%s "$0"); '
        f'  if [ "$s" -le {max_inline} ]; then base64 -w0 "$0" 2>/dev/null; fi; '
        f'  printf "\\0"'
        f"' {{}} \\; 2>/dev/null"
    )
    try:
        res = await sbx.commands.run(enumerate_cmd, timeout=15)  # type: ignore[attr-defined]
    except Exception:
        return

    stdout = getattr(res, "stdout", "") or ""
    fields = stdout.split("\0")
    # Last element after the trailing NUL is the empty tail — discard. Group
    # the remainder in 3-tuples (path, size, body); a partial trailing group
    # means find was interrupted mid-record and we skip it.
    for i in range(0, len(fields) - (len(fields) % 3), 3):
        rel = fields[i]
        size_str = fields[i + 1]
        body_b64 = fields[i + 2]
        if not rel:
            continue
        try:
            size_bytes = int(size_str) if size_str else 0
        except ValueError:
            size_bytes = 0
        content_type = detect_content_type(rel)
        inline_body = _decode_inline(body_b64, size_bytes, content_type)
        with contextlib.suppress(Exception):
            await publish_artifact_event(
                user_id,
                upsert_event(
                    session_id,
                    ArtifactInfo(
                        path=rel,
                        size_bytes=size_bytes,
                        mtime=time.time(),
                        content_type=content_type,
                    ),
                    body=inline_body,
                ),
            )




def _decode_inline(
    body_b64: str, size_bytes: int, content_type: str | None
) -> str | None:
    """Decode the inline body if the file is small + textual, else None."""
    if not body_b64:
        return None
    if size_bytes <= 0 or size_bytes > INLINE_ARTIFACT_MAX_BYTES:
        return None
    if not is_inlineable_content_type(content_type):
        return None
    try:
        return base64.b64decode(body_b64).decode("utf-8", errors="replace")
    except (ValueError, UnicodeDecodeError):
        return None


async def _persist_run_log(sbx: object, run_id: str, stdout: str, stderr: str) -> None:
    """Write the full foreground output to /workspace/.gaia/runs/{run_id}.log.

    The bash docstring promises this; it lets the agent re-read output that
    was truncated in the tool return value.
    """
    log_path = f"{runs_log_dir()}/{run_id}.log"
    body = stdout + "\n---STDERR---\n" + stderr
    payload = base64.b64encode(body.encode("utf-8")).decode("ascii")
    with contextlib.suppress(Exception):
        await sbx.commands.run(  # type: ignore[attr-defined]
            f"mkdir -p {sh_quote(runs_log_dir())} && "
            f"printf %s {sh_quote(payload)} | base64 -d > {sh_quote(log_path)}",
            timeout=10,
        )


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

    result = await sbx.commands.run(  # type: ignore[attr-defined]
        command,
        cwd=cwd or WORKSPACE_ROOT,
        timeout=timeout,
        on_stdout=_on_stdout,
        on_stderr=_on_stderr,
    )

    stdout = getattr(result, "stdout", "") or ""
    stderr = getattr(result, "stderr", "") or ""
    exit_code = getattr(result, "exit_code", None)

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
    result = await sbx.commands.run(  # type: ignore[attr-defined]
        wrapped, cwd=cwd or WORKSPACE_ROOT, timeout=10
    )
    pid = (getattr(result, "stdout", "") or "").strip()
    if not pid:
        return (
            "Error: failed to start background command "
            f"(stderr: {getattr(result, 'stderr', '')})"
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
