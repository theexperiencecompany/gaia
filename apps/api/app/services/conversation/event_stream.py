"""A conversation's output frames on one Redis Stream: the Frames port's writer and the events endpoint's reader.

Every frame is an idempotent upsert on the client (entries by seq, deltas by index), so a
reader may replay a frame it already applied; it must never miss one. The stream is
capped, and anything older than what it retains is replayed from the log.
"""

from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import TypedDict

from pydantic import TypeAdapter

from app.constants.conversation import (
    EVENTS_BLOCK_MS,
    EVENTS_KEY_PREFIX,
    EVENTS_OPEN_REPLY_KEY_PREFIX,
    EVENTS_STREAM_MAXLEN,
    EVENTS_STREAM_START,
    EVENTS_STREAM_TTL_SECONDS,
)
from app.db.redis import redis_cache
from app.models.conversation_frame_models import (
    EntryFrame,
    EntryUpdatedFrame,
    OutputFrame,
    ReplyDeltaFrame,
    WorkDeltaFrame,
    state_frame,
)
from app.models.conversation_log_models import (
    ConversationState,
    LoggedEntry,
    Reply,
    ReplySettled,
)
from app.models.conversation_send_models import ConversationEvent
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


# Trims to the retention only while no reply is open, so a reload mid-reply replays every delta it showed.
_PUBLISH = """
if ARGV[4] == 'open' then
  redis.call('SET', KEYS[2], '1', 'EX', ARGV[3])
elseif ARGV[4] == 'settle' then
  redis.call('DEL', KEYS[2])
end
if redis.call('EXISTS', KEYS[2]) == 1 then
  redis.call('XADD', KEYS[1], '*', 'frame', ARGV[1])
else
  redis.call('XADD', KEYS[1], 'MAXLEN', '~', ARGV[2], '*', 'frame', ARGV[1])
end
redis.call('EXPIRE', KEYS[1], ARGV[3])
return 1
"""


def _open_key(conversation_id: str) -> str:
    return f"{EVENTS_OPEN_REPLY_KEY_PREFIX}{conversation_id}"


def _reply_mark(frame: OutputFrame) -> str:
    """Return open when frame opens a reply, settle when it settles one, else empty."""
    if isinstance(frame, EntryFrame) and isinstance(frame.entry, Reply):
        return "open"
    if isinstance(frame, EntryFrame) and isinstance(frame.entry, ReplySettled):
        return "settle"
    return ""


class RedisStreamFrames:
    """The Frames port on the conversation's Redis Stream."""

    async def publish(self, conversation_id: str, frame: OutputFrame) -> None:
        """Append frame and keep the stream alive; it is trimmed only up to the reply still open."""
        await redis_cache.client.eval(
            _PUBLISH,
            2,
            _key(conversation_id),
            _open_key(conversation_id),
            frame.model_dump_json(),
            str(EVENTS_STREAM_MAXLEN),
            str(EVENTS_STREAM_TTL_SECONDS),
            _reply_mark(frame),
        )


def _streamed(stream_id: str, fields: object) -> StreamedFrame:
    return StreamedFrame(
        stream_id=stream_id, frame=_FRAME.validate_json(_FIELDS.validate_python(fields)["frame"])
    )


async def read_frames(
    conversation_id: str, cursor: str, *, block_ms: int = EVENTS_BLOCK_MS
) -> list[StreamedFrame]:
    """Return the frames after cursor, waiting up to block_ms for the first; empty when none came."""
    results = await redis_cache.client.xread({_key(conversation_id): cursor}, block=block_ms)
    return [
        _streamed(stream_id, fields)
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
    entries, state = await _log_after(log, conversation_id, user_id, after_seq)
    return _log_frames(entries, state)


async def _log_after(
    log: ConversationLog, conversation_id: str, user_id: str, after_seq: int
) -> tuple[Sequence[LoggedEntry], ConversationState]:
    return (
        await log.read_after(conversation_id, user_id, after_seq),
        await log.state(conversation_id, user_id),
    )


def _log_frames(entries: Sequence[LoggedEntry], state: ConversationState) -> list[StreamedFrame]:
    frames: list[OutputFrame] = [
        *(EntryFrame(seq=logged.seq, at=logged.at, entry=logged.entry) for logged in entries),
        state_frame(state),
    ]
    return [StreamedFrame(stream_id=None, frame=frame) for frame in frames]


async def follow(
    log: ConversationLog, conversation_id: str, user_id: str, after: str
) -> AsyncIterator[StreamedFrame | None]:
    """Yield every frame after the cursor once, then follow live; after is a stream id or a seq.

    None follows every read that drained or timed out, so the caller can check its client is still there.
    A seq replays the log after it, then from the stream only what the log cannot say: the open
    reply's and live work's deltas, and updates to entries the client already had.
    """
    cursor, covered = after, 0
    if not _is_stream_id(after):
        after_seq = int(after or 0)
        # Taken before the log read, so a frame published after it is followed live, never lost.
        cursor = await latest_frame_id(conversation_id)
        entries, state = await _log_after(log, conversation_id, user_id, after_seq)
        for replayed in _log_frames(entries, state):
            yield replayed
        for unlogged in await _unlogged_frames(conversation_id, cursor, state, after_seq):
            yield unlogged
        covered = entries[-1].seq if entries else after_seq
    while True:
        for streamed in await read_frames(conversation_id, cursor):
            if streamed.stream_id is not None:
                cursor = streamed.stream_id
            if not (isinstance(streamed.frame, EntryFrame) and streamed.frame.seq <= covered):
                yield streamed
        yield None


async def _unlogged_frames(
    conversation_id: str, through: str, state: ConversationState, after_seq: int
) -> list[StreamedFrame]:
    """Return the stream's frames up to through that came after entry after_seq and that no log entry carries yet."""
    if through == EVENTS_STREAM_START:
        return []
    raw = await redis_cache.client.xrange(_key(conversation_id), "-", through)
    frames = [_streamed(stream_id, fields) for stream_id, fields in raw]
    seen = next(
        (
            index
            for index, streamed in enumerate(frames)
            if isinstance(streamed.frame, EntryFrame) and streamed.frame.seq == after_seq
        ),
        -1,
    )
    live_tasks = {work.task_id for work in state.work}
    return [
        streamed
        for streamed in frames[seen + 1 :]
        if _unlogged(streamed.frame, state.open_reply, live_tasks, after_seq)
    ]


def _unlogged(
    frame: OutputFrame, open_reply: str | None, live_tasks: set[str], after_seq: int
) -> bool:
    match frame:
        case ReplyDeltaFrame(reply_id=reply_id):
            return reply_id is not None and reply_id == open_reply
        case WorkDeltaFrame(task_id=task_id):
            return task_id in live_tasks
        case EntryUpdatedFrame(seq=seq):
            return seq <= after_seq
        case _:
            return False


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
