"""Request/response bridge between agent tools and the desktop app.

A tool running mid-graph publishes a ``desktop_tool_request`` frame onto the
conversation's SSE stream. The Electron renderer that owns that stream executes
the action via IPC and POSTs the result to ``/desktop/tool-result``, which
relays it over a per-request Redis channel back to the awaiting tool. Redis
pub/sub crosses uvicorn workers the same way ``stream:channel:`` does, so the
awaiting tool and the HTTP process receiving the result never need to share a
process.
"""

import asyncio
from dataclasses import dataclass
import json
from typing import Any
from uuid import uuid4

from app.constants.cache import (
    DESKTOP_REQUEST_PREFIX,
    DESKTOP_REQUEST_TTL,
    DESKTOP_RESULT_CHANNEL_PREFIX,
)
from app.core.stream_manager import stream_manager
from app.db.redis import redis_cache
from shared.py.wide_events import log

DESKTOP_TOOL_TIMEOUT_SECONDS = 30.0
_PUBSUB_POLL_SECONDS = 1.0

ERROR_TIMEOUT = (
    "The desktop app did not respond in time — it may be closed. "
    "Ask the user to make sure the GAIA desktop app is open."
)
ERROR_REDIS_UNAVAILABLE = "Desktop bridge unavailable (no Redis connection)."


@dataclass
class DesktopToolOutcome:
    """Result of a desktop-executed action, as reported by the Electron app."""

    ok: bool
    data: dict[str, Any] | None = None
    error: str | None = None


async def request_desktop_action(
    *,
    stream_id: str,
    user_id: str,
    tool: str,
    params: dict[str, Any] | None = None,
    timeout: float = DESKTOP_TOOL_TIMEOUT_SECONDS,
) -> DesktopToolOutcome:
    """Execute one action on the user's desktop and await its result.

    Publishes the request onto the chat SSE stream and blocks (up to
    ``timeout``) on the per-request Redis result channel.
    """
    if not redis_cache.redis:
        log.error("Desktop bridge: Redis unavailable")
        return DesktopToolOutcome(ok=False, error=ERROR_REDIS_UNAVAILABLE)

    request_id = str(uuid4())
    request_key = f"{DESKTOP_REQUEST_PREFIX}{request_id}"
    result_channel = f"{DESKTOP_RESULT_CHANNEL_PREFIX}{request_id}"

    log.set(
        desktop_tool={
            "request_id": request_id,
            "tool": tool,
            "stream_id": stream_id,
        }
    )

    await redis_cache.set(
        request_key,
        {"user_id": user_id, "stream_id": stream_id, "tool": tool},
        ttl=DESKTOP_REQUEST_TTL,
    )

    pubsub = redis_cache.redis.pubsub()
    try:
        # Subscribe before publishing the request so a fast desktop reply
        # can never slip between publish and subscribe.
        await pubsub.subscribe(result_channel)

        frame = {
            "desktop_tool_request": {
                "request_id": request_id,
                "tool": tool,
                "params": params or {},
                "timeout_ms": int(timeout * 1000),
            }
        }
        await stream_manager.publish_chunk(stream_id, f"data: {json.dumps(frame)}\n\n")

        try:
            async with asyncio.timeout(timeout):
                outcome = await _await_result(pubsub)
        except TimeoutError:
            log.warning(f"Desktop tool '{tool}' timed out after {timeout}s")
            return DesktopToolOutcome(ok=False, error=ERROR_TIMEOUT)

        return outcome
    finally:
        await redis_cache.delete(request_key)
        try:
            await pubsub.unsubscribe(result_channel)
            await pubsub.aclose()
        except Exception:  # nosec B110 - cleanup must not mask the outcome
            pass


async def _await_result(pubsub: Any) -> DesktopToolOutcome:
    """Block on the result channel until a parseable outcome arrives."""
    while True:
        message = await pubsub.get_message(
            ignore_subscribe_messages=True,
            timeout=_PUBSUB_POLL_SECONDS,
        )
        if message is None or message["type"] != "message":
            continue

        raw = message["data"]
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("Desktop bridge: discarding malformed result payload")
            continue

        return DesktopToolOutcome(
            ok=bool(payload.get("ok")),
            data=payload.get("data"),
            error=payload.get("error"),
        )


async def publish_desktop_result(
    request_id: str,
    *,
    ok: bool,
    data: dict[str, Any] | None,
    error: str | None,
) -> None:
    """Relay a result POSTed by the desktop app to the awaiting tool."""
    if not redis_cache.redis:
        log.error("Desktop bridge: Redis unavailable, dropping result")
        return
    await redis_cache.redis.publish(
        f"{DESKTOP_RESULT_CHANNEL_PREFIX}{request_id}",
        json.dumps({"ok": ok, "data": data, "error": error}),
    )
