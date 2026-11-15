"""advance under random interleavings of inputs, run scripts, killed steps and concurrent steps."""

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from itertools import count, pairwise, takewhile

from hypothesis import example, given, settings, strategies as st

from app.constants.chat import ConversationSource
from app.models.conversation_frame_models import (
    EntryFrame,
    EntryUpdatedFrame,
    MessageBoundaryEvent,
    ResponseEvent,
    ToolDataEvent,
    ToolOutputEvent,
)
from app.models.conversation_log_models import (
    CommsPhase,
    ConversationState,
    Entry,
    LoggedEntry,
    Rejected,
    Reply,
    ReplySettled,
    StopBy,
    StopRequested,
    UserMessage,
    WorkFinished,
    WorkOutcome,
    WorkStarted,
)
from app.models.stream_events import MessageBoundaryPayload, ToolOutputPayload
from app.services.conversation.log import accept
from app.services.conversation.ports import (
    Answered,
    EntryRejected,
    Finished,
    ModelOutput,
    Reacted,
    Replied,
    RunOutcome,
    Silent,
    Streamed,
    Summarized,
)
from app.services.conversation.reducer import reduce
from app.services.conversation.screen import handoff_call_id, project_screen
from app.services.conversation.screen_patches import screen_patches
from app.services.conversation.step import advance
from app.utils.errors import ShownReplyRetriedError
from shared.py.conversation_wire import (
    NEW_MESSAGE_BREAKER,
    BubblesDelta,
    BubbleTextDelta,
    CardsDelta,
    ReplyDeltaFrame,
    ReplyOutcome,
    ToolDataEntry,
)
from tests.hypothesis_profiles import property_examples
from tests.unit.services.conversation.log_helpers import (
    EMPTY,
    asked,
    barge,
    decided,
    fired,
    stop,
    user,
)
from tests.unit.services.conversation.runtime_doubles import (
    CONVERSATION,
    USER,
    Action,
    Close,
    Do,
    Fail,
    Forgetful,
    Pause,
    Runtime,
    ScriptItem,
)

APPEND_KINDS = (
    "user",
    "bot_user",
    "stop",
    "gaia_stop",
    "fire",
    "barge",
    "work_start",
    "ask",
    "decide",
    "retry",
    "work_done",
    "work_cancelled",
)
QUIET_ROUNDS = 30
STEP_EXAMPLES = property_examples(2000)


_STATELESS: dict[str, Callable[[int], Entry]] = {
    "user": lambda number: user(f"u{number}"),
    "stop": lambda number: stop(f"s{number}"),
    "fire": lambda number: fired(f"wf{number}"),
    "bot_user": lambda number: UserMessage(
        id=f"b{number}", text="yes", surface=ConversationSource.TELEGRAM
    ),
}


@dataclass(frozen=True)
class AppendOp:
    kind: str


@dataclass(frozen=True)
class AdvanceOp:
    # Kill the step at its kill_at-th port call; None lets it run to the end.
    kill_at: int | None
    concurrent: bool


Op = AppendOp | AdvanceOp


