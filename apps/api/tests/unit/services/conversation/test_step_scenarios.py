"""advance, one named scenario per row: the exact log, frames and runner calls each one produces."""

import asyncio

from app.constants.chat import EMPTY_RESPONSE_FALLBACK, ConversationSource
from app.constants.hil import HIL_ACK_APPROVED
from app.models.conversation_frame_models import ResponseEvent, RetractFrame
from app.models.conversation_log_models import (
    ApprovalDecided,
    CommsPhase,
    Entry,
    Reaction,
    ReactionBy,
    Reply,
    ReplyOutcome,
    ReplySettled,
    StopBy,
    UserMessage,
    WorkStarted,
)
from app.services.conversation.log import accept
from app.services.conversation.ports import (
    CancelReason,
    Finished,
    ModelOutput,
    Reacted,
    Replied,
    Silent,
    Streamed,
    Summarized,
)
from app.services.conversation.step import advance
from tests.unit.services.conversation.log_helpers import (
    asked,
    barge,
    finished,
    fired,
    opened,
    stop,
    user,
)
from tests.unit.services.conversation.runtime_doubles import (
    CONVERSATION,
    USER,
    Absorbed,
    Action,
    Cancelled,
    Do,
    Fail,
    Pause,
    Runtime,
    Started,
)

RESTART = Cancelled(CancelReason.RESTART)
STOP = Cancelled(CancelReason.STOP)
LOST = Cancelled(CancelReason.LOST)


def text(chunk: str) -> Streamed:
    return Streamed(payload=ResponseEvent(response=chunk))


def kinds(rt: Runtime) -> list[str]:
    return [item.entry.kind.value for item in rt.entries()]


def settles(rt: Runtime) -> list[ReplySettled]:
    return [item.entry for item in rt.entries() if isinstance(item.entry, ReplySettled)]


def replies(rt: Runtime) -> list[Reply]:
    return [item.entry for item in rt.entries() if isinstance(item.entry, Reply)]


def answered(rt: Runtime) -> list[tuple[ReplyOutcome, tuple[str, ...]]]:
    return [(item.outcome, item.answers) for item in settles(rt)]


def frame_kinds(rt: Runtime) -> list[str]:
    return [frame.kind.value for frame in rt.frames.published]


def bot_user(entry_id: str) -> UserMessage:
    return UserMessage(id=entry_id, text="yes do it", surface=ConversationSource.TELEGRAM)


async def send(rt: Runtime, *entries: Entry) -> None:
    for entry in entries:
        await accept(rt.ports, CONVERSATION, USER, entry)


def arrive(rt: Runtime, *entries: Entry) -> Action:
    async def action() -> None:
        await send(rt, *entries)

    return action


async def run(rt: Runtime) -> None:
    await advance(rt.ports, CONVERSATION, USER)


async def assert_quiet(rt: Runtime) -> None:
    state = await rt.log.state(CONVERSATION)
    assert (state.comms, state.unsettled_waking, state.open_reply) == (CommsPhase.IDLE, (), None)
    assert await rt.log.claim(CONVERSATION, USER) is not None
    assert rt.runner.overlaps == 0


async def start_work(rt: Runtime) -> None:
    """u0 asks for work; the reply says on it and the task t1 stays live."""
    work = WorkStarted(id="w", task_id="t1", cause_through=1, answers=("u0",))
    rt.runner.script([Do(arrive(rt, work)), Finished(Replied("on it"))])
    await send(rt, user("u0"))
    await run(rt)
    rt.runner.calls.clear()


async def test_one_message_gets_one_reply() -> None:
    rt = Runtime()
    rt.runner.script(
        [text("hi"), text(" there"), ModelOutput(False), Finished(Replied("hi there"))]
    )
    await send(rt, user("u1"))
    await run(rt)
    assert kinds(rt) == ["user_message", "reply", "reply_settled"]
    assert replies(rt)[0].text == "hi there"
    assert settles(rt)[0].through == 1
    assert answered(rt) == [(ReplyOutcome.ANSWERED, ("u1",))]
    assert rt.runner.calls == [Started(batch=(1,), context=())]
    assert frame_kinds(rt) == [
        "entry",
        "entry",
        "state",
        "entry",
        "reply_delta",
        "reply_delta",
        "entry_updated",
        "entry",
        "state",
    ]
    await assert_quiet(rt)


