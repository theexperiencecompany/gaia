"""Per-turn workspace upkeep and artifact-event forwarding.

:func:`schedule_last_active_touch` is the only workspace work a chat turn now
does — a fire-and-forget bump of the session's ``last_active`` so the daily
idle-prune doesn't reap an actively-used conversation. The heavy per-user
materialization (system files, skill/instruction catalog, integration tree) is
event-driven elsewhere: registration, integration connect/disconnect, and
startup. Session dirs are created at conversation creation
(:func:`app.services.chat.persistence.initialize_new_conversation`).

:func:`forward_artifact_events` is the bridge between the coding tools
(which write to ``artifacts:{user_id}`` on Redis pub/sub) and the live SSE
stream. Each forwarded event is ``$push``-ed straight onto the turn's bot
message in Mongo so the card persists with the conversation on server reload.
"""

import asyncio
import contextlib
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

from app.constants.outbound import OUTBOUND_QUEUES
from app.core.stream_manager import stream_manager
from app.db.mongodb.collections import conversations_collection
from app.db.redis import redis_cache
from app.models.chat_models import ConversationSource
from app.services.artifact_events import artifact_channel
from app.services.outbound_delivery import publish_outbound_file
from app.services.storage import (
    JuiceFSUnavailable,
    resolve_session_path,
    touch_session_last_active,
)
from shared.py.wide_events import log


def _bot_source(source: str | None) -> ConversationSource | None:
    """Return the bot ``ConversationSource`` for ``source`` if it has an outbound
    queue (whatsapp/telegram/discord/slack), else None (web/mobile/unknown)."""
    if not source:
        return None
    try:
        cs = ConversationSource(source)
    except ValueError:
        return None
    return cs if cs in OUTBOUND_QUEUES else None


_last_active_tasks: set[asyncio.Task[None]] = set()
_warm_tasks: set[asyncio.Task[None]] = set()


