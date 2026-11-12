"""advance under random interleavings of inputs, run scripts, killed steps and concurrent steps."""

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from itertools import count, pairwise

from hypothesis import given, settings, strategies as st

from app.constants.chat import ConversationSource
from app.models.conversation_frame_models import (
    EntryFrame,
    EntryUpdatedFrame,
    ReplyDeltaFrame,
    ResponseEvent,
    ToolDataEvent,
)
from app.models.conversation_log_models import (
    CommsPhase,
    ConversationState,
    Entry,
    LoggedEntry,
    Rejected,
    Reply,
    ReplyOutcome,
    ReplySettled,
    StopBy,
    StopRequested,
    UserMessage,
    WorkFinished,
    WorkOutcome,
    WorkStarted,
)
from app.services.conversation.log import accept
from app.services.conversation.ports import (
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
from app.services.conversation.step import advance
from tests.unit.services.conversation.log_helpers import EMPTY, asked, barge, fired, stop, user
from tests.unit.services.conversation.runtime_doubles import (
    CONVERSATION,
    USER,
    Action,
    Do,
    Fail,
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
    "work_done",
    "work_cancelled",
)
QUIET_ROUNDS = 30


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
            self.rt.log.lapse(CONVERSATION)
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
        state = await self.rt.log.state(CONVERSATION)
        entry: Entry | None
        match kind:
            case "gaia_stop":
                entry = stop(f"g{number}", covers_through=state.settled_through, by=StopBy.GAIA)
            case "barge":
                entry = barge(f"v{number}", state.open_reply) if state.open_reply else None
            case "ask":
                live = state.work[0].task_id if state.work else None
                entry = asked(f"a{number}", live, f"ap{number}") if live else None
            case "work_start":
                entry = self._work_start(state, number)
            case _:
                entry = self._work_end(state, number, kind)
        return entry

    def _work_start(self, state: ConversationState, number: int) -> WorkStarted | None:
        if state.head <= state.stopped_through:
            return None
        causes = [
            item.entry.id
            for item in self.rt.entries()
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
        self.rt.log.lapse(CONVERSATION)
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
            state = await self.rt.log.state(CONVERSATION)
            assert (state.comms, state.unsettled_waking) == (CommsPhase.IDLE, ())


OUTCOMES: dict[str, RunOutcome] = {
    "replied": Replied("an answer"),
    "empty": Replied(""),
    "reacted": Reacted("👍"),
    "silent": Silent(),
}


@st.composite
def scripts(draw: st.DrawFn, world_kinds: st.SearchStrategy[str]) -> list[tuple[str, str]]:
    steps = draw(
        st.lists(
            st.tuples(
                st.sampled_from(["text", "card", "tool_call", "model", "summary", "do", "pause"]),
                world_kinds,
            ),
            max_size=5,
        )
    )
    end = draw(st.sampled_from(["replied", "empty", "reacted", "silent", "fail"]))
    return [*steps, (end, "")]


def _script(world: World, plan: Sequence[tuple[str, str]]) -> list[ScriptItem]:
    items: list[ScriptItem] = []
    for step, kind in plan:
        match step:
            case "text":
                items.append(Streamed(payload=ResponseEvent(response="word ")))
            case "card":
                card = ToolDataEvent(tool_data={"tool_name": "search", "data": {"n": len(items)}})
                items.append(Streamed(payload=card))
            case "tool_call":
                items.append(ModelOutput(has_tool_calls=True))
            case "model":
                items.append(ModelOutput(has_tool_calls=False))
            case "summary":
                items.append(Summarized())
            case "do":
                items.append(Do(world.action(kind)))
            case "pause":
                items.append(Pause((world.action(kind),)))
            case "fail":
                items.append(Fail(RuntimeError("model down")))
            case _:
                items.append(Finished(OUTCOMES[step]))
    return items


ops = st.lists(
    st.one_of(
        st.sampled_from(APPEND_KINDS).map(AppendOp),
        st.builds(AdvanceOp, st.none() | st.integers(1, 40), st.booleans()),
    ),
    min_size=1,
    max_size=10,
)
run_plans = st.lists(scripts(st.sampled_from((*APPEND_KINDS, "lapse"))), max_size=6)


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
        state = await rt.log.state(CONVERSATION)
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
    removed_by = _removals(entries)
    causes = _causes(entries)
    owed: dict[str, set[str]] = {}
    for woken in _woken(entries):
        remover = removed_by.get(woken.seq)
        assert remover is not None, f"seq {woken.seq} ({woken.entry.id}) never settled"
        match remover.entry:
            case ReplySettled(answers=answers, id=settle_id):
                assert woken.entry.id in answers, f"{settle_id} settled {woken.entry.id} unanswered"
                owed.setdefault(settle_id, set()).update(
                    {woken.entry.id, *causes.get(woken.entry.id, ())}
                )
            case StopRequested():
                pass
            case other:
                raise AssertionError(f"seq {woken.seq} removed by {other.kind}")
    for logged in entries:
        if isinstance(logged.entry, ReplySettled):
            extra = set(logged.entry.answers) - owed.get(logged.entry.id, set())
            assert not extra, f"{logged.entry.id} answers {extra}, which it did not cover"


def _assert_no_reply_settled_twice(entries: Sequence[LoggedEntry]) -> None:
    settled = [item.entry.reply_id for item in entries if isinstance(item.entry, ReplySettled)]
    assert len(settled) == len(set(settled)), settled


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
        text = "".join(
            frame.payload.response for frame in deltas if isinstance(frame.payload, ResponseEvent)
        )
        cards = tuple(
            frame.payload.tool_data for frame in deltas if isinstance(frame.payload, ToolDataEvent)
        )
        if reply.heard_through is not None:
            text = text[: reply.heard_through]
        assert (reply.text, reply.tool_data) == (text, cards), reply.reply_id


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


@settings(max_examples=300)
@given(op_list=ops, plans=run_plans, approves=st.booleans())
def test_any_interleaving_answers_every_input_once_with_one_run_at_a_time(
    op_list: list[Op], plans: list[list[tuple[str, str]]], approves: bool
) -> None:
    world = asyncio.run(_play(op_list, plans, approves))
    entries = world.rt.entries()
    state = asyncio.run(world.rt.log.state(CONVERSATION))
    assert (state.comms, state.unsettled_waking, state.open_reply) == (CommsPhase.IDLE, (), None)
    assert world.rt.runner.overlaps == 0
    assert all(a.seq < b.seq for a, b in pairwise(entries))
    _assert_every_input_answered_once_or_stopped(entries)
    _assert_no_reply_settled_twice(entries)
    _assert_no_empty_answer(entries)
    _assert_frames_reproduce_the_log(world, entries)
    _assert_saved_replies_keep_everything_shown(world, entries)
