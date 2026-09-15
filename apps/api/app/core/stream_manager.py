"""Redis-backed stream manager for background LangGraph execution, decoupled from HTTP.

Background tasks publish chunks to a Redis stream; HTTP endpoints subscribe
and replay them, so a client disconnect never stops the run. Progress is
saved to Redis for recovery, cancellation is a Redis signal, and the
conversation is always persisted to MongoDB on completion.
"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import json
import time
from typing import Any, cast

from app.constants.cache import (
    STREAM_ACTIVE_PREFIX,
    STREAM_EVENTS_MAXLEN,
    STREAM_EVENTS_PREFIX,
    STREAM_LIVENESS_REFRESH_AFTER,
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
from app.services.latency_metrics import observe_transport_redis_publish
from app.utils.message_breaks import append_message_bubble
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

        Without this it expires after STREAM_TTL even though turns often
        outlive it (EXECUTOR_WAIT_TIMEOUT is 30 min). Uses EXPIRE, not SET:
        SET would resurrect an index a finished turn already deleted; EXPIRE
        on a missing key is a no-op.
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
        await cls._touch_liveness(stream_id)

    @classmethod
    async def _touch_liveness(cls, stream_id: str) -> None:
        """Keep the resume and cancel keys alive for as long as the turn emits frames.

        Frames extend STREAM_ACTIVE/SIGNAL/PROGRESS keys because update_progress
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
        progress_data = await redis_cache.get(progress_key)
        if progress_data:
            await cls._refresh_active_index(progress_data)

    @classmethod
    async def _control_signal_frame(cls, stream_id: str, data: str) -> tuple[bool, str | None]:
        """Map a stream entry to (is_terminal, frame_to_yield).

        DONE ends the stream with no frame; CANCELLED and ERROR end it with a
        final SSE frame; a normal chunk returns (False, None) so the caller
        yields it and keeps reading.
        """
        if data == STREAM_DONE_SIGNAL:
            log.debug(f"{LogTag.STARTUP} Stream completed successfully", stream_id=stream_id)
            return True, None

        if data == STREAM_CANCELLED_SIGNAL:
            log.info(f"{LogTag.STARTUP} Stream was cancelled by user", stream_id=stream_id)
            return True, "data: [DONE]\n\n"

        if data == STREAM_ERROR_SIGNAL:
            log.error(f"{LogTag.STARTUP} Stream encountered an error", stream_id=stream_id)
            progress = await cls.get_progress(stream_id)
            error_msg = (
                progress.get("error", "An unexpected error occurred")
                if progress
                else "An unexpected error occurred"
            )
            return True, f"data: {json.dumps({'error': error_msg})}\n\n"

        return False, None

    @classmethod
    async def subscribe_stream(
        cls,
        stream_id: str,
        keepalive_interval: float = SSE_KEEPALIVE_INTERVAL_SECONDS,
        last_event_id: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """Read the stream's event log and yield SSE frames, then follow live.

        Replays everything after last_event_id so attach timing never loses
        frames. Each frame carries an SSE id: line (the Redis entry id) for
        Last-Event-ID reconnects, and DONE/CANCELLED/ERROR control entries
        end the stream.
        """
        if not redis_cache.redis:
            log.error(f"{LogTag.STARTUP} Redis not available for stream subscription")
            return

        events_key = f"{STREAM_EVENTS_PREFIX}{stream_id}"
        cursor = last_event_id or "0-0"
        # no mutate: the only read is `if not saw_chunk`, so any falsy init (False
        # vs None) is behaviourally identical — an equivalent mutant no test can kill.
        saw_chunk = False  # pragma: no mutate
        block_ms = int(keepalive_interval * 1000)

        try:
            while True:
                results = await redis_cache.redis.xread(
                    {events_key: cursor}, block=block_ms, count=256
                )

                if not results:
                    # No entry within the interval — send keepalive as a data event.
                    # SSE comment format (": keepalive") triggers onmessage with empty
                    # data in @microsoft/fetch-event-source, causing JSON.parse("") errors.
                    yield SSE_KEEPALIVE_FRAME
                    continue

                for _key, entries in results:
                    for entry_id, fields in entries:
                        cursor = entry_id
                        data = fields.get("data", "")

                        is_terminal, frame = await cls._control_signal_frame(stream_id, data)
                        if is_terminal:
                            if frame is not None:
                                yield frame
                            return

                        saw_chunk = True
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
            if not saw_chunk:
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

        Redis Streams, not pub/sub: entries persist until TTL/MAXLEN, and each
        entry's monotonic id doubles as the SSE id: field, so late-attach and
        reload-resume can replay everything a subscriber missed.
        """
        if redis_cache.redis:
            publish_start = time.perf_counter()
            key = f"{STREAM_EVENTS_PREFIX}{stream_id}"
            await redis_cache.redis.xadd(
                key,
                {"data": message},
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
        """Update streaming progress in Redis as chunks are processed."""
        key = f"{STREAM_PROGRESS_PREFIX}{stream_id}"
        progress_data = await redis_cache.get(key)

        if not progress_data:
            return

        if message_chunk:
            progress_data["pending_message"] = (
                progress_data.get("pending_message", "") + message_chunk
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
    async def settle_message_progress(cls, stream_id: str, *, discarded: bool) -> None:
        """Close the message that just ended: keep its text as a bubble, or drop it.

        Mirrors _settle_message_boundary in the graph driver. Without it a turn
        recovered from Redis glues the planning preamble onto the real reply,
        with two kept bubbles running into one sentence.
        """
        key = f"{STREAM_PROGRESS_PREFIX}{stream_id}"
        progress_data = await redis_cache.get(key)
        if not progress_data:
            return

        pending = progress_data.pop("pending_message", "")
        progress_data["pending_message"] = ""
        if pending and not discarded:
            progress_data["complete_message"] = append_message_bubble(
                progress_data.get("complete_message") or "", pending
            )
        await redis_cache.set(key, progress_data, ttl=STREAM_TTL)

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
    """Forward frames, injecting a keepalive whenever nothing is yielded for interval seconds.

    A consumer that filters frames (e.g. the bot translator) can leave the
    socket silent while the turn stays busy even though the Redis log isn't
    idle, and a reverse proxy reads that as dead — nginx's stock
    proxy_read_timeout is 60s.
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
            # Await the cancellation before closing: the task is suspended inside
            # frames.__anext__(), so aclose() would raise "asynchronous generator
            # is already running" — the ordinary case for a client that disconnects while quiet.
            pending.cancel()
            with suppress(asyncio.CancelledError, StopAsyncIteration):
                await pending
        await frames.aclose()


# Module-level singleton for convenient imports
stream_manager = StreamManager()