async def test_second_message_before_commit_restarts_into_one_reply_answering_both() -> None:
    rt = Runtime()
    rt.runner.script(
        [Do(arrive(rt, user("u2"))), text("first")],
        [text("both"), Finished(Replied("both"))],
    )
    await send(rt, user("u1"))
    await run(rt)
    assert rt.runner.calls == [
        Started(batch=(1,), context=()),
        RESTART,
        Started(batch=(1, 2), context=()),
    ]
    assert RetractFrame(attempt_id="1.1") in rt.frames.published
    assert answered(rt) == [(ReplyOutcome.ANSWERED, ("u1", "u2"))]
    assert len(replies(rt)) == 1
    await assert_quiet(rt)


async def test_second_message_after_visible_text_gets_its_own_reply() -> None:
    rt = Runtime()
    rt.runner.script(
        [text("one"), Do(arrive(rt, user("u2"))), Finished(Replied("one"))],
        [Finished(Replied("two"))],
    )
    await send(rt, user("u1"))
    await run(rt)
    assert rt.runner.calls == [Started(batch=(1,), context=()), Started(batch=(3,), context=(2, 4))]
    assert answered(rt) == [(ReplyOutcome.ANSWERED, ("u1",)), (ReplyOutcome.ANSWERED, ("u2",))]
    assert [settled.quote_target for settled in settles(rt)] == [None, None]
    await assert_quiet(rt)


async def test_second_message_while_a_tool_call_is_pending_is_absorbed_into_one_reply() -> None:
    rt = Runtime()
    rt.runner.script(
        [text("on it"), Do(arrive(rt, user("u2"))), ModelOutput(True), Finished(Replied("both"))]
    )
    await send(rt, user("u1"))
    await run(rt)
    assert rt.runner.calls == [Started(batch=(1,), context=()), Absorbed((3,))]
    assert answered(rt) == [(ReplyOutcome.ANSWERED, ("u1", "u2"))]
    assert settles(rt)[0].through == 3
    await assert_quiet(rt)


async def test_a_message_after_the_restart_window_does_not_restart() -> None:
    rt = Runtime()

    async def late() -> None:
        rt.clock.advance(21)
        await send(rt, user("u2"))

    rt.runner.script([Do(late), text("one"), Finished(Replied("one"))], [Finished(Replied("two"))])
    await send(rt, user("u1"))
    await run(rt)
    assert rt.runner.calls == [Started(batch=(1,), context=()), Started(batch=(2,), context=(3, 4))]
    assert answered(rt) == [(ReplyOutcome.ANSWERED, ("u1",)), (ReplyOutcome.ANSWERED, ("u2",))]


async def test_an_attempt_that_ran_the_summarization_call_never_restarts() -> None:
    rt = Runtime()
    rt.runner.script(
        [Summarized(), Do(arrive(rt, user("u2"))), text("one"), Finished(Replied("one"))],
        [Finished(Replied("two"))],
    )
    await send(rt, user("u1"))
    await run(rt)
    assert [call for call in rt.runner.calls if isinstance(call, Cancelled)] == []
    assert answered(rt) == [(ReplyOutcome.ANSWERED, ("u1",)), (ReplyOutcome.ANSWERED, ("u2",))]


async def test_a_workflow_during_an_interactive_run_never_restarts_or_merges() -> None:
    rt = Runtime()
    rt.runner.script(
        [Do(arrive(rt, fired("wf"))), ModelOutput(True), text("one"), Finished(Replied("one"))],
        [Finished(Replied("workflow done"))],
    )
    await send(rt, user("u1"))
    await run(rt)
    assert rt.runner.calls == [Started(batch=(1,), context=()), Started(batch=(2,), context=(3, 4))]
    assert answered(rt) == [(ReplyOutcome.ANSWERED, ("u1",)), (ReplyOutcome.ANSWERED, ("wf",))]