@dataclass
class World:
    """One generated history: the runtime, the scripts, and the kill switch for step tasks."""

    rt: Runtime
    ids: "count[int]" = field(default_factory=lambda: count(1))
    steps: set[asyncio.Task[None]] = field(default_factory=set)
    calls: int = 0
    kill_at: int | None = None
    lapsed: bool = False

    async def pause(self, point: str) -> None:
        if asyncio.current_task() not in self.steps:
            return
        self.calls += 1
        if self.calls == self.kill_at:
            raise asyncio.CancelledError

    async def append(self, kind: str) -> None:
        if kind == "lapse":
            # The holder's process stalls past its liveness, so its claim can be taken over.
            await self.rt.lapse()
            self.lapsed = True
            return
        entry = await self._entry(kind, next(self.ids))
        if entry is None:
            return
        try:
            await accept(self.rt.ports, CONVERSATION, USER, entry)
        except EntryRejected:
            # A producer whose cause was stopped meanwhile is refused; that is its contract.
            return

    def action(self, kind: str) -> Action:
        async def append() -> None:
            await self.append(kind)

        return append

    async def _entry(self, kind: str, number: int) -> Entry | None:
        if kind in _STATELESS:
            return _STATELESS[kind](number)
        state = await self.rt.log.state(CONVERSATION, USER)
        entry: Entry | None
        match kind:
            case "gaia_stop":
                entry = stop(f"g{number}", covers_through=state.settled_through, by=StopBy.GAIA)
            case "barge":
                entry = barge(f"v{number}", state.open_reply) if state.open_reply else None
            case "ask":
                live = state.work[0].task_id if state.work else None
                entry = asked(f"a{number}", live, f"ap{number}") if live else None
            case "decide":
                waiting = [approval for item in state.work for approval in item.pending_approvals]
                entry = decided(f"d{number}", waiting[0]) if waiting else None
            case "retry":
                entry = await self._retry(number)
            case "work_start":
                entry = await self._work_start(state, number)
            case _:
                entry = self._work_end(state, number, kind)
        return entry

    async def _retry(self, number: int) -> UserMessage | None:
        entries = await self.rt.entries()
        sent = [item.entry.id for item in entries if isinstance(item.entry, UserMessage)]
        return user(f"y{number}").model_copy(update={"retry_of": sent[-1]}) if sent else None

    async def _work_start(self, state: ConversationState, number: int) -> WorkStarted | None:
        if state.head <= state.stopped_through:
            return None
        causes = [
            item.entry.id
            for item in await self.rt.entries()
            if isinstance(item.entry, UserMessage) and item.seq > state.stopped_through
        ]
        return WorkStarted(
            id=f"w{number}",
            task_id=f"t{number}",
            cause_through=state.head,
            answers=tuple(causes[-1:]),
        )

    def _work_end(self, state: ConversationState, number: int, kind: str) -> WorkFinished | None:
        if not state.work:
            return None
        outcome = WorkOutcome.DONE if kind == "work_done" else WorkOutcome.CANCELLED
        return WorkFinished(
            id=f"f{number}", task_id=state.work[0].task_id, outcome=outcome, report="r"
        )

    async def advance(self, op: AdvanceOp) -> None:
        await self.rt.lapse()
        self.calls, self.kill_at, self.lapsed = 0, op.kill_at, False
        tasks = [asyncio.create_task(advance(self.rt.ports, CONVERSATION, USER))]
        if op.concurrent:
            tasks.append(asyncio.create_task(advance(self.rt.ports, CONVERSATION, USER)))
        self.steps.update(tasks)
        await asyncio.gather(*tasks, return_exceptions=True)
        self.steps.difference_update(tasks)
        for task in tasks:
            if not task.cancelled():
                assert task.exception() is None, repr(task.exception())
        if not self.lapsed and not any(task.cancelled() for task in tasks):
            # A step that was neither killed nor lost its claim leaves nothing to repair.
            state = await self.rt.log.state(CONVERSATION, USER)
            assert (state.comms, state.unsettled_waking) == (CommsPhase.IDLE, ())


OUTCOMES: dict[str, RunOutcome] = {
    "replied": Replied("an answer"),
    "empty": Replied(""),
    "reacted": Reacted("👍"),
    "silent": Silent(),
}


# call_/output_ steps of two parallel tool calls, ordered freely: results land out of order.
RUN_STEPS = (
    "text",
    "card",
    "tool_call",
    "model",
    "summary",
    "do",
    "pause",
    "call_c1",
    "call_c2",
    "output_c1",
    "output_c2",
    "boundary",
    "retry",
    # The model names every message still open (answered), or never names anything (forget).
    "name",
    "forget",
)
RUN_ENDS = ("replied", "empty", "reacted", "silent", "fail", "answered")


