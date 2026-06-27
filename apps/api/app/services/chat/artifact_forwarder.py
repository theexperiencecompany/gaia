"""Per-turn forwarding of a conversation's artifact events to the chat SSE stream.

One :class:`ArtifactForwarder` runs per chat turn. It subscribes to
``artifacts:{user_id}`` (published by the coding tools and the upload pipeline),
keeps only this conversation's events, and runs each through a fixed pipeline:

    show it live  →  save it (registry + message ref)  →  deliver to bot  →  warm cache

"Show it live" streams the full file data so the web client populates its map
immediately; "save it" writes the conversation-level registry (the source of
truth) plus a lightweight ``{session_id, path, event}`` reference on the bot
message so the card re-renders on reload. A per-turn ``mtime`` map, loaded once,
makes whole-dir re-emits idempotent: an unchanged file is skipped entirely.
"""

import asyncio
from collections import deque
import contextlib
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from app.constants.artifacts import (
    ARTIFACT_LOG_PREFIX,
    ARTIFACT_PERSIST_MAX_ATTEMPTS,
    ARTIFACT_PERSIST_RETRY_BASE_DELAY,
    ARTIFACT_WARM_CHUNK_BYTES,
    ARTIFACT_WARM_MAX_CONCURRENCY,
)
from app.constants.outbound import OUTBOUND_QUEUES
from app.core.stream_manager import stream_manager
from app.db.mongodb.collections import conversations_collection
from app.db.redis import redis_cache
from app.models.chat_models import ConversationSource
from app.services.artifact_events import artifact_channel
from app.services.chat.artifacts_registry import (
    get_conversation_artifacts,
    remove_conversation_artifact,
    upsert_conversation_artifact,
)
from app.services.outbound_delivery import publish_outbound_file
from app.services.storage import resolve_session_path
from app.utils.artifact_utils import build_artifact_full_entry, build_artifact_ref_entry
from shared.py.wide_events import log

_warm_semaphore = asyncio.Semaphore(ARTIFACT_WARM_MAX_CONCURRENCY)

# Module-level task-reference sets: they keep fire-and-forget work that can
# outlive a forwarder instance from being garbage-collected mid-flight.
_warm_tasks: set[asyncio.Task[None]] = set()
_publish_tasks: set[asyncio.Task[bool]] = set()


async def forward_artifact_events(
    user_id: str,
    conversation_id: str,
    stream_id: str,
    bot_message_id: str | None,
    source: str | None = None,
) -> None:
    """Bridge this conversation's artifact events to its chat SSE stream."""
    await ArtifactForwarder(user_id, conversation_id, stream_id, bot_message_id, source).run()


@dataclass
class _TurnStats:
    """Per-turn tallies, emitted as one canonical log line when the turn ends."""

    upserts: int = 0
    removes: int = 0
    unchanged: int = 0
    delivered: int = 0

    def as_wide_event(self, conversation_id: str) -> dict[str, Any]:
        return {
            "conversation_id": conversation_id,
            "upserts": self.upserts,
            "removes": self.removes,
            "unchanged": self.unchanged,
            "delivered_to_bot": self.delivered,
        }


