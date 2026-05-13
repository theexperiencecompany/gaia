"""Persistent `bash` tool — run shell commands in the user's E2B sandbox."""

from __future__ import annotations

import uuid
from typing import Annotated

from shared.py.wide_events import log
from app.agents.tools.coding._context import get_user_id, safe_emit
from app.decorators import with_doc, with_rate_limiting
from app.services.sandbox import SandboxAcquisitionError, acquire_sandbox
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
    cwd: Annotated[str, "Working directory; defaults to /workspace"] = "/workspace",
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

    safe_emit(
        {
            "bash_data": {
                "id": run_id,
                "command": command,
                "cwd": cwd,
                "status": "starting",
            }
        }
    )

    try:
        async with acquire_sandbox(user_id) as sbx:
            if background:
                return await _run_background(sbx, run_id, command, cwd)
            return await _run_foreground(sbx, run_id, command, cwd, timeout)
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
            }
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
            }
        )
        return f"Error executing command: {e}"


async def _run_foreground(
    sbx: object, run_id: str, command: str, cwd: str, timeout: int
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
            }
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
            }
        )

    result = await sbx.commands.run(  # type: ignore[attr-defined]
        command,
        cwd=cwd,
        timeout=timeout,
        on_stdout=_on_stdout,
        on_stderr=_on_stderr,
    )

    stdout = getattr(result, "stdout", "") or ""
    stderr = getattr(result, "stderr", "") or ""
    exit_code = getattr(result, "exit_code", None)

    safe_emit(
        {
            "bash_data": {
                "id": run_id,
                "status": "exited",
                "exit_code": exit_code,
            }
        }
    )

    parts: list[str] = [f"exit_code: {exit_code}"]
    if stdout:
        parts.append("stdout:\n" + truncate_head_tail(stdout))
    if stderr:
        parts.append("stderr:\n" + truncate_head_tail(stderr))
    return "\n\n".join(parts)


async def _run_background(sbx: object, run_id: str, command: str, cwd: str) -> str:
    """Detach a long-running command and return its pid + log path."""
    log_path = f"/workspace/.gaia/runs/{run_id}.log"
    wrapped = (
        f"mkdir -p /workspace/.gaia/runs && "
        f"nohup bash -c {_sh_quote(command)} > {log_path} 2>&1 & echo $!"
    )
    result = await sbx.commands.run(wrapped, cwd=cwd, timeout=10)  # type: ignore[attr-defined]
    pid = (getattr(result, "stdout", "") or "").strip()
    if not pid:
        return f"Error: failed to start background command (stderr: {getattr(result, 'stderr', '')})"
    safe_emit(
        {
            "bash_data": {
                "id": run_id,
                "status": "background_started",
                "pid": pid,
                "log_path": log_path,
            }
        }
    )
    return f"Started in background. pid={pid}, log_path={log_path}\nTail the log via bash(\"tail -f {log_path}\")"


def _sh_quote(s: str) -> str:
    """Single-quote a string for safe inclusion in a shell command."""
    return "'" + s.replace("'", "'\"'\"'") + "'"
