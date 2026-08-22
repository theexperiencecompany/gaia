"""
Redis Pub/Sub Stream Manager for Background Execution.

This module provides infrastructure for running LangGraph streaming in background
tasks, decoupled from HTTP request lifecycle. Key features:

1. Background Execution: Stream continues even if client disconnects
2. Redis Pub/Sub: Chunks published to channel, HTTP endpoint subscribes
3. Progress Tracking: State saved to Redis for recovery
4. Graceful Cancellation: Cancel signal via Redis + pub/sub notification
5. Reliable Saving: Conversation always saved to MongoDB on completion

Architecture:
    HTTP Request                          Background Task
         │                                      │
         ├──▶ Start background task ──────────▶│ LangGraph Execution
         │                                      │
         └──◀ Subscribe to Redis channel ◀─────┤ Publish chunks to Redis
                                               │
          Client disconnects?                  │ Stream continues!
               ↓                               │
          No problem!                          ▼
                                          Save to MongoDB

Usage:
    # In endpoint - start stream
    await stream_manager.start_stream(stream_id, conversation_id, user_id)

    # In background task - publish chunks
    await stream_manager.publish_chunk(stream_id, chunk)
    await stream_manager.update_progress(stream_id, message_chunk)

    # In endpoint - subscribe and forward to client
    async for chunk in stream_manager.subscribe_stream(stream_id):
        yield chunk

    # Cancel from frontend
    await stream_manager.cancel_stream(stream_id)
"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import json
from typing import Any, cast

from app.constants.cache import (
    STREAM_ACTIVE_PREFIX,
    STREAM_EVENTS_MAXLEN,
    STREAM_EVENTS_PREFIX,
    STREAM_PROGRESS_PREFIX,
    STREAM_SIGNAL_PREFIX,
    STREAM_TTL,
)
from app.constants.log_tags import LogTag
from app.constants.streaming import (
    SSE_KEEPALIVE_FRAME,
    SSE_KEEPALIVE_INTERVAL_SECONDS,
    STREAM_CANCELLED_SIGNAL,
    STREAM_DONE_SIGNAL,
    STREAM_ERROR_SIGNAL,
)
from app.db.redis import redis_cache
from shared.py.wide_events import log


@dataclass
class StreamProgress:
    """
    Tracks streaming progress for a conversation.

    Stored in Redis for recovery and final persistence to MongoDB.
    """

    conversation_id: str
    user_id: str
    complete_message: str = ""
    tool_data: dict[str, Any] = field(default_factory=dict)
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    is_cancelled: bool = False
    is_complete: bool = False
    error: str | None = None


class StreamManager:
    """
    Redis-backed stream manager for background execution.

    Provides pub/sub communication between background streaming tasks
    and HTTP response handlers, with progress tracking and cancellation.
    """

    # -------------------------------------------------------------------------
    # Stream Lifecycle
    # -------------------------------------------------------------------------

    @classmethod
    async def start_stream(
        cls,
        stream_id: str,
        conversation_id: str,
        user_id: str,
    ) -> None:
        """
        Initialize stream tracking in Redis.

        Call this before starting the background streaming task.

        Args:
            stream_id: Unique identifier for this stream session
            conversation_id: Associated conversation ID
            user_id: User who initiated the stream
        """
        progress = StreamProgress(
            conversation_id=conversation_id,
            user_id=user_id,
        )

        log.set(
            stream={
                "stream_id": stream_id,
                "conversation_id": conversation_id,
                "user_id": user_id,
            }
        )

        await redis_cache.set(
            f"{STREAM_PROGRESS_PREFIX}{stream_id}",
            asdict(progress),
            ttl=STREAM_TTL,
        )

        # Reverse index so a reloaded client can rediscover the in-flight turn
        # for a conversation and re-attach with full replay.
        await redis_cache.set(
            f"{STREAM_ACTIVE_PREFIX}{user_id}:{conversation_id}",
            stream_id,
            ttl=STREAM_TTL,
        )

        log.debug(
            f"{LogTag.STARTUP} Stream started for conversation",
            stream_id=stream_id,
            conversation_id=conversation_id,
        )

    @classmethod
    async def complete_stream(cls, stream_id: str) -> None:
        """
        Mark stream as complete and notify subscribers.

        Call this when streaming finishes successfully.
        """
        # Update progress to complete
        key = f"{STREAM_PROGRESS_PREFIX}{stream_id}"
        progress_data = await redis_cache.get(key)

        if progress_data:
            progress_data["is_complete"] = True
            await redis_cache.set(key, progress_data, ttl=STREAM_TTL)
            await cls._clear_active_index(progress_data)

        # Notify subscribers that stream is done
        await cls._publish(stream_id, STREAM_DONE_SIGNAL)

        log.debug(f"{LogTag.STARTUP} Stream completed", stream_id=stream_id)

    @classmethod
    async def cleanup(cls, stream_id: str) -> None:
        """
        Clean up Redis keys after stream ends.

        Call this in the finally block of background task. The replayable event
        log is intentionally KEPT until its TTL — a client that reloads right at
        completion can still re-attach and replay the finished turn.
        """
        progress_data = await redis_cache.get(f"{STREAM_PROGRESS_PREFIX}{stream_id}")
        if progress_data:
            await cls._clear_active_index(progress_data)
        await redis_cache.delete(f"{STREAM_PROGRESS_PREFIX}{stream_id}")
        await redis_cache.delete(f"{STREAM_SIGNAL_PREFIX}{stream_id}")

        log.debug(f"{LogTag.STARTUP} Stream cleaned up", stream_id=stream_id)

    @classmethod
    async def _clear_active_index(cls, progress_data: dict[str, Any]) -> None:
        """Drop the conversation -> stream reverse index for a finished stream."""
        user_id = progress_data.get("user_id")
        conversation_id = progress_data.get("conversation_id")
        if user_id and conversation_id:
            await redis_cache.delete(f"{STREAM_ACTIVE_PREFIX}{user_id}:{conversation_id}")

    @classmethod
    async def _refresh_active_index(cls, progress_data: dict[str, Any]) -> None:
        """Extend the reverse index's TTL for a turn that is still streaming.

        Without this the index is written once at start_stream and expires after
        STREAM_TTL even while the turn runs — and turns routinely outlive it
        (EXECUTOR_WAIT_TIMEOUT is 30 minutes). get_resumable_stream_id then
        reports "no turn is running" for a running turn, which the web client
        treats as authoritative and marks the user's own message failed.

        EXPIRE, not SET: a finished turn had its index deleted deliberately
        (_clear_active_index), and re-creating it here would hand a reloading
        client a stream that has already sent [DONE]. EXPIRE on a missing key is
        a no-op, so that clear stays final.
        """
        user_id = progress_data.get("user_id")
        conversation_id = progress_data.get("conversation_id")
        if user_id and conversation_id and redis_cache.redis:
            await redis_cache.redis.expire(
                f"{STREAM_ACTIVE_PREFIX}{user_id}:{conversation_id}", STREAM_TTL
            )

    @classmethod
    async def get_active_stream_id(cls, user_id: str, conversation_id: str) -> str | None:
        """Stream id of the conversation's in-flight turn, or None."""
        stream_id = await redis_cache.get(f"{STREAM_ACTIVE_PREFIX}{user_id}:{conversation_id}")
        return stream_id if isinstance(stream_id, str) else None

    @classmethod
    async def get_resumable_stream_id(cls, user_id: str, conversation_id: str) -> str | None:
        """Stream id a reloaded client can re-attach to, or None when idle.

        Validates the reverse index against progress: an indexed turn that
        already completed/cancelled (index clear still pending) is not
        resumable, so absence is reported instead of a stale stream id.
        """
        stream_id = await cls.get_active_stream_id(user_id, conversation_id)
        if not stream_id:
            return None
        progress = await cls.get_progress(stream_id)
        if not progress or progress.get("is_complete") or progress.get("is_cancelled"):
            return None
        return stream_id

    # -------------------------------------------------------------------------
    # Event-log Communication
    # -------------------------------------------------------------------------

    @classmethod
    async def publish_chunk(cls, stream_id: str, chunk: str) -> None:
        """
        Publish a streaming chunk to the stream's event log.

        Args:
            stream_id: Stream identifier
            chunk: SSE-formatted chunk to publish
        """
        await cls._publish(stream_id, chunk)

    @classmethod
    async def subscribe_stream(
        cls,
        stream_id: str,
        keepalive_interval: float = SSE_KEEPALIVE_INTERVAL_SECONDS,
        last_event_id: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """
        Read the stream's event log and yield SSE frames, then follow live.

        Replays everything after ``last_event_id`` (or from the beginning) —
        attach timing can never lose frames. Each frame carries an SSE ``id:``
        line (the Redis Stream entry id) so clients reconnect with
        ``Last-Event-ID``. Handles DONE/CANCELLED/ERROR control entries and
        yields keepalive frames during idle periods.

        Args:
            stream_id: Stream identifier
            keepalive_interval: Seconds between keepalive frames when idle
            last_event_id: Resume cursor (exclusive); None replays from start

        Yields:
            ``id:``-tagged SSE frames from the background streaming task,
            interspersed with keepalive data frames during idle periods.
        """
        if not redis_cache.redis:
            log.error(f"{LogTag.STARTUP} Redis not available for stream subscription")
            return

        events_key = f"{STREAM_EVENTS_PREFIX}{stream_id}"
        cursor = last_event_id or "0-0"
        chunks_received = 0
        block_ms = int(keepalive_interval * 1000)

        try:
            while True:
                results = await redis_cache.redis.xread(
                    {events_key: cursor}, block=block_ms, count=256
                )

                if not results:
                    # No entry within the interval — send keepalive as a data
                    # event. SSE comment format (": keepalive") triggers
                    # onmessage with empty data in @microsoft/fetch-event-source
                    # due to a spec non-compliance, causing JSON.parse("") errors.
                    yield SSE_KEEPALIVE_FRAME
                    continue

                for _key, entries in results:
                    for entry_id, fields in entries:
                        cursor = entry_id
                        data = fields.get("data", "")

                        if data == STREAM_DONE_SIGNAL:
                            log.debug(
                                f"{LogTag.STARTUP} Stream completed successfully ( chunks)",
                                stream_id=stream_id,
                                chunks_received=chunks_received,
                            )
                            return

                        if data == STREAM_CANCELLED_SIGNAL:
                            log.info(
                                f"{LogTag.STARTUP} Stream was cancelled by user",
                                stream_id=stream_id,
                            )
                            yield "data: [DONE]\n\n"
                            return

                        if data == STREAM_ERROR_SIGNAL:
                            log.error(
                                f"{LogTag.STARTUP} Stream encountered an error", stream_id=stream_id
                            )
                            progress = await cls.get_progress(stream_id)
                            error_msg = (
                                progress.get("error", "An unexpected error occurred")
                                if progress
                                else "An unexpected error occurred"
                            )
                            yield f"data: {json.dumps({'error': error_msg})}\n\n"
                            return

                        chunks_received += 1
                        yield f"id: {entry_id}\n{data}"

        except Exception as e:
            log.error(
                f"{LogTag.STARTUP} Error in stream subscription",
                stream_id=stream_id,
                error=str(e),
                error_type=type(e).__name__,
                exc_info=True,
            )
            yield f"data: {json.dumps({'error': 'Stream subscription failed'})}\n\n"
        finally:
            if chunks_received == 0:
                log.warning(
                    f"{LogTag.STARTUP} Stream ended without receiving any chunks",
                    stream_id=stream_id,
                )

    @classmethod
    async def has_events(cls, stream_id: str) -> bool:
        """Whether the stream's replayable event log still exists (pre-TTL)."""
        if not redis_cache.redis:
            return False
        return bool(await redis_cache.redis.exists(f"{STREAM_EVENTS_PREFIX}{stream_id}"))

    @classmethod
    async def _publish(cls, stream_id: str, message: str) -> None:
        """Append a message to the stream's replayable event log.

        Redis Streams (not pub/sub): entries persist until TTL/MAXLEN, and each
        gets a monotonic id that doubles as the SSE ``id:`` field — so
        subscribers can attach at any time (or reconnect with ``Last-Event-ID``)
        and replay everything they missed. This is what makes late-attach,
        reload-resume, and the init frame race structurally impossible to lose.
        """
        if redis_cache.redis:
            key = f"{STREAM_EVENTS_PREFIX}{stream_id}"
            await redis_cache.redis.xadd(
                key,
                {"data": message},
                maxlen=STREAM_EVENTS_MAXLEN,
                approximate=True,
            )
            await redis_cache.redis.expire(key, STREAM_TTL)

    # -------------------------------------------------------------------------
    # Cancellation
    # -------------------------------------------------------------------------

    @classmethod
    async def cancel_stream(cls, stream_id: str) -> bool:
        """
        Cancel a running stream.

        Sets cancellation flag and notifies subscribers.

        Returns:
            True if cancellation was set successfully
        """
        # Set cancellation signal
        await redis_cache.set(
            f"{STREAM_SIGNAL_PREFIX}{stream_id}",
            "cancelled",
            ttl=STREAM_TTL,
        )

        # Update progress
        key = f"{STREAM_PROGRESS_PREFIX}{stream_id}"
        progress_data = await redis_cache.get(key)
        if progress_data:
            progress_data["is_cancelled"] = True
            await redis_cache.set(key, progress_data, ttl=STREAM_TTL)
            await cls._clear_active_index(progress_data)

        # Notify subscribers
        await cls._publish(stream_id, STREAM_CANCELLED_SIGNAL)

        log.info(f"{LogTag.STARTUP} Stream cancelled", stream_id=stream_id)
        return True

    @classmethod
    async def is_cancelled(cls, stream_id: str) -> bool:
        """
        Check if stream has been cancelled.

        Call this periodically in the streaming loop.
        """
        signal = await redis_cache.get(f"{STREAM_SIGNAL_PREFIX}{stream_id}")
        return bool(signal == "cancelled")

    # -------------------------------------------------------------------------
    # Progress Tracking
    # -------------------------------------------------------------------------

    @classmethod
    async def update_progress(
        cls,
        stream_id: str,
        message_chunk: str = "",
        tool_data: dict[str, Any] | None = None,
    ) -> None:
        """
        Update streaming progress in Redis.

        Call this as chunks are processed to track progress.

        Args:
            stream_id: Stream identifier
            message_chunk: Text to append to complete_message
            tool_data: Tool data to merge with existing
        """
        key = f"{STREAM_PROGRESS_PREFIX}{stream_id}"
        progress_data = await redis_cache.get(key)

        if not progress_data:
            return

        if message_chunk:
            progress_data["complete_message"] = (
                progress_data.get("complete_message", "") + message_chunk
            )

        if tool_data:
            existing = progress_data.get("tool_data", {})
            # Merge tool_data arrays
            if "tool_data" in tool_data and "tool_data" in existing:
                existing["tool_data"] = existing.get("tool_data", []) + tool_data.get(
                    "tool_data", []
                )
            else:
                existing.update(tool_data)
            progress_data["tool_data"] = existing

        await redis_cache.set(key, progress_data, ttl=STREAM_TTL)
        # The turn is demonstrably alive, so keep the resume index alive with it
        # — the event log already self-refreshes on every publish_chunk.
        await cls._refresh_active_index(progress_data)

    @classmethod
    async def get_progress(cls, stream_id: str) -> dict[str, Any] | None:
        """
        Get current stream progress.

        Returns:
            Progress data dict or None if not found
        """
        return cast(
            "dict[str, Any] | None", await redis_cache.get(f"{STREAM_PROGRESS_PREFIX}{stream_id}")
        )

    @classmethod
    async def set_error(cls, stream_id: str, error: str) -> None:
        """
        Record an error in stream progress.

        Args:
            stream_id: Stream identifier
            error: Error message
        """
        key = f"{STREAM_PROGRESS_PREFIX}{stream_id}"
        progress_data = await redis_cache.get(key)

        if progress_data:
            progress_data["error"] = error
            await redis_cache.set(key, progress_data, ttl=STREAM_TTL)

        # Notify subscribers of error
        await cls._publish(stream_id, STREAM_ERROR_SIGNAL)


async def with_heartbeat(
    frames: AsyncGenerator[str, None],
    interval: float = SSE_KEEPALIVE_INTERVAL_SECONDS,
) -> AsyncGenerator[str, None]:
    """Forward ``frames``, injecting a keepalive whenever nothing has been
    yielded for ``interval`` seconds.

    ``subscribe_stream`` only emits its own keepalive when the Redis event log
    is idle, which is not the same thing as the socket being idle: a consumer
    that FILTERS frames (the bot translator drops web-only frames like
    ``tool_data``) leaves the connection silent for as long as the turn stays
    busy. A reverse proxy reads that silence as a dead upstream and hangs up
    mid-turn — nginx's stock ``proxy_read_timeout`` is 60s.

    Wrapping at the point bytes leave makes that impossible regardless of what
    any stage upstream decides to swallow, so no proxy in the path needs to be
    configured to tolerate a long-running stream.
    """
    iterator = frames.__aiter__()
    pending: asyncio.Task[str] | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(iterator.__anext__())
            try:
                # shield keeps the in-flight read alive across a heartbeat: the
                # timeout cancels the wrapper, not the pull from the event log.
                frame = await asyncio.wait_for(asyncio.shield(pending), interval)
            except TimeoutError:
                yield SSE_KEEPALIVE_FRAME
                continue
            except StopAsyncIteration:
                return
            pending = None
            yield frame
    finally:
        if pending is not None:
            # Await the cancellation before closing: the task is suspended
            # INSIDE frames.__anext__(), so the generator is still running and
            # aclose() would raise "asynchronous generator is already running"
            # — leaving the event-log subscription to be closed by GC instead
            # of here. This is the ordinary disconnect: a client that drops
            # while the turn is quiet always has a pull in flight.
            pending.cancel()
            with suppress(asyncio.CancelledError, StopAsyncIteration):
                await pending
        await frames.aclose()


# Module-level singleton for convenient imports
stream_manager = StreamManager()
