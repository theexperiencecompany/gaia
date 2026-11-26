"""follow_screen: a follow opens on the newest page of the screen, at the log's head."""

import asyncio
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
import json

import fakeredis.aioredis
from pydantic import JsonValue
import pytest

from app.constants.chat import ARTIFACT_CARD
from app.constants.conversation import (
    EVENTS_KEY_PREFIX,
    EVENTS_RESUME_PAGE,
    EVENTS_RESUME_PAGE_GROWTH,
    EVENTS_STREAM_START,
    EventsWire,
)
from app.models.conversation_frame_models import (
    EntryFrame,
    EntryUpdatedFrame,
    OutputFrame,
    StateFrame,
    StreamPayload,
    ToolDataEvent,
    WorkDeltaFrame,
)
from app.models.conversation_log_models import DisplayState, WorkStarted
from app.models.conversation_screen_models import ScreenFrame, ScreenUpdateFrame, WorkItem
from app.services.conversation import event_stream, screen_patches
from app.services.conversation.event_stream import (
    StreamedFrame,
    UnreadableFrames,
    _unlogged,
    _until,
    event_lines,
    follow_screen,
)
from app.services.conversation.ports import ConversationLog
from app.services.conversation.screen import TOOL_CALL_CARD
from shared.py.conversation_wire import BubbleTextDelta, ReplyDeltaFrame, ToolDataEntry
from tests.helpers import captured_wide_event
from tests.unit.services.conversation.log_helpers import opened, settled, user
from tests.unit.services.conversation.runtime_doubles import Runtime

pytestmark = pytest.mark.unit

CONVERSATION = "conv-follow"
USER = "user-1"


async def test_a_follow_opens_on_the_screen_at_the_head_of_the_log() -> None:
    runtime = Runtime()
    await runtime.log.append(CONVERSATION, USER, user("u1"))
    await runtime.log.append(CONVERSATION, USER, user("u2"))

    frames = follow_screen(runtime.log, CONVERSATION, USER)
    opening = await anext(frames)
    await frames.aclose()

    assert isinstance(opening, ScreenFrame)
    assert opening.head == 2
    assert [item.id for item in opening.items] == ["u1", "u2"]


async def test_an_empty_conversation_opens_on_an_empty_screen_at_head_zero() -> None:
    frames = follow_screen(Runtime().log, CONVERSATION, USER)
    opening = await anext(frames)
    await frames.aclose()

    assert opening == ScreenFrame(items=(), head=0)


async def test_a_client_leaving_mid_wait_closes_the_follow_without_an_aclose_race() -> None:
    """Regression: cancelling the response while a frame was pending raised RuntimeError from aclose."""
    runtime = Runtime()
    await runtime.log.append(CONVERSATION, USER, user("u1"))
    lines = event_lines(
        follow_screen(runtime.log, CONVERSATION, USER), USER, _never_disconnected, asyncio.Event()
    )
    assert (await anext(lines)).startswith("data: ")
    pending = asyncio.ensure_future(anext(lines))
    await asyncio.sleep(0)
    pending.cancel()

    with pytest.raises(asyncio.CancelledError):
        await pending


async def _never_disconnected() -> bool:
    return False


_CARD: ToolDataEntry = {
    "tool_name": TOOL_CALL_CARD,
    "data": {"tool_name": "search", "tool_call_id": "c1"},
}


async def test_a_follow_patches_running_work_and_passes_deltas_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = Runtime()
    await runtime.log.append(CONVERSATION, USER, user("u1"))
    started = WorkStarted(id="work:t1", task_id="t1", cause_through=1, answers=("u1",))
    await runtime.log.append(CONVERSATION, USER, started)
    records: list[tuple[str, str]] = []

    async def work_payloads(conversation_id: str, task_id: str) -> list[StreamPayload]:
        records.append((conversation_id, task_id))
        return []

    delta = ReplyDeltaFrame(
        attempt_id="a1", reply_id="r1", index=0, payload=BubbleTextDelta(bubble=0, text="he")
    )
    followed: list[tuple[str, str, int]] = []

    async def follow(
        log: ConversationLog, conversation_id: str, user_id: str, after_seq: int
    ) -> AsyncGenerator[StreamedFrame | None]:
        followed.append((conversation_id, user_id, after_seq))
        card = WorkDeltaFrame(task_id="t1", index=0, payload=ToolDataEvent(tool_data=_CARD))
        yield StreamedFrame(stream_id="1-0", frame=card)
        yield None
        yield StreamedFrame(stream_id="2-0", frame=delta)

    monkeypatch.setattr(screen_patches, "work_payloads", work_payloads)
    monkeypatch.setattr(event_stream, "follow", follow)
    frames = follow_screen(runtime.log, CONVERSATION, USER)
    opening, patch, keepalive, passed = [await anext(frames) for _ in range(4)]
    await frames.aclose()

    assert isinstance(opening, ScreenFrame)
    assert (records, followed) == ([(CONVERSATION, "t1")], [(CONVERSATION, USER, 2)])
    assert isinstance(patch, ScreenUpdateFrame)
    assert isinstance(patch.item, WorkItem)
    assert patch.item.tool_data == (_CARD,)
    assert (keepalive, passed) == (None, delta)