class ArtifactForwarder:
    """Forwards one turn's artifact events: live SSE + registry + bot delivery.

    All per-turn mutable state lives on the instance: ``registry_mtimes`` dedups
    re-emits, ``published_files`` caps bot delivery at once per file, and
    ``stats`` tallies the turn. The public entry point is
    :func:`forward_artifact_events`.
    """

    def __init__(
        self,
        user_id: str,
        conversation_id: str,
        stream_id: str,
        bot_message_id: str | None,
        source: str | None = None,
    ) -> None:
        self.user_id = user_id
        self.conversation_id = conversation_id
        self.stream_id = stream_id
        self.bot_message_id = bot_message_id
        self.bot_platform = _bot_source(source)
        self.registry_mtimes: dict[str, str | None] = {}
        self.published_files: set[str] = set()
        self.stats = _TurnStats()

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Load the registry, then forward every event of this turn until close."""
        if redis_cache.redis is None:
            return
        await self._load_registry()
        channel = artifact_channel(self.user_id)
        pubsub = redis_cache.redis.pubsub()
        try:
            await pubsub.subscribe(channel)
            log.info(
                f"{ARTIFACT_LOG_PREFIX} subscribed "
                f"(conv={self.conversation_id}, registry={len(self.registry_mtimes)})"
            )
            await self._consume(pubsub)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — log and exit; orchestrator cleans up
            log.warning(f"{ARTIFACT_LOG_PREFIX} forwarder error (conv={self.conversation_id}): {e}")
        finally:
            self._log_summary()
            await _close_pubsub(pubsub, channel)

    async def _load_registry(self) -> None:
        """Seed the per-turn ``path → mtime`` map so re-emits dedup against it."""
        self.registry_mtimes = {
            artifact["path"]: artifact.get("mtime")
            for artifact in await get_conversation_artifacts(self.user_id, self.conversation_id)
        }

    async def _consume(self, pubsub: Any) -> None:
        """Forward each artifact event; one bad event is logged, never fatal."""
        async for message in pubsub.listen():
            payload = _parse_artifact_message(message, self.conversation_id)
            if payload is None:
                continue
            try:
                await self._handle_event(payload)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 — one bad event must not kill the turn
                log.warning(
                    f"{ARTIFACT_LOG_PREFIX} event failed (conv={self.conversation_id}): {e}"
                )

    # ── Per-event routing ──────────────────────────────────────────────────

    async def _handle_event(self, payload: dict[str, Any]) -> None:
        """Route one event: remove → drop, unchanged → skip, else → publish."""
        path = payload.get("path")
        event = payload.get("event")
        if event == "remove":
            await self._apply_remove(path)
        elif self._is_unchanged(path, payload):
            self.stats.unchanged += 1  # idempotent re-emit — kills the cross-turn leak
            log.debug(f"{ARTIFACT_LOG_PREFIX} skip unchanged path={path}")
        else:
            await self._apply_upsert(payload, path, event)

    def _is_unchanged(self, path: str | None, payload: dict[str, Any]) -> bool:
        return path is not None and self.registry_mtimes.get(path) == payload.get("mtime")

    async def _apply_upsert(
        self, payload: dict[str, Any], path: str | None, event: str | None
    ) -> None:
        """A new or changed file — the main pipeline."""
        if not path:
            return
        # Optimistic dedup: the live card is the user-facing truth; the Mongo
        # writes below are reload durability and must not gate it.
        self.registry_mtimes[path] = payload.get("mtime")
        self.stats.upserts += 1

        await self._stream_entry(build_artifact_full_entry(payload))  # 1. show live (full data)
        await upsert_conversation_artifact(  # 2. registry = source of truth
            self.user_id, self.conversation_id, payload
        )
        await self._persist_entry(  # 3. message ref so the card survives reload
            build_artifact_ref_entry(self.conversation_id, path, event)
        )
        self._maybe_deliver_to_bot(payload, path, event)  # 4. bot outbound queue (once/turn)
        self._maybe_warm_cache(payload, path, event)  # 5. warm JuiceFS cache

    async def _apply_remove(self, path: str | None) -> None:
        """A deleted file — drop from the registry and tell the client to drop it."""
        if not path:
            return
        self.registry_mtimes.pop(path, None)
        self.stats.removes += 1
        ref = build_artifact_ref_entry(self.conversation_id, path, "remove")
        await self._stream_entry(ref)
        await remove_conversation_artifact(self.user_id, self.conversation_id, path)
        await self._persist_entry(ref)

    # ── Pipeline steps ─────────────────────────────────────────────────────

    async def _stream_entry(self, entry: dict[str, Any]) -> None:
        """Publish one ``artifact_data`` chunk to the live SSE stream."""
        chunk = "data: " + json.dumps({"tool_data": entry}) + "\n\n"
        await stream_manager.publish_chunk(self.stream_id, chunk)

    async def _persist_entry(self, entry: dict[str, Any]) -> None:
        """``$push`` one ``artifact_data`` reference onto the turn's bot message.

        Best-effort: the live stream already delivered the card, so a failed
        persist only costs the reload re-render. A not-yet-saved bot message (an
        early-turn artifact racing ``_persist_turn``) is retried with a short
        backoff so the entry isn't dropped before the row exists.
        """
        if not self.bot_message_id:
            return
        try:
            for attempt in range(ARTIFACT_PERSIST_MAX_ATTEMPTS):
                result = await conversations_collection.update_one(
                    {
                        "user_id": self.user_id,
                        "conversation_id": self.conversation_id,
                        "messages.message_id": self.bot_message_id,
                    },
                    {"$push": {"messages.$.tool_data": entry}},
                )
                if result.matched_count:
                    return
                await asyncio.sleep(ARTIFACT_PERSIST_RETRY_BASE_DELAY * (attempt + 1))
            log.warning(
                f"{ARTIFACT_LOG_PREFIX} persist matched no bot message after retries "
                f"(conv={self.conversation_id}, msg={self.bot_message_id})"
            )
        except Exception as e:  # noqa: BLE001 — best-effort; live stream already delivered it
            log.warning(f"{ARTIFACT_LOG_PREFIX} failed to persist artifact entry: {e}")

    def _maybe_deliver_to_bot(self, payload: dict[str, Any], path: str, event: str | None) -> None:
        """Push an agent-generated artifact to a bot user's outbound queue, once.

        User uploads (``event == "upload"``) are skipped — the user already has
        them; the web SSE card isn't visible to a bot user, hence this path.
        """
        if not (
            self.bot_platform is not None and event == "upsert" and path not in self.published_files
        ):
            return
        self.published_files.add(path)
        self.stats.delivered += 1
        pub_task = asyncio.create_task(
            publish_outbound_file(
                platform=self.bot_platform,
                user_id=self.user_id,
                conversation_id=self.conversation_id,
                path=path,
                filename=path.rsplit("/", 1)[-1],
                content_type=payload.get("content_type"),
            )
        )
        _publish_tasks.add(pub_task)
        pub_task.add_done_callback(_publish_tasks.discard)

    def _maybe_warm_cache(self, payload: dict[str, Any], path: str, event: str | None) -> None:
        """Warm the JuiceFS cache for follow-up-fetch files (those with no inline
        body); inlined files carry their body and never hit the file endpoint."""
        if event != "upsert" or payload.get("body"):
            return
        warm = asyncio.create_task(self._warm_cache(path))
        _warm_tasks.add(warm)
        warm.add_done_callback(_warm_tasks.discard)

    async def _warm_cache(self, path: str) -> None:
        """Pre-read a freshly written artifact into the host JuiceFS cache so the
        user's first open is served warm (local cache) instead of cold (from R2).

        Best-effort: a failure (mount absent, file not yet flushed, deleted) just
        means the on-demand read pays the cold cost as it did before.
        """
        try:
            async with _warm_semaphore:
                host_path = await resolve_session_path(
                    self.user_id, self.conversation_id, "artifacts", path
                )
                await asyncio.to_thread(_warm_artifact_blocks, host_path)
        except Exception as e:  # noqa: BLE001 — best-effort cache warm
            log.debug(f"{ARTIFACT_LOG_PREFIX} cache warm skipped: {e}")

    def _log_summary(self) -> None:
        s = self.stats
        log.set(artifacts=s.as_wide_event(self.conversation_id))
        log.info(
            f"{ARTIFACT_LOG_PREFIX} closed (conv={self.conversation_id}, "
            f"upserts={s.upserts}, removes={s.removes}, "
            f"unchanged={s.unchanged}, delivered={s.delivered})"
        )


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


async def _close_pubsub(pubsub: Any, channel: str) -> None:
    """Unsubscribe and close, swallowing teardown errors (the turn is over)."""
    with contextlib.suppress(Exception):
        await pubsub.unsubscribe(channel)
    with contextlib.suppress(Exception):
        await pubsub.aclose()


def _warm_artifact_blocks(host_path: Path) -> None:
    """Read a file through the FUSE mount to pull its blocks into the JuiceFS
    local cache. Constant memory: chunks are read and discarded."""
    with host_path.open("rb") as fh:
        # Drain the file in fixed-size chunks, discarding each: the read is the
        # side effect (it pulls blocks into the cache), the bytes aren't kept.
        deque(iter(lambda: fh.read(ARTIFACT_WARM_CHUNK_BYTES), b""), maxlen=0)
