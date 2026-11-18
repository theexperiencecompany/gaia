"""The step's writes, scenario by scenario: segments, quotes, carried bubbles, frame addresses and the log reads they spend."""

from collections import Counter

import pytest

from app.constants.chat import ConversationSource
from app.models.conversation_frame_models import ResponseEvent, RetractFrame
from app.models.conversation_log_models import Entry, Reply, ReplySettled, UserMessage, WorkStarted
from app.services.conversation.log import accept
from app.services.conversation.ports import Finished, ModelOutput, Replied, Streamed
from app.services.conversation.step import advance
from shared.py.analytics.catalog.chat import ChatMessageCompleted
from shared.py.conversation_wire import (
    NEW_MESSAGE_BREAKER,
    BubbleTextDelta,
    ReplyDeltaFrame,
    ReplyOutcome,
)
from tests.helpers import captured_wide_event
from tests.unit.services.conversation.log_helpers import asked, user
from tests.unit.services.conversation.runtime_doubles import (
    CONVERSATION,
    USER,
    Absorbed,
    Action,
    Close,
    Do,
    RecordingAnalytics,
    Runtime,
    ScriptedRun,
    Started,
)


def text(chunk: str) -> Streamed:
    return Streamed(payload=ResponseEvent(response=chunk))


async def send(rt: Runtime, *entries: Entry) -> None:
    for entry in entries:
        await accept(rt.ports, CONVERSATION, USER, entry)


def arrive(rt: Runtime, entry_id: str) -> Action:
    async def action() -> None:
        await send(rt, user(entry_id))

    return action


def counting_log_calls(rt: Runtime) -> Counter[str]:
    """Count every call made on the log, by method, from now on."""
    calls: Counter[str] = Counter()

    async def count(point: str) -> None:
        if not point.endswith(":done"):
            calls[point] += 1

    rt.log.pause = count
    return calls


async def run(rt: Runtime) -> None:
    await advance(rt.ports, CONVERSATION, USER)


async def replies(rt: Runtime) -> list[Reply]:
    return [item.entry for item in await rt.entries() if isinstance(item.entry, Reply)]


async def settles(rt: Runtime) -> list[ReplySettled]:
    return [item.entry for item in await rt.entries() if isinstance(item.entry, ReplySettled)]


async def test_each_handed_message_opens_its_own_numbered_segment_below_it() -> None:
    rt = Runtime()
    rt.runner.script(
        [
            text("a"),
            Do(arrive(rt, "u2")),
            ModelOutput(True),
            text("b"),
            Close(seqs=(3,)),
            Do(arrive(rt, "u3")),
            ModelOutput(True),
            text("c"),
            Finished(Replied("c")),
        ]
    )
    await send(rt, user("u1"))
    await run(rt)
    assert [(reply.text, reply.attempt_id) for reply in await replies(rt)] == [
        ("a", "1.1"),
        ("b", "1.1/1"),
        ("c", "1.1/2"),
    ]
    # "a" sits above u2, so it answers nothing; "b" names u2; "c" closes what is left.
    assert [(item.answers, item.outcome) for item in await settles(rt)] == [
        ((), ReplyOutcome.INTERIM),
        (("u2",), ReplyOutcome.ANSWERED),
        (("u1", "u3"), ReplyOutcome.ANSWERED),
    ]


async def test_a_settled_segment_stays_committed_so_a_later_message_waits_instead_of_restarting() -> (
    None
):
    rt = Runtime()
    rt.runner.script(
        [
            text("on it"),
            Do(arrive(rt, "u2")),
            ModelOutput(True),
            ModelOutput(True),
            Do(arrive(rt, "u3")),
            text("both"),
            Finished(Replied("both")),
        ],
        [Finished(Replied("three"))],
    )
    await send(rt, user("u1"))
    await run(rt)
    seq_of = {item.entry.id: item.seq for item in await rt.entries()}
    assert rt.runner.calls[:2] == [Started(batch=(1,), context=()), Absorbed((3,))]
    assert [call.batch for call in rt.runner.calls[2:] if isinstance(call, Started)] == [
        (seq_of["u3"],)
    ]
    assert [reply.text for reply in await replies(rt)] == ["on it", "both", "three"]
    assert [item.answers for item in await settles(rt)] == [(), ("u1", "u2"), ("u3",)]


async def test_a_reply_opening_below_a_message_that_arrived_after_commit_quotes_what_it_answers() -> (
    None
):
    rt = Runtime()
    rt.runner.script(
        [ModelOutput(False), Do(arrive(rt, "u2")), text("for u1"), Finished(Replied("for u1"))],
        [Finished(Replied("for u2"))],
    )
    await send(rt, user("u1"))
    await run(rt)
    first, _ = await replies(rt)
    assert (first.text, first.quote_target) == ("for u1", "u1")
    assert [(item.answers, item.quote_target) for item in await settles(rt)] == [
        (("u1",), "u1"),
        (("u2",), "u2"),
    ]
    assert set(rt.frames.conversations) == {CONVERSATION}


