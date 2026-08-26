"""One shared per-pod subscription to the runtime-config channel.

``provider_credentials_service.invalidate`` publishes credential writes on
Redis so a Settings/setup-wizard save reaches every pod — but publishing only
informs pods that LISTEN. Without this subscriber (the F4 gap), other pods kept
serving stale credentials until their 60s TTL expired; single-pod installs
apply updates locally before publishing and never needed it.

The listener mirrors ``services/device/revoke_listener.py``: subscribe once per
pod, apply each update through the service's own pod-local invalidation, and
re-subscribe on a dropped connection instead of dying silently.
"""

import asyncio
import contextlib
import json

from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.services.providers.provider_credentials_service import (
    RUNTIME_CONFIG_CHANNEL,
    invalidate_locally,
)
from shared.py.wide_events import log, log_context

#: Delay before re-subscribing after a dropped connection (same policy as the
#: device listeners).
_RESUBSCRIBE_SECONDS: float = 5.0

_subscriber_task: asyncio.Task[None] | None = None


def _parse_provider(data: str | bytes) -> str | None:
    """The provider named in a published payload, or ``None`` when malformed.

    Payload contract (see ``invalidate``): ``{"scope": "provider:<name>"}``.
    A malformed message must never take the listener down — log loud, skip.
    """
    raw = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else data
    try:
        payload: object = json.loads(raw)
    except json.JSONDecodeError as e:
        log.warning(
            f"{LogTag.API} Malformed runtime-config update ignored",
            channel=RUNTIME_CONFIG_CHANNEL,
            error=str(e),
        )
        return None
    scope = payload.get("scope") if isinstance(payload, dict) else None
    prefix = "provider:"
    if not isinstance(scope, str) or not scope.startswith(prefix):
        log.warning(
            f"{LogTag.API} Runtime-config update with unknown scope ignored",
            channel=RUNTIME_CONFIG_CHANNEL,
            scope=scope,
        )
        return None
    return scope[len(prefix) :]


async def _apply_update(data: str | bytes) -> None:
    """Apply one remote invalidation under its own wide-event boundary."""
    provider = _parse_provider(data)
    if provider is None:
        return
    async with log_context("runtime_config_update", provider={"name": provider}):
        # Same fan-out a local save runs — cache drop, registry reset, aux LLM
        # caches — so the next resolution re-reads Mongo and rebuilds clients.
        invalidate_locally(provider)
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
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message is None or message.get("type") != "message":
                continue
            await _apply_update(message["data"])
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
