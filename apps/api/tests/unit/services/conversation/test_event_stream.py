"""follow_screen: a follow opens on the newest page of the screen, at the log's head."""

import asyncio
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest

from app.constants.conversation import EVENTS_STREAM_START
from app.models.conversation_frame_models import (
    EntryFrame,
    StateFrame,
    StreamPayload,
    ToolDataEvent,
    WorkDeltaFrame,
)
from app.models.conversation_log_models import WorkStarted
from app.models.conversation_screen_models import ScreenFrame, ScreenUpdateFrame, WorkItem
from app.services.conversation import event_stream, screen_patches
from app.services.conversation.event_stream import (
    StreamedFrame,
    _unlogged,
    _until,
    event_lines,
    follow_screen,
)
from app.services.conversation.ports import ConversationLog
from app.services.conversation.screen import TOOL_CALL_CARD
from shared.py.conversation_wire import BubbleTextDelta, ReplyDeltaFrame, ToolDataEntry
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