async def test_a_side_question_during_work_is_answered_while_the_work_continues() -> None:
    rt = Runtime()
    await start_work(rt)
    rt.runner.script([Finished(Replied("it is 3pm"))])
    await send(rt, user("u5"))
    await run(rt)
    state = await rt.log.state(CONVERSATION)
    assert [item.task_id for item in state.work] == ["t1"]
    assert answered(rt)[-1] == (ReplyOutcome.ANSWERED, ("u5",))
    rt.runner.script([Finished(Replied("here is the report"))])
    await send(rt, finished("f", "t1"))
    await run(rt)
    last = settles(rt)[-1]
    # The late result quotes the original request: the side question sits between them.
    assert (last.reply_id, last.answers, last.quote_target) == ("t1", ("f", "u0"), "u0")
    await assert_quiet(rt)


async def test_an_addition_during_work_answered_by_a_reaction_leaves_no_bubble() -> None:
    rt = Runtime()
    await start_work(rt)
    rt.runner.script([Finished(Reacted("👍"))])
    await send(rt, user("u5"))
    await run(rt)
    message = next(item.entry for item in rt.entries() if item.entry.id == "u5")
    assert isinstance(message, UserMessage)
    assert message.reaction == Reaction(emoji="👍", by=ReactionBy.CHAT_MODEL)
    assert message.revision == 1
    silent = replies(rt)[-1]
    assert (silent.text, silent.tool_data) == ("", ())
    assert answered(rt)[-1] == (ReplyOutcome.SILENT, ("u5",))
    assert settles(rt)[-1].quote_target is None
    await assert_quiet(rt)


async def test_an_approval_answer_on_a_buttonless_surface_settles_with_an_ack_and_no_run() -> None:
    rt = Runtime()
    await start_work(rt)
    await send(rt, asked("ask", "t1", "ap1"))
    rt.approvals.decision = "approve"
    await send(rt, bot_user("u6"))
    await run(rt)
    assert rt.runner.calls == []
    assert rt.approvals.asked == ["yes do it"]
    decided = [item.entry for item in rt.entries() if isinstance(item.entry, ApprovalDecided)]
    assert [(item.approval_id, item.decision) for item in decided] == [("ap1", "approve")]
    assert replies(rt)[-1].text == HIL_ACK_APPROVED
    assert answered(rt)[-1] == (ReplyOutcome.ANSWERED, ("u6",))
    state = await rt.log.state(CONVERSATION)
    assert [item.pending_approvals for item in state.work] == [frozenset()]
    await assert_quiet(rt)


async def test_a_buttonless_message_that_is_not_an_approval_answer_runs_normally() -> None:
    rt = Runtime()
    await start_work(rt)
    await send(rt, asked("ask", "t1", "ap1"))
    rt.runner.script([Finished(Replied("sure"))])
    await send(rt, bot_user("u6"))
    await run(rt)
    assert rt.approvals.asked == ["yes do it"]
    assert [type(call) for call in rt.runner.calls] == [Started]
    assert not any(isinstance(item.entry, ApprovalDecided) for item in rt.entries())


async def test_the_web_surface_never_classifies_an_approval_answer() -> None:
    rt = Runtime()
    await start_work(rt)
    await send(rt, asked("ask", "t1", "ap1"))
    rt.approvals.decision = "approve"
    rt.runner.script([Finished(Replied("use the button"))])
    await send(rt, user("u6"))
    await run(rt)
    assert rt.approvals.asked == []
    assert [type(call) for call in rt.runner.calls] == [Started]


