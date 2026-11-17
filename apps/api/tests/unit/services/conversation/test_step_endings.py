"""How an attempt ends, scenario by scenario: crashes, spoken-over replies, follow-ups, reactions and stops."""

from collections.abc import Sequence

import pytest

from app.constants.general import CALL_EXECUTOR_NAME
from app.models.chat_models import ReactionBy
from app.models.conversation_frame_models import (
    EntryUpdatedFrame,
    OutputFrame,
    ResponseEvent,
    RetractFrame,
    ToolDataEvent,
)
from app.models.conversation_log_models import (
    Batch,
    Entry,
    LoggedEntry,
    Reaction,
    Reply,
    ReplySettled,
    StepClaim,
    UserMessage,
    Verdict,
)
from app.services.conversation.log import accept
from app.services.conversation.ports import (
    NOTHING_KEPT,
    Answered,
    CancelReason,
    Finished,
    Kept,
    ModelOutput,
    Reacted,
    Replied,
    Silent,
    Streamed,
)
from app.services.conversation.reply_analytics import spoken_context
from app.services.conversation.screen import TOOL_CALL_CARD
from app.services.conversation.step import advance
from app.services.conversation.step_attempt import Attempt, Drafting
from app.services.conversation.step_endings import end_attempt
from app.services.conversation.step_view import StepView
from shared.py.analytics import Dedupe
from shared.py.analytics.catalog.chat import ChatTurnReacted
from shared.py.conversation_wire import FailureReason, ReplyOutcome, ToolDataEntry
from tests.helpers import captured_wide_event
from tests.unit.services.conversation.log_helpers import barge, fired, user
from tests.unit.services.conversation.runtime_doubles import (
    CONVERSATION,
    USER,
    Action,
    Cancelled,
    Close,
    Do,
    Fail,
    Forgetful,
    HandedOff,
    Pause,
    RecordingAnalytics,
    RecordingFrames,
    Runtime,
    ScriptedRun,
    Started,
)

HANDOFF_CARD: ToolDataEntry = {
    "tool_name": TOOL_CALL_CARD,
    "data": {"tool_name": CALL_EXECUTOR_NAME, "tool_call_id": "h1", "inputs": {}},
}
CARD: ToolDataEntry = {"tool_name": "search", "data": {"query": "flights"}}


def text(chunk: str) -> Streamed:
    return Streamed(payload=ResponseEvent(response=chunk))


def card(tool_data: ToolDataEntry = CARD) -> Streamed:
    return Streamed(payload=ToolDataEvent(tool_data=tool_data))


async def send(rt: Runtime, *entries: Entry) -> None:
    for entry in entries:
        await accept(rt.ports, CONVERSATION, USER, entry)


def arrive(rt: Runtime, *entries: Entry) -> Action:
    async def action() -> None:
        await send(rt, *entries)

    return action


async def run(rt: Runtime) -> None:
    await advance(rt.ports, CONVERSATION, USER)


async def replies(rt: Runtime) -> list[Reply]:
    return [item.entry for item in await rt.entries() if isinstance(item.entry, Reply)]


async def settles(rt: Runtime) -> list[ReplySettled]:
    return [item.entry for item in await rt.entries() if isinstance(item.entry, ReplySettled)]


async def test_a_run_that_crashes_after_its_answer_settled_is_cancelled_and_only_warned_about() -> (
    None
):
    rt = Runtime()
    rt.runner.script([text("done"), Answered(Replied("done")), Fail(RuntimeError("boom"))])
    await send(rt, user("u1"))
    async with captured_wide_event() as event:
        await run(rt)
    assert rt.runner.calls == [Started(batch=(1,), context=()), Cancelled(CancelReason.LOST)]
    assert [(item.outcome, item.answers) for item in await settles(rt)] == [
        (ReplyOutcome.ANSWERED, ("u1",))
    ]
    assert event["warnings"] == [
        {
            "msg": "comms run failed after its reply settled; no follow-up suggestions",
            "error_type": "RuntimeError",
            "conversation_id": CONVERSATION,
        }
    ]
    assert "errors" not in event


