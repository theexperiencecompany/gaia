"""The conversation events stream on real Redis: what a publish writes, and what a follower replays and follows."""

from __future__ import annotations

import asyncio

import pytest
from redis.asyncio import Redis

from app.constants.conversation import (
    EVENTS_KEY_PREFIX,
    EVENTS_OPEN_REPLY_KEY_PREFIX,
    EVENTS_STREAM_START,
    EVENTS_STREAM_TTL_SECONDS,
)
from app.models.conversation_frame_models import (
    EntryFrame,
    EntryUpdatedFrame,
    OutputFrame,
    ResponseEvent,
    RetractFrame,
    WorkDeltaFrame,
    state_frame,
)
from app.models.conversation_log_models import CommsPhase, Entry
from app.models.conversation_send_models import ConversationEvent
from app.services.conversation.event_stream import (
    RedisStreamFrames,
    StreamedFrame,
    event_lines,
    follow,
    latest_frame_id,
    read_frames,
)
from shared.py.conversation_wire import BubbleTextDelta, ReplyDeltaFrame
from tests.unit.services.conversation.log_helpers import at, opened, settled, started, user
from tests.unit.services.conversation.runtime_doubles import (
    FakeClock,
    InMemoryConversationLog,
)

CID = "c-events"
UID = "u-events"
STREAM = f"{EVENTS_KEY_PREFIX}{CID}"
OPEN = f"{EVENTS_OPEN_REPLY_KEY_PREFIX}{CID}"


def _delta(attempt_id: str, reply_id: str | None, index: int = 0) -> ReplyDeltaFrame:
    return ReplyDeltaFrame(
        attempt_id=attempt_id,
        reply_id=reply_id,
        index=index,
        payload=BubbleTextDelta(bubble=0, text=f"delta {index}"),
    )


def _work(task_id: str) -> WorkDeltaFrame:
    return WorkDeltaFrame(task_id=task_id, index=0, payload=ResponseEvent(response="working"))


def _frame(seq: int, entry: Entry) -> EntryFrame:
    return EntryFrame(seq=seq, at=at(seq), entry=entry)


def _frames(streamed: list[StreamedFrame]) -> list[OutputFrame]:
    return [item.frame for item in streamed]


async def _log(*entries: Entry) -> InMemoryConversationLog:
    log = InMemoryConversationLog(FakeClock())
    for entry in entries:
        await log.append(CID, UID, entry)
    return log


async def _comms_thinking(log: InMemoryConversationLog) -> None:
    """Put comms in a running attempt, as a step does once it claims."""
    claim = await log.claim(CID, UID)
    assert claim is not None
    await log.set_comms(claim, CommsPhase.THINKING)


async def test_published_frames_are_read_back_in_order_after_any_cursor(redis: Redis) -> None:
    assert await latest_frame_id(CID) == EVENTS_STREAM_START
    frames: list[OutputFrame] = [_frame(1, user("u1")), _work("t1"), _delta("a1", None)]

    await RedisStreamFrames().publish(CID, *frames)

    streamed = await read_frames(CID, EVENTS_STREAM_START, block_ms=10)
    assert _frames(streamed) == frames
    assert all(item.stream_id is not None for item in streamed)
    assert await latest_frame_id(CID) == streamed[-1].stream_id
    assert _frames(await read_frames(CID, streamed[0].stream_id or "", block_ms=10)) == frames[1:]
    assert await read_frames(CID, streamed[-1].stream_id or "", block_ms=10) == []
    assert 0 < await redis.ttl(STREAM) <= EVENTS_STREAM_TTL_SECONDS


@pytest.mark.parametrize(
    ("frame", "open_after"),
    [
        (_delta("a1", None), True),
        (_frame(2, opened("e2")), True),
        (_frame(3, settled("e3", ["u1"], 1)), False),
        (RetractFrame(attempt_id="a1"), False),
        (_work("t1"), True),
    ],
    ids=["delta-opens", "reply-opens", "settle-closes", "retract-closes", "work-keeps"],
)
async def test_a_reply_being_written_holds_the_stream_untrimmed_until_it_ends(
    redis: Redis, frame: OutputFrame, open_after: bool
) -> None:
    await RedisStreamFrames().publish(CID, _delta("a0", None))
    assert await redis.exists(OPEN) == 1

    await RedisStreamFrames().publish(CID, frame)

    assert await redis.exists(OPEN) == int(open_after)
    if open_after:
        assert 0 < await redis.ttl(OPEN) <= EVENTS_STREAM_TTL_SECONDS