@st.composite
def scripts(draw: st.DrawFn, world_kinds: st.SearchStrategy[str]) -> list[tuple[str, str]]:
    steps = draw(st.lists(st.tuples(st.sampled_from(RUN_STEPS), world_kinds), max_size=7))
    end = draw(st.sampled_from(RUN_ENDS))
    return [*steps, (end, "")]


def _call_card(call: str) -> ToolDataEvent:
    data = {"tool_name": "search", "tool_call_id": call}
    return ToolDataEvent(tool_data={"tool_name": "tool_calls_data", "data": data})


def _tool_result(call: str) -> Streamed:
    # A running tool's result: it stays beside its call, above inputs handed since.
    output = ToolOutputPayload(tool_call_id=call, output="done")
    return Streamed(payload=ToolOutputEvent(tool_output=output), by_model=False)


_FIXED_ITEMS: dict[str, tuple[ScriptItem, ...]] = {
    "text": (Streamed(payload=ResponseEvent(response="word ")),),
    "tool_call": (ModelOutput(has_tool_calls=True),),
    "model": (ModelOutput(has_tool_calls=False),),
    "summary": (Summarized(),),
    "name": (Close(),),
    "forget": (Forgetful(),),
    **{f"call_{call}": (Streamed(payload=_call_card(call)),) for call in ("c1", "c2")},
    **{f"output_{call}": (_tool_result(call),) for call in ("c1", "c2")},
    "answered": (Answered(Replied("an answer")), Finished(Replied("an answer"))),
    **{end: (Finished(outcome),) for end, outcome in OUTCOMES.items()},
}


def _shows_text(item: ScriptItem) -> bool:
    return isinstance(item, Streamed) and isinstance(item.payload, ResponseEvent)


def _script(world: World, plan: Sequence[tuple[str, str]]) -> list[ScriptItem]:
    items: list[ScriptItem] = []
    for step, kind in plan:
        match step:
            case "card":
                card = ToolDataEvent(tool_data={"tool_name": "search", "data": {"n": len(items)}})
                items.append(Streamed(payload=card))
            case "do":
                items.append(Do(world.action(kind)))
            case "pause":
                items.append(Pause((world.action(kind),)))
            case "fail":
                items.append(Fail(RuntimeError("model down")))
            case "boundary":
                boundary = MessageBoundaryPayload(message_id=f"m{len(items)}")
                items.append(Streamed(payload=MessageBoundaryEvent(message_boundary=boundary)))
            case "retry" if any(_shows_text(item) for item in items):
                # A model call retried after its text showed: the run fails as shown, never retracting.
                items.append(Fail(ShownReplyRetriedError(message="retried after text showed")))
            case "retry":
                pass
            case _:
                items.extend(_FIXED_ITEMS[step])
    return items


ops = st.lists(
    st.one_of(
        st.sampled_from(APPEND_KINDS).map(AppendOp),
        st.builds(AdvanceOp, st.none() | st.integers(1, 40), st.booleans()),
    ),
    min_size=1,
    max_size=10,
)
# Half of a run's mid-run inputs are a user message: the input placement turns on.
run_inputs = st.just("user") | st.sampled_from((*APPEND_KINDS, "lapse"))
run_plans = st.lists(scripts(run_inputs), min_size=1, max_size=6)


async def _play(
    op_list: Sequence[Op], plans: Sequence[Sequence[tuple[str, str]]], approves: bool
) -> World:
    rt = Runtime()
    rt.approvals.decision = "approve" if approves else None
    world = World(rt=rt)
    rt.log.pause = world.pause
    rt.runner.unscripted = (Finished(Replied("caught up")),)
    rt.runner.script(*(_script(world, plan) for plan in plans))
    for op in op_list:
        if isinstance(op, AppendOp):
            await world.append(op.kind)
        else:
            await world.advance(op)
    for _ in range(QUIET_ROUNDS):
        await world.advance(AdvanceOp(kill_at=None, concurrent=False))
        state = await rt.log.state(CONVERSATION, USER)
        if not state.unsettled_waking and state.comms is CommsPhase.IDLE:
            break
    return world


