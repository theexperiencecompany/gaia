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

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, Optional

from app.config.loggers import chat_logger as logger
from app.constants.streaming import (
    STREAM_CANCELLED_SIGNAL,
    STREAM_CHANNEL_PREFIX,
    STREAM_DONE_SIGNAL,
    STREAM_ERROR_SIGNAL,
    STREAM_PROGRESS_PREFIX,
    STREAM_SIGNAL_PREFIX,
    STREAM_TTL,
)
from app.db.redis import redis_cache


@dataclass
class StreamProgress:
    """
    Tracks streaming progress for a conversation.

    Stored in Redis for recovery and final persistence to MongoDB.
    """

    conversation_id: str
    user_id: str
    complete_message: str = ""
    tool_data: Dict[str, Any] = field(default_factory=dict)
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    is_cancelled: bool = False
    is_complete: bool = False
    error: Optional[str] = None


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

        await redis_cache.set(
            f"{STREAM_PROGRESS_PREFIX}{stream_id}",
            asdict(progress),
            ttl=STREAM_TTL,
        )

        logger.debug(f"Stream {stream_id} started for conversation {conversation_id}")

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

        # Notify subscribers that stream is done
        await cls._publish(stream_id, STREAM_DONE_SIGNAL)

        logger.debug(f"Stream {stream_id} completed")

    @classmethod
    async def cleanup(cls, stream_id: str) -> None:
        """
        Clean up Redis keys after stream ends.

        Call this in the finally block of background task.
        """
        await redis_cache.delete(f"{STREAM_PROGRESS_PREFIX}{stream_id}")
        await redis_cache.delete(f"{STREAM_SIGNAL_PREFIX}{stream_id}")

        logger.debug(f"Stream {stream_id} cleaned up")

    # -------------------------------------------------------------------------
    # Pub/Sub Communication
    # -------------------------------------------------------------------------

    @classmethod
    async def publish_chunk(cls, stream_id: str, chunk: str) -> None:
        """
        Publish a streaming chunk to the Redis channel.

        Args:
            stream_id: Stream identifier
            chunk: SSE-formatted chunk to publish
        """
        await cls._publish(stream_id, chunk)

    @classmethod
    async def subscribe_stream(cls, stream_id: str) -> AsyncGenerator[str, None]:
        """
        Subscribe to stream channel and yield chunks.

        Use this in the HTTP endpoint to forward chunks to the client.
        Automatically handles DONE and CANCELLED signals.

        Yields:
            SSE-formatted chunks from the background streaming task
        """
        if not redis_cache.redis:
            logger.error("Redis not available for stream subscription")
            return

        pubsub = redis_cache.redis.pubsub()
        channel = f"{STREAM_CHANNEL_PREFIX}{stream_id}"

        try:
            await pubsub.subscribe(channel)
            logger.debug(f"Subscribed to stream channel: {channel}")

            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue

                data = message["data"]

                # Handle control signals
                if data == STREAM_DONE_SIGNAL:
                    logger.debug(f"Stream {stream_id} received DONE signal")
                    break

                if data == STREAM_CANCELLED_SIGNAL:
                    logger.debug(f"Stream {stream_id} received CANCELLED signal")
                    yield "data: [DONE]\n\n"
                    break

                if data == STREAM_ERROR_SIGNAL:
                    logger.debug(f"Stream {stream_id} received ERROR signal")
                    break

                # Forward chunk to client
                yield data

        except Exception as e:
            logger.error(f"Error in stream subscription {stream_id}: {e}")
        finally:
            try:
                await pubsub.unsubscribe(channel)
                await pubsub.close()
            except Exception:  # nosec B110 - Intentional: cleanup should not raise
                pass

    @classmethod
    async def _publish(cls, stream_id: str, message: str) -> None:
        """Internal: Publish message to stream channel."""
        if redis_cache.redis:
            await redis_cache.redis.publish(
                f"{STREAM_CHANNEL_PREFIX}{stream_id}",
                message,
            )

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

        # Notify subscribers
        await cls._publish(stream_id, STREAM_CANCELLED_SIGNAL)

        logger.info(f"Stream {stream_id} cancelled")
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
        tool_data: Optional[Dict[str, Any]] = None,
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
    async def get_progress(cls, stream_id: str) -> Optional[Dict[str, Any]]:
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
