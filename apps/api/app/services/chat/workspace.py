"""Per-turn workspace setup and artifact-event forwarding.

:func:`prepare_user_workspace` is the fused host-side bootstrap — what used to
be three sequential ``asyncio.to_thread`` hops (sessions dir + INDEX/GUIDE +
integrations tree) is now one call into the storage layer. It soft-fails when
the JuiceFS mount is missing so chat still serves in dev.

:func:`forward_artifact_events` is the bridge between the coding tools
(which write to ``artifacts:{user_id}`` on Redis pub/sub) and the live SSE
stream. Forwarded events are appended to the shared ``tool_data`` accumulator
so the card persists with the conversation on server reload.
"""

import asyncio
import contextlib
from datetime import UTC, datetime
import json
from typing import Any

from app.core.stream_manager import stream_manager
from app.db.redis import redis_cache
from app.services.artifact_events import artifact_channel
from app.services.integrations.user_integrations import (
    get_user_connected_integrations,
)
from app.services.storage import JuiceFSUnavailable, bootstrap_user_session
from shared.py.wide_events import log


async def prepare_user_workspace(user_id: str, conversation_id: str) -> None:
    """Materialize the user's session dirs + INDEX/GUIDE + integrations tree.

    Soft-fails when JuiceFS isn't mounted (dev mode) so the chat stream still
    serves; coding-tool errors will surface clearly if the user tries to use
    the sandbox.
    """
    try:
        docs = await get_user_connected_integrations(user_id)
    except Exception as e:  # noqa: BLE001 — Mongo flake must not block chat
        log.warning(f"[chat] could not load connected integrations: {e}")
        docs = []
    connected_ids = {
        str(d.get("integration_id"))
        for d in docs
        if d.get("status") == "connected" and d.get("integration_id")
    }
    try:
        await bootstrap_user_session(user_id, conversation_id, connected_ids)
    except JuiceFSUnavailable:
        return  # dev mode — proceed; tool errors will surface clearly
    except Exception as e:  # noqa: BLE001 — never block chat on FS infra
        log.warning(f"[chat] session dir setup failed: {e}")


async def forward_artifact_events(
    user_id: str,
    conversation_id: str,
    stream_id: str,
    tool_data: dict[str, Any],
) -> None:
    """Forward this conversation's artifact events to the chat SSE stream
    *and* record them into the conversation's ``tool_data`` so they persist.

    Subscribes to ``artifacts:{user_id}`` (published by the coding tools and the
    upload pipeline) and re-emits events whose ``session_id`` matches this
    conversation as ``artifact_data`` tool chunks. Each forwarded artifact is
    also appended to the shared ``tool_data`` accumulator that the persistence
    layer writes to Mongo — without this the card only lives in the live stream
    / client cache and is gone on a server reload.

    De-duped by ``path`` (artifacts are pushed repeatedly in real time): an
    unchanged file is neither re-sent nor re-persisted; the last write wins.
    """
    if redis_cache.redis is None:
        return
    channel = artifact_channel(user_id)
    pubsub = redis_cache.redis.pubsub()
    seen: dict[str, tuple[str | None, str | None, int | None, str | None]] = {}
    try:
        await pubsub.subscribe(channel)
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            try:
                payload = json.loads(message["data"])
            except (ValueError, TypeError):
                continue
            if payload.get("session_id") != conversation_id:
                continue
            path = payload.get("path")
            event = payload.get("event")
            sig: tuple[str | None, str | None, int | None, str | None] = (
                event,
                path,
                payload.get("size_bytes"),
                payload.get("mtime"),
            )
            if path and seen.get(path) == sig:
                continue  # unchanged — skip duplicate push/persist
            if path:
                if event == "remove":
                    seen.pop(path, None)
                else:
                    seen[path] = sig
            entry = {
                "tool_name": "artifact_data",
                "data": payload,
                "timestamp": datetime.now(UTC).isoformat(),
                "tool_category": "artifact",
            }
            # Persist with the conversation (re-renders on server reload)…
            tool_data.setdefault("tool_data", []).append(entry)
            # …and push live so the card appears during this turn.
            chunk = "data: " + json.dumps({"tool_data": entry}) + "\n\n"
            await stream_manager.publish_chunk(stream_id, chunk)
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001 — log and exit; orchestrator cleans up
        log.warning(f"[chat] artifact forwarder error: {e}")
    finally:
        with contextlib.suppress(Exception):
            await pubsub.unsubscribe(channel)
        with contextlib.suppress(Exception):
            await pubsub.aclose()