async def test_a_work_result_before_commit_restarts_into_one_reply() -> None:
    rt = Runtime()
    await start_work(rt)
    rt.runner.script(
        [Do(arrive(rt, finished("f", "t1"))), text("x")],
        [Finished(Replied("both"))],
    )
    await send(rt, user("u5"))
    await run(rt)
    assert rt.runner.calls[1:3] == [RESTART, Started(batch=(5, 6), context=(2, 3, 4))]
    assert answered(rt)[-1] == (ReplyOutcome.ANSWERED, ("u5", "f", "u0"))
    assert settles(rt)[-1].reply_id == "t1"


async def test_a_work_result_after_commit_is_answered_by_the_next_run() -> None:
    rt = Runtime()
    await start_work(rt)
    rt.runner.script(
        [text("x"), Do(arrive(rt, finished("f", "t1"))), Finished(Replied("x"))],
        [Finished(Replied("report"))],
    )
    await send(rt, user("u5"))
    await run(rt)
    assert answered(rt)[-2:] == [
        (ReplyOutcome.ANSWERED, ("u5",)),
        (ReplyOutcome.ANSWERED, ("f", "u0")),
    ]
    await assert_quiet(rt)


async def test_a_message_the_instant_work_finishes_shares_its_reply() -> None:
    rt = Runtime()
    await start_work(rt)
    rt.runner.script([Finished(Replied("done, and yes"))])
    await send(rt, finished("f", "t1"), user("u6"))
    await run(rt)
    assert rt.runner.calls == [Started(batch=(5, 6), context=(2, 3, 4))]
    last = settles(rt)[-1]
    assert (last.reply_id, last.answers) == ("t1", ("f", "u6", "u0"))


async def test_stop_while_thinking_withdraws_the_attempt_and_writes_no_reply() -> None:
    rt = Runtime()
    rt.runner.script([Pause((arrive(rt, stop("s")),))])
    await send(rt, user("u1"))
    await run(rt)
    assert kinds(rt) == ["user_message", "stop_requested"]
    assert rt.runner.calls == [Started(batch=(1,), context=()), STOP]
    assert RetractFrame(attempt_id="1.1") in rt.frames.published
    assert (await rt.log.state(CONVERSATION)).stopped_through == 1
    await assert_quiet(rt)


async def test_stop_mid_text_settles_the_reply_stopped_with_the_partial_text() -> None:
    rt = Runtime()
    rt.runner.script([text("partial"), Pause((arrive(rt, stop("s")),))])
    await send(rt, user("u1"))
    await run(rt)
    assert kinds(rt) == ["user_message", "reply", "stop_requested", "reply_settled"]
    assert replies(rt)[0].text == "partial"
    assert answered(rt) == [(ReplyOutcome.STOPPED, ())]
    assert settles(rt)[0].through == 2
    await assert_quiet(rt)


async def test_stop_then_a_new_message_answers_the_new_message_normally() -> None:
    rt = Runtime()
    rt.runner.script(
        [Pause((arrive(rt, stop("s"), user("u3")),))],
        [Finished(Replied("hello"))],
    )
    await send(rt, user("u1"))
    await run(rt)
    assert rt.runner.calls == [
        Started(batch=(1,), context=()),
        STOP,
        Started(batch=(3,), context=(1, 2)),
    ]
    assert answered(rt) == [(ReplyOutcome.ANSWERED, ("u3",))]
    await assert_quiet(rt)


async def test_a_typed_stop_issued_by_the_run_does_not_stop_its_own_batch() -> None:
    rt = Runtime()
    own_stop = stop("s", covers_through=0, by=StopBy.GAIA)
    rt.runner.script(
        [ModelOutput(True), Do(arrive(rt, own_stop)), text("stopped it"), Finished(Replied("ok"))]
    )
    await send(rt, user("u1"))
    await run(rt)
    assert rt.runner.calls == [Started(batch=(1,), context=())]
    assert answered(rt) == [(ReplyOutcome.ANSWERED, ("u1",))]


