"""A conversation's output frames on one Redis Stream: the Frames port's writer and the events endpoint's reader.

Every frame is an idempotent upsert on the client (entries by seq, deltas by index), so a
reader may replay a frame it already applied; it must never miss one. The stream is
capped, and anything older than what it retains is replayed from the log.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import TypedDict

from pydantic import TypeAdapter

from app.constants.conversation import (
    EVENTS_BLOCK_MS,
    EVENTS_KEY_PREFIX,
    EVENTS_STREAM_MAXLEN,
    EVENTS_STREAM_START,
    EVENTS_STREAM_TTL_SECONDS,
)
from app.db.redis import redis_cache
from app.models.conversation_frame_models import EntryFrame, OutputFrame
from app.models.conversation_send_models import ConversationEvent
from app.services.conversation.log import state_frame
from app.services.conversation.ports import ConversationLog

_FRAME: TypeAdapter[OutputFrame] = TypeAdapter(OutputFrame)


class _StreamFields(TypedDict):
    """One stream entry's fields as this module writes them."""

    frame: str


_FIELDS: TypeAdapter[_StreamFields] = TypeAdapter(_StreamFields)


@dataclass(frozen=True)
class StreamedFrame:
    """A frame and the stream id a reader resumes after; None for a frame replayed from the log."""

    stream_id: str | None
    frame: OutputFrame


def _key(conversation_id: str) -> str:
    return f"{EVENTS_KEY_PREFIX}{conversation_id}"


class RedisStreamFrames:
    """The Frames port on the conversation's Redis Stream."""

    async def publish(self, conversation_id: str, frame: OutputFrame) -> None:
        """Append frame to the conversation's stream and keep the stream alive."""
        key = _key(conversation_id)
        await redis_cache.client.xadd(
            key, {"frame": frame.model_dump_json()}, maxlen=EVENTS_STREAM_MAXLEN
        )
        await redis_cache.client.expire(key, EVENTS_STREAM_TTL_SECONDS)


async def read_frames(
    conversation_id: str, cursor: str, *, block_ms: int = EVENTS_BLOCK_MS
) -> list[StreamedFrame]:
    """Return the frames after cursor, waiting up to block_ms for the first; empty when none came."""
    results = await redis_cache.client.xread({_key(conversation_id): cursor}, block=block_ms)
    return [
        StreamedFrame(
            stream_id=stream_id,
            frame=_FRAME.validate_json(_FIELDS.validate_python(fields)["frame"]),
        )
        for _stream, entries in results
        for stream_id, fields in entries
    ]


async def latest_frame_id(conversation_id: str) -> str:
    """Return the id of the stream's newest frame, so a reader can start after it."""
    newest = await redis_cache.client.xrevrange(_key(conversation_id), count=1)
    return newest[0][0] if newest else EVENTS_STREAM_START


async def replay_from_log(
    log: ConversationLog, conversation_id: str, user_id: str, after_seq: int
) -> list[StreamedFrame]:
    """Return the entries after after_seq and the current state, as the frames that announced them."""
    entries = await log.read_after(conversation_id, user_id, after_seq)
    state = await log.state(conversation_id, user_id)
    frames: list[OutputFrame] = [
        *(EntryFrame(seq=logged.seq, at=logged.at, entry=logged.entry) for logged in entries),
        state_frame(state),
    ]
    return [StreamedFrame(stream_id=None, frame=frame) for frame in frames]


async def follow(
    log: ConversationLog, conversation_id: str, user_id: str, after: str
) -> AsyncIterator[StreamedFrame | None]:
    """Yield every frame after the cursor, then follow live; after is a stream id or a seq.

    None follows every read that drained or timed out, so the caller can check its client is still there.

    A seq replays the log after it and then every frame the stream still holds, so an
    open reply's deltas are shown again; a stream id resumes exactly after that frame.
    """
    cursor = after
    if not _is_stream_id(after):
        for replayed in await replay_from_log(log, conversation_id, user_id, int(after or 0)):
            yield replayed
        cursor = EVENTS_STREAM_START
    while True:
        for streamed in await read_frames(conversation_id, cursor):
            if streamed.stream_id is not None:
                cursor = streamed.stream_id
            yield streamed
        yield None


def _is_stream_id(cursor: str) -> bool:
    return "-" in cursor


async def event_lines(
    log: ConversationLog,
    conversation_id: str,
    user_id: str,
    after: str,
    disconnected: Callable[[], Awaitable[bool]],
) -> AsyncIterator[str]:
    """Render the conversation's frames as SSE until the client goes; a stream frame carries its id to resume after."""
    async for streamed in follow(log, conversation_id, user_id, after):
        if await disconnected():
            return
        if streamed is None:
            yield ": keepalive\n\n"
            continue
        event = ConversationEvent(stream_id=streamed.stream_id, frame=streamed.frame)
        cursor = f"id: {streamed.stream_id}\n" if streamed.stream_id is not None else ""
        yield f"{cursor}data: {event.model_dump_json()}\n\n"