async def test_a_stuttered_break_is_never_shown_so_nothing_shown_is_taken_back() -> None:
    # The split drops a stuttered sentinel whole, so the stream holds it until it reads as text or a break.
    rt = Runtime()
    rt.runner.script(
        [
            text("Hi"),
            text(f"{NEW_MESSAGE_BREAKER[:3]}<"),
            text(NEW_MESSAGE_BREAKER[1:]),
            Finished(Replied("Hi")),
        ]
    )
    await send(rt, user("u1"))
    await run(rt)
    deltas = [f.payload for f in rt.frames.published if isinstance(f, ReplyDeltaFrame)]
    [reply] = await replies(rt)
    assert reply.text == "Hi"
    assert deltas == [BubbleTextDelta(bubble=0, text="Hi")]


async def test_a_path_held_back_while_it_streamed_reaches_clients_resolved_when_the_reply_saves() -> (
    None
):
    rt = Runtime()
    rt.runner.script(
        [text("Saved to /workspace/sessions/s1/notes.txt"), Finished(Replied("unused"))]
    )
    await send(rt, user("u1"))
    await run(rt)
    deltas = [f.payload for f in rt.frames.published if isinstance(f, ReplyDeltaFrame)]
    assert deltas == [
        BubbleTextDelta(bubble=0, text="Saved to"),
        BubbleTextDelta(bubble=0, text=" notes.txt"),
    ]


async def test_a_plain_turn_reads_nothing_its_own_writes_already_told_it() -> None:
    rt = Runtime()
    rt.runner.script([Finished(Replied("first"))], [text("hi"), Finished(Replied("hi"))])
    await send(rt, user("u1"))
    await run(rt)
    calls = counting_log_calls(rt)
    await send(rt, user("u2"))
    await run(rt)
    assert calls == Counter(
        append=1,
        claim=1,
        unsettled=1,
        set_comms=1,
        hint=3,
        append_fenced=2,
        amend=1,
        # What the user pinned is no write of the step's: each run reads it once.
        pinned=1,
        release=1,
    )


async def test_a_turn_that_hands_its_run_a_message_spends_a_fixed_number_of_log_calls() -> None:
    rt = Runtime()
    rt.runner.script(
        [
            text("on it"),
            Do(arrive(rt, "u2")),
            ModelOutput(True),
            text("both"),
            Finished(Replied("both")),
        ]
    )
    await send(rt, user("u1"))
    calls = counting_log_calls(rt)
    await run(rt)
    # The arrival is the one append; every read past the view is for what it logged. The interim
    # reply the arrival split off answers no one, so its settle reads nothing to count it.
    assert calls == Counter(
        append=1,
        claim=1,
        unsettled=2,
        set_comms=1,
        hint=4,
        read_after=5,
        state=4,
        append_fenced=4,
        amend=2,
        pinned=1,
        release=1,
    )


async def test_a_typed_approval_answer_quotes_the_message_it_answers_and_times_its_ack() -> None:
    rt = Runtime(analytics=RecordingAnalytics())
    work = WorkStarted(id="w", task_id="t1", cause_through=1, answers=("u0",))
    rt.runner.script([Do(lambda: send(rt, work)), Finished(Replied("on it"))])
    await send(rt, user("u0"))
    await run(rt)
    rt.approvals.decision = "approve"
    rt.runner.script([Finished(Replied("noted"))])
    typed = UserMessage(id="u6", text="yes do it", surface=ConversationSource.TELEGRAM)
    later = UserMessage(id="u7", text="and then?", surface=ConversationSource.TELEGRAM)
    await send(rt, asked("ask", "t1", "ap1"), typed, later)
    rt.frames.conversations.clear()
    await run(rt)
    assert [(item.answers, item.quote_target) for item in await settles(rt)][1:] == [
        (("u6",), "u6"),
        (("u7",), "u7"),
    ]
    assert set(rt.frames.conversations) == {CONVERSATION}
    analytics = rt.analytics
    assert isinstance(analytics, RecordingAnalytics)
    ends = [event for _, event, _, _ in analytics.ended if isinstance(event, ChatMessageCompleted)]
    assert all(event.ttft_ms is not None for event in ends)


async def test_a_restarted_attempt_is_withdrawn_from_its_own_conversation() -> None:
    rt = Runtime()
    rt.runner.script(
        [Do(arrive(rt, "u2")), text("first")],
        [text("both"), Finished(Replied("both"))],
    )
    await send(rt, user("u1"))
    await run(rt)
    assert RetractFrame(attempt_id="1.1") in rt.frames.published
    assert set(rt.frames.conversations) == {CONVERSATION}


