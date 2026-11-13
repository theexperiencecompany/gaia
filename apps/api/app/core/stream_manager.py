"""Redis-backed stream manager for background LangGraph execution, decoupled from HTTP.

Background tasks publish chunks to a Redis stream; HTTP endpoints subscribe
and replay them, so a client disconnect never stops the run. Progress is
saved to Redis for recovery, cancellation is a Redis signal, and the
conversation is always persisted to MongoDB on completion.
"""

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import time
from typing import Any, TypedDict, cast

from app.constants.cache import (
    STREAM_EVENTS_MAXLEN,
    STREAM_EVENTS_PREFIX,
    STREAM_LIVENESS_REFRESH_AFTER,
    STREAM_PROGRESS_PREFIX,
    STREAM_SIGNAL_PREFIX,
    STREAM_TTL,
)
from app.constants.log_tags import LogTag
from app.constants.streaming import (
    STREAM_CANCELLED_SIGNAL,
    STREAM_DONE_SIGNAL,
)
from app.db.redis import redis_cache
from app.services.latency_metrics import observe_transport_redis_publish
from shared.py.wide_events import log


@dataclass
class StreamProgress:
    """
    Tracks streaming progress for a conversation.

    Stored in Redis for recovery and final persistence to MongoDB.
    """

    conversation_id: str
    user_id: str
    #: Settled bubbles only — text whose message reached a boundary that kept it.
    complete_message: str = ""
    #: Text since the last boundary, held out of complete_message: a message
    #: that goes on to announce a tool call is a preamble the user must not
    #: keep; the driver's own accumulator holds it the same way.
    pending_message: str = ""
    tool_data: dict[str, Any] = field(default_factory=dict)
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    is_cancelled: bool = False
    is_complete: bool = False
    error: str | None = None


class StreamProgressRecord(TypedDict, total=False):
    """StreamProgress as start_stream stores it in Redis; every read tolerates a missing key."""

    conversation_id: str
    user_id: str
    complete_message: str
    pending_message: str
    # Not ProgressToolData: services/chat/state.py adopts it as its dict tool_data accumulator.
    tool_data: Mapping[str, object]
    started_at: str
    is_cancelled: bool
    is_complete: bool
    error: str | None


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
        """Initialize stream tracking in Redis before starting the background streaming task."""
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
        progress_data: StreamProgressRecord | None = await cls.get_progress(stream_id)

        if progress_data:
            progress_data["is_complete"] = True
            await redis_cache.set(key, progress_data, ttl=STREAM_TTL)

        # Notify subscribers that stream is done
        await cls._publish(stream_id, STREAM_DONE_SIGNAL)

        log.debug(f"{LogTag.STARTUP} Stream completed", stream_id=stream_id)

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
        await cls._touch_liveness(stream_id)

    @classmethod
    async def _touch_liveness(cls, stream_id: str) -> None:
        """Keep the stream's progress key alive for as long as the run emits frames.

        Frames extend the PROGRESS key because update_progress
        alone missed executor-parked turns (30 min). Uses EXPIRE, not SET, so a
        finished turn's deleted keys stay gone; the TTL read throttles refreshes.
        """
        if not redis_cache.redis:
            return
        progress_key = f"{STREAM_PROGRESS_PREFIX}{stream_id}"
        ttl = await redis_cache.redis.ttl(progress_key)
        if ttl < 0 or ttl > STREAM_LIVENESS_REFRESH_AFTER:
            return
        await redis_cache.redis.expire(progress_key, STREAM_TTL)

    @classmethod
    async def _publish(cls, stream_id: str, message: str, error: str | None = None) -> None:
        """Append a message to the stream's replayable event log.

        Redis Streams, not pub/sub: entries persist until TTL/MAXLEN, and each
        entry's monotonic id doubles as the SSE id: field, so late-attach and
        reload-resume can replay everything a subscriber missed.
        """
        if redis_cache.redis:
            publish_start = time.perf_counter()
            key = f"{STREAM_EVENTS_PREFIX}{stream_id}"
            fields = {"data": message} if error is None else {"data": message, "error": error}
            await redis_cache.redis.xadd(
                key,
                fields,
                maxlen=STREAM_EVENTS_MAXLEN,
                approximate=True,
            )
            await redis_cache.redis.expire(key, STREAM_TTL)
            observe_transport_redis_publish(time.perf_counter() - publish_start)

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
        progress_data: StreamProgressRecord | None = await cls.get_progress(stream_id)
        if progress_data:
            progress_data["is_cancelled"] = True
            await redis_cache.set(key, progress_data, ttl=STREAM_TTL)

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
    async def get_progress(cls, stream_id: str) -> StreamProgressRecord | None:
        """Get current stream progress, or None if not found."""
        # Only start_stream writes this key, from asdict(StreamProgress).
        return cast(
            "StreamProgressRecord | None",
            await redis_cache.get(f"{STREAM_PROGRESS_PREFIX}{stream_id}"),
        )


# Module-level singleton for convenient imports
stream_manager = StreamManager()