def schedule_last_active_touch(user_id: str, conversation_id: str) -> None:
    """Fire-and-forget bump of the session's ``last_active`` for idle-prune.

    The heavy per-user workspace materialization is no longer done on the chat
    turn — it's event-driven (registration, integration connect/disconnect,
    startup). All a turn owes the workspace is keeping the conversation's
    ``last_active`` current so the daily idle-prune doesn't reap an actively-used
    session. Non-blocking; soft-fails when JuiceFS is unmounted (dev).
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    async def _touch() -> None:
        try:
            await touch_session_last_active(user_id, conversation_id)
        except JuiceFSUnavailable:
            return  # dev mode — no mount, nothing to touch
        except Exception as e:  # noqa: BLE001 — last_active bump must not affect chat
            log.warning(f"[chat] last_active touch failed: {e}")

    task = loop.create_task(_touch())
    _last_active_tasks.add(task)
    task.add_done_callback(_last_active_tasks.discard)


async def forward_artifact_events(
    user_id: str,
    conversation_id: str,
    stream_id: str,
    bot_message_id: str | None,
    source: str | None = None,
) -> None:
    """Forward this conversation's artifact events to the chat SSE stream
    *and* persist each one onto the turn's bot message so it survives a reload.

    Subscribes to ``artifacts:{user_id}`` (published by the coding tools and the
    upload pipeline) and re-emits events whose ``session_id`` matches this
    conversation as ``artifact_data`` tool chunks. Each forwarded artifact is
    also ``$push``-ed straight onto the bot message's ``tool_data`` in Mongo.
    We persist on arrival rather than via the in-memory accumulator because the
    turn's early ``_persist_turn`` saves before the background executor has
    created any artifact, and the executor-tool-data attach only drains the
    executor's own events, so an appended entry would never reach Mongo and the
    card would vanish on reload.

    De-duped by ``path`` (artifacts are pushed repeatedly in real time): an
    unchanged file is neither re-sent nor re-persisted; the last write wins.
    """
    if redis_cache.redis is None:
        return
    channel = artifact_channel(user_id)
    pubsub = redis_cache.redis.pubsub()
    seen: dict[str, tuple[str | None, str | None, int | None, str | None]] = {}
    # Bot file delivery: on a messaging-platform turn, each generated artifact is
    # also pushed to the platform's outbound queue (the SSE card the web UI gets
    # isn't visible to a bot user). Publish each path at most once per turn.
    bot_platform = _bot_source(source)
    published_files: set[str] = set()
    publish_tasks: set[asyncio.Task[bool]] = set()
    try:
        await pubsub.subscribe(channel)
        async for message in pubsub.listen():
            payload = _parse_artifact_message(message, conversation_id)
            if payload is None:
                continue
            path = payload.get("path")
            event = payload.get("event")
            if _is_duplicate_artifact(payload, path, event, seen):
                continue  # unchanged — skip duplicate push/persist
            _maybe_deliver_to_bot(
                payload=payload,
                path=path,
                event=event,
                bot_platform=bot_platform,
                user_id=user_id,
                conversation_id=conversation_id,
                published_files=published_files,
                publish_tasks=publish_tasks,
            )
            entry = {
                "tool_name": "artifact_data",
                "data": payload,
                "timestamp": datetime.now(UTC).isoformat(),
                "tool_category": "artifact",
            }
            # Persist onto the bot message so the card re-renders on reload…
            await _persist_artifact_entry(user_id, conversation_id, bot_message_id, entry)
            # …and push live so the card appears during this turn.
            chunk = "data: " + json.dumps({"tool_data": entry}) + "\n\n"
            await stream_manager.publish_chunk(stream_id, chunk)
            # Warm the host JuiceFS cache for files that need a follow-up fetch
            # (no inline body) so the user's first "open" is served from local
            # cache instead of a cold R2 read. Inlined files carry their body and
            # never hit the file endpoint, so they don't need warming.
            if event == "upsert" and path and not payload.get("body"):
                warm = asyncio.create_task(_warm_artifact_cache(user_id, conversation_id, path))
                _warm_tasks.add(warm)
                warm.add_done_callback(_warm_tasks.discard)
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001 — log and exit; orchestrator cleans up
        log.warning(f"[chat] artifact forwarder error: {e}")
    finally:
        with contextlib.suppress(Exception):
            await pubsub.unsubscribe(channel)
        with contextlib.suppress(Exception):
            await pubsub.aclose()


async def _persist_artifact_entry(
    user_id: str,
    conversation_id: str,
    bot_message_id: str | None,
    entry: dict[str, Any],
) -> None:
    """``$push`` one ``artifact_data`` entry onto the turn's bot message.

    Best-effort: the live SSE stream already delivered the card, so a failed
    persist (or a not-yet-saved bot message) only costs the reload re-render,
    which the ``GET /sessions/{conv}/artifacts`` recovery path still backstops.
    """
    if not bot_message_id:
        return
    try:
        result = await conversations_collection.update_one(
            {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "messages.message_id": bot_message_id,
            },
            {"$push": {"messages.$.tool_data": entry}},
        )
        if result.matched_count == 0:
            log.warning(
                "[chat] artifact persist matched no bot message "
                f"(conv={conversation_id}, msg={bot_message_id})"
            )
    except Exception as e:  # noqa: BLE001 — best-effort; live stream already delivered it
        log.warning(f"[chat] failed to persist artifact entry: {e}")


# JuiceFS default block size: reading in block-sized chunks pulls each block
# into the local cache with no wasted partial fetches.
_WARM_CHUNK_BYTES = 4 * 1024 * 1024

# Cap concurrent cache-warm reads so a burst of artifacts in one turn can't
# saturate the shared default thread pool (``asyncio.to_thread``) and starve
# other blocking IO. Tasks past the cap queue on the semaphore, not the pool.
_WARM_MAX_CONCURRENCY = 4
_warm_semaphore = asyncio.Semaphore(_WARM_MAX_CONCURRENCY)


def _warm_artifact_blocks(host_path: Path) -> None:
    """Read a file through the FUSE mount to pull its blocks into the JuiceFS
    local cache. Constant memory: chunks are read and discarded."""
    with host_path.open("rb") as fh:
        while fh.read(_WARM_CHUNK_BYTES):
            pass


async def _warm_artifact_cache(user_id: str, conversation_id: str, path: str) -> None:
    """Pre-read a freshly written artifact into the host JuiceFS cache so the
    user's first open is served warm (local cache) instead of cold (from R2).

    Best-effort: a failure (mount absent, file not yet flushed, deleted) just
    means the on-demand read pays the cold cost as it did before.
    """
    try:
        async with _warm_semaphore:
            host_path = await resolve_session_path(user_id, conversation_id, "artifacts", path)
            await asyncio.to_thread(_warm_artifact_blocks, host_path)
    except Exception as e:  # noqa: BLE001 — best-effort cache warm
        log.debug(f"[chat] artifact cache warm skipped: {e}")


def _parse_artifact_message(message: dict[str, Any], conversation_id: str) -> dict[str, Any] | None:
    """Decode a pub/sub message into an artifact payload for this conversation.

    Returns ``None`` when the message isn't a data frame, can't be parsed, or
    belongs to a different conversation.
    """
    if message.get("type") != "message":
        return None
    try:
        payload = json.loads(message["data"])
    except (ValueError, TypeError):
        return None
    if payload.get("session_id") != conversation_id:
        return None
    return payload


def _is_duplicate_artifact(
    payload: dict[str, Any],
    path: str | None,
    event: str | None,
    seen: dict[str, tuple[str | None, str | None, int | None, str | None]],
) -> bool:
    """Return True if this artifact is unchanged since last seen; else record it."""
    sig: tuple[str | None, str | None, int | None, str | None] = (
        event,
        path,
        payload.get("size_bytes"),
        payload.get("mtime"),
    )
    if path and seen.get(path) == sig:
        return True
    if path:
        if event == "remove":
            seen.pop(path, None)
        else:
            seen[path] = sig
    return False


def _maybe_deliver_to_bot(
    *,
    payload: dict[str, Any],
    path: str | None,
    event: str | None,
    bot_platform: ConversationSource | None,
    user_id: str,
    conversation_id: str,
    published_files: set[str],
    publish_tasks: set[asyncio.Task[bool]],
) -> None:
    """Push agent-generated artifacts to a bot user's outbound queue, at most once.

    User uploads (``event == "upload"``) are skipped — the user already has them.
    """
    if not (
        bot_platform is not None and event == "upsert" and path and path not in published_files
    ):
        return
    published_files.add(path)
    pub_task = asyncio.create_task(
        publish_outbound_file(
            platform=bot_platform,
            user_id=user_id,
            conversation_id=conversation_id,
            path=path,
            filename=path.rsplit("/", 1)[-1],
            content_type=payload.get("content_type"),
        )
    )
    publish_tasks.add(pub_task)
    pub_task.add_done_callback(publish_tasks.discard)