def _removals(entries: Sequence[LoggedEntry]) -> dict[int, LoggedEntry]:
    """Map each waking seq to the entry whose append took it out of unsettled_waking."""
    state = EMPTY
    removed_by: dict[int, LoggedEntry] = {}
    for logged in entries:
        result = reduce(state, logged)
        assert not isinstance(result, Rejected), result
        gone = set(state.unsettled_waking) - set(result.state.unsettled_waking)
        removed_by.update(dict.fromkeys(gone, logged))
        state = result.state
    return removed_by


def _woken(entries: Sequence[LoggedEntry]) -> list[LoggedEntry]:
    state = EMPTY
    woken = []
    for logged in entries:
        result = reduce(state, logged)
        assert not isinstance(result, Rejected), result
        if logged.seq in result.state.unsettled_waking:
            woken.append(logged)
        state = result.state
    return woken


def _causes(entries: Sequence[LoggedEntry]) -> dict[str, tuple[str, ...]]:
    """Map each WorkFinished id to the user messages that caused its work."""
    started = {
        item.entry.task_id: item.entry.answers
        for item in entries
        if isinstance(item.entry, WorkStarted)
    }
    return {
        item.entry.id: started.get(item.entry.task_id, ())
        for item in entries
        if isinstance(item.entry, WorkFinished)
    }


def _assert_every_input_answered_once_or_stopped(entries: Sequence[LoggedEntry]) -> None:
    """Check no run ended owing: every input is named by exactly one settle, or a Stop took it out."""
    removed_by = _removals(entries)
    causes = _causes(entries)
    settles = [item.entry for item in entries if isinstance(item.entry, ReplySettled)]
    owed: dict[str, set[str]] = {}
    for woken in _woken(entries):
        remover = removed_by.get(woken.seq)
        assert remover is not None, f"seq {woken.seq} ({woken.entry.id}) never settled"
        # A settle that delivers finished work also names the messages that caused it.
        naming = [
            settled
            for settled in settles
            if woken.entry.id in settled.answers
            and not any(woken.entry.id in causes.get(answer, ()) for answer in settled.answers)
        ]
        assert len(naming) <= 1, f"{woken.entry.id} answered by {[n.id for n in naming]}"
        naming = naming or [settled for settled in settles if woken.entry.id in settled.answers][:1]
        if not naming:
            assert isinstance(remover.entry, StopRequested), (
                f"{woken.entry.id} was dropped: removed by {remover.entry.kind}, named by no reply"
            )
            continue
        owed.setdefault(naming[0].id, set()).update(
            {woken.entry.id, *causes.get(woken.entry.id, ())}
        )
    for settled in settles:
        extra = set(settled.answers) - owed.get(settled.id, set())
        assert not extra, f"{settled.id} answers {extra}, which it did not cover"


def _assert_no_reply_settled_twice(entries: Sequence[LoggedEntry]) -> None:
    settled = [item.entry.reply_id for item in entries if isinstance(item.entry, ReplySettled)]
    assert len(settled) == len(set(settled)), settled


def _streamed(deltas: list[ReplyDeltaFrame]) -> tuple[str, tuple[ToolDataEntry, ...]]:
    """Return the text and cards a client following the deltas shows."""
    bubbles: list[str] = []
    cards: tuple[ToolDataEntry, ...] = ()
    for frame in deltas:
        match frame.payload:
            case BubbleTextDelta(bubble=bubble, text=more):
                if bubble == len(bubbles):
                    bubbles.append("")
                bubbles[bubble] += more
            case BubblesDelta(bubbles=now):
                bubbles = list(now)
            case CardsDelta(tool_data=now):
                cards = now
            case _:
                pass
    return NEW_MESSAGE_BREAKER.join(bubbles), cards


