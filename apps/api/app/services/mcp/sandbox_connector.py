"""An mcp_use connector that speaks MCP over the sandbox bridge.

Subclasses DeviceConnector and reuses its entire framing/session pump — only
the addressing (which Redis down-channel) and the presence/ownership gate
differ. A ``sandbox://`` integration resolves to the caller's live sandbox,
so every open also proves ``sandbox.user_id == caller user_id``.
"""

from typing import Any

from app.db.redis import redis_cache
from app.services.mcp.device_connector import DeviceConnectionError, DeviceConnector
from app.services.sandbox.bridge_registry import (
    SandboxOwnershipError,
    check_sandbox_ownership,
    is_online,
    send_sandbox_down,
)


class SandboxConnectionError(DeviceConnectionError):
    """The sandbox is offline, unreachable, or owned by a different user."""


class SandboxConnector(DeviceConnector):
    """MCP connector that tunnels a session to a local server in the user's sandbox."""

    def __init__(self, sandbox_id: str, user_id: str, server_key: str) -> None:
        # device_id stays set as an alias: the shared pump never reads it
        # directly (all sends go through _send_down), but keep it truthful.
        super().__init__(device_id=sandbox_id, server_key=server_key)
        self.sandbox_id = sandbox_id
        self.user_id = user_id

    @property
    def public_identifier(self) -> str:
        return f"sandbox:{self.sandbox_id}:{self.server_key}"

    async def _check_online(self) -> None:
        if not redis_cache.redis:
            raise SandboxConnectionError("Sandbox bridge unavailable (no Redis connection)")
        if not await is_online(self.sandbox_id):
            raise SandboxConnectionError(
                "Your sandbox is offline. Re-run the task so a fresh sandbox is acquired."
            )
        try:
            await check_sandbox_ownership(self.sandbox_id, self.user_id)
        except SandboxOwnershipError as e:
            raise SandboxConnectionError(str(e)) from e

    async def _send_down(self, frame: dict[str, Any]) -> None:
        await send_sandbox_down(self.sandbox_id, frame)