async def test_a_barge_in_cuts_the_reply_to_what_was_heard_and_is_answered_next() -> None:
    rt = Runtime()
    rt.runner.script(
        [text("hello there friend"), Pause((arrive(rt, barge("b", "r1.1")),))],
        [Finished(Replied("go on"))],
    )
    await send(rt, user("u1", voice=True))
    await run(rt)
    assert rt.runner.calls[:2] == [
        Started(batch=(1,), context=()),
        Cancelled(CancelReason.TRUNCATE),
    ]
    cut = replies(rt)[0]
    assert (cut.text, cut.heard_through) == ("hello", 5)
    assert answered(rt) == [(ReplyOutcome.STOPPED, ("u1",)), (ReplyOutcome.ANSWERED, ("b",))]
    await assert_quiet(rt)


async def test_a_ten_message_burst_gets_one_reply() -> None:
    rt = Runtime()
    ids = [f"u{n}" for n in range(1, 11)]
    rt.runner.script([Finished(Replied("all of it"))])
    await send(rt, *(user(entry_id) for entry_id in ids))
    await run(rt)
    assert rt.runner.calls == [Started(batch=tuple(range(1, 11)), context=())]
    assert answered(rt) == [(ReplyOutcome.ANSWERED, tuple(ids))]


async def test_a_run_that_raises_before_commit_leaves_a_failed_bubble() -> None:
    rt = Runtime()
    rt.runner.script([Fail(RuntimeError("model down"))])
    await send(rt, user("u1"))
    await run(rt)
    assert rt.runner.calls == [Started(batch=(1,), context=()), LOST]
    assert kinds(rt) == ["user_message", "reply", "reply_settled"]
    assert answered(rt) == [(ReplyOutcome.FAILED, ("u1",))]
    await assert_quiet(rt)


async def test_a_run_that_raises_after_commit_keeps_what_was_shown() -> None:
    rt = Runtime()
    rt.runner.script([text("half"), Fail(RuntimeError("model down"))])
    await send(rt, user("u1"))
    await run(rt)
    assert replies(rt)[0].text == "half"
    assert answered(rt) == [(ReplyOutcome.FAILED, ("u1",))]
    await assert_quiet(rt)


async def test_a_silent_run_for_a_user_still_answers_with_the_fallback() -> None:
    rt = Runtime()
    rt.runner.script([Finished(Silent())])
    await send(rt, user("u1"))
    await run(rt)
    assert replies(rt)[0].text == EMPTY_RESPONSE_FALLBACK
    assert answered(rt) == [(ReplyOutcome.ANSWERED, ("u1",))]


async def test_a_silent_run_for_a_workflow_settles_silently() -> None:
    rt = Runtime()
    rt.runner.script([Finished(Silent())])
    await send(rt, fired("wf"))
    await run(rt)
    assert answered(rt) == [(ReplyOutcome.SILENT, ("wf",))]
    assert replies(rt)[0].text == ""


async def test_a_first_tool_call_with_no_text_appends_no_reply_until_something_shows() -> None:
    rt = Runtime()
    seen: list[list[str]] = []

    async def look() -> None:
        seen.append(kinds(rt))

    rt.runner.script([ModelOutput(True), Do(look), text("found it"), Finished(Replied("found it"))])
    await send(rt, user("u1"))
    await run(rt)
    assert seen == [["user_message"]]
    assert kinds(rt) == ["user_message", "reply", "reply_settled"]


async def test_two_advance_calls_at_once_run_exactly_one_step() -> None:
    rt = Runtime()
    rt.runner.script([Finished(Replied("once"))])
    await send(rt, user("u1"))
    await asyncio.gather(run(rt), run(rt))
    assert rt.runner.calls == [Started(batch=(1,), context=())]
    assert answered(rt) == [(ReplyOutcome.ANSWERED, ("u1",))]