async def test_a_run_that_fails_logs_what_failed_on_which_attempt() -> None:
    rt = Runtime()
    rt.runner.script([text("half"), Fail(RuntimeError("model down"))])
    await send(rt, user("u1"))
    async with captured_wide_event() as event:
        await run(rt)
    assert rt.runner.calls[-1] == Cancelled(CancelReason.LOST)
    assert event["errors"] == [
        {
            "msg": "comms run failed",
            "error": "model down",
            "error_type": "RuntimeError",
            "conversation_id": CONVERSATION,
            "attempt_id": "1.1",
        }
    ]


async def _attempt_on(rt: Runtime, progress: Drafting | None) -> tuple[Attempt, StepClaim]:
    """Log u1 and claim its step, returning an attempt over it in the given progress."""
    await send(rt, user("u1"))
    claim = await rt.log.claim(CONVERSATION, USER)
    assert claim is not None
    unsettled = await rt.log.unsettled(CONVERSATION, USER)
    [waking] = unsettled.entries
    batch = Batch(start=1, end=1, waking=(waking,), first_at=waking.at)
    attempt = Attempt(
        claim=claim,
        run_id="1.1",
        reply_id="r1.1",
        batch=batch,
        handed=batch.waking,
        ledger="c1:1.1",
        seen=1,
        view=StepView(state=unsettled.state, after=0, entries=list(unsettled.entries)),
        hint_head=unsettled.state.head,
        progress=progress,
    )
    return attempt, claim


async def test_speaking_over_a_drafted_hand_off_saves_the_draft_as_truncated() -> None:
    rt = Runtime()
    draft = Reply(id="1.1:reply", reply_id="r1.1", attempt_id="1.1", tool_data=(HANDOFF_CARD,))
    attempt, claim = await _attempt_on(rt, Drafting(reply=draft))
    run_ = await rt.runner.start(claim, attempt.batch, (), attempt.ledger)
    await end_attempt(rt.ports, attempt, run_, Verdict.TRUNCATE)
    assert rt.runner.calls[-1] == Cancelled(CancelReason.TRUNCATE)
    [saved] = await replies(rt)
    assert (saved.reply_id, saved.tool_data) == ("r1.1", (HANDOFF_CARD,))
    assert [(item.outcome, item.answers) for item in await settles(rt)] == [
        (ReplyOutcome.TRUNCATED, ("u1",))
    ]


async def test_speaking_over_an_attempt_that_showed_nothing_withdraws_it() -> None:
    rt = Runtime()
    attempt, claim = await _attempt_on(rt, None)
    run_ = await rt.runner.start(claim, attempt.batch, (), attempt.ledger)
    await end_attempt(rt.ports, attempt, run_, Verdict.TRUNCATE)
    assert [item.entry.id for item in await rt.entries()] == ["u1"]
    assert rt.frames.published[-1] == RetractFrame(attempt_id="1.1")


async def test_a_reply_heard_to_its_end_is_saved_once_as_heard_in_full() -> None:
    rt = Runtime()
    rt.runner.script(
        [text("hello there"), Pause((arrive(rt, barge("b", "r1.1", 99)),))],
    )
    await send(rt, user("u1", voice=True))
    await run(rt)
    [spoken_over] = await replies(rt)
    assert (spoken_over.heard_through, spoken_over.revision) == (len("hello there"), 1)
    assert [item.outcome for item in await settles(rt)] == [ReplyOutcome.TRUNCATED]


async def test_a_message_said_while_speaking_over_a_reply_is_answered_next() -> None:
    rt = Runtime()
    rt.runner.script(
        [
            text("hello there friend"),
            Pause((arrive(rt, barge("b", "r1.1"), user("u2", voice=True)),)),
        ],
        [Finished(Replied("go on"))],
    )
    await send(rt, user("u1", voice=True))
    await run(rt)
    first, _ = await replies(rt)
    assert (first.text, first.heard_through) == ("hello there friend", 5)
    assert [(item.outcome, item.answers) for item in await settles(rt)] == [
        (ReplyOutcome.TRUNCATED, ("u1",)),
        (ReplyOutcome.ANSWERED, ("u2",)),
    ]