async def test_no_reply_frame_opens_nothing(redis: Redis) -> None:
    await RedisStreamFrames().publish(CID, _work("t1"), _frame(1, user("u1")))

    assert await redis.exists(OPEN) == 0
    assert await redis.xlen(STREAM) == 2


async def test_a_follower_replays_the_log_then_only_what_the_log_cannot_say(redis: Redis) -> None:
    log = await _log(user("u1"), started("w2", "live", 1), opened("e3", "r1"))
    publish = RedisStreamFrames().publish
    await publish(CID, _frame(1, user("u1")))
    await publish(
        CID,
        _delta("a1", "r1", 0),
        _delta("a0", "r0", 0),
        _work("live"),
        _work("gone"),
        EntryUpdatedFrame(seq=1, entry=user("u1")),
        EntryUpdatedFrame(seq=3, entry=opened("e3", "r1")),
    )
    state = await log.state(CID, UID)

    follower = follow(log, CID, UID, 1)
    replayed = [await anext(follower) for _ in range(6)]

    logged = await log.read_after(CID, UID, 1)
    assert [item.frame for item in replayed if item is not None] == [
        *(EntryFrame(seq=entry.seq, at=entry.at, entry=entry.entry) for entry in logged),
        state_frame(state),
        _delta("a1", "r1", 0),
        _work("live"),
        EntryUpdatedFrame(seq=1, entry=user("u1")),
    ]
    assert all(item is not None and item.stream_id is None for item in replayed)

    await publish(CID, _frame(3, opened("e3", "r1")), _frame(4, user("u4")))
    live = await anext(follower)
    assert live is not None
    assert live.frame == _frame(4, user("u4"))
    assert live.stream_id == await latest_frame_id(CID)
    await follower.aclose()


async def test_a_drafting_attempt_with_no_reply_entry_yet_is_replayed(redis: Redis) -> None:
    log = await _log(user("u1"))
    await _comms_thinking(log)
    publish = RedisStreamFrames().publish
    await publish(CID, _frame(1, user("u1")), _delta("a1", "r9", 0), _delta("a1", "r9", 1))

    follower = follow(log, CID, UID, 1)
    replayed = [await anext(follower) for _ in range(3)]

    assert [item.frame for item in replayed if item is not None][1:] == [
        _delta("a1", "r9", 0),
        _delta("a1", "r9", 1),
    ]
    await follower.aclose()


async def test_a_retracted_draft_is_not_replayed(redis: Redis) -> None:
    log = await _log(user("u1"))
    await _comms_thinking(log)
    publish = RedisStreamFrames().publish
    await publish(CID, _frame(1, user("u1")), _delta("a1", "r9", 0), RetractFrame(attempt_id="a1"))

    follower = follow(log, CID, UID, 1)
    assert isinstance((await anext(follower)).frame, type(state_frame(await log.state(CID, UID))))
    await publish(CID, _frame(2, user("u2")))

    after = await anext(follower)

    assert after is not None
    assert after.frame == _frame(2, user("u2"))
    await follower.aclose()


async def test_event_lines_render_frames_as_sse_and_stop_with_the_process(redis: Redis) -> None:
    log = await _log(user("u1"))
    stopping = asyncio.Event()
    lines = event_lines(log, CID, UID, _never, stopping)

    shown = [await anext(lines), await anext(lines)]
    assert all(line.startswith("data: ") and line.endswith("\n\n") for line in shown)
    for line in shown:
        ConversationEvent.model_validate_json(line.removeprefix("data: "))

    pending = asyncio.ensure_future(anext(lines))
    await asyncio.sleep(0.05)
    assert not pending.done()
    stopping.set()
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(pending, timeout=5)


async def test_event_lines_end_when_the_client_is_gone(redis: Redis) -> None:
    log = await _log(user("u1"))

    async def gone() -> bool:
        return True

    lines = [line async for line in event_lines(log, CID, UID, gone, asyncio.Event())]

    assert lines == []


async def _never() -> bool:
    return False
