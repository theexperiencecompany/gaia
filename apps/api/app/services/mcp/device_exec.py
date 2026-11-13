"""Run a shell command on a paired device over the bridge (run_on_device).

Mirrors DeviceConnector's transport — send_down plus the shared per-pod
up-listener inbox keyed on the session id — but for the exec frame pair instead
of MCP: send one EXEC_OPEN and accumulate the EXEC_STDOUT/EXEC_STDERR stream
until EXEC_EXIT, bounded by a wall-clock timeout. The daemon runs the command
as the user; this side only relays and collects.
"""

from __future__ import annotations

import asyncio
import uuid

from pydantic import BaseModel

from app.constants.device_bridge import (
    DEVICE_EXEC_MAX_OUTPUT_BYTES,
    DEVICE_EXEC_TIMEOUT_SECONDS,
    FRAME_EXEC_EXIT,
    FRAME_EXEC_OPEN,
    FRAME_EXEC_STDERR,
    FRAME_EXEC_STDOUT,
)
from app.db.redis import redis_cache
from app.services.device.bridge import POD_ID, is_online, send_down
from app.services.device.up_listener import register_up_session, unregister_up_session

# The device kills the process at DEVICE_EXEC_TIMEOUT_SECONDS and sends EXEC_EXIT;
# wait a little longer here so that terminal frame wins over our own timeout.
_CLOUD_EXIT_GRACE_SECONDS = 15.0


class DeviceExecError(RuntimeError):
    """The device is offline or the command could not be dispatched."""


class DeviceExecResult(BaseModel):
    exit_code: int
    stdout: str
    stderr: str
    truncated: bool


async def run_device_command(
    device_id: str, command: str, cwd: str | None = None
) -> DeviceExecResult:
    """Send command to the device and collect its output until it exits."""
    if not redis_cache.redis:
        raise DeviceExecError("Device bridge unavailable (no Redis connection)")
    if not await is_online(device_id):
        raise DeviceExecError(
            "Your device is offline. Run `gaia bridge up` on that machine and try again."
        )

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
        await send_down(
            device_id,
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
        raise DeviceExecError(
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