async def test_the_next_run_reads_a_settled_reply_as_the_part_the_user_heard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rt = Runtime()
    contexts: list[Sequence[LoggedEntry]] = []
    start = rt.runner.start

    async def recording_start(
        claim: StepClaim,
        batch: Batch,
        context: Sequence[LoggedEntry],
        ledger: str,
        note: str | None = None,
        *,
        kept: Kept = NOTHING_KEPT,
    ) -> ScriptedRun:
        contexts.append(context)
        return await start(claim, batch, context, ledger, note, kept=kept)

    monkeypatch.setattr(rt.runner, "start", recording_start)
    rt.runner.script([text("hello there friend"), Finished(Replied("hello there friend"))])
    await send(rt, user("u1", voice=True))
    await run(rt)
    rt.runner.script([Finished(Replied("go on"))])
    await send(rt, barge("b", "r1.1", 5), user("u2", voice=True))
    await run(rt)
    heard = [item.entry for item in contexts[-1] if isinstance(item.entry, Reply)]
    assert [(reply.text, reply.heard_through) for reply in heard] == [("hello there friend", 5)]


async def test_a_settled_reply_without_new_suggestions_is_not_rewritten() -> None:
    rt = Runtime()
    rt.runner.script([text("done"), Answered(Replied("done")), Finished(Replied("done"))])
    await send(rt, user("u1"))
    await run(rt)
    [reply] = await replies(rt)
    assert (reply.revision, reply.follow_up_actions) == (1, ())


async def test_a_settled_reply_of_cards_only_gets_no_suggestions() -> None:
    rt = Runtime()
    rt.runner.script(
        [card(), Answered(Replied("")), Finished(Replied("", follow_up_actions=("Book it",)))]
    )
    await send(rt, user("u1"))
    await run(rt)
    [reply] = await replies(rt)
    assert (reply.tool_data, reply.follow_up_actions) == ((CARD,), ())
    assert not [f for f in rt.frames.published if isinstance(f, EntryUpdatedFrame) and f.seq != 2][
        1:
    ]


async def test_a_reaction_is_counted_once_per_message_and_emoji() -> None:
    analytics = RecordingAnalytics()
    rt = Runtime(analytics=analytics)
    rt.runner.script([Finished(Reacted("👍"))])
    await send(rt, user("u1"))
    await run(rt)
    reacted = [
        (event, dedupe)
        for _, event, _, dedupe in analytics.ended
        if isinstance(event, ChatTurnReacted)
    ]
    message = (await rt.entries())[0]
    assert isinstance(message.entry, UserMessage)
    assert message.entry.reaction == Reaction(emoji="👍", by=ReactionBy.CHAT_MODEL)
    assert [
        (user_id, context)
        for user_id, event, context, _ in analytics.ended
        if isinstance(event, ChatTurnReacted)
    ] == [(USER, spoken_context(message.entry))]
    assert [(event.emoji, dedupe.key) for event, dedupe in reacted] == [("👍", "reacted:u1:👍")]
    [(_, dedupe)] = reacted
    assert dedupe == Dedupe(key="reacted:u1:👍", occurred_at=message.at)


async def test_suggestions_made_after_the_reply_settled_are_added_to_it() -> None:
    rt = Runtime()
    rt.runner.script(
        [
            text("done"),
            Answered(Replied("done")),
            Finished(Replied("done", follow_up_actions=("Book it",))),
        ]
    )
    await send(rt, user("u1"))
    await run(rt)
    [reply] = await replies(rt)
    assert (reply.text, reply.follow_up_actions, reply.revision) == ("done", ("Book it",), 2)


async def test_naming_a_message_below_the_shown_reply_ends_that_reply_and_answers_below() -> None:
    rt = Runtime()
    rt.runner.script(
        [text("a"), Do(arrive(rt, user("u2"))), ModelOutput(True), Finished(Replied(""))]
    )
    await send(rt, user("u1"))
    await run(rt)
    assert [(item.outcome, item.answers) for item in await settles(rt)] == [
        (ReplyOutcome.INTERIM, ()),
        (ReplyOutcome.SILENT, ("u1", "u2")),
    ]


async def _settled_voice_reply(rt: Runtime) -> None:
    rt.runner.script([text("hello there friend"), Finished(Replied("hello there friend"))])
    await send(rt, user("u1", voice=True))
    await run(rt)
    rt.runner.script([Finished(Replied("go on"))])