async def test_a_reply_settling_as_a_follow_opens_is_replayed_before_the_state_it_settled_into(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A bot woken by a reply opens its follow while the reply settles; a state naming the settle
    # before the settle was replayed ends the follow on idle with the reply never delivered.
    settling = [settled("s3", ["u1"], 1)]

    async def settle_between_the_reads(point: str) -> None:
        if point == "state" and settling:
            await runtime.log.append(CONVERSATION, USER, settling.pop())

    async def no_frames(conversation_id: str, cursor: str) -> list[StreamedFrame]:
        return []

    async def stream_start(conversation_id: str) -> str:
        return EVENTS_STREAM_START

    runtime = Runtime()
    await runtime.log.append(CONVERSATION, USER, user("u1"))
    await runtime.log.append(CONVERSATION, USER, opened("e2", "r1"))
    runtime.log.pause = settle_between_the_reads
    monkeypatch.setattr(event_stream, "latest_frame_id", stream_start)
    monkeypatch.setattr(event_stream, "read_frames", no_frames)

    follower = event_stream.follow(runtime.log, CONVERSATION, USER, 2)
    replayed = [await anext(follower) for _ in range(2)]
    await follower.aclose()

    frames = [item.frame for item in replayed if item is not None]
    states = [frame for frame in frames if isinstance(frame, StateFrame)]
    entries = [frame.seq for frame in frames if isinstance(frame, EntryFrame)]
    assert states, frames
    assert all(seq in entries for seq in range(3, states[0].head + 1)), frames


def test_a_frame_the_log_carries_is_never_replayed_from_the_stream() -> None:
    logged = EntryFrame(seq=3, at=datetime(2026, 1, 1, tzinfo=UTC), entry=user("u3"))
    assert _unlogged(logged, None, set(), 2) is False


async def _counted(*values: int) -> AsyncGenerator[ScreenFrame | None]:
    for value in values:
        yield ScreenFrame(items=(), head=value)


async def test_a_follow_that_ends_ends_the_stream_after_its_last_frame() -> None:
    stream = _until(asyncio.Event(), _counted(1, 2))
    heads = [frame.head async for frame in stream if isinstance(frame, ScreenFrame)]
    assert heads == [1, 2]


async def test_a_stop_cuts_off_the_read_the_follow_is_blocked_in() -> None:
    blocked = asyncio.Event()
    cut_off = asyncio.Event()

    async def hangs() -> AsyncGenerator[ScreenFrame | None]:
        yield ScreenFrame(items=(), head=1)
        blocked.set()
        try:
            await asyncio.Event().wait()
        finally:
            cut_off.set()
        yield None

    stopping = asyncio.Event()
    stream = _until(stopping, hangs())
    assert await anext(stream) == ScreenFrame(items=(), head=1)
    rest = asyncio.ensure_future(anext(stream))
    await blocked.wait()
    stopping.set()
    with pytest.raises(StopAsyncIteration):
        await rest
    assert cut_off.is_set()


async def _publish(redis: fakeredis.aioredis.FakeRedis, *frames: OutputFrame) -> None:
    """Put frames on the conversation's stream as RedisStreamFrames stores them."""
    for frame in frames:
        await redis.xadd(f"{EVENTS_KEY_PREFIX}{CONVERSATION}", {"frame": frame.model_dump_json()})


async def _said(runtime: Runtime, redis: fakeredis.aioredis.FakeRedis, *ids: str) -> None:
    """Log each message and publish its entry frame, as an accepted send does."""
    for message_id in ids:
        appended = await runtime.log.append(CONVERSATION, USER, user(message_id))
        entry = appended.logged
        await _publish(redis, EntryFrame(seq=entry.seq, at=entry.at, entry=entry.entry))


async def _opening(runtime: Runtime, after: int) -> list[str]:
    frames = follow_screen(runtime.log, CONVERSATION, USER, after)
    opening = await anext(frames)
    await frames.aclose()
    assert isinstance(opening, ScreenFrame)
    assert opening.head == 3
    return [item.id for item in opening.items]


async def test_a_follow_after_a_head_the_stream_holds_opens_on_what_is_newer_and_the_newest_user_message(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    runtime = Runtime()
    await _publish(fake_redis, StateFrame(head=0, display=DisplayState.IDLE, work=()))
    await _said(runtime, fake_redis, "u1", "u2", "u3")

    assert await _opening(runtime, 0) == ["u1", "u2", "u3"]
    assert await _opening(runtime, 1) == ["u2", "u3"]
    assert await _opening(runtime, 2) == ["u3"]
    # Nothing is newer: only the message a chat platform shows typing on.
    assert await _opening(runtime, 3) == ["u3"]


async def test_a_follow_after_a_head_the_stream_does_not_hold_opens_on_the_whole_screen(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    runtime = Runtime()
    for message_id in ("u1", "u2", "u3"):
        await runtime.log.append(CONVERSATION, USER, user(message_id))
    await _publish(fake_redis, StateFrame(head=2, display=DisplayState.IDLE, work=()))

    assert await _opening(runtime, 2) == ["u1", "u2", "u3"]
    assert await _opening(runtime, 9) == ["u1", "u2", "u3"]


async def test_a_stream_holding_only_an_older_entry_s_frame_vouches_for_nothing(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    runtime = Runtime()
    await _said(runtime, fake_redis, "u1")
    for message_id in ("u2", "u3"):
        await runtime.log.append(CONVERSATION, USER, user(message_id))

    assert await _opening(runtime, 2) == ["u1", "u2", "u3"]
    assert await _opening(runtime, 1) == ["u2", "u3"]


async def test_another_conversation_s_stream_vouches_for_nothing(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    runtime = Runtime()
    for message_id in ("u1", "u2", "u3"):
        await runtime.log.append(CONVERSATION, USER, user(message_id))
    frame = EntryFrame(seq=2, at=datetime.now(UTC), entry=user("u2"))
    await fake_redis.xadd(f"{EVENTS_KEY_PREFIX}other", {"frame": frame.model_dump_json()})

    assert await _opening(runtime, 2) == ["u1", "u2", "u3"]


@pytest.mark.parametrize(
    ("amended_seq", "placed_after_head", "resumed"),
    [
        (2, True, False),
        (1, True, False),
        (3, True, True),
        (2, False, True),
    ],
    ids=["the head entry", "an older entry", "a newer entry", "before the head was reached"],
)
async def test_an_amendment_since_the_head_to_an_entry_the_client_held_opens_on_the_whole_screen(
    fake_redis: fakeredis.aioredis.FakeRedis,
    amended_seq: int,
    placed_after_head: bool,
    resumed: bool,
) -> None:
    runtime = Runtime()
    amended = EntryUpdatedFrame(seq=amended_seq, entry=user(f"u{amended_seq}"))
    await _said(runtime, fake_redis, "u1")
    if not placed_after_head:
        await _publish(fake_redis, amended)
    await _said(runtime, fake_redis, "u2")
    if placed_after_head:
        await _publish(fake_redis, amended)
    await _said(runtime, fake_redis, "u3")

    assert await _opening(runtime, 2) == (["u3"] if resumed else ["u1", "u2", "u3"])


async def test_an_amendment_two_frames_past_the_head_still_opens_on_the_whole_screen(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    runtime = Runtime()
    await _said(runtime, fake_redis, "u1", "u2", "u3")
    await _publish(fake_redis, EntryUpdatedFrame(seq=1, entry=user("u1")))

    assert await _opening(runtime, 2) == ["u1", "u2", "u3"]


async def test_a_reply_the_client_held_is_projected_with_its_conversation_s_links(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    runtime = Runtime()
    await _said(runtime, fake_redis, "u1")
    artifact: ToolDataEntry = {
        "tool_name": ARTIFACT_CARD,
        "data": {"event": "upsert", "path": "/a/report.pdf", "content_type": "application/pdf"},
    }
    reply = opened("r1").model_copy(update={"text": "here", "tool_data": (artifact,)})
    for entry in (reply, settled("s3", ["u1"], 1)):
        appended = await runtime.log.append(CONVERSATION, USER, entry)
        await _publish(
            fake_redis, EntryFrame(seq=appended.logged.seq, at=appended.logged.at, entry=entry)
        )

    assert await _opening(runtime, 3) == ["u1"]


async def test_the_newest_user_message_opens_the_screen_even_when_the_page_no_longer_reaches_it(
    fake_redis: fakeredis.aioredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(event_stream, "CONVERSATION_READ_LIMIT", 1)
    runtime = Runtime()
    await _said(runtime, fake_redis, "u1")
    reply = opened("r1").model_copy(update={"text": "here"})
    for entry in (reply, settled("s3", ["u1"], 1)):
        appended = await runtime.log.append(CONVERSATION, USER, entry)
        await _publish(
            fake_redis, EntryFrame(seq=appended.logged.seq, at=appended.logged.at, entry=entry)
        )

    assert await _opening(runtime, 0) == ["u1", "r1"]


async def test_a_follow_that_met_an_unreadable_frame_reopens_on_the_whole_screen(
    fake_redis: fakeredis.aioredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = Runtime()
    await _said(runtime, fake_redis, "u1", "u2", "u3")
    calls = 0

    async def follow(
        log: ConversationLog, conversation_id: str, user_id: str, after_seq: int
    ) -> AsyncGenerator[StreamedFrame | None]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise UnreadableFrames(conversation_id, "9-0")
        yield None

    monkeypatch.setattr(event_stream, "follow", follow)
    frames = follow_screen(runtime.log, CONVERSATION, USER, 2)
    first, second = await anext(frames), await anext(frames)
    await frames.aclose()

    assert isinstance(first, ScreenFrame) and isinstance(second, ScreenFrame)
    assert [item.id for item in first.items] == ["u3"]
    assert [item.id for item in second.items] == ["u1", "u2", "u3"]


async def _lines(runtime: Runtime, count: int, wire: EventsWire | None = None) -> list[JsonValue]:
    frames = follow_screen(runtime.log, CONVERSATION, USER)
    lines = (
        event_lines(frames, USER, _never_disconnected, asyncio.Event())
        if wire is None
        else event_lines(frames, USER, _never_disconnected, asyncio.Event(), wire)
    )
    read = [json.loads((await anext(lines)).removeprefix("data: "))["frame"] for _ in range(count)]
    await lines.aclose()
    return read


async def test_event_lines_write_whole_items_unless_the_client_reads_patches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = Runtime()
    await runtime.log.append(CONVERSATION, USER, user("u1"))
    started = WorkStarted(id="work:t1", task_id="t1", cause_through=1, answers=("u1",))
    await runtime.log.append(CONVERSATION, USER, started)

    async def follow(
        log: ConversationLog, conversation_id: str, user_id: str, after_seq: int
    ) -> AsyncGenerator[StreamedFrame | None]:
        card = WorkDeltaFrame(task_id="t1", index=0, payload=ToolDataEvent(tool_data=_CARD))
        yield StreamedFrame(stream_id="1-0", frame=card)

    async def no_payloads(conversation_id: str, task_id: str) -> list[StreamPayload]:
        return []

    monkeypatch.setattr(screen_patches, "work_payloads", no_payloads)
    monkeypatch.setattr(event_stream, "follow", follow)

    plain = [await _lines(runtime, 2), await _lines(runtime, 2, EventsWire.ITEMS)]
    patched = await _lines(runtime, 2, EventsWire.PATCHES)

    for screen, update in plain:
        assert isinstance(screen, dict) and isinstance(update, dict)
        assert update["kind"] == "screen_update"
        assert isinstance(update["item"], dict) and update["item"]["tool_data"] == [_CARD]
    screen, patch = patched
    assert isinstance(screen, dict) and isinstance(patch, dict)
    assert "tool_data" not in json.dumps(screen)
    assert (patch["kind"], patch["id"], patch["base"]) == ("screen_patch", "work:t1", 0)


@pytest.mark.parametrize("stored", ["not json", "{}", '{"kind": "entry", "seq": "two"}'])
async def test_a_stream_entry_that_is_no_frame_vouches_for_nothing_and_is_logged(
    fake_redis: fakeredis.aioredis.FakeRedis, stored: str
) -> None:
    runtime = Runtime()
    await _said(runtime, fake_redis, "u1", "u2", "u3")
    stream_id = await fake_redis.xadd(f"{EVENTS_KEY_PREFIX}{CONVERSATION}", {"frame": stored})

    async with captured_wide_event() as event:
        assert await _opening(runtime, 2) == ["u1", "u2", "u3"]
    [warning] = event["warnings"]
    assert warning["msg"] == "conversation stream frame unreadable, so it vouches for no head"
    assert (warning["conversation_id"], warning["stream_id"]) == (CONVERSATION, stream_id)


def _reply_text(index: int) -> ReplyDeltaFrame:
    return ReplyDeltaFrame(
        attempt_id="a1", reply_id="r1", index=index, payload=BubbleTextDelta(bubble=0, text="x")
    )


@pytest.fixture
def pages_read(
    fake_redis: fakeredis.aioredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> list[int | None]:
    """Record how many frames each read of the stream's newest end asked for."""
    asked: list[int | None] = []
    read = fake_redis.xrevrange

    async def counted(name: str, *, count: int | None = None) -> object:
        asked.append(count)
        return await read(name, count=count)

    monkeypatch.setattr(fake_redis, "xrevrange", counted)
    return asked


async def test_the_head_check_reads_one_page_when_the_head_is_among_the_newest_frames(
    fake_redis: fakeredis.aioredis.FakeRedis, pages_read: list[int | None]
) -> None:
    runtime = Runtime()
    await _said(runtime, fake_redis, "u1", "u2")
    await _publish(fake_redis, *(_reply_text(index) for index in range(5 * EVENTS_RESUME_PAGE)))
    await _said(runtime, fake_redis, "u3")
    pages_read.clear()

    assert await _opening(runtime, 3) == ["u3"]
    # The opening also reads the newest id once, to follow from it.
    assert [count for count in pages_read if count != 1] == [EVENTS_RESUME_PAGE]


async def test_the_head_check_reads_further_back_until_it_meets_the_head(
    fake_redis: fakeredis.aioredis.FakeRedis, pages_read: list[int | None]
) -> None:
    runtime = Runtime()
    await _said(runtime, fake_redis, "u1", "u2")
    await _publish(fake_redis, *(_reply_text(index) for index in range(EVENTS_RESUME_PAGE + 5)))
    await _said(runtime, fake_redis, "u3")
    pages_read.clear()

    assert await _opening(runtime, 2) == ["u3"]
    grown = EVENTS_RESUME_PAGE * EVENTS_RESUME_PAGE_GROWTH
    assert [count for count in pages_read if count != 1] == [EVENTS_RESUME_PAGE, grown]


async def test_an_amendment_past_the_first_page_still_opens_on_the_whole_screen(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    runtime = Runtime()
    await _said(runtime, fake_redis, "u1", "u2")
    await _publish(fake_redis, EntryUpdatedFrame(seq=1, entry=user("u1")))
    await _publish(fake_redis, *(_reply_text(index) for index in range(EVENTS_RESUME_PAGE + 5)))
    await _said(runtime, fake_redis, "u3")

    assert await _opening(runtime, 2) == ["u1", "u2", "u3"]


async def test_a_head_older_than_everything_a_long_stream_holds_opens_on_the_whole_screen(
    fake_redis: fakeredis.aioredis.FakeRedis, pages_read: list[int | None]
) -> None:
    runtime = Runtime()
    for message_id in ("u1", "u2"):
        await runtime.log.append(CONVERSATION, USER, user(message_id))
    await _publish(fake_redis, *(_reply_text(index) for index in range(EVENTS_RESUME_PAGE)))
    await _said(runtime, fake_redis, "u3")
    pages_read.clear()

    assert await _opening(runtime, 2) == ["u1", "u2", "u3"]
    grown = EVENTS_RESUME_PAGE * EVENTS_RESUME_PAGE_GROWTH
    assert [count for count in pages_read if count != 1] == [EVENTS_RESUME_PAGE, grown]
