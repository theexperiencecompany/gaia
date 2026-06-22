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
from http import HTTPStatus
import json
from typing import Any
from uuid import uuid4

from app.constants.cache import (
    DESKTOP_REQUEST_PREFIX,
    DESKTOP_REQUEST_TTL_GRACE_SECONDS,
    DESKTOP_RESULT_CHANNEL_PREFIX,
)
from app.constants.log_tags import LogTag
from app.core.stream_manager import stream_manager
from app.db.redis import redis_cache
from app.utils.errors import AppError
from shared.py.wide_events import log

DESKTOP_TOOL_TIMEOUT_SECONDS = 30.0
_PUBSUB_POLL_SECONDS = 1.0

ERROR_TIMEOUT = (
    "The desktop app did not respond in time — it may be closed. "
    "Ask the user to make sure the GAIA desktop app is open."
)
ERROR_REDIS_UNAVAILABLE = "Desktop bridge unavailable (no Redis connection)."


class DesktopRequestNotFound(AppError):
    """The pending request key is gone — expired or already resolved."""

    def __init__(self) -> None:
        super().__init__(
            message="Desktop tool request expired or already resolved",
            status_code=HTTPStatus.GONE,
        )


class DesktopRequestForbidden(AppError):
    """A result was POSTed by a user who does not own the pending request."""

    def __init__(self) -> None:
        super().__init__(
            message="Desktop tool request belongs to another user",
            status_code=HTTPStatus.FORBIDDEN,
        )


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
) -> DesktopToolOutcome:
    """Execute one action on the user's desktop and await its result.

    Publishes the request onto the chat SSE stream and blocks (up to
    ``DESKTOP_TOOL_TIMEOUT_SECONDS``) on the per-request Redis result channel.
    """
    if not redis_cache.redis:
        log.error(f"{LogTag.DESKTOP} Desktop bridge: Redis unavailable")
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
        # Derive the TTL from the tool timeout so the key always outlives the
        # wait (see DESKTOP_REQUEST_TTL_GRACE_SECONDS).
        ttl=int(DESKTOP_TOOL_TIMEOUT_SECONDS) + DESKTOP_REQUEST_TTL_GRACE_SECONDS,
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
                "timeout_ms": int(DESKTOP_TOOL_TIMEOUT_SECONDS * 1000),
            }
        }
        await stream_manager.publish_chunk(stream_id, f"data: {json.dumps(frame)}\n\n")

        try:
            async with asyncio.timeout(DESKTOP_TOOL_TIMEOUT_SECONDS):
                outcome = await _await_result(pubsub)
        except TimeoutError:
            log.warning(
                f"{LogTag.DESKTOP} Desktop tool '{tool}' timed out after {DESKTOP_TOOL_TIMEOUT_SECONDS}s"
            )
            return DesktopToolOutcome(ok=False, error=ERROR_TIMEOUT)

        return outcome
    finally:
        # Best-effort cleanup in independent guards: a failure here must never
        # mask the real outcome, and a failed key-delete must not skip the
        # pubsub teardown (the request key also carries a TTL, so it expires
        # regardless).
        try:
            await redis_cache.delete(request_key)
        except Exception:  # nosec B110 - cleanup must not mask the outcome
            pass
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
            log.warning(f"{LogTag.DESKTOP} Desktop bridge: discarding malformed result payload")
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
        log.error(f"{LogTag.DESKTOP} Desktop bridge: Redis unavailable, dropping result")
        return
    await redis_cache.redis.publish(
        f"{DESKTOP_RESULT_CHANNEL_PREFIX}{request_id}",
        json.dumps({"ok": ok, "data": data, "error": error}),
    )


async def relay_desktop_result(
    *,
    request_id: str,
    user_id: str,
    ok: bool,
    data: dict[str, Any] | None,
    error: str | None,
) -> None:
    """Validate ownership of a pending desktop request and relay its result.

    Deletes the request key (so late/duplicate deliveries cannot double-resolve)
    before publishing. Raises :class:`DesktopRequestNotFound` if the request
    expired or was already resolved, or :class:`DesktopRequestForbidden` if the
    POSTing user does not own it.
    """
    request_key = f"{DESKTOP_REQUEST_PREFIX}{request_id}"
    pending = await redis_cache.get(request_key)
    if not pending:
        raise DesktopRequestNotFound()
    if pending.get("user_id") != user_id:
        raise DesktopRequestForbidden()

    await redis_cache.delete(request_key)
    await publish_desktop_result(request_id, ok=ok, data=data, error=error)