async def test_a_barge_heard_to_the_end_of_a_settled_reply_changes_nothing() -> None:
    rt = Runtime()
    await _settled_voice_reply(rt)
    await send(rt, barge("b1", "r1.1", len("hello there friend")), user("u2", voice=True))
    await run(rt)
    [first, _] = await replies(rt)
    assert (first.heard_through, first.revision) == (None, 1)


async def test_only_the_first_barge_on_a_settled_reply_cuts_it() -> None:
    rt = Runtime()
    await _settled_voice_reply(rt)
    await send(rt, barge("b1", "r1.1", 5), barge("b2", "r1.1", 3), user("u2", voice=True))
    await run(rt)
    [first, _] = await replies(rt)
    assert (first.heard_through, first.revision) == (5, 2)


async def outcomes(rt: Runtime) -> list[tuple[ReplyOutcome, tuple[str, ...]]]:
    return [(item.outcome, item.answers) for item in await settles(rt)]


async def test_a_run_that_crashes_after_a_tool_closed_its_message_keeps_that_answer() -> None:
    rt = Runtime()
    rt.runner.script([text("done"), Close(seqs=(1,)), Fail(RuntimeError("boom"))])
    await send(rt, user("u1"))
    await run(rt)
    first, *_ = await settles(rt)
    assert (first.outcome, first.answers) == (ReplyOutcome.ANSWERED, ("u1",))
    assert ("u1",) not in [
        answers for outcome, answers in await outcomes(rt) if outcome is ReplyOutcome.FAILED
    ]


async def test_words_answering_the_one_open_message_settle_it_and_take_later_suggestions() -> None:
    rt = Runtime()
    rt.runner.script(
        [
            Forgetful(),
            text("36"),
            Answered(Replied("36")),
            Finished(Replied("36", follow_up_actions=("Show the maths",))),
        ]
    )
    await send(rt, user("u1"))
    await run(rt)
    assert rt.runner.calls == [Started(batch=(1,), context=())]
    [reply] = await replies(rt)
    assert (reply.text, reply.follow_up_actions) == ("36", ("Show the maths",))
    assert await outcomes(rt) == [(ReplyOutcome.ANSWERED, ("u1",))]


async def test_cards_alone_leave_the_one_open_message_owed_to_a_second_run() -> None:
    rt = Runtime()
    rt.runner.script(
        [Forgetful(), card(), Finished(Replied(""))],
        [Close(seqs=(1,)), Finished(Silent())],
    )
    await send(rt, user("u1"))
    await run(rt)
    first, again = rt.runner.calls
    assert first == Started(batch=(1,), context=())
    assert isinstance(again, Started) and again.note is not None
    assert await outcomes(rt) == [(ReplyOutcome.ANSWERED, ("u1",))]


async def test_a_message_owed_when_the_answer_was_final_is_told_to_one_second_run() -> None:
    rt = Runtime()
    rt.runner.script(
        [Forgetful(), Answered(Silent()), Finished(Silent())],
        [Close(seqs=(1,)), Finished(Silent())],
    )
    await send(rt, user("u1"))
    await run(rt)
    assert [type(call) for call in rt.runner.calls] == [Started, Started]
    assert await outcomes(rt) == [(ReplyOutcome.SILENT, ("u1",))]


async def test_a_message_owed_after_the_reminder_is_handed_off_under_the_steps_claim() -> None:
    rt = Runtime()
    rt.runner.script([Forgetful(), Finished(Silent())], [Forgetful(), Finished(Silent())])
    await send(rt, user("u1"))
    await run(rt)
    assert [type(call) for call in rt.runner.calls] == [Started, Started, HandedOff]
    assert rt.runner.calls[-1] == HandedOff((1,))
    assert [claim.conversation_id for claim in rt.runner.runs[-1].handed_by] == [CONVERSATION]
    assert await outcomes(rt) == [(ReplyOutcome.SILENT, ("u1",))]


async def test_a_hand_off_made_when_the_answer_was_final_counts_as_the_settled_answer() -> None:
    rt = Runtime()
    rt.runner.script(
        [Forgetful(), Finished(Silent())],
        [Forgetful(), Answered(Silent()), Do(rt.frames.mark), Fail(RuntimeError("late"))],
    )
    await send(rt, user("u1"))
    async with captured_wide_event() as event:
        await run(rt)
    assert await outcomes(rt) == [(ReplyOutcome.SILENT, ("u1",))]
    assert rt.frames.since_mark() == []
    assert "errors" not in event


