"""A conversation's output frames on one Redis Stream: the Frames port's writer and the events endpoint's reader.

Every frame is an idempotent upsert on the client (entries by seq, deltas by index), so a
reader may replay a frame it already applied; it must never miss one. The stream is
capped, and anything older than what it retains is replayed from the log.
"""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass

from pydantic import BaseModel, TypeAdapter

from app.constants.chat import CONVERSATION_READ_LIMIT
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
    RetractFrame,
    WorkDeltaFrame,
    state_frame,
)
from app.models.conversation_log_models import (
    CommsPhase,
    ConversationState,
    LoggedEntry,
    Reply,
    ReplySettled,
)
from app.models.conversation_screen_models import ScreenFrame, ScreenStreamFrame
from app.models.conversation_send_models import ConversationEvent
from app.services.conversation.ports import ConversationLog
from app.services.conversation.screen_patches import ScreenTracker

_FRAME: TypeAdapter[OutputFrame] = TypeAdapter(OutputFrame)


class _StreamFields(BaseModel):
    """One stream entry's fields as this module writes them."""

    frame: str


@dataclass(frozen=True)
class StreamedFrame:
    """A frame and the stream id a reader resumes after; None for a frame replayed from the log."""

    stream_id: str | None
    frame: OutputFrame


def _key(conversation_id: str) -> str:
    return f"{EVENTS_KEY_PREFIX}{conversation_id}"


# Trims to the retention only while no reply is being written, so a reload mid-reply replays every delta it showed.
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
    """Return open while a reply is being written (drafting or open), settle once it ended, else empty."""
    match frame:
        case ReplyDeltaFrame() | EntryFrame(entry=Reply()):
            return "open"
        case EntryFrame(entry=ReplySettled()) | RetractFrame():
            return "settle"
        case _:
            return ""


class RedisStreamFrames:
    """The Frames port on the conversation's Redis Stream."""

    async def publish(self, conversation_id: str, *frames: OutputFrame) -> None:
        """Append frames in order and keep the stream alive; it is trimmed only up to the reply still open."""
        pipeline = redis_cache.client.pipeline(transaction=False)
        for frame in frames:
            pipeline.eval(
                _PUBLISH,
                2,
                _key(conversation_id),
                _open_key(conversation_id),
                frame.model_dump_json(),
                str(EVENTS_STREAM_MAXLEN),
                str(EVENTS_STREAM_TTL_SECONDS),
                _reply_mark(frame),
            )
        await pipeline.execute()


def _streamed(stream_id: str, fields: object) -> StreamedFrame:
    return StreamedFrame(
        stream_id=stream_id, frame=_FRAME.validate_json(_StreamFields.model_validate(fields).frame)
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
    log: ConversationLog, conversation_id: str, user_id: str, after_seq: int
) -> AsyncGenerator[StreamedFrame | None]:
    """Yield every frame after entry after_seq once, then follow live.

    None follows every read that drained or timed out, so the caller can check its client is still there.
    The log after after_seq is replayed first, then from the stream only what the log cannot say: the
    deltas of the reply being written and of live work, and updates to entries the client already had.
    """
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
    unseen = [streamed.frame for streamed in frames[seen + 1 :]]
    writing = state.open_reply or _drafting(unseen, state)
    live_tasks = {work.task_id for work in state.work}
    return [
        StreamedFrame(stream_id=None, frame=frame)
        for frame in unseen
        if _unlogged(frame, writing, live_tasks, after_seq)
    ]


def _drafting(frames: Sequence[OutputFrame], state: ConversationState) -> str | None:
    """Return the reply a running attempt is drafting with no entry yet: its deltas only the stream holds."""
    if state.comms is CommsPhase.IDLE:
        return None
    deltas = [frame for frame in frames if isinstance(frame, ReplyDeltaFrame)]
    if not deltas:
        return None
    last = deltas[-1]
    ended = any(
        (isinstance(frame, RetractFrame) and frame.attempt_id == last.attempt_id)
        or (
            isinstance(frame, EntryFrame)
            and isinstance(frame.entry, ReplySettled)
            and frame.entry.reply_id == last.reply_id
        )
        for frame in frames
    )
    return None if ended else last.reply_id


def _unlogged(
    frame: OutputFrame, writing: str | None, live_tasks: set[str], after_seq: int
) -> bool:
    match frame:
        case ReplyDeltaFrame(reply_id=reply_id):
            return reply_id is not None and reply_id == writing
        case WorkDeltaFrame(task_id=task_id):
            return task_id in live_tasks
        case EntryUpdatedFrame(seq=seq):
            return seq <= after_seq
        case _:
            return False


async def follow_screen(
    log: ConversationLog, conversation_id: str, user_id: str
) -> AsyncGenerator[ScreenStreamFrame | None]:
    """Yield the newest page of the screen, then its patches and the deltas of what is still being written.

    A reconnect is a fresh call: the screen it opens with is how a client heals any gap.
    """
    entries = await log.read_after(conversation_id, user_id, 0)
    tracker = await ScreenTracker.load(conversation_id, entries)
    yield ScreenFrame(items=tuple(tracker.items[-CONVERSATION_READ_LIMIT:]))
    head = entries[-1].seq if entries else 0
    async for streamed in follow(log, conversation_id, user_id, head):
        if streamed is None:
            yield None
            continue
        frame = streamed.frame
        if isinstance(frame, EntryFrame | EntryUpdatedFrame):
            for patch in tracker.take(frame):
                yield patch
        elif isinstance(frame, WorkDeltaFrame):
            for patch in await tracker.on_work(frame):
                yield patch
        else:
            yield frame


async def event_lines(
    log: ConversationLog,
    conversation_id: str,
    user_id: str,
    disconnected: Callable[[], Awaitable[bool]],
    stopping: asyncio.Event,
) -> AsyncIterator[str]:
    """Render the conversation's screen frames as SSE until the client goes or the process stops.

    A client cut off by a stopping process reconnects and opens on a fresh screen; the
    keepalive is an SSE comment, never a data line.
    """
    async for frame in _until(stopping, follow_screen(log, conversation_id, user_id)):
        if await disconnected():
            return
        if frame is None:
            yield ": keepalive\n\n"
            continue
        yield f"data: {ConversationEvent(frame=frame).model_dump_json()}\n\n"


async def _until(
    stopping: asyncio.Event, frames: AsyncGenerator[ScreenStreamFrame | None]
) -> AsyncIterator[ScreenStreamFrame | None]:
    """Yield frames until stopping is set, cutting off the read it is blocked in."""
    stopped = asyncio.ensure_future(stopping.wait())
    try:
        while True:
            following = asyncio.ensure_future(anext(frames))
            await asyncio.wait({following, stopped}, return_when=asyncio.FIRST_COMPLETED)
            if not following.done():
                following.cancel()
                await asyncio.wait({following})
                if not following.cancelled():
                    following.result()
                return
            try:
                streamed = following.result()
            except StopAsyncIteration:
                return
            yield streamed
    finally:
        stopped.cancel()
        await frames.aclose()