def _assert_no_empty_answer(entries: Sequence[LoggedEntry]) -> None:
    replies = {item.entry.reply_id: item.entry for item in entries if isinstance(item.entry, Reply)}
    for item in entries:
        if isinstance(item.entry, ReplySettled) and item.entry.outcome is ReplyOutcome.ANSWERED:
            reply = replies[item.entry.reply_id]
            assert reply.text or reply.tool_data, f"{reply.reply_id} answered with an empty bubble"


def _assert_saved_replies_keep_everything_shown(
    world: World, entries: Sequence[LoggedEntry]
) -> None:
    """Check each reply its own attempt settled carries exactly the fold of the deltas it showed."""
    shown: dict[str, list[ReplyDeltaFrame]] = {}
    for frame in world.rt.frames.published:
        if isinstance(frame, ReplyDeltaFrame):
            shown.setdefault(frame.attempt_id, []).append(frame)
    own_settles = {item.entry.id for item in entries if isinstance(item.entry, ReplySettled)}
    for item in entries:
        reply = item.entry
        if not isinstance(reply, Reply) or reply.attempt_id not in shown:
            continue
        if f"{reply.attempt_id}:settled" not in own_settles:
            continue
        deltas = sorted(shown[reply.attempt_id], key=lambda frame: frame.index)
        assert [frame.index for frame in deltas] == list(range(len(deltas)))
        text, cards = _streamed(deltas)
        own = tuple(card for card in reply.tool_data if handoff_call_id(card) is None)
        assert (reply.text, own) == (text, cards), reply.reply_id


def _assert_every_reply_sits_below_what_it_answers(entries: Sequence[LoggedEntry]) -> None:
    """Check every input a settled reply answers, a message or finished work, is logged above its slot."""
    replies = {item.entry.reply_id: item.seq for item in entries if isinstance(item.entry, Reply)}
    inputs = {item.entry.id: item.seq for item in _woken(entries)}
    for item in entries:
        settled = item.entry
        if not isinstance(settled, ReplySettled) or settled.reply_id not in replies:
            continue
        newest = max((inputs[a] for a in settled.answers if a in inputs), default=0)
        assert replies[settled.reply_id] > newest, (
            f"{settled.reply_id} sits above an input it answers"
        )


def _assert_every_live_screen_keeps_its_items_and_reloads_the_same(
    world: World, entries: Sequence[LoggedEntry]
) -> None:
    """Replay the frames as a client does: every prefix keeps the invariant and each shown item."""
    view: dict[int, LoggedEntry] = {}
    shown = project_screen([])
    for frame in world.rt.frames.published:
        if not isinstance(frame, EntryFrame | EntryUpdatedFrame):
            continue
        held = view.get(frame.seq)
        if held is not None and _revision(frame.entry) <= _revision(held.entry):
            continue
        at = frame.at if isinstance(frame, EntryFrame) else view[frame.seq].at
        view[frame.seq] = LoggedEntry(seq=frame.seq, at=at, entry=frame.entry)
        prefix = [view[seq] for seq in sorted(view)]
        # A killed step's frame may be missing until recovery republishes it: fold only the unbroken run.
        unbroken = list(takewhile(view.__contains__, count(1)))
        _assert_every_reply_sits_below_what_it_answers([view[seq] for seq in unbroken])
        if isinstance(frame.entry, Reply) and isinstance(held_reply := held and held.entry, Reply):
            assert frame.entry.text.startswith(held_reply.text), "a shown reply's text shrank"
        screen = project_screen(prefix)
        screen_patches(shown, screen, max(view))
        shown = screen
    assert shown == project_screen(list(entries))


