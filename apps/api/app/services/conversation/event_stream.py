"""A conversation's output frames on one Redis Stream: the Frames port's writer and the events endpoint's reader.

Every frame is an idempotent upsert on the client (entries by seq, deltas by index), so a
reader may replay a frame it already applied; it must never miss one. The stream is
capped, and anything older than what it retains is replayed from the log.
"""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass

from pydantic import BaseModel, TypeAdapter, ValidationError

from app.constants.chat import CONVERSATION_READ_LIMIT
from app.constants.conversation import (
    EVENTS_BLOCK_MS,
    EVENTS_KEY_PREFIX,
    EVENTS_OPEN_REPLY_KEY_PREFIX,
    EVENTS_RESUME_PAGE,
    EVENTS_RESUME_PAGE_GROWTH,
    EVENTS_STREAM_MAXLEN,
    EVENTS_STREAM_START,
    EVENTS_STREAM_TTL_SECONDS,
    EventsWire,
)
from app.db.redis import redis_cache
from app.models.conversation_frame_models import (
    EntryFrame,
    EntryUpdatedFrame,
    OutputFrame,
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
from app.models.conversation_screen_models import (
    ScreenFrame,
    ScreenItem,
    ScreenStreamFrame,
    UserItem,
)
from app.models.conversation_send_models import ConversationEvent
from app.services.conversation.patched_wire import PatchedWire
from app.services.conversation.ports import ConversationLog
from app.services.conversation.screen import project_screen
from app.services.conversation.screen_patches import ScreenTracker
from app.services.conversation.shown_links import shown_frame
from app.utils.artifact_utils import FILE_LINKS
from shared.py.conversation_wire import FrameKind, ReplyDeltaFrame
from shared.py.wide_events import EventsResume, log as wide_log

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
            return ""  # pragma: no mutate — any mark but open or settle leaves the open key alone


class RedisStreamFrames:
    """The Frames port on the conversation's Redis Stream."""

    async def publish(self, conversation_id: str, *frames: OutputFrame) -> None:
        """Append frames in order and keep the stream alive; it is trimmed only up to the reply still open."""
        # Equivalent under mutation: each script is atomic on its own; MULTI would only wrap them.
        pipeline = redis_cache.client.pipeline(transaction=False)  # pragma: no mutate
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


class UnreadableFrames(Exception):
    """The stream holds frames another deploy wrote in a shape this code cannot read; through is the newest."""

    def __init__(self, conversation_id: str, through: str) -> None:
        super().__init__(f"unreadable frames in {conversation_id}'s stream through {through}")
        self.through = through


def _readable(
    conversation_id: str, entries: Sequence[tuple[str, object]]
) -> tuple[list[StreamedFrame], int]:
    """Return the frames this code can read, and how many it cannot, logging those loudly."""
    frames: list[StreamedFrame] = []
    for stream_id, fields in entries:
        try:
            frame = _FRAME.validate_json(_StreamFields.model_validate(fields).frame)
        except ValidationError as error:
            wide_log.warning(
                "conversation stream frame unreadable, written by another deploy",
                conversation_id=conversation_id,
                stream_id=stream_id,
                error=str(error)[:300],
            )
            continue
        frames.append(StreamedFrame(stream_id=stream_id, frame=frame))
    return frames, len(entries) - len(frames)


async def read_frames(
    conversation_id: str, cursor: str, *, block_ms: int = EVENTS_BLOCK_MS
) -> list[StreamedFrame]:
    """Return the frames after cursor, waiting up to block_ms for the first; empty when none came.

    Raises UnreadableFrames when one can't be read: the reader can't know what it missed.
    """
    results = await redis_cache.client.xread({_key(conversation_id): cursor}, block=block_ms)
    entries = [entry for _stream, stream_entries in results for entry in stream_entries]
    frames, unreadable = _readable(conversation_id, entries)
    if unreadable:
        raise UnreadableFrames(conversation_id, entries[-1][0])
    return frames


async def latest_frame_id(conversation_id: str) -> str:
    """Return the id of the stream's newest frame, so a reader can start after it."""
    # Equivalent under mutation: only the newest id is read; the count spares the rest.
    newest = await redis_cache.client.xrevrange(_key(conversation_id), count=1)  # pragma: no mutate
    return newest[0][0] if newest else EVENTS_STREAM_START


async def _log_after(
    log: ConversationLog, conversation_id: str, user_id: str, after_seq: int
) -> tuple[Sequence[LoggedEntry], ConversationState]:
    """Return the entries after after_seq through the state's head, and that state: one consistent snapshot.

    The state is read first: read second, it could name entries logged after the read, and a
    follower ends on an idle state before ever seeing the reply that settled into it.
    """
    state = await log.state(conversation_id, user_id)
    entries = await log.read_after(conversation_id, user_id, after_seq)
    # Entries logged after the state read are followed live: their frames came after the cursor.
    return [logged for logged in entries if logged.seq <= state.head], state


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
    # Frames an older deploy wrote are skipped: the screen the follower opened on came from the log.
    readable, _unreadable = _readable(
        conversation_id, await redis_cache.client.xrange(_key(conversation_id), "-", through)
    )
    frames = [streamed.frame for streamed in readable]
    seen = next(
        (
            index
            for index, frame in enumerate(frames)
            if isinstance(frame, EntryFrame) and frame.seq == after_seq
        ),
        -1,
    )
    unseen = frames[seen + 1 :]
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
        case _:  # pragma: no mutate — without it the match returns None, as falsy as False
            return False


async def follow_screen(
    log: ConversationLog, conversation_id: str, user_id: str, after: int = 0
) -> AsyncGenerator[ScreenStreamFrame | None]:
    """Yield the screen a client at entry after still lacks, then its patches and the deltas of what is being written.

    after is 0 for a client that holds nothing. A live frame another deploy wrote, which this
    code can't read, reopens on the full screen: that is how a client heals any gap.
    """
    if not after:
        wide_log.set_ns("conversation", resume=EventsResume.FRESH)
    while True:
        try:
            async for frame in _screen_from_the_head(log, conversation_id, user_id, after):
                yield frame
        except UnreadableFrames:
            after = 0


async def _screen_from_the_head(
    log: ConversationLog, conversation_id: str, user_id: str, after: int
) -> AsyncGenerator[ScreenStreamFrame | None]:
    entries = await log.read_after(conversation_id, user_id, 0)
    tracker = await ScreenTracker.load(conversation_id, entries)
    head = entries[-1].seq if entries else 0
    held = await _held_at(conversation_id, entries, after)
    # A chat platform shows typing on the newest user message, which a bot resuming after it never held.
    answering = next((item for item in reversed(tracker.items) if isinstance(item, UserItem)), None)
    page = tracker.items[-CONVERSATION_READ_LIMIT:]
    # Long work can put more than a page of items after the message it answers.
    before_page = [] if answering is None or answering in page else [answering]
    yield ScreenFrame(
        items=tuple(
            item
            for item in (*before_page, *page)
            # Running work's cards are in no entry, so its item never equals the one held at after.
            if held.get(item.id) != item or item is answering
        ),
        head=head,
    )
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


class _Positioned(BaseModel):
    """Where a stream frame sits in the log, read without building its entry."""

    kind: str
    seq: int | None = None


def _vouches(
    conversation_id: str, stream_id: str, fields: object, after: int
) -> EventsResume | None:
    """Return what one stream entry says of a client at entry after: None when it is newer and says nothing."""
    try:
        frame = _Positioned.model_validate_json(_StreamFields.model_validate(fields).frame)
    except ValidationError as error:
        # It may be the amendment or the entry looked for: the whole screen is the safe answer.
        wide_log.warning(
            "conversation stream frame unreadable, so it vouches for no head",
            conversation_id=conversation_id,
            stream_id=stream_id,
            error=str(error)[:300],
        )
        return EventsResume.FULL_UNREADABLE
    if frame.seq is None or frame.seq > after:
        return None
    # The newest frame of an entry the client held: its own, or an amendment it may have missed.
    if frame.kind != FrameKind.ENTRY:
        return EventsResume.FULL_AMENDED
    return EventsResume.RESUMED if frame.seq == after else EventsResume.FULL_NOT_HELD


async def _vouched(conversation_id: str, after: int) -> EventsResume:
    """Return RESUMED when the stream still holds entry after's frame with no amendment since to an entry at or below it.

    Read newest first, a page at a time: everything before the entry's own frame came after it,
    and a reply's deltas can put hundreds of frames past a head a page would otherwise reach.
    """
    count, read = EVENTS_RESUME_PAGE, 0
    while True:
        page = await redis_cache.client.xrevrange(_key(conversation_id), count=count)
        # Frames published since the last read sit at the front, so none past read is new.
        for stream_id, fields in page[read:]:
            verdict = _vouches(conversation_id, stream_id, fields, after)
            if verdict is not None:
                return verdict
        if len(page) < count:
            return EventsResume.FULL_NOT_HELD
        count, read = count * EVENTS_RESUME_PAGE_GROWTH, len(page)


async def _held_at(
    conversation_id: str, entries: Sequence[LoggedEntry], after: int
) -> dict[str, ScreenItem]:
    """Return the items a client that followed through entry after still holds as they stand, by id.

    Empty unless the stream vouches for it: it must still hold that entry's frame, with no
    amendment to an entry at or below it since, which the log read after it cannot show.
    """
    if after <= 0:
        return {}
    resume = await _vouched(conversation_id, after)
    wide_log.set_ns("conversation", resume=resume)
    if resume is not EventsResume.RESUMED:
        return {}
    seen = [logged for logged in entries if logged.seq <= after]
    return {item.id: item for item in project_screen(conversation_id, seen, FILE_LINKS)}


async def event_lines(
    frames: AsyncGenerator[ScreenStreamFrame | None],
    user_id: str,
    disconnected: Callable[[], Awaitable[bool]],
    stopping: asyncio.Event,
    wire: EventsWire = EventsWire.ITEMS,
) -> AsyncGenerator[str]:
    """Render a followed screen's frames as SSE, in the client's wire, until it goes or the process stops.

    A client cut off by a stopping process reconnects from the head it reached; the
    keepalive is an SSE comment, never a data line.
    """
    patched = PatchedWire() if wire is EventsWire.PATCHES else None
    async for frame in _until(stopping, frames):
        if await disconnected():
            return
        if frame is None:
            yield ": keepalive\n\n"
            continue
        shown = await shown_frame(user_id, frame)
        line = (
            ConversationEvent(frame=shown).model_dump_json()
            if patched is None
            else patched.line(shown)
        )
        yield f"data: {line}\n\n"


async def _until(
    stopping: asyncio.Event, frames: AsyncGenerator[ScreenStreamFrame | None]
) -> AsyncIterator[ScreenStreamFrame | None]:
    """Yield frames until stopping is set, cutting off the read it is blocked in."""
    stopped = asyncio.ensure_future(stopping.wait())
    following = asyncio.ensure_future(anext(frames))
    try:
        while True:
            await asyncio.wait({following, stopped}, return_when=asyncio.FIRST_COMPLETED)
            if not following.done():
                return
            try:
                streamed = following.result()
            except StopAsyncIteration:
                return
            yield streamed
            following = asyncio.ensure_future(anext(frames))
    finally:
        stopped.cancel()
        # The pending read is still inside frames (a stop, or the client leaving mid-wait);
        # it must end before frames can be closed.
        if not following.done():
            following.cancel()
            await asyncio.wait({following})
            if not following.cancelled():
                following.result()
        await frames.aclose()
