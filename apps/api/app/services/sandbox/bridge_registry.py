"""Server-side registry for sandbox bridge sessions.

Tracks which sandboxes hold a live /ws/sandbox socket (Redis presence, like
the device bridge) and who owns each one, so every mcp.open/exec.open can
gate on ``sandbox.user_id == caller user_id``. Also owns the per-pod socket
table and the downstream publish helper.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar, Final, cast

from fastapi import WebSocket

from app.constants.log_tags import LogTag
from app.constants.sandbox import (
    SANDBOX_DOWN_CHANNEL_PREFIX,
    SANDBOX_OWNER_PREFIX,
    SANDBOX_PRESENCE_PREFIX,
    SANDBOX_PRESENCE_TTL_SECONDS,
)
from app.db.redis import redis_cache
from shared.py.wide_events import log

# Compare-and-delete: clear a key only if it still holds the expected value,
# so a stale pod's teardown can't wipe a live reconnect's re-claimed key.
# Same shape as the device bridge's presence guard.
_CAD_LUA: Final[str] = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) end\nreturn 0"
)


class SandboxOwnershipError(RuntimeError):
    """The sandbox is offline or owned by a different user."""


def sandbox_down_channel(sandbox_id: str) -> str:
    return f"{SANDBOX_DOWN_CHANNEL_PREFIX}{sandbox_id}"


def _presence_key(sandbox_id: str) -> str:
    return f"{SANDBOX_PRESENCE_PREFIX}{sandbox_id}"


def _owner_key(user_id: str) -> str:
    return f"{SANDBOX_OWNER_PREFIX}{user_id}"


def _decode(value: str | bytes | None) -> str | None:
    if value is None:
        return None
    return value.decode("utf-8") if isinstance(value, bytes) else value


async def mark_online(sandbox_id: str, user_id: str) -> None:
    """Claim presence for the sandbox, stamped with its owning user."""
    if not redis_cache.redis:
        return
    await redis_cache.redis.set(_presence_key(sandbox_id), user_id, ex=SANDBOX_PRESENCE_TTL_SECONDS)
    await redis_cache.redis.set(_owner_key(user_id), sandbox_id, ex=SANDBOX_PRESENCE_TTL_SECONDS)


async def mark_offline(sandbox_id: str, user_id: str) -> None:
    """Clear presence only if this socket still owns it (compare-and-delete)."""
    if not redis_cache.redis:
        return
    await redis_cache.redis.eval(_CAD_LUA, 1, _presence_key(sandbox_id), user_id)
    await redis_cache.redis.eval(_CAD_LUA, 1, _owner_key(user_id), sandbox_id)


async def is_online(sandbox_id: str) -> bool:
    if not redis_cache.redis:
        return False
    return bool(await redis_cache.redis.exists(_presence_key(sandbox_id)))


async def get_sandbox_owner(sandbox_id: str) -> str | None:
    """Return the user_id owning the live socket, or None if offline."""
    if not redis_cache.redis:
        return None
    return _decode(await redis_cache.redis.get(_presence_key(sandbox_id)))


async def get_online_sandbox_id(user_id: str) -> str | None:
    """Return the user's live sandbox_id, or None if its bridge is offline."""
    if not redis_cache.redis:
        return None
    return _decode(await redis_cache.redis.get(_owner_key(user_id)))


async def check_sandbox_ownership(sandbox_id: str, user_id: str) -> None:
    """Raise unless sandbox_id is online and owned by user_id.

    Checked on every mcp.open/exec.open, mirroring the device tunnel's hard
    gate — a leaked or stale id can't cross the user boundary.
    """
    owner = await get_sandbox_owner(sandbox_id)
    if owner is None:
        raise SandboxOwnershipError(f"Sandbox {sandbox_id} is offline")
    if owner != user_id:
        raise SandboxOwnershipError(
            f"Sandbox {sandbox_id} is not an active sandbox owned by user {user_id}"
        )


async def send_sandbox_down(sandbox_id: str, frame: dict[str, Any]) -> None:
    """Publish a frame to the sandbox's owning pod for relay down the socket."""
    if not redis_cache.redis:
        raise RuntimeError("Sandbox bridge unavailable (no Redis connection)")
    await redis_cache.redis.publish(sandbox_down_channel(sandbox_id), json.dumps(frame))


class SandboxConnectionManager:
    """Singleton tracking sandbox sockets held by *this* pod.

    Cross-pod delivery is Redis pub/sub; this only maps a sandbox_id to the
    local socket so the down-relay task can write to it.
    """

    _instance: ClassVar[Any] = None

    def __new__(cls) -> SandboxConnectionManager:
        if cls._instance is None:
            instance = super().__new__(cls)
            instance._connections = {}
            cls._instance = instance
        return cast("SandboxConnectionManager", cls._instance)

    def __init__(self) -> None:
        self._connections: dict[str, WebSocket]

    def add(self, sandbox_id: str, websocket: WebSocket) -> None:
        self._connections[sandbox_id] = websocket
        log.info(f"{LogTag.API} Sandbox socket registered", sandbox_id=sandbox_id)

    def remove(self, sandbox_id: str, websocket: WebSocket) -> None:
        # Only drop if the stored socket is the one closing — a fast re-dial
        # must not evict the live socket.
        if self._connections.get(sandbox_id) is websocket:
            del self._connections[sandbox_id]
            log.info(f"{LogTag.API} Sandbox socket unregistered", sandbox_id=sandbox_id)

    def get(self, sandbox_id: str) -> WebSocket | None:
        return self._connections.get(sandbox_id)

    def owns(self, sandbox_id: str) -> bool:
        return sandbox_id in self._connections


sandbox_connection_manager = SandboxConnectionManager()