def _assert_frames_reproduce_the_log(world: World, entries: Sequence[LoggedEntry]) -> None:
    view: dict[int, Entry] = {}
    for frame in world.rt.frames.published:
        if isinstance(frame, EntryFrame | EntryUpdatedFrame):
            held = view.get(frame.seq)
            if held is None or _revision(frame.entry) > _revision(held):
                view[frame.seq] = frame.entry
    assert view == {item.seq: item.entry for item in entries}


def _revision(entry: Entry) -> int:
    return entry.revision if isinstance(entry, Reply | UserMessage) else 0


_CARDS_THEN_A_NEW_ASK = [
    ("tool_call", ""),
    ("card", ""),
    ("do", "user"),
    ("card", ""),
    ("tool_call", ""),
    ("text", ""),
    ("replied", ""),
]
_RESULTS_OUT_OF_ORDER_AFTER_A_NEW_ASK = [
    ("call_c1", ""),
    ("call_c2", ""),
    ("text", ""),
    ("do", "user"),
    ("tool_call", ""),
    ("output_c2", ""),
    ("output_c1", ""),
    ("text", ""),
    ("answered", ""),
]
_TEXT_THEN_A_NEW_ASK = [
    ("text", ""),
    ("do", "user"),
    ("tool_call", ""),
    ("text", ""),
    ("replied", ""),
]
# A stop while a new ask waits below the shown text: the shown reply ends stopped, answering nothing.
_A_STOP_WITH_A_NEW_ASK_BELOW = [
    ("text", ""),
    ("do", "user"),
    ("tool_call", ""),
    ("do", "stop"),
    ("text", ""),
    ("replied", ""),
]
# A model call retried after its text showed: the shown reply fails as it stood.
_RETRIED_AFTER_TEXT_SHOWED = [("text", ""), ("retry", ""), ("replied", "")]


@settings(max_examples=STEP_EXAMPLES)
@given(op_list=ops, plans=run_plans, approves=st.booleans())
@example(op_list=[AppendOp("user")], plans=[_CARDS_THEN_A_NEW_ASK], approves=False)
@example(op_list=[AppendOp("user")], plans=[_RESULTS_OUT_OF_ORDER_AFTER_A_NEW_ASK], approves=False)
@example(op_list=[AppendOp("user")], plans=[_TEXT_THEN_A_NEW_ASK], approves=False)
@example(op_list=[AppendOp("user")], plans=[_RETRIED_AFTER_TEXT_SHOWED], approves=False)
@example(op_list=[AppendOp("user")], plans=[_A_STOP_WITH_A_NEW_ASK_BELOW], approves=False)
@example(
    op_list=[AppendOp("user"), AdvanceOp(15, False), AppendOp("user")],
    plans=[_A_STOP_WITH_A_NEW_ASK_BELOW],
    approves=False,
)
@example(op_list=[AppendOp("fire")], plans=[_RETRIED_AFTER_TEXT_SHOWED], approves=False)
@example(
    op_list=[AppendOp("user")],
    plans=[[("text", ""), ("retry", ""), ("fail", "")]],
    approves=False,
)
def test_any_interleaving_answers_every_input_once_with_one_run_at_a_time(
    op_list: list[Op], plans: list[list[tuple[str, str]]], approves: bool
) -> None:
    world = asyncio.run(_play(op_list, plans, approves))
    entries = asyncio.run(world.rt.entries())
    state = asyncio.run(world.rt.log.state(CONVERSATION, USER))
    assert (state.comms, state.unsettled_waking, state.open_reply) == (CommsPhase.IDLE, (), None)
    assert world.rt.runner.overlaps == 0
    assert all(a.seq < b.seq for a, b in pairwise(entries))
    _assert_every_input_answered_once_or_stopped(entries)
    _assert_no_reply_settled_twice(entries)
    _assert_no_empty_answer(entries)
    _assert_frames_reproduce_the_log(world, entries)
    _assert_saved_replies_keep_everything_shown(world, entries)
    _assert_every_reply_sits_below_what_it_answers(entries)
    _assert_every_live_screen_keeps_its_items_and_reloads_the_same(world, entries)
