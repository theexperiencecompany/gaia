"""Cross-worker routing between agent workers and a device's WebSocket.

Only one pod holds a given device's socket. Any worker (possibly on another pod)
reaches the device by publishing to a per-device Redis channel; the owning pod
relays that frame down the socket. Frames coming back up the socket are published
by the owning pod onto a per-(device, session) channel that the waiting worker
subscribes to. This mirrors the desktop bridge's Redis-pub/sub-crosses-workers
design, generalized to a long-lived bidirectional MCP stream.
"""

from __future__ import annotations

import json
from typing import Any, Final
import uuid

from app.constants.device_bridge import (
    DEVICE_DISCONNECT_CHANNEL,
    DEVICE_DOWN_CHANNEL_PREFIX,
    DEVICE_PRESENCE_PREFIX,
    DEVICE_PRESENCE_TTL_SECONDS,
    DEVICE_REVOKE_CHANNEL,
    DEVICE_UP_POD_CHANNEL_PREFIX,
)
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from shared.py.wide_events import log

# Unique per process. Two uses: (1) stamped into a device's presence key so
# teardown can tell "I still own this device" from "it reconnected onto another
# pod" (the ownership guard DeviceConnectionManager.remove applies to the socket
# map); (2) the address of this pod's shared up-channel, so a device's owning pod
# can route reply frames to whichever pod is running the MCP session.
POD_ID: Final[str] = uuid.uuid4().hex

# Compare-and-delete: clear the presence key only if it still holds this pod's id,
# so a device that moved to another pod isn't marked offline by the old pod.
_PRESENCE_CAD_LUA: Final[str] = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) end\nreturn 0"
)


def down_channel(device_id: str) -> str:
    return f"{DEVICE_DOWN_CHANNEL_PREFIX}{device_id}"


def up_pod_channel(pod_id: str) -> str:
    return f"{DEVICE_UP_POD_CHANNEL_PREFIX}{pod_id}"


def _presence_key(device_id: str) -> str:
    return f"{DEVICE_PRESENCE_PREFIX}{device_id}"


async def mark_online(device_id: str) -> None:
    """Refresh the device's presence key (TTL heartbeat), stamped with this pod's id."""
    if not redis_cache.redis:
        return
    await redis_cache.redis.set(_presence_key(device_id), POD_ID, ex=DEVICE_PRESENCE_TTL_SECONDS)


async def mark_offline(device_id: str) -> None:
    """Clear presence only if this pod still owns it (compare-and-delete).

    Prevents a stale pod's teardown from deleting a presence key that a live
    reconnect already re-claimed on another pod.
    """
    if not redis_cache.redis:
        return
    await redis_cache.redis.eval(_PRESENCE_CAD_LUA, 1, _presence_key(device_id), POD_ID)


async def is_online(device_id: str) -> bool:
    if not redis_cache.redis:
        return False
    return bool(await redis_cache.redis.exists(_presence_key(device_id)))


async def online_device_ids(device_ids: list[str]) -> set[str]:
    online: set[str] = set()
    for device_id in device_ids:
        if await is_online(device_id):
            online.add(device_id)
    return online


async def send_down(device_id: str, frame: dict[str, Any]) -> None:
    """Publish a frame to the device's owning pod for relay down the socket."""
    if not redis_cache.redis:
        raise RuntimeError("Device bridge unavailable (no Redis connection)")
    await redis_cache.redis.publish(down_channel(device_id), json.dumps(frame))


async def publish_up_to_pod(pod_id: str, raw_frame: str) -> None:
    """Address an already-serialized upstream frame to the pod running the session.

    The frame arrives off the socket as JSON text carrying the consumer ``pod``
    id; we route it verbatim to that pod's up-channel rather than parse-and-
    re-serialize (the down leg is symmetric — see ``_down_relay``).
    """
    if not redis_cache.redis:
        return
    await redis_cache.redis.publish(up_pod_channel(pod_id), raw_frame)


async def publish_disconnect(device_id: str) -> None:
    """Fan out a socket teardown so every pod fails its in-flight sessions on the device.

    The daemon drops all its local MCP sessions when the socket closes, so a
    call still parked on a reply would otherwise hang until the tunnel's call
    timeout. Consumers usually run on other pods, and no device-to-session
    registry spans pods, so this broadcasts the device_id; each pod's up-listener
    fails the sessions it holds for that device.
    """
    if not redis_cache.redis:
        return
    await redis_cache.redis.publish(DEVICE_DISCONNECT_CHANNEL, device_id)


async def request_revoke(device_id: str) -> None:
    """Fan out a revoke so whichever pod owns the socket drops it immediately."""
    if not redis_cache.redis:
        return
    await redis_cache.redis.publish(DEVICE_REVOKE_CHANNEL, device_id)
    log.set(device={"operation": "revoke_fanout", "device_id": device_id})
    log.info(f"{LogTag.API} Device revoke fanned out")
