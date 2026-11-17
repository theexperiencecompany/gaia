"""entry_outcome: an entry's outcome is final only once nothing it caused is running or unanswered."""

import asyncio
from collections.abc import Sequence

import pytest

from app.models.conversation_frame_models import EntryFrame
from app.models.conversation_log_models import Entry, LoggedEntry, Reply, WorkOutcome, WorkStarted
from app.services.conversation import outcome as outcome_module
from app.services.conversation.event_stream import StreamedFrame, UnreadableFrames
from app.services.conversation.outcome import STOPPED, EntryOutcome, await_outcome, entry_outcome
from shared.py.conversation_wire import BubbleTextDelta, ReplyDeltaFrame, ReplyOutcome
from tests.unit.services.conversation.log_helpers import (
    finished,
    fired,
    fold,
    logged,
    opened,
    settled,
    stop,
    user,
)
from tests.unit.services.conversation.runtime_doubles import (
    CONVERSATION,
    USER,
    FakeClock,
    InMemoryConversationLog,
)


def _work(entry_id: str, task_id: str, cause_through: int, answers: Sequence[str]) -> WorkStarted:
    return WorkStarted(
        id=entry_id, task_id=task_id, cause_through=cause_through, answers=tuple(answers)
    )


def _reply(entry_id: str, reply_id: str, text: str) -> Reply:
    return Reply(id=entry_id, reply_id=reply_id, attempt_id=f"a-{reply_id}", text=text)


def _outcome(entries: Sequence[Entry]) -> EntryOutcome | None:
    state, _ = fold(entries)
    log: list[LoggedEntry] = [logged(seq, entry) for seq, entry in enumerate(entries, start=1)]
    return entry_outcome("wf", log, state)


def test_an_entry_answered_with_no_work_is_final_with_its_reply() -> None:
    outcome = _outcome([fired("wf"), _reply("o1", "r1", "your brief"), settled("s1", ["wf"], 1)])
    assert outcome is not None
    assert (outcome.failure, outcome.text) == (None, "your brief")


def test_an_entry_is_not_final_while_the_work_it_caused_runs() -> None:
    entries: list[Entry] = [
        fired("wf"),
        _work("w1", "t1", 1, ["wf"]),
        _reply("o1", "r1", "on it"),
        settled("s1", ["wf"], 1),
    ]
    assert _outcome(entries) is None


def test_an_entry_is_not_final_while_its_finished_work_awaits_its_reply() -> None:
    entries: list[Entry] = [
        fired("wf"),
        _work("w1", "t1", 1, ["wf"]),
        _reply("o1", "r1", "on it"),
        settled("s1", ["wf"], 1),
        finished("f1", "t1"),
    ]
    assert _outcome(entries) is None


def test_the_work_reply_that_answers_it_last_is_its_outcome() -> None:
    entries: list[Entry] = [
        fired("wf"),
        _work("w1", "t1", 1, ["wf"]),
        _reply("o1", "r1", "on it"),
        settled("s1", ["wf"], 1),
        finished("f1", "t1"),
        _reply("o2", "t1", "here are your emails"),
        settled("s2", ["f1", "wf"], 6, reply_id="t1"),
    ]
    outcome = _outcome(entries)
    assert outcome is not None
    assert (outcome.failure, outcome.text) == (None, "here are your emails")
    assert [work.task_id for work in outcome.work] == ["t1"]


def test_failed_work_fails_the_entry_even_when_its_reply_answered() -> None:
    entries: list[Entry] = [
        fired("wf"),
        _work("w1", "t1", 1, ["wf"]),
        _reply("o1", "r1", "on it"),
        settled("s1", ["wf"], 1),
        finished("f1", "t1", WorkOutcome.FAILED),
        _reply("o2", "t1", "it failed"),
        settled("s2", ["f1", "wf"], 5, reply_id="t1"),
    ]
    outcome = _outcome(entries)
    assert outcome is not None
    assert outcome.failure == "work failed: report"


def test_a_failed_reply_fails_the_entry() -> None:
    entries: list[Entry] = [
        fired("wf"),
        _reply("o1", "r1", ""),
        settled("s1", ["wf"], 1, outcome=ReplyOutcome.FAILED),
    ]
    outcome = _outcome(entries)
    assert outcome is not None
    assert outcome.failure == "server_restart"


def test_a_stop_before_any_reply_ends_the_entry_as_stopped() -> None:
    outcome = _outcome([fired("wf"), stop("x")])
    assert outcome is not None
    assert (outcome.failure, outcome.settled) == (STOPPED, None)


def test_a_reply_to_another_input_does_not_finish_the_entry() -> None:
    entries: list[Entry] = [
        user("u1"),
        fired("wf"),
        _reply("o1", "r1", "hi"),
        settled("s1", ["u1"], 1),
    ]
    state, _ = fold(entries)
    log = [logged(seq, entry) for seq, entry in enumerate(entries, start=1)]
    assert entry_outcome("wf", log[1:], state) is None


