"""advance, one named scenario per row: the exact log, frames and runner calls each one produces."""

import asyncio
from dataclasses import dataclass
from typing import cast

import pytest

from app.constants.chat import EMPTY_RESPONSE_FALLBACK, ConversationSource
from app.constants.hil import HIL_ACK_APPROVED
from app.models.chat_models import ReactionBy
from app.models.conversation_frame_models import (
    EntryFrame,
    OutputFrame,
    ResponseEvent,
    RetractFrame,
    ToolDataEvent,
    ToolOutputEvent,
)
from app.models.conversation_log_models import (
    ApprovalDecided,
    BargeIn,
    CommsPhase,
    Entry,
    Reaction,
    Reply,
    ReplySettled,
    StopBy,
    UserMessage,
    WorkStarted,
)
from app.models.stream_events import ToolOutputPayload
from app.services.conversation.composition import PostHogTurnAnalytics
from app.services.conversation.log import accept
from app.services.conversation.ports import (
    Answered,
    CancelReason,
    EntryRejected,
    Finished,
    ModelOutput,
    Reacted,
    Replied,
    Silent,
    StepLimitReached,
    Streamed,
    Summarized,
)
from app.services.conversation.step import advance
from shared.py.conversation_wire import FailureReason, ReplyDeltaFrame, ReplyOutcome, ToolDataEntry
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
    RecordingFrames,
    Runtime,
    ScriptItem,
    Started,
)

RESTART = Cancelled(CancelReason.RESTART)
STOP = Cancelled(CancelReason.STOP)
LOST = Cancelled(CancelReason.LOST)
TRUNCATE = Cancelled(CancelReason.TRUNCATE)


CARD: ToolDataEntry = {"tool_name": "search", "data": {"query": "flights"}}
FILE_CARD: ToolDataEntry = {
    "tool_name": "artifact_data",
    "data": {
        "event": "upsert",
        "session_id": CONVERSATION,
        "path": "out/report.pdf",
        "size_bytes": 2048,
        "mtime": 1_700_000_000.0,
        "content_type": "application/pdf",
    },
}


def card() -> Streamed:
    return Streamed(payload=ToolDataEvent(tool_data=CARD))


def text(chunk: str) -> Streamed:
    return Streamed(payload=ResponseEvent(response=chunk))


async def kinds(rt: Runtime) -> list[str]:
    return [item.entry.kind.value for item in await rt.entries()]


async def settles(rt: Runtime) -> list[ReplySettled]:
    return [item.entry for item in await rt.entries() if isinstance(item.entry, ReplySettled)]


async def replies(rt: Runtime) -> list[Reply]:
    return [item.entry for item in await rt.entries() if isinstance(item.entry, Reply)]


async def answered(rt: Runtime) -> list[tuple[ReplyOutcome, tuple[str, ...]]]:
    return [(item.outcome, item.answers) for item in await settles(rt)]


_TURN_ENDS = ("chat:message_completed", "chat:message_cancelled")
_TURN_END_KEYS = (
    "stream_id",
    "conversation_id",
    "is_new_conversation",
    "delegated",
    "queued",
    "source",
)


def turn_ends(events: list[dict[str, object]]) -> list[tuple[object, ...]]:
    """Each reply-end event as (name, whose, attribution, the catalog's identifying properties)."""
    ends = []
    for event in events:
        if event["event"] not in _TURN_ENDS:
            continue
        props = cast(dict[str, object], event["properties"])
        attribution = (props["actor"], props["trigger"], props["surface"])
        ends.append(
            (event["event"], event["distinct_id"], attribution, *(props[k] for k in _TURN_END_KEYS))
        )
    return ends


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
    state = await rt.log.state(CONVERSATION, USER)
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