async def test_a_lost_claim_mid_run_writes_nothing_more_and_the_next_holder_finishes() -> None:
    rt = Runtime()

    async def die() -> None:
        rt.log.lapse(CONVERSATION)

    rt.runner.script([text("half"), Pause((die,))], [Finished(Replied("whole"))])
    await send(rt, user("u1"))
    await run(rt)
    assert rt.runner.calls == [Started(batch=(1,), context=()), LOST]
    assert kinds(rt) == ["user_message", "reply"]
    await run(rt)
    assert kinds(rt) == ["user_message", "reply", "reply_settled", "reply", "reply_settled"]
    assert rt.runner.calls[-1] == Started(batch=(1,), context=(2, 3))
    assert answered(rt) == [(ReplyOutcome.FAILED, ()), (ReplyOutcome.ANSWERED, ("u1",))]
    await assert_quiet(rt)


async def test_a_swallowed_first_cancel_starts_no_second_run_until_the_first_is_dead() -> None:
    rt = Runtime()
    rt.runner.swallow_first_cancel = True
    rt.runner.script([Pause((arrive(rt, user("u2")),))], [Finished(Replied("both"))])
    await send(rt, user("u1"))
    await run(rt)
    assert rt.runner.calls == [
        Started(batch=(1,), context=()),
        RESTART,
        Started(batch=(1, 2), context=()),
    ]
    assert rt.runner.runs[0].cancel_attempts == 2
    assert rt.runner.overlaps == 0


async def test_taking_over_a_dead_uncommitted_holder_redoes_its_inputs() -> None:
    rt = Runtime()
    await send(rt, user("u1"))
    dead = await rt.log.claim(CONVERSATION, USER)
    assert dead is not None
    await rt.log.set_comms(dead, CommsPhase.THINKING)
    rt.log.lapse(CONVERSATION)
    rt.runner.script([Finished(Replied("answer"))])
    await run(rt)
    assert rt.runner.calls == [Started(batch=(1,), context=())]
    assert answered(rt) == [(ReplyOutcome.ANSWERED, ("u1",))]
    await assert_quiet(rt)


async def test_taking_over_a_dead_committed_holder_fails_its_reply_and_answers_again() -> None:
    rt = Runtime()
    await send(rt, user("u1"))
    dead = await rt.log.claim(CONVERSATION, USER)
    assert dead is not None
    await rt.log.append_fenced(dead, opened("o", "r_dead").model_copy(update={"text": "par"}))
    rt.log.lapse(CONVERSATION)
    rt.runner.script([Finished(Replied("answer"))])
    await run(rt)
    assert rt.runner.calls == [Started(batch=(1,), context=(2, 3))]
    assert answered(rt) == [(ReplyOutcome.FAILED, ()), (ReplyOutcome.ANSWERED, ("u1",))]
    assert replies(rt)[0].text == "par"
    # The reply a dead holder appended is republished, since its frame may never have gone out.
    assert [frame.kind.value for frame in rt.frames.published[:3]] == ["entry", "entry", "entry"]
    await assert_quiet(rt)


async def test_a_step_killed_mid_run_kills_its_run_and_leaves_its_reply_to_recovery() -> None:
    rt = Runtime()
    step: asyncio.Task[None] | None = None
    hints: list[str] = []

    async def die_at_the_second_hint(point: str) -> None:
        if point == "hint" and asyncio.current_task() is step:
            hints.append(point)
            if len(hints) == 2:
                raise asyncio.CancelledError

    rt.log.pause = die_at_the_second_hint
    rt.runner.script([text("half"), Finished(Replied("whole"))], [Finished(Replied("again"))])
    await send(rt, user("u1"))
    step = asyncio.create_task(run(rt))
    await asyncio.gather(step, return_exceptions=True)
    assert step.cancelled()
    assert rt.runner.calls == [Started(batch=(1,), context=()), LOST]
    assert kinds(rt) == ["user_message", "reply"]
    rt.log.lapse(CONVERSATION)
    await run(rt)
    assert answered(rt) == [(ReplyOutcome.FAILED, ()), (ReplyOutcome.ANSWERED, ("u1",))]
    await assert_quiet(rt)