async def test_a_message_logged_while_a_failed_reply_opens_is_quoted_past_by_its_settle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No verdict ran, so no hint read saw u2: only the reply's own seq says the view is behind.
    rt = Runtime()
    await send(rt, user("u1"))

    async def cannot_start(*_args: object) -> ScriptedRun:
        raise RuntimeError("model down")

    landed: list[str] = []

    async def log_u2_before_the_reply(point: str) -> None:
        if point == "append_fenced" and not landed:
            landed.append("u2")
            await send(rt, user("u2"))

    monkeypatch.setattr(rt.runner, "start", cannot_start)
    rt.log.pause = log_u2_before_the_reply
    await run(rt)
    assert [(item.outcome, item.answers, item.quote_target) for item in await settles(rt)][0] == (
        ReplyOutcome.FAILED,
        ("u1",),
        "u1",
    )


async def test_a_message_named_right_after_it_was_handed_below_the_shown_reply_is_answered_below() -> (
    None
):
    rt = Runtime()
    rt.runner.script(
        [
            text("a"),
            Do(arrive(rt, "u2")),
            ModelOutput(True),
            Close(seqs=(3,)),
            ModelOutput(False),
            text("b"),
            Finished(Replied("b")),
        ]
    )
    await send(rt, user("u1"))
    await run(rt)
    assert [(item.answers, item.outcome) for item in await settles(rt)] == [
        ((), ReplyOutcome.INTERIM),
        (("u2",), ReplyOutcome.SILENT),
        (("u1",), ReplyOutcome.ANSWERED),
    ]


async def test_a_reply_split_twice_by_handed_messages_answers_them_all_in_its_last_segment() -> (
    None
):
    rt = Runtime()
    rt.runner.script(
        [
            text("a"),
            Do(arrive(rt, "u2")),
            ModelOutput(True),
            text("b"),
            Do(arrive(rt, "u3")),
            ModelOutput(True),
            text("c"),
            Finished(Replied("c")),
        ]
    )
    await send(rt, user("u1"))
    await run(rt)
    assert [reply.text for reply in await replies(rt)] == ["a", "b", "c"]
    assert [(item.answers, item.outcome) for item in await settles(rt)] == [
        ((), ReplyOutcome.INTERIM),
        ((), ReplyOutcome.INTERIM),
        (("u1", "u2", "u3"), ReplyOutcome.ANSWERED),
    ]


async def test_each_reply_delta_streams_under_its_own_segments_reply_id() -> None:
    rt = Runtime()
    rt.runner.script(
        [text("a"), Do(arrive(rt, "u2")), ModelOutput(True), text("b"), Finished(Replied("b"))]
    )
    await send(rt, user("u1"))
    await run(rt)
    deltas = [f for f in rt.frames.published if isinstance(f, ReplyDeltaFrame)]
    assert {(f.attempt_id, f.reply_id) for f in deltas} == {("1.1", "r1.1"), ("1.1/1", "r1.1/1")}


async def test_each_segment_counts_the_turn_of_only_the_message_it_answered() -> None:
    analytics = RecordingAnalytics()
    rt = Runtime(analytics=analytics)
    rt.runner.script(
        [
            text("a"),
            Do(arrive(rt, "u2")),
            ModelOutput(True),
            text("b"),
            Close(seqs=(3,)),
            ModelOutput(False),
            text("c"),
            Finished(Replied("c")),
        ]
    )
    await send(rt, user("u1"))
    await run(rt)
    ends = [event for _, event, _, _ in analytics.ended if isinstance(event, ChatMessageCompleted)]
    assert [(event.stream_id, event.is_new_conversation) for event in ends] == [
        ("u2", False),
        ("u1", True),
    ]


async def test_words_after_every_message_was_answered_settle_interim_and_count_no_turn() -> None:
    analytics = RecordingAnalytics()
    rt = Runtime(analytics=analytics)
    rt.runner.script(
        [
            text("done"),
            Close(seqs=(1,)),
            ModelOutput(False),
            text("one more thing"),
            Finished(Replied("one more thing")),
        ]
    )
    await send(rt, user("u1"))
    async with captured_wide_event() as event:
        await run(rt)
    assert "errors" not in event
    assert [item.outcome for item in await settles(rt)] == [
        ReplyOutcome.ANSWERED,
        ReplyOutcome.INTERIM,
    ]
    ends = [event for _, event, _, _ in analytics.ended if isinstance(event, ChatMessageCompleted)]
    assert [event.stream_id for event in ends] == ["u1"]
