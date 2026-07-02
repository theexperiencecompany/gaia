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

from collections.abc import AsyncGenerator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import json
from typing import Any

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

        log.debug(f"{LogTag.STARTUP} Stream {stream_id} started for conversation {conversation_id}")

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

        log.debug(f"{LogTag.STARTUP} Stream {stream_id} completed")

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

        log.debug(f"{LogTag.STARTUP} Stream {stream_id} cleaned up")

    @classmethod
    async def _clear_active_index(cls, progress_data: dict[str, Any]) -> None:
        """Drop the conversation -> stream reverse index for a finished stream."""
        user_id = progress_data.get("user_id")
        conversation_id = progress_data.get("conversation_id")
        if user_id and conversation_id:
            await redis_cache.delete(f"{STREAM_ACTIVE_PREFIX}{user_id}:{conversation_id}")

    @classmethod
    async def get_active_stream_id(cls, user_id: str, conversation_id: str) -> str | None:
        """Stream id of the conversation's in-flight turn, or None."""
        stream_id = await redis_cache.get(f"{STREAM_ACTIVE_PREFIX}{user_id}:{conversation_id}")
        return stream_id if isinstance(stream_id, str) else None

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
        keepalive_interval: float = 15,
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
                    yield 'data: {"keepalive":true}\n\n'
                    continue

                for _key, entries in results:
                    for entry_id, fields in entries:
                        cursor = entry_id
                        data = fields.get("data", "")

                        if data == STREAM_DONE_SIGNAL:
                            log.debug(
                                f"{LogTag.STARTUP} Stream {stream_id} completed successfully "
                                f"({chunks_received} chunks)"
                            )
                            return

                        if data == STREAM_CANCELLED_SIGNAL:
                            log.info(f"{LogTag.STARTUP} Stream {stream_id} was cancelled by user")
                            yield "data: [DONE]\n\n"
                            return

                        if data == STREAM_ERROR_SIGNAL:
                            log.error(f"{LogTag.STARTUP} Stream {stream_id} encountered an error")
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
                f"{LogTag.STARTUP} Error in stream subscription {stream_id}: {e}", exc_info=True
            )
            yield f"data: {json.dumps({'error': 'Stream subscription failed'})}\n\n"
        finally:
            if chunks_received == 0:
                log.warning(
                    f"{LogTag.STARTUP} Stream {stream_id} ended without receiving any chunks"
                )

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

        log.info(f"{LogTag.STARTUP} Stream {stream_id} cancelled")
        return True

    @classmethod
    async def is_cancelled(cls, stream_id: str) -> bool:
        """
        Check if stream has been cancelled.

        Call this periodically in the streaming loop.
        """
        signal = await redis_cache.get(f"{STREAM_SIGNAL_PREFIX}{stream_id}")
        return signal == "cancelled"

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

    @classmethod
    async def get_progress(cls, stream_id: str) -> dict[str, Any] | None:
        """
        Get current stream progress.

        Returns:
            Progress data dict or None if not found
        """
        return await redis_cache.get(f"{STREAM_PROGRESS_PREFIX}{stream_id}")

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


# Module-level singleton for convenient imports
stream_manager = StreamManager()