class StepScenarios:
    """Every scenario here must hold over every ConversationLog the step runs on."""

    @pytest.fixture
    def rt(self) -> Runtime:
        raise NotImplementedError

    @pytest.fixture
    def posthog_turns(
        self, rt: Runtime, posthog_events: list[dict[str, object]]
    ) -> list[dict[str, object]]:
        """Count turn ends through the production PostHog port; return what PostHog would receive."""
        rt.analytics = PostHogTurnAnalytics()
        return posthog_events

    async def test_one_message_gets_one_reply(self, rt: Runtime) -> None:
        rt.runner.script(
            [text("hi"), text(" there"), ModelOutput(False), Finished(Replied("hi there"))]
        )
        await send(rt, user("u1"))
        await run(rt)
        assert await kinds(rt) == ["user_message", "reply", "reply_settled"]
        assert (await replies(rt))[0].text == "hi there"
        assert (await settles(rt))[0].through == 1
        assert await answered(rt) == [(ReplyOutcome.ANSWERED, ("u1",))]
        assert rt.runner.calls == [Started(batch=(1,), context=())]
        # The accepted message streams once: a step that took no one's place republishes nothing.
        assert frame_kinds(rt) == [
            "entry",
            "state",
            "state",
            "entry",
            "reply_delta",
            "reply_delta",
            "entry_updated",
            "entry",
            "state",
        ]
        await assert_quiet(rt)

    async def test_second_message_before_commit_restarts_into_one_reply_answering_both(
        self, rt: Runtime
    ) -> None:
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
        assert await answered(rt) == [(ReplyOutcome.ANSWERED, ("u1", "u2"))]
        assert len(await replies(rt)) == 1
        await assert_quiet(rt)

    async def test_second_message_after_visible_text_gets_its_own_reply(self, rt: Runtime) -> None:
        rt.runner.script(
            [text("one"), Do(arrive(rt, user("u2"))), Finished(Replied("one"))],
            [Finished(Replied("two"))],
        )
        await send(rt, user("u1"))
        await run(rt)
        assert rt.runner.calls == [
            Started(batch=(1,), context=()),
            Started(batch=(3,), context=(2, 4)),
        ]
        assert await answered(rt) == [
            (ReplyOutcome.ANSWERED, ("u1",)),
            (ReplyOutcome.ANSWERED, ("u2",)),
        ]
        await assert_quiet(rt)
        assert [settled.quote_target for settled in await settles(rt)] == [None, None]

    async def test_a_message_absorbed_after_text_was_read_continues_in_a_reply_below_it(
        self, rt: Runtime
    ) -> None:
        # The text the user read keeps its slot; what the attempt says after the absorb answers below u2.
        rt.runner.script(
            [
                text("on it"),
                Do(arrive(rt, user("u2"))),
                ModelOutput(True),
                text("both"),
                Finished(Replied("on it")),
            ]
        )
        await send(rt, user("u1"))
        await run(rt)
        assert rt.runner.calls == [Started(batch=(1,), context=()), Absorbed((3,))]
        assert await kinds(rt) == [
            "user_message",
            "reply",
            "user_message",
            "reply_settled",
            "reply",
            "reply_settled",
        ]
        assert [reply.text for reply in await replies(rt)] == ["on it", "both"]
        assert await answered(rt) == [
            (ReplyOutcome.ANSWERED, ("u1",)),
            (ReplyOutcome.ANSWERED, ("u2",)),
        ]
        assert [settled.through for settled in await settles(rt)] == [1, 3]
        assert [settled.quote_target for settled in await settles(rt)] == [None, None]
        first, second = await replies(rt)
        assert first.reply_id != second.reply_id
        assert first.attempt_id != second.attempt_id
        # Each segment streams as its own draft, so settling the first never swallows the second's deltas.
        deltas = [f for f in rt.frames.published if isinstance(f, ReplyDeltaFrame)]
        assert [(f.attempt_id, f.index) for f in deltas] == [
            (first.attempt_id, 0),
            (second.attempt_id, 0),
        ]
        await assert_quiet(rt)

    @pytest.mark.parametrize(
        "ending",
        [Finished(Replied("")), Fail(RuntimeError("model down"))],
        ids=["replied-empty", "failed"],
    )
    async def test_a_run_ending_right_after_an_absorb_answers_the_absorbed_below_them(
        self, rt: Runtime, ending: ScriptItem
    ) -> None:
        # Regression: the shown reply above u2 was settled as answering u2 when the model never wrote again.
        rt.runner.script([text("on it"), Do(arrive(rt, user("u2"))), ModelOutput(True), ending])
        await send(rt, user("u1"))
        await run(rt)
        entries = await rt.entries()
        seq_of = {logged.entry.id: logged.seq for logged in entries}
        reply_seq = {
            logged.entry.reply_id: logged.seq
            for logged in entries
            if isinstance(logged.entry, Reply)
        }
        settled = await settles(rt)
        assert [settle.answers for settle in settled] == [("u1",), ("u2",)]
        for settle in settled:
            assert all(reply_seq[settle.reply_id] > seq_of[answered] for answered in settle.answers)
        assert [reply.text for reply in await replies(rt)][0] == "on it"
        await assert_quiet(rt)

    async def test_cards_shown_before_a_message_arrives_stay_above_it_and_the_answer_follows_it(
        self, rt: Runtime
    ) -> None:
        # Conversation d0fb1e04: searches for u1 were showing when u2 changed the ask.
        rt.runner.script(
            [
                ModelOutput(True),
                card(),
                Do(arrive(rt, user("u2"))),
                card(),
                ModelOutput(True),
                text("PDEU is a university"),
                ModelOutput(False),
                Finished(Replied("PDEU is a university")),
            ]
        )
        await send(rt, user("u1"))
        await run(rt)
        assert rt.runner.calls == [Started(batch=(1,), context=()), Absorbed((3,))]
        assert await kinds(rt) == [
            "user_message",
            "reply",
            "user_message",
            "reply_settled",
            "reply",
            "reply_settled",
        ]
        cards, answer = await replies(rt)
        assert (cards.text, cards.tool_data) == ("", (CARD, CARD))
        assert (answer.text, answer.tool_data) == ("PDEU is a university", ())
        assert await answered(rt) == [
            (ReplyOutcome.ANSWERED, ("u1",)),
            (ReplyOutcome.ANSWERED, ("u2",)),
        ]
        entry_seqs = [f.seq for f in rt.frames.published if isinstance(f, EntryFrame)]
        assert entry_seqs == sorted(entry_seqs)
        await assert_quiet(rt)

    async def test_a_chat_model_reaction_lands_on_the_newest_message_of_a_burst(
        self, rt: Runtime
    ) -> None:
        # The instant reaction is decided per message at accept; the chat model's only on the newest.
        rt.runner.script([Finished(Reacted("👍"))])
        await send(rt, user("u1"), user("u2"))
        await run(rt)
        reactions = {
            item.entry.id: item.entry.reaction
            for item in await rt.entries()
            if isinstance(item.entry, UserMessage)
        }
        assert reactions == {"u1": None, "u2": Reaction(emoji="👍", by=ReactionBy.CHAT_MODEL)}
        assert (await answered(rt))[-1] == (ReplyOutcome.SILENT, ("u1", "u2"))

    async def test_a_reply_of_cards_only_takes_its_slot_at_its_first_card(
        self, rt: Runtime
    ) -> None:
        rt.runner.script(
            [card(), Do(arrive(rt, user("u2"))), Finished(Replied(""))],
            [Finished(Replied("two"))],
        )
        await send(rt, user("u1"))
        await run(rt)
        assert (await kinds(rt))[:4] == ["user_message", "reply", "user_message", "reply_settled"]
        assert (await replies(rt))[0].tool_data == (CARD,)
        assert (await answered(rt))[0] == (ReplyOutcome.ANSWERED, ("u1",))
        # It sits directly under the message it answers, so it quotes nothing.
        assert (await settles(rt))[0].quote_target is None
        await assert_quiet(rt)

    async def test_a_comms_tool_card_keeps_its_output_in_the_saved_reply(self, rt: Runtime) -> None:
        call: ToolDataEntry = {
            "tool_name": "tool_calls_data",
            "data": {"tool_name": "web_search_tool", "tool_call_id": "c1", "inputs": {"q": "x"}},
        }
        rt.runner.script(
            [
                Streamed(payload=ToolDataEvent(tool_data=call)),
                Streamed(
                    payload=ToolOutputEvent(
                        tool_output=ToolOutputPayload(tool_call_id="c1", output="sunny, 31C")
                    )
                ),
                text("It is sunny."),
                Finished(Replied("It is sunny.")),
            ]
        )
        await send(rt, user("u1"))
        await run(rt)
        # What a reload reads: the log's reply entry.
        (reply,) = await replies(rt)
        assert reply.tool_data[0]["data"]["output"] == "sunny, 31C"
        assert "output" not in call["data"]

    async def test_a_message_arriving_with_a_tool_only_output_joins_instead_of_restarting(
        self, rt: Runtime
    ) -> None:
        # The tool call is already checkpointed when its event arrives: a restart would leave it unanswered.
        rt.runner.script(
            [Do(arrive(rt, user("u2"))), ModelOutput(True), Finished(Replied("both"))],
            [Finished(Replied("restarted"))],
        )
        await send(rt, user("u1"))
        await run(rt)
        assert rt.runner.calls == [Started(batch=(1,), context=()), Absorbed((2,))]
        assert await answered(rt) == [(ReplyOutcome.ANSWERED, ("u1", "u2"))]
        await assert_quiet(rt)

    async def test_a_dead_attempt_that_started_work_unseen_is_not_redone_silently(
        self, rt: Runtime
    ) -> None:
        async def die() -> None:
            await rt.lapse()

        work = WorkStarted(id="w", task_id="t1", cause_through=1, answers=("u1",))
        rt.runner.script(
            [Do(arrive(rt, work)), ModelOutput(True), Pause((die,))],
            [Finished(Replied("sorry, I was restarted; the work is running"))],
        )
        await send(rt, user("u1"))
        await run(rt)
        await run(rt)
        assert [s.failure for s in await settles(rt)] == [FailureReason.SERVER_RESTART, None]

    async def test_a_message_after_the_restart_window_does_not_restart(self, rt: Runtime) -> None:
        async def late() -> None:
            rt.clock.advance(21)
            await send(rt, user("u2"))

        rt.runner.script(
            [Do(late), text("one"), Finished(Replied("one"))], [Finished(Replied("two"))]
        )
        await send(rt, user("u1"))
        await run(rt)
        assert rt.runner.calls == [
            Started(batch=(1,), context=()),
            Started(batch=(2,), context=(3, 4)),
        ]
        assert await answered(rt) == [
            (ReplyOutcome.ANSWERED, ("u1",)),
            (ReplyOutcome.ANSWERED, ("u2",)),
        ]

    async def test_an_attempt_that_ran_the_summarization_call_never_restarts(
        self, rt: Runtime
    ) -> None:
        rt.runner.script(
            [Summarized(), Do(arrive(rt, user("u2"))), text("one"), Finished(Replied("one"))],
            [Finished(Replied("two"))],
        )
        await send(rt, user("u1"))
        await run(rt)
        assert [call for call in rt.runner.calls if isinstance(call, Cancelled)] == []
        assert await answered(rt) == [
            (ReplyOutcome.ANSWERED, ("u1",)),
            (ReplyOutcome.ANSWERED, ("u2",)),
        ]

    async def test_a_workflow_during_an_interactive_run_never_restarts_or_merges(
        self, rt: Runtime
    ) -> None:
        rt.runner.script(
            [Do(arrive(rt, fired("wf"))), ModelOutput(True), text("one"), Finished(Replied("one"))],
            [Finished(Replied("workflow done"))],
        )
        await send(rt, user("u1"))
        await run(rt)
        assert rt.runner.calls == [
            Started(batch=(1,), context=()),
            Started(batch=(2,), context=(3, 4)),
        ]
        assert await answered(rt) == [
            (ReplyOutcome.ANSWERED, ("u1",)),
            (ReplyOutcome.ANSWERED, ("wf",)),
        ]

    async def test_a_side_question_during_work_is_answered_while_the_work_continues(
        self, rt: Runtime
    ) -> None:
        await start_work(rt)
        rt.runner.script([Finished(Replied("it is 3pm"))])
        await send(rt, user("u5"))
        await run(rt)
        state = await rt.log.state(CONVERSATION, USER)
        assert [item.task_id for item in state.work] == ["t1"]
        assert (await answered(rt))[-1] == (ReplyOutcome.ANSWERED, ("u5",))
        rt.runner.script([Finished(Replied("here is the report"))])
        await send(rt, finished("f", "t1"))
        await run(rt)
        last = (await settles(rt))[-1]
        # The late result quotes the original request: the side question sits between them.
        assert (last.narrates, last.answers, last.quote_target) == (("t1",), ("f", "u0"), "u0")
        assert [(r.narrates, r.quote_target) for r in await replies(rt)][-1] == (("t1",), "u0")
        await assert_quiet(rt)

    async def test_a_write_up_that_says_nothing_settles_silent_and_leaves_the_cards_to_the_work(
        self, rt: Runtime
    ) -> None:
        await start_work(rt)
        rt.runner.script([Finished(Replied(""))])
        await send(rt, finished("f", "t1").model_copy(update={"tool_data": (CARD,)}))
        await run(rt)
        assert (await answered(rt))[-1] == (ReplyOutcome.SILENT, ("f", "u0"))
        write_up = (await replies(rt))[-1]
        assert (write_up.tool_data, write_up.narrates) == ((), ("t1",))

    async def test_a_streamed_late_result_quotes_the_request_from_its_first_frame(
        self, rt: Runtime
    ) -> None:
        await start_work(rt)
        rt.runner.script([Finished(Replied("it is 3pm"))])
        await send(rt, user("u5"))
        await run(rt)
        rt.runner.script([text("here is"), Finished(Replied("here is"))])
        await send(rt, finished("f", "t1"))
        await run(rt)
        opened = [
            f.entry
            for f in rt.frames.published
            if isinstance(f, EntryFrame)
            and isinstance(f.entry, Reply)
            and f.entry.narrates == ("t1",)
        ]
        assert [reply.quote_target for reply in opened][:1] == ["u0"]

    async def test_an_addition_during_work_answered_by_a_reaction_leaves_no_bubble(
        self, rt: Runtime
    ) -> None:
        await start_work(rt)
        rt.runner.script([Finished(Reacted("👍"))])
        await send(rt, user("u5"))
        await run(rt)
        message = next(item.entry for item in await rt.entries() if item.entry.id == "u5")
        assert isinstance(message, UserMessage)
        assert message.reaction == Reaction(emoji="👍", by=ReactionBy.CHAT_MODEL)
        assert message.revision == 1
        silent = (await replies(rt))[-1]
        assert (silent.text, silent.tool_data) == ("", ())
        assert (await answered(rt))[-1] == (ReplyOutcome.SILENT, ("u5",))
        assert (await settles(rt))[-1].quote_target is None
        await assert_quiet(rt)

    async def test_an_approval_answer_on_a_buttonless_surface_settles_with_an_ack_and_no_run(
        self, rt: Runtime
    ) -> None:
        await start_work(rt)
        await send(rt, asked("ask", "t1", "ap1"))
        rt.approvals.decision = "approve"
        await send(rt, bot_user("u6"))
        await run(rt)
        assert rt.runner.calls == []
        assert rt.approvals.asked == ["yes do it"]
        assert rt.approvals.histories == [
            [
                {"role": "user", "content": "text of u0"},
                {"role": "assistant", "content": "on it"},
            ]
        ]
        decided = [
            item.entry for item in await rt.entries() if isinstance(item.entry, ApprovalDecided)
        ]
        assert [(item.approval_id, item.outcome) for item in decided] == [("ap1", "approved")]
        assert (await replies(rt))[-1].text == HIL_ACK_APPROVED
        assert (await answered(rt))[-1] == (ReplyOutcome.ANSWERED, ("u6",))
        state = await rt.log.state(CONVERSATION, USER)
        assert [item.pending_approvals for item in state.work] == [frozenset()]
        await assert_quiet(rt)

    async def test_a_mixed_typed_answer_logs_each_approval_once_with_its_own_decision(
        self, rt: Runtime
    ) -> None:
        await start_work(rt)
        await send(rt, asked("ask1", "t1", "ap1"), asked("ask2", "t1", "ap2"))
        rt.approvals.decision = "approve"
        rt.approvals.each = {"ap2": "deny"}
        await send(rt, bot_user("u6"))
        await run(rt)
        decided = [
            item.entry for item in await rt.entries() if isinstance(item.entry, ApprovalDecided)
        ]
        assert sorted((item.approval_id, item.outcome, item.decider) for item in decided) == [
            ("ap1", "approved", "user"),
            ("ap2", "denied", "user"),
        ]
        await assert_quiet(rt)

    async def test_a_typed_approval_answer_publishes_each_decision_it_logs(
        self, rt: Runtime
    ) -> None:
        await start_work(rt)
        await send(rt, asked("ask", "t1", "ap1"))
        rt.approvals.decision = "approve"
        await send(rt, bot_user("u6"))
        await run(rt)
        decided = [item for item in await rt.entries() if isinstance(item.entry, ApprovalDecided)]
        published = [
            (frame.seq, frame.entry)
            for frame in rt.frames.published
            if isinstance(frame, EntryFrame) and isinstance(frame.entry, ApprovalDecided)
        ]
        assert published == [(item.seq, item.entry) for item in decided]
        assert len(published) == 1

    async def test_a_buttonless_message_that_is_not_an_approval_answer_runs_normally(
        self, rt: Runtime
    ) -> None:
        await start_work(rt)
        await send(rt, asked("ask", "t1", "ap1"))
        rt.runner.script([Finished(Replied("sure"))])
        await send(rt, bot_user("u6"))
        await run(rt)
        assert rt.approvals.asked == ["yes do it"]
        assert [type(call) for call in rt.runner.calls] == [Started]
        assert not any(isinstance(item.entry, ApprovalDecided) for item in await rt.entries())

    async def test_the_web_surface_never_classifies_an_approval_answer(self, rt: Runtime) -> None:
        await start_work(rt)
        await send(rt, asked("ask", "t1", "ap1"))
        rt.approvals.decision = "approve"
        rt.runner.script([Finished(Replied("use the button"))])
        await send(rt, user("u6"))
        await run(rt)
        assert rt.approvals.asked == []
        assert [type(call) for call in rt.runner.calls] == [Started]

    async def test_a_work_result_before_commit_restarts_into_one_reply(self, rt: Runtime) -> None:
        await start_work(rt)
        rt.runner.script(
            [Do(arrive(rt, finished("f", "t1"))), text("x")],
            [Finished(Replied("both"))],
        )
        await send(rt, user("u5"))
        await run(rt)
        assert rt.runner.calls[1:3] == [RESTART, Started(batch=(5, 6), context=(2, 3, 4))]
        assert (await answered(rt))[-1] == (ReplyOutcome.ANSWERED, ("u5", "f", "u0"))
        assert (await settles(rt))[-1].narrates == ("t1",)

    async def test_a_work_result_after_commit_is_answered_by_the_next_run(
        self, rt: Runtime
    ) -> None:
        await start_work(rt)
        rt.runner.script(
            [text("x"), Do(arrive(rt, finished("f", "t1"))), Finished(Replied("x"))],
            [Finished(Replied("report"))],
        )
        await send(rt, user("u5"))
        await run(rt)
        assert (await answered(rt))[-2:] == [
            (ReplyOutcome.ANSWERED, ("u5",)),
            (ReplyOutcome.ANSWERED, ("f", "u0")),
        ]
        await assert_quiet(rt)

    async def test_a_message_the_instant_work_finishes_shares_its_reply(self, rt: Runtime) -> None:
        await start_work(rt)
        rt.runner.script([Finished(Replied("done, and yes"))])
        await send(rt, finished("f", "t1"), user("u6"))
        await run(rt)
        assert rt.runner.calls == [Started(batch=(5, 6), context=(2, 3, 4))]
        last = (await settles(rt))[-1]
        assert (last.narrates, last.answers) == (("t1",), ("f", "u6", "u0"))

    async def test_stop_while_thinking_withdraws_the_attempt_and_writes_no_reply(
        self, rt: Runtime
    ) -> None:
        rt.runner.script([Pause((arrive(rt, stop("s")),))])
        await send(rt, user("u1"))
        await run(rt)
        assert await kinds(rt) == ["user_message", "stop_requested"]
        assert rt.runner.calls == [Started(batch=(1,), context=()), STOP]
        assert RetractFrame(attempt_id="1.1") in rt.frames.published
        assert (await rt.log.state(CONVERSATION, USER)).stopped_through == 1
        await assert_quiet(rt)

    async def test_stop_mid_text_settles_the_reply_stopped_with_the_partial_text(
        self, rt: Runtime
    ) -> None:
        rt.runner.script([text("partial"), Pause((arrive(rt, stop("s")),))])
        await send(rt, user("u1"))
        await run(rt)
        assert await kinds(rt) == ["user_message", "reply", "stop_requested", "reply_settled"]
        assert (await replies(rt))[0].text == "partial"
        assert await answered(rt) == [(ReplyOutcome.STOPPED, ())]
        assert (await settles(rt))[0].through == 2
        await assert_quiet(rt)

    async def test_a_store_error_mid_attempt_settles_it_failed_and_releases(
        self, rt: Runtime
    ) -> None:
        rt.frames = _FlakyFrames()
        rt.runner.script([text("hel"), text("lo"), Finished(Replied("hello"))])
        await send(rt, user("u1"))
        await run(rt)
        assert await answered(rt) == [(ReplyOutcome.FAILED, ("u1",))]
        await assert_quiet(rt)

    async def test_a_message_stopped_before_any_run_saw_it_never_reaches_the_next(
        self, rt: Runtime
    ) -> None:
        rt.runner.script([Finished(Replied("hello"))])
        await send(rt, user("u1"), stop("s"), user("u3"))
        await run(rt)
        # The Stop's marker, never the stopped message.
        assert rt.runner.calls == [Started(batch=(3,), context=(2,))]
        assert await answered(rt) == [(ReplyOutcome.ANSWERED, ("u3",))]

    async def test_stop_then_a_new_message_answers_the_new_message_normally(
        self, rt: Runtime
    ) -> None:
        rt.runner.script(
            [Pause((arrive(rt, stop("s"), user("u3")),))],
            [Finished(Replied("hello"))],
        )
        await send(rt, user("u1"))
        await run(rt)
        assert rt.runner.calls == [
            Started(batch=(1,), context=()),
            STOP,
            Started(batch=(3,), context=(2,)),
        ]
        assert await answered(rt) == [(ReplyOutcome.ANSWERED, ("u3",))]
        await assert_quiet(rt)

    async def test_a_typed_stop_issued_by_the_run_does_not_stop_its_own_batch(
        self, rt: Runtime
    ) -> None:
        own_stop = stop("s", covers_through=0, by=StopBy.GAIA)
        rt.runner.script(
            [
                ModelOutput(True),
                Do(arrive(rt, own_stop)),
                text("stopped it"),
                Finished(Replied("ok")),
            ]
        )
        await send(rt, user("u1"))
        await run(rt)
        assert rt.runner.calls == [Started(batch=(1,), context=())]
        assert await answered(rt) == [(ReplyOutcome.ANSWERED, ("u1",))]

    async def test_a_barge_in_mid_reply_keeps_only_the_heard_part_and_waits_for_the_words(
        self, rt: Runtime
    ) -> None:
        rt.runner.script(
            [text("hello there friend"), Pause((arrive(rt, barge("b", "r1.1", 5)),))],
            [Finished(Replied("go on"))],
        )
        await send(rt, user("u1", voice=True))
        await run(rt)
        assert rt.runner.calls == [Started(batch=(1,), context=()), TRUNCATE]
        cut = (await replies(rt))[0]
        assert (cut.text, cut.heard_through) == ("hello", 5)
        assert await answered(rt) == [(ReplyOutcome.TRUNCATED, ("u1",))]
        assert (await rt.log.state(CONVERSATION, USER)).unsettled_waking == ()
        await send(rt, user("u2", voice=True))
        await run(rt)
        # The cut reply rides in the next attempt's context, where it reads as only its heard part.
        assert rt.runner.calls[2] == Started(batch=(5,), context=(2, 3, 4))
        assert await answered(rt) == [
            (ReplyOutcome.TRUNCATED, ("u1",)),
            (ReplyOutcome.ANSWERED, ("u2",)),
        ]
        await assert_quiet(rt)

    async def test_a_barge_in_on_a_reply_already_settled_cuts_it_to_the_heard_part(
        self, rt: Runtime
    ) -> None:
        rt.runner.script([text("hello there friend"), Finished(Replied("hello there friend"))])
        await send(rt, user("u1", voice=True))
        await run(rt)
        await send(rt, barge("b", "r1.1", 5))
        await run(rt)
        cut = (await replies(rt))[0]
        assert (cut.text, cut.heard_through) == ("hello", 5)
        assert await answered(rt) == [(ReplyOutcome.ANSWERED, ("u1",))]
        assert rt.runner.calls == [Started(batch=(1,), context=())]
        await assert_quiet(rt)

    @pytest.mark.parametrize(
        "spoken_over",
        [barge("b", "r1.1", len("hello there friend")), barge("b", "r-unknown", 5)],
        ids=["heard-to-the-end", "names-no-reply"],
    )
    async def test_a_barge_in_that_cut_nothing_off_changes_nothing(
        self, rt: Runtime, spoken_over: BargeIn
    ) -> None:
        rt.runner.script([text("hello there friend"), Finished(Replied("hello there friend"))])
        await send(rt, user("u1", voice=True))
        await run(rt)
        await send(rt, spoken_over)
        await run(rt)
        reply = (await replies(rt))[0]
        assert (reply.text, reply.heard_through) == ("hello there friend", None)
        assert rt.runner.calls == [Started(batch=(1,), context=())]
        await assert_quiet(rt)

    async def test_a_ten_message_burst_gets_one_reply(self, rt: Runtime) -> None:
        ids = [f"u{n}" for n in range(1, 11)]
        rt.runner.script([Finished(Replied("all of it"))])
        await send(rt, *(user(entry_id) for entry_id in ids))
        await run(rt)
        assert rt.runner.calls == [Started(batch=tuple(range(1, 11)), context=())]
        assert await answered(rt) == [(ReplyOutcome.ANSWERED, tuple(ids))]

    async def test_a_run_that_raises_before_commit_leaves_a_failed_bubble(
        self, rt: Runtime
    ) -> None:
        rt.runner.script([Fail(RuntimeError("model down"))])
        await send(rt, user("u1"))
        await run(rt)
        assert rt.runner.calls == [Started(batch=(1,), context=()), LOST]
        assert await kinds(rt) == ["user_message", "reply", "reply_settled"]
        assert await answered(rt) == [(ReplyOutcome.FAILED, ("u1",))]
        await assert_quiet(rt)

    async def test_a_run_that_raises_after_commit_keeps_what_was_shown(self, rt: Runtime) -> None:
        rt.runner.script([text("half"), Fail(RuntimeError("model down"))])
        await send(rt, user("u1"))
        await run(rt)
        assert (await replies(rt))[0].text == "half"
        assert await answered(rt) == [(ReplyOutcome.FAILED, ("u1",))]
        assert [s.failure for s in await settles(rt)] == [FailureReason.MODEL_ERROR]
        await assert_quiet(rt)

    async def test_a_run_that_hits_the_step_limit_says_so_on_its_settle(self, rt: Runtime) -> None:
        rt.runner.script([text("half"), Fail(StepLimitReached("limit"))])
        await send(rt, user("u1"))
        await run(rt)
        assert [s.failure for s in await settles(rt)] == [FailureReason.STEP_LIMIT]

    async def test_a_second_fire_while_the_first_is_unanswered_is_refused(
        self, rt: Runtime
    ) -> None:
        rt.runner.script([Finished(Replied("first run"))])
        await send(rt, fired("wf1"))
        with pytest.raises(EntryRejected):
            await send(rt, fired("wf2", "ex_2"))
        await run(rt)
        assert await answered(rt) == [(ReplyOutcome.ANSWERED, ("wf1",))]
        await send(rt, fired("wf3", "ex_3"))
        assert (await rt.log.state(CONVERSATION, USER)).unsettled_waking == (4,)

    async def test_a_silent_run_for_a_user_still_answers_with_the_fallback(
        self, rt: Runtime
    ) -> None:
        rt.runner.script([Finished(Silent())])
        await send(rt, user("u1"))
        await run(rt)
        assert (await replies(rt))[0].text == EMPTY_RESPONSE_FALLBACK
        assert await answered(rt) == [(ReplyOutcome.ANSWERED, ("u1",))]

    async def test_a_silent_run_for_a_workflow_settles_silently(self, rt: Runtime) -> None:
        rt.runner.script([Finished(Silent())])
        await send(rt, fired("wf"))
        await run(rt)
        assert await answered(rt) == [(ReplyOutcome.SILENT, ("wf",))]
        assert (await replies(rt))[0].text == ""

    async def test_a_first_tool_call_with_no_text_appends_no_reply_until_something_shows(
        self, rt: Runtime
    ) -> None:
        seen: list[list[str]] = []

        async def look() -> None:
            seen.append(await kinds(rt))

        rt.runner.script(
            [ModelOutput(True), Do(look), text("found it"), Finished(Replied("found it"))]
        )
        await send(rt, user("u1"))
        await run(rt)
        assert seen == [["user_message"]]
        assert await kinds(rt) == ["user_message", "reply", "reply_settled"]

    async def test_a_reply_settles_when_its_answer_is_final_and_follow_ups_arrive_as_an_update(
        self, rt: Runtime
    ) -> None:
        """Regression (live test): settle waited ~4 s for the follow-up suggestions after the answer."""
        while_suggesting: list[list[str]] = []

        async def look() -> None:
            while_suggesting.append(await kinds(rt))

        rt.runner.script(
            [
                text("hi"),
                ModelOutput(False),
                Answered(Replied("hi")),
                Do(look),
                Finished(Replied("hi", follow_up_actions=("Ask more",))),
            ]
        )
        await send(rt, user("u1"))
        await run(rt)
        assert while_suggesting == [["user_message", "reply", "reply_settled"]]
        assert await answered(rt) == [(ReplyOutcome.ANSWERED, ("u1",))]
        assert (await replies(rt))[0].follow_up_actions == ("Ask more",)
        assert frame_kinds(rt)[-1] == "entry_updated"

    async def test_two_advance_calls_at_once_run_exactly_one_step(self, rt: Runtime) -> None:
        rt.runner.script([Finished(Replied("once"))])
        await send(rt, user("u1"))
        await asyncio.gather(run(rt), run(rt))
        assert rt.runner.calls == [Started(batch=(1,), context=())]
        assert await answered(rt) == [(ReplyOutcome.ANSWERED, ("u1",))]

    async def test_a_lost_claim_mid_run_writes_nothing_more_and_the_next_holder_finishes(
        self, rt: Runtime
    ) -> None:
        async def die() -> None:
            await rt.lapse()

        rt.runner.script([text("half"), Pause((die,))], [Finished(Replied("whole"))])
        await send(rt, user("u1"))
        await run(rt)
        assert rt.runner.calls == [Started(batch=(1,), context=()), LOST]
        assert await kinds(rt) == ["user_message", "reply"]
        await run(rt)
        assert await kinds(rt) == [
            "user_message",
            "reply",
            "reply_settled",
            "reply",
            "reply_settled",
        ]
        assert rt.runner.calls[-1] == Started(batch=(1,), context=(2, 3))
        assert await answered(rt) == [(ReplyOutcome.FAILED, ()), (ReplyOutcome.ANSWERED, ("u1",))]
        assert [s.failure for s in await settles(rt)] == [FailureReason.SERVER_RESTART, None]
        await assert_quiet(rt)

    async def test_a_swallowed_first_cancel_starts_no_second_run_until_the_first_is_dead(
        self, rt: Runtime
    ) -> None:
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

    async def test_taking_over_a_dead_uncommitted_holder_redoes_its_inputs(
        self, rt: Runtime
    ) -> None:
        await send(rt, user("u1"))
        dead = await rt.log.claim(CONVERSATION, USER)
        assert dead is not None
        await rt.log.set_comms(dead, CommsPhase.THINKING)
        await rt.lapse()
        rt.runner.script([Finished(Replied("answer"))])
        await run(rt)
        assert rt.runner.calls == [Started(batch=(1,), context=())]
        assert await answered(rt) == [(ReplyOutcome.ANSWERED, ("u1",))]
        await assert_quiet(rt)

    async def test_taking_over_a_dead_committed_holder_fails_its_reply_and_answers_again(
        self, rt: Runtime
    ) -> None:
        await send(rt, user("u1"))
        dead = await rt.log.claim(CONVERSATION, USER)
        assert dead is not None
        await rt.log.append_fenced(dead, opened("o", "r_dead").model_copy(update={"text": "par"}))
        await rt.lapse()
        rt.runner.script([Finished(Replied("answer"))])
        await run(rt)
        assert rt.runner.calls == [Started(batch=(1,), context=(2, 3))]
        assert await answered(rt) == [(ReplyOutcome.FAILED, ()), (ReplyOutcome.ANSWERED, ("u1",))]
        assert (await replies(rt))[0].text == "par"
        # The reply a dead holder appended is republished, since its frame may never have gone out.
        assert [frame.kind.value for frame in rt.frames.published[:4]] == [
            "entry",
            "state",
            "entry",
            "entry",
        ]
        await assert_quiet(rt)

    async def test_a_step_killed_mid_run_kills_its_run_and_leaves_its_reply_to_recovery(
        self, rt: Runtime
    ) -> None:
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
        assert await kinds(rt) == ["user_message", "reply"]
        await rt.lapse()
        await run(rt)
        assert await answered(rt) == [(ReplyOutcome.FAILED, ()), (ReplyOutcome.ANSWERED, ("u1",))]
        await assert_quiet(rt)

    async def test_stop_after_text_and_a_card_saves_both_on_the_stopped_reply(
        self, rt: Runtime
    ) -> None:
        rt.runner.script([text("looking"), card(), Pause((arrive(rt, stop("s")),))])
        await send(rt, user("u1"))
        await run(rt)
        saved = (await replies(rt))[0]
        assert (saved.text, saved.tool_data) == ("looking", (CARD,))
        assert await answered(rt) == [(ReplyOutcome.STOPPED, ())]

    async def test_a_failure_after_a_card_with_no_text_saves_the_card_and_settles_failed(
        self, rt: Runtime
    ) -> None:
        rt.runner.script([card(), Fail(RuntimeError("model down"))])
        await send(rt, user("u1"))
        await run(rt)
        saved = (await replies(rt))[0]
        assert (saved.text, saved.tool_data) == ("", (CARD,))
        assert await answered(rt) == [(ReplyOutcome.FAILED, ("u1",))]

    async def test_each_answered_reply_counts_once_as_completed_on_the_message_it_answers(
        self, rt: Runtime, posthog_turns: list[dict[str, object]]
    ) -> None:
        rt.runner.script(
            [text("hi"), Do(arrive(rt, user("u2"))), Finished(Replied("hi"))],
            [Finished(Replied("again"))],
        )
        await send(rt, user("u1"))
        await run(rt)
        await run(rt)
        spoken = ("user", "interactive", "web")
        completed = ("chat:message_completed", USER, spoken)
        assert turn_ends(posthog_turns) == [
            (*completed, "u1", CONVERSATION, True, False, False, "web"),
            (*completed, "u2", CONVERSATION, False, False, True, "web"),
        ]
        ended = [e for e in posthog_turns if e["event"] == "chat:message_completed"]
        props = cast(dict[str, object], ended[0]["properties"])
        assert isinstance(props["ttft_ms"], float) and isinstance(props["e2e_full_ms"], float)
        assert 0 <= props["ttft_ms"] <= props["e2e_full_ms"]

    async def test_a_stopped_reply_counts_once_as_cancelled(
        self, rt: Runtime, posthog_turns: list[dict[str, object]]
    ) -> None:
        rt.runner.script([text("partial"), Pause((arrive(rt, stop("s")),))])
        await send(rt, user("u1", voice=True))
        await run(rt)
        assert turn_ends(posthog_turns) == [
            (
                "chat:message_cancelled",
                USER,
                ("user", "interactive", "voice"),
                "u1",
                CONVERSATION,
                True,
                False,
                False,
                "web",
            )
        ]

    async def test_a_reply_is_counted_in_the_browser_session_its_message_came_from(
        self, rt: Runtime, posthog_turns: list[dict[str, object]]
    ) -> None:
        rt.runner.script([Finished(Replied("hi"))])
        await send(rt, user("u1").model_copy(update={"posthog_session_id": "0190f00d-sess"}))
        await run(rt)
        [ended] = [e for e in posthog_turns if e["event"] == "chat:message_completed"]
        assert cast(dict[str, object], ended["properties"])["$session_id"] == "0190f00d-sess"

    async def test_a_file_the_run_made_is_saved_on_the_reply(self, rt: Runtime) -> None:
        made = Streamed(payload=ToolDataEvent(tool_data=FILE_CARD))
        rt.runner.script([text("here it is"), made, made, Finished(Replied("here it is"))])
        await send(rt, user("u1"))
        await run(rt)
        [reply] = [
            logged.entry
            for logged in await rt.log.read_after(CONVERSATION, USER, 0)
            if isinstance(logged.entry, Reply)
        ]
        assert FILE_CARD in reply.tool_data

    async def test_a_reply_that_dispatched_work_counts_as_delegated(
        self, rt: Runtime, posthog_turns: list[dict[str, object]]
    ) -> None:
        await start_work(rt)
        [end] = turn_ends(posthog_turns)
        assert end[3:6] == ("u0", CONVERSATION, True) and end[6] is True

    async def test_a_reply_to_no_user_message_and_a_failed_reply_count_nothing(
        self, rt: Runtime, posthog_turns: list[dict[str, object]]
    ) -> None:
        rt.runner.script([Finished(Replied("the workflow ran"))], [Fail(RuntimeError("down"))])
        await send(rt, fired("wf"))
        await run(rt)
        await send(rt, user("u1"))
        await run(rt)
        assert await answered(rt) == [
            (ReplyOutcome.ANSWERED, ("wf",)),
            (ReplyOutcome.FAILED, ("u1",)),
        ]
        assert turn_ends(posthog_turns) == []

    async def test_a_reply_that_resolves_to_a_reaction_counts_it_once_on_the_user(
        self, rt: Runtime, posthog_turns: list[dict[str, object]]
    ) -> None:
        rt.runner.script([Finished(Reacted("👍"))])
        await send(rt, user("u1"))
        await run(rt)
        reacted = [e for e in posthog_turns if e["event"] == "chat:turn_reacted"]
        assert [
            (e["distinct_id"], cast(dict[str, object], e["properties"])["emoji"]) for e in reacted
        ] == [(USER, "👍")]
        props = cast(dict[str, object], reacted[0]["properties"])
        assert (props["actor"], props["trigger"], props["surface"]) == (
            "user",
            "interactive",
            "web",
        )


@dataclass
class _FlakyFrames(RecordingFrames):
    """Fails the first reply delta once, as a Redis blip mid-reply would."""

    failed: bool = False

    async def publish(self, conversation_id: str, *frames: OutputFrame) -> None:
        if any(isinstance(frame, ReplyDeltaFrame) for frame in frames) and not self.failed:
            self.failed = True
            raise ConnectionError("redis down")
        await super().publish(conversation_id, *frames)


class TestStepScenariosInMemory(StepScenarios):
    @pytest.fixture
    def rt(self) -> Runtime:
        return Runtime()