@pytest.mark.usefixtures("fake_redis")
async def test_an_outcome_read_while_the_reply_settles_still_sees_the_settle() -> None:
    log = InMemoryConversationLog(FakeClock())
    first = await log.append(CONVERSATION, USER, user("u1"))
    claim = await log.claim(CONVERSATION, USER)
    assert claim is not None
    await log.append_fenced(claim, opened("o1"))
    settling = [settled("s1", ["u1"], 1)]

    async def settle_mid_read(point: str) -> None:
        if point == "state" and settling:
            await log.append_fenced(claim, settling.pop())

    log.pause = settle_mid_read
    outcome = await await_outcome(log, CONVERSATION, USER, first.logged, timeout=1)

    assert outcome.settled is not None
    assert outcome.settled.outcome is ReplyOutcome.ANSWERED


def test_an_entry_stopped_after_its_work_ended_keeps_that_works_end() -> None:
    work = _work("w1", "t1", 1, ["wf"])
    done = finished("f1", "t1", WorkOutcome.FAILED)
    outcome = _outcome([fired("wf"), work, done, stop("x")])
    assert outcome is not None
    assert (outcome.failure, outcome.work) == (STOPPED, (done,))


class _Stream:
    """The conversation's frame stream as await_outcome reads it: frames after a cursor, or a wait."""

    def __init__(self) -> None:
        self.frames: list[StreamedFrame] = []
        self.reads = 0
        self._moved = asyncio.Event()

    def publish(self, frame: EntryFrame | ReplyDeltaFrame) -> None:
        self.frames.append(StreamedFrame(stream_id=f"{len(self.frames) + 1}-0", frame=frame))
        self._moved.set()

    async def latest(self, conversation_id: str) -> str:
        assert conversation_id == CONVERSATION
        return self.frames[-1].stream_id or "" if self.frames else "0-0"

    async def read(self, conversation_id: str, cursor: str) -> list[StreamedFrame]:
        assert conversation_id == CONVERSATION
        self.reads += 1
        await asyncio.sleep(0)
        after = [f for f in self.frames if (f.stream_id or "") > cursor]
        if after:
            return after
        self._moved.clear()
        await self._moved.wait()
        return [f for f in self.frames if (f.stream_id or "") > cursor]


@pytest.fixture
def stream(monkeypatch: pytest.MonkeyPatch) -> _Stream:
    frames = _Stream()
    monkeypatch.setattr(outcome_module, "latest_frame_id", frames.latest)
    monkeypatch.setattr(outcome_module, "read_frames", frames.read)
    return frames


async def test_an_outcome_not_yet_final_is_read_again_only_once_a_frame_says_the_log_moved(
    stream: _Stream,
) -> None:
    log = InMemoryConversationLog(FakeClock())
    first = await log.append(CONVERSATION, USER, user("u1"))
    # A frame from before the wait began never wakes it.
    stream.publish(EntryFrame(seq=1, at=first.logged.at, entry=user("u1")))
    reads: list[str] = []

    async def count_reads(point: str) -> None:
        if point == "state":
            reads.append(point)

    log.pause = count_reads
    waiting = asyncio.create_task(await_outcome(log, CONVERSATION, USER, first.logged, timeout=5))
    await asyncio.sleep(0.05)
    assert (waiting.done(), len(reads)) == (False, 1)
    claim = await log.claim(CONVERSATION, USER)
    assert claim is not None
    # A delta moves no entry: the wait reads past it without reading the log again.
    stream.publish(
        ReplyDeltaFrame(
            attempt_id="a1", reply_id="r1", index=0, payload=BubbleTextDelta(bubble=0, text="he")
        )
    )
    await asyncio.sleep(0.05)
    assert (waiting.done(), len(reads), stream.reads) == (False, 1, 2)
    await log.append_fenced(claim, _reply("o1", "r1", "hello"))
    answered = await log.append_fenced(claim, settled("s1", ["u1"], 1))
    stream.publish(
        EntryFrame(seq=answered.logged.seq, at=answered.logged.at, entry=answered.logged.entry)
    )
    outcome = await asyncio.wait_for(waiting, timeout=2)
    assert (outcome.text, len(reads), stream.reads) == ("hello", 2, 2)


async def test_an_outcome_that_never_settles_times_out(stream: _Stream) -> None:
    log = InMemoryConversationLog(FakeClock())
    first = await log.append(CONVERSATION, USER, user("u1"))
    with pytest.raises(TimeoutError):
        await await_outcome(log, CONVERSATION, USER, first.logged, timeout=0.05)


async def test_a_block_of_replayed_frames_keeps_the_wait_at_its_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delta = ReplyDeltaFrame(
        attempt_id="a1", reply_id="r1", index=0, payload=BubbleTextDelta(bubble=0, text="he")
    )
    blocks = [[StreamedFrame(stream_id=None, frame=delta)], []]
    cursors: list[str] = []

    async def read(conversation_id: str, cursor: str) -> list[StreamedFrame]:
        cursors.append(cursor)
        return blocks.pop(0)

    monkeypatch.setattr(outcome_module, "read_frames", read)
    assert await outcome_module._until_the_log_moves(CONVERSATION, "7-0") == "7-0"
    assert cursors == ["7-0", "7-0"]


async def test_an_unreadable_frame_ends_the_wait_after_it_so_the_log_is_reread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def read(conversation_id: str, cursor: str) -> list[StreamedFrame]:
        raise UnreadableFrames(conversation_id, "9-0")

    monkeypatch.setattr(outcome_module, "read_frames", read)
    assert await outcome_module._until_the_log_moves(CONVERSATION, "7-0") == "9-0"
