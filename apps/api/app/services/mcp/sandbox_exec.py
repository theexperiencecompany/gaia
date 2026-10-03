"""Run a shell command inside the caller's sandbox over the bridge.

Mirrors device_exec.run_device_command — one EXEC_OPEN, accumulate the
EXEC_STDOUT/EXEC_STDERR stream until EXEC_EXIT — plus the ownership gate:
``sandbox.user_id`` must equal the caller, checked before anything is sent.
"""

from __future__ import annotations

import asyncio
import uuid

from app.constants.device_bridge import (
    DEVICE_EXEC_MAX_OUTPUT_BYTES,
    DEVICE_EXEC_TIMEOUT_SECONDS,
    FRAME_EXEC_EXIT,
    FRAME_EXEC_OPEN,
    FRAME_EXEC_STDERR,
    FRAME_EXEC_STDOUT,
)
from app.db.redis import redis_cache
from app.services.device.bridge import POD_ID
from app.services.device.up_listener import register_up_session, unregister_up_session
from app.services.mcp.device_exec import DeviceExecError, DeviceExecResult
from app.services.sandbox.bridge_registry import (
    SandboxOwnershipError,
    check_sandbox_ownership,
    send_sandbox_down,
)

_CLOUD_EXIT_GRACE_SECONDS = 15.0


class SandboxExecError(DeviceExecError):
    """The sandbox is offline, unreachable, or owned by a different user."""


async def run_sandbox_command(
    user_id: str, sandbox_id: str, command: str, cwd: str | None = None
) -> DeviceExecResult:
    """Send command to the user's sandbox and collect its output until it exits."""
    if not redis_cache.redis:
        raise SandboxExecError("Sandbox bridge unavailable (no Redis connection)")
    try:
        await check_sandbox_ownership(sandbox_id, user_id)
    except SandboxOwnershipError as e:
        raise SandboxExecError(str(e)) from e

    sid = uuid.uuid4().hex
    inbox = register_up_session(sid)
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    collected = 0
    truncated = False

    async def _collect() -> int:
        nonlocal collected, truncated
        while True:
            frame = await inbox.get()
            frame_type = frame.get("t")
            if frame_type in (FRAME_EXEC_STDOUT, FRAME_EXEC_STDERR):
                data = frame.get("data")
                if not isinstance(data, str):
                    continue
                remaining = DEVICE_EXEC_MAX_OUTPUT_BYTES - collected
                if remaining <= 0:
                    truncated = True
                    continue
                chunk = data[:remaining]
                collected += len(chunk)
                target = stdout_parts if frame_type == FRAME_EXEC_STDOUT else stderr_parts
                target.append(chunk)
                if len(data) > remaining:
                    truncated = True
            elif frame_type == FRAME_EXEC_EXIT:
                code = frame.get("code")
                return int(code) if isinstance(code, (int, float)) else -1

    try:
        await send_sandbox_down(
            sandbox_id,
            {
                "t": FRAME_EXEC_OPEN,
                "sid": sid,
                "command": command,
                "cwd": cwd,
                "pod": POD_ID,
            },
        )
        exit_code = await asyncio.wait_for(
            _collect(), timeout=DEVICE_EXEC_TIMEOUT_SECONDS + _CLOUD_EXIT_GRACE_SECONDS
        )
    except TimeoutError as e:
        raise SandboxExecError(
            f"Command did not finish within {DEVICE_EXEC_TIMEOUT_SECONDS:.0f}s"
        ) from e
    finally:
        unregister_up_session(sid)

    return DeviceExecResult(
        exit_code=exit_code,
        stdout="".join(stdout_parts),
        stderr="".join(stderr_parts),
        truncated=truncated,
    )
