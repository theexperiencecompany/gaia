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
    runs_log_dir,
    session_artifacts,
    session_dir,
)
from app.decorators import with_doc, with_rate_limiting
from app.services.artifact_events import publish_artifact_event, upsert_event
from app.services.sandbox import SandboxAcquisitionError, acquire_sandbox
from app.services.storage import ArtifactInfo
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
        async with acquire_sandbox(user_id) as sbx:
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
    """Enumerate the session's `artifacts/` in the sandbox and push each
    file as a real-time artifact event (covers cat/python/mv/curl, etc.)."""
    artifacts_root = session_artifacts(session_id)
    try:
        res = await sbx.commands.run(  # type: ignore[attr-defined]
            f"find {sh_quote(artifacts_root)} -type f -printf '%P\\t%s\\n' 2>/dev/null",
            timeout=10,
        )
    except Exception:
        return
    for line in (getattr(res, "stdout", "") or "").splitlines():
        rel, _, size = line.partition("\t")
        rel = rel.strip()
        if not rel:
            continue
        try:
            size_bytes = int(size.strip() or 0)
        except ValueError:
            size_bytes = 0
        content_type = detect_content_type(rel)
        inline_body = await _read_inline_body(
            sbx, f"{artifacts_root}/{rel}", size_bytes, content_type
        )
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


async def _read_inline_body(
    sbx: object, abs_path: str, size_bytes: int, content_type: str | None
) -> str | None:
    """Return the file's UTF-8 contents iff small enough and textual.

    Sandbox files written via bash (cat/python/mv/curl) aren't in our memory,
    so we cat them back to inline the body in the artifact event — keeps the
    side-panel preview instant and lets the persisted conversation render on
    reload without a fetch. Falls back to None on any failure.
    """
    if size_bytes <= 0 or size_bytes > INLINE_ARTIFACT_MAX_BYTES:
        return None
    if not is_inlineable_content_type(content_type):
        return None
    try:
        res = await sbx.commands.run(  # type: ignore[attr-defined]
            f"base64 -w0 -- {sh_quote(abs_path)} 2>/dev/null",
            timeout=10,
        )
    except Exception:
        return None
    encoded = (getattr(res, "stdout", "") or "").strip()
    if not encoded:
        return None
    try:
        return base64.b64decode(encoded).decode("utf-8", errors="replace")
    except Exception:
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