async def test_a_hand_off_the_executor_refuses_fails_the_owed_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def refuse(run_: ScriptedRun, claim: StepClaim, messages: Sequence[LoggedEntry]) -> bool:
        return False

    monkeypatch.setattr(ScriptedRun, "hand_off", refuse)
    rt = Runtime()
    rt.runner.script([Forgetful(), Finished(Silent())], [Forgetful(), Finished(Silent())])
    await send(rt, user("u1"))
    async with captured_wide_event() as event:
        await run(rt)
    assert [type(call) for call in rt.runner.calls] == [Started, Started]
    assert "errors" not in event
    [settle] = await settles(rt)
    assert (settle.outcome, settle.answers, settle.failure) == (
        ReplyOutcome.FAILED,
        ("u1",),
        FailureReason.MODEL_ERROR,
    )


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ([text("report"), Finished(Replied("report"))], ReplyOutcome.ANSWERED),
        ([card(), Finished(Replied(""))], ReplyOutcome.ANSWERED),
        ([Finished(Silent())], ReplyOutcome.SILENT),
    ],
)
async def test_a_run_for_a_workflow_answers_it_only_when_it_showed_something(
    script: list[Streamed | Finished], expected: ReplyOutcome
) -> None:
    rt = Runtime()
    rt.runner.script(script)
    await send(rt, fired("wf"))
    await run(rt)
    assert await outcomes(rt) == [(expected, ("wf",))]


async def test_words_after_the_last_message_was_answered_end_as_an_interim_reply() -> None:
    rt = Runtime()
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
    await run(rt)
    assert [reply.text for reply in await replies(rt)] == ["done", "one more thing"]
    assert await outcomes(rt) == [
        (ReplyOutcome.ANSWERED, ("u1",)),
        (ReplyOutcome.INTERIM, ()),
    ]


async def test_a_run_that_crashes_after_its_words_answered_the_one_open_message_shows_nothing_more() -> (
    None
):
    rt = Runtime()
    rt.runner.script(
        [
            Forgetful(),
            text("36"),
            Answered(Replied("36")),
            Do(rt.frames.mark),
            Fail(RuntimeError("late")),
        ]
    )
    await send(rt, user("u1"))
    await run(rt)
    assert await outcomes(rt) == [(ReplyOutcome.ANSWERED, ("u1",))]
    assert rt.frames.since_mark() == []


class _FirstAmendBlips(RecordingFrames):
    """Fails the first entry update once, as a Redis blip while a reply settles would."""

    failed: bool = False

    async def publish(self, conversation_id: str, *frames: OutputFrame) -> None:
        if any(isinstance(frame, EntryUpdatedFrame) for frame in frames) and not self.failed:
            self.failed = True
            raise ConnectionError("redis down")
        await super().publish(conversation_id, *frames)


async def test_a_reply_that_failed_to_end_above_an_absorbed_message_still_fails_below_it() -> None:
    rt = Runtime(frames=_FirstAmendBlips())
    rt.runner.script(
        [text("a"), Do(arrive(rt, user("u2"))), ModelOutput(True), Finished(Replied("a"))]
    )
    await send(rt, user("u1"))
    await run(rt)
    assert await outcomes(rt) == [
        (ReplyOutcome.INTERIM, ()),
        (ReplyOutcome.FAILED, ("u1", "u2")),
    ]


async def test_speaking_over_a_reply_that_a_later_message_split_ends_it_heard_and_answers_both() -> (
    None
):
    rt = Runtime()
    rt.runner.script(
        [
            text("hello there friend"),
            Do(arrive(rt, user("u2", voice=True))),
            ModelOutput(True),
            Pause((arrive(rt, barge("b", "r1.1", 5)),)),
        ],
    )
    await send(rt, user("u1", voice=True))
    await run(rt)
    spoken_over = (await replies(rt))[0]
    assert (spoken_over.text, spoken_over.heard_through) == ("hello there friend", 5)
    assert [(item.outcome, item.answers) for item in await settles(rt)] == [
        (ReplyOutcome.INTERIM, ()),
        (ReplyOutcome.TRUNCATED, ("u1", "u2")),
    ]
