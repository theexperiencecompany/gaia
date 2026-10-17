"""One shared per-pod subscription to the runtime-config channel.

Credential writes publish on Redis so a Settings or setup-wizard save reaches
every pod, but publishing only informs pods that listen. Without this
subscriber other pods keep serving stale credentials until their 60s TTL
expires; single-pod installs apply updates locally before publishing and never
needed it. The listener mirrors services/device/revoke_listener.py: subscribe
once per pod, apply each update through the service's own pod-local
invalidation, and re-subscribe on a dropped connection instead of dying.
"""

import asyncio
import contextlib
import json
from typing import TypedDict, cast

from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.services.composio.auth_config_resolver import invalidate_auth_config_cache
from app.services.composio.instance_toolkits import load_instance_toolkits
from app.services.providers.provider_credentials_service import invalidate_locally
from app.services.runtime.config_updates import (
    COMPOSIO_AUTH_CONFIGS_SCOPE,
    INSTANCE_TOOLKITS_SCOPE,
    PROVIDER_SCOPE_PREFIX,
    RUNTIME_CONFIG_CHANNEL,
)
from shared.py.wide_events import log, log_context

#: Delay before re-subscribing after a dropped connection (same policy as the
#: device listeners).
_RESUBSCRIBE_SECONDS: float = 5.0

_subscriber_task: asyncio.Task[None] | None = None


class _InvalidationPayload(TypedDict):
    """The published invalidation message this listener reads.

    Wire shape is one scope, as publish_config_update sends it.
    """

    scope: str


class _PubSubMessage(TypedDict, total=False):
    """The Redis pub/sub envelope this listener reads.

    Redis returns type message or subscribe plus a data payload; every other
    key is ignored.
    """

    type: str
    data: str | bytes


def _parse_scope(data: str | bytes) -> str | None:
    """Return the scope named in a published payload, or None when malformed.

    A malformed message must never take the listener down: log loud, skip.
    """
    raw = data.decode(errors="replace") if isinstance(data, bytes) else data
    try:
        payload: object = json.loads(raw)
    except json.JSONDecodeError as e:
        log.warning(
            f"{LogTag.API} Malformed runtime-config update ignored",
            channel=RUNTIME_CONFIG_CHANNEL,
            error=str(e),
        )
        return None
    # Validated into the declared shape once, at this boundary, rather than read
    # off a bare json.loads dict.
    parsed: _InvalidationPayload | None = (
        cast(_InvalidationPayload, payload)
        if isinstance(payload, dict) and "scope" in payload
        else None
    )
    scope = parsed.get("scope") if parsed else None
    return scope if isinstance(scope, str) else None


async def _apply_update(data: str | bytes) -> None:
    """Apply one remote invalidation under its own wide-event boundary."""
    scope = _parse_scope(data)
    async with log_context("runtime_config_update", runtime_config={"scope": scope}):
        # The same pod-local drop a save runs on the saving pod, so the next
        # read here re-reads Mongo and rebuilds its clients.
        if scope == COMPOSIO_AUTH_CONFIGS_SCOPE:
            invalidate_auth_config_cache()
        elif scope == INSTANCE_TOOLKITS_SCOPE:
            await load_instance_toolkits()
        elif scope is not None and scope.startswith(PROVIDER_SCOPE_PREFIX):
            invalidate_locally(scope.removeprefix(PROVIDER_SCOPE_PREFIX))
        else:
            log.warning(
                f"{LogTag.API} Runtime-config update with unknown scope ignored",
                channel=RUNTIME_CONFIG_CHANNEL,
                scope=scope,
            )
            return
        log.info(f"{LogTag.API} Applied runtime-config update from another pod")


async def _consume() -> None:
    """Subscribe once and apply remote invalidations until the connection drops."""
    client = redis_cache.redis
    if client is None:
        return
    pubsub = client.pubsub()
    await pubsub.subscribe(RUNTIME_CONFIG_CHANNEL)
    try:
        while True:
            # Blocks until the next message; subscribe acks fail the type check below.
            raw_message = await pubsub.get_message(timeout=None)
            if not isinstance(raw_message, dict):
                continue
            message: _PubSubMessage = cast(_PubSubMessage, raw_message)
            if message.get("type") != "message":
                continue
            data = message.get("data")
            if data is None:
                continue
            await _apply_update(data)
    finally:
        with contextlib.suppress(Exception):
            await pubsub.unsubscribe(RUNTIME_CONFIG_CHANNEL)
            await pubsub.aclose()


async def _listener_loop() -> None:
    """Re-subscribe on a dropped connection instead of dying silently."""
    if not redis_cache.redis:
        log.warning(f"{LogTag.API} Runtime-config subscriber disabled (no Redis connection)")
        return
    while True:
        try:
            await _consume()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning(
                f"{LogTag.API} Runtime-config subscriber dropped, resubscribing",
                error=str(e),
                error_type=type(e).__name__,
            )
        await asyncio.sleep(_RESUBSCRIBE_SECONDS)


def start_runtime_config_subscriber() -> None:
    """Start the shared per-pod runtime-config subscriber (idempotent)."""
    global _subscriber_task
    if _subscriber_task is not None and not _subscriber_task.done():
        return
    _subscriber_task = asyncio.get_running_loop().create_task(_listener_loop())
    log.info(f"{LogTag.API} Runtime-config subscriber started")


async def stop_runtime_config_subscriber() -> None:
    """Cancel and await the runtime-config subscriber."""
    global _subscriber_task
    if _subscriber_task is None:
        return
    _subscriber_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await _subscriber_task
    _subscriber_task = None
