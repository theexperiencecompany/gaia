"""Deterministic doubles for the conversation runtime's ports: an in-memory log and a scripted comms run."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from app.constants.hil import DECISION_OUTCOME, ApprovalDecision
from app.models.conversation_frame_models import OutputFrame
from app.models.conversation_log_models import (
    ApprovalDecided,
    BargeIn,
    Batch,
    CancelWork,
    CommsPhase,
    ConversationState,
    Entry,
    LoggedEntry,
    PreemptHint,
    Rejected,
    Reply,
    StepClaim,
    UserMessage,
)
from app.models.message_models import MessageDict
from app.models.work_cancel_models import WorkCancelled
from app.services.conversation.log import accept
from app.services.conversation.ports import (
    Appended,
    CancelReason,
    ClaimLost,
    ConversationAnalyticsEvent,
    ConversationLog,
    EntryRejected,
    Finished,
    RunEvent,
    RuntimePorts,
    TurnAnalytics,
    Unsettled,
)
from app.services.conversation.reducer import reduce
from shared.py.analytics import Dedupe
from shared.py.analytics.context import AnalyticsContext
from shared.py.approvals import ApprovalDecider
from tests.unit.services.conversation.log_helpers import EMPTY, T0

LIVENESS = timedelta(seconds=10)
Action = Callable[[], Awaitable[None]]


@dataclass
class FakeClock:
    now: datetime = T0

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


async def _no_pause(point: str) -> None:
    return None


@dataclass
class _Conversation:
    user_id: str
    entries: list[LoggedEntry] = field(default_factory=list)
    state: ConversationState = EMPTY
    first_results: dict[str, Appended] = field(default_factory=dict)
    epoch: int = 0
    holder: int | None = None
    alive_until: datetime = T0
    barged_reply: str | None = None


class InMemoryConversationLog:
    """The ConversationLog port over a dict; pause(point) runs before and after every call."""

    def __init__(
        self, clock: Callable[[], datetime], pause: Callable[[str], Awaitable[None]] = _no_pause
    ) -> None:
        self._clock = clock
        self._conversations: dict[str, _Conversation] = {}
        self.pause = pause

    async def append(self, conversation_id: str, user_id: str, entry: Entry) -> Appended:
        await self.pause("append")
        conversation = self._conversations.setdefault(conversation_id, _Conversation(user_id))
        result = self._append(conversation, entry)
        await self.pause("append:done")
        return result

    async def append_fenced(self, claim: StepClaim, entry: Entry) -> Appended:
        await self.pause("append_fenced")
        result = self._append(self._holding(claim), entry)
        await self.pause("append_fenced:done")
        return result

    async def amend(self, claim: StepClaim, entry: Reply | UserMessage) -> LoggedEntry:
        await self.pause("amend")
        conversation = self._holding(claim)
        index = next(i for i, item in enumerate(conversation.entries) if item.entry.id == entry.id)
        old = conversation.entries[index]
        stored = old.entry
        assert isinstance(stored, Reply | UserMessage) and type(stored) is type(entry), (
            f"amend cannot turn {stored.kind} into {entry.kind}"
        )
        revised = entry.model_copy(update={"revision": stored.revision + 1})
        conversation.entries[index] = amended = old.model_copy(update={"entry": revised})
        await self.pause("amend:done")
        return amended

    async def read_after(
        self, conversation_id: str, user_id: str, seq: int
    ) -> Sequence[LoggedEntry]:
        await self.pause("read_after")
        return [item for item in self._conv(conversation_id).entries if item.seq > seq]

    async def state(self, conversation_id: str, user_id: str) -> ConversationState:
        await self.pause("state")
        return self._conv(conversation_id).state

    async def unsettled(self, conversation_id: str, user_id: str) -> Unsettled:
        await self.pause("unsettled")
        conversation = self._conv(conversation_id)
        since = max(conversation.state.settled_through, conversation.state.stopped_through)
        entries = [item for item in conversation.entries if item.seq > since]
        return Unsettled(state=conversation.state, entries=entries)

    async def claim(self, conversation_id: str, user_id: str) -> StepClaim | None:
        await self.pause("claim")
        conversation = self._conversations.setdefault(conversation_id, _Conversation(user_id))
        if conversation.holder is not None and self._clock() < conversation.alive_until:
            return None
        took_over = conversation.holder is not None
        conversation.epoch += 1
        conversation.holder = conversation.epoch
        conversation.alive_until = self._clock() + LIVENESS
        await self.pause("claim:done")
        return StepClaim(
            conversation_id=conversation_id,
            user_id=user_id,
            epoch=conversation.epoch,
            took_over=took_over,
        )

    async def release_if_caught_up(self, claim: StepClaim) -> bool:
        await self.pause("release")
        conversation = self._holding(claim)
        if conversation.state.unsettled_waking:
            return False
        conversation.holder = None
        await self.pause("release:done")
        return True

    async def set_comms(self, claim: StepClaim, phase: CommsPhase) -> ConversationState:
        await self.pause("set_comms")
        conversation = self._holding(claim)
        conversation.state = conversation.state.model_copy(update={"comms": phase})
        await self.pause("set_comms:done")
        return conversation.state

    async def hint(self, conversation_id: str, user_id: str) -> PreemptHint:
        await self.pause("hint")
        conversation = self._conv(conversation_id)
        state = conversation.state
        barged = conversation.barged_reply
        return PreemptHint(
            head=state.head,
            stop_through=state.stopped_through,
            barge_reply_id=barged if barged is not None and barged == state.open_reply else None,
            epoch=conversation.epoch,
        )

    async def beat(self, claim: StepClaim) -> bool:
        await self.pause("beat")
        conversation = self._conv(claim.conversation_id)
        if conversation.holder != claim.epoch or self._clock() >= conversation.alive_until:
            return False
        conversation.alive_until = self._clock() + LIVENESS
        return True

    def lapse(self, conversation_id: str) -> None:
        """Let the holder's liveness run out, as when its process dies."""
        self._conv(conversation_id).alive_until = self._clock()

    def _conv(self, conversation_id: str) -> _Conversation:
        return self._conversations.get(conversation_id) or _Conversation(user_id="")

    def _holding(self, claim: StepClaim) -> _Conversation:
        conversation = self._conv(claim.conversation_id)
        if conversation.holder != claim.epoch:
            raise ClaimLost
        return conversation

    def _append(self, conversation: _Conversation, entry: Entry) -> Appended:
        first = conversation.first_results.get(entry.id)
        if first is not None:
            state = conversation.state
            return Appended(
                logged=first.logged, previous=state, state=state, effects=(), duplicate=True
            )
        logged = LoggedEntry(seq=conversation.state.head + 1, at=self._clock(), entry=entry)
        result = reduce(conversation.state, logged)
        if isinstance(result, Rejected):
            raise EntryRejected(result.reason)
        appended = Appended(
            logged=logged,
            previous=conversation.state,
            state=result.state,
            effects=result.effects,
            duplicate=False,
        )
        conversation.entries.append(logged)
        conversation.state = result.state
        conversation.first_results[entry.id] = appended
        if isinstance(entry, BargeIn):
            conversation.barged_reply = entry.reply_id
        return appended


class PausingLog:
    """Any ConversationLog with pause(point) awaited before each call, at the points the in-memory log pauses."""

    def __init__(self, inner: ConversationLog) -> None:
        self._inner = inner
        self.pause: Callable[[str], Awaitable[None]] = _no_pause

    async def append(self, conversation_id: str, user_id: str, entry: Entry) -> Appended:
        await self.pause("append")
        return await self._inner.append(conversation_id, user_id, entry)

    async def append_fenced(self, claim: StepClaim, entry: Entry) -> Appended:
        await self.pause("append_fenced")
        return await self._inner.append_fenced(claim, entry)

    async def amend(self, claim: StepClaim, entry: Reply | UserMessage) -> LoggedEntry:
        await self.pause("amend")
        return await self._inner.amend(claim, entry)

    async def read_after(
        self, conversation_id: str, user_id: str, seq: int
    ) -> Sequence[LoggedEntry]:
        await self.pause("read_after")
        return await self._inner.read_after(conversation_id, user_id, seq)

    async def state(self, conversation_id: str, user_id: str) -> ConversationState:
        await self.pause("state")
        return await self._inner.state(conversation_id, user_id)

    async def unsettled(self, conversation_id: str, user_id: str) -> Unsettled:
        await self.pause("unsettled")
        return await self._inner.unsettled(conversation_id, user_id)

    async def claim(self, conversation_id: str, user_id: str) -> StepClaim | None:
        await self.pause("claim")
        return await self._inner.claim(conversation_id, user_id)

    async def release_if_caught_up(self, claim: StepClaim) -> bool:
        await self.pause("release")
        return await self._inner.release_if_caught_up(claim)

    async def set_comms(self, claim: StepClaim, phase: CommsPhase) -> ConversationState:
        await self.pause("set_comms")
        return await self._inner.set_comms(claim, phase)

    async def hint(self, conversation_id: str, user_id: str) -> PreemptHint:
        await self.pause("hint")
        return await self._inner.hint(conversation_id, user_id)

    async def beat(self, claim: StepClaim) -> bool:
        await self.pause("beat")
        return await self._inner.beat(claim)


class TickGate:
    """The step's tick: it fires only when a Pause in a run script releases it."""

    def __init__(self) -> None:
        self._tokens: asyncio.Queue[None] = asyncio.Queue()
        self._entered = asyncio.Event()
        self._parks = 0
        self._waiting = False
        self.fired = 0

    async def tick(self) -> None:
        self._parks += 1
        self._waiting = True
        self._entered.set()
        try:
            await self._tokens.get()
        finally:
            self._waiting = False
        self.fired += 1

    async def release(self) -> None:
        """Fire one tick and return once the step is waiting on the next one."""
        await self._until(lambda: self._waiting)
        parks = self._parks
        self._tokens.put_nowait(None)
        await self._until(lambda: self._parks > parks)

    async def _until(self, ready: Callable[[], bool]) -> None:
        while not ready():
            self._entered.clear()
            await self._entered.wait()


@dataclass(frozen=True)
class Do:
    """Run action when the step asks for the next event, before that event is produced."""

    action: Action


@dataclass(frozen=True)
class Pause:
    """The model is silent: for each action, run it and let one tick fire."""

    actions: tuple[Action, ...]


@dataclass(frozen=True)
class Fail:
    """The run raises when the step asks for the next event."""

    error: Exception


ScriptItem = RunEvent | Do | Pause | Fail


@dataclass(frozen=True)
class Started:
    batch: tuple[int, ...]
    context: tuple[int, ...]


@dataclass(frozen=True)
class Absorbed:
    seqs: tuple[int, ...]


@dataclass(frozen=True)
class Cancelled:
    reason: CancelReason


RunnerCall = Started | Absorbed | Cancelled


class ScriptedRun:
    """A comms run that plays its script in its own task, one event per request from the step."""

    def __init__(
        self,
        script: Sequence[ScriptItem],
        ticks: TickGate,
        calls: list[RunnerCall],
        *,
        swallow_first_cancel: bool,
    ) -> None:
        self._script = script
        self._ticks = ticks
        self._calls = calls
        self._swallow = swallow_first_cancel
        self._wanted: asyncio.Queue[None] = asyncio.Queue()
        self._out: asyncio.Queue[RunEvent | Exception] = asyncio.Queue()
        self._held = False
        self._swallowed = asyncio.Event()
        self.cancel_attempts = 0
        self.task = asyncio.create_task(self._play())

    async def events(self) -> AsyncIterator[RunEvent]:
        while True:
            self._wanted.put_nowait(None)
            item = await self._out.get()
            if isinstance(item, Exception):
                raise item
            yield item
            if isinstance(item, Finished):
                return

    async def absorb(self, entries: Sequence[LoggedEntry]) -> None:
        self._calls.append(Absorbed(tuple(item.seq for item in entries)))

    async def cancel(self, reason: CancelReason) -> None:
        self._calls.append(Cancelled(reason))
        while not self.task.done():
            self.cancel_attempts += 1
            self.task.cancel()
            swallowed = asyncio.ensure_future(self._swallowed.wait())
            await asyncio.wait((self.task, swallowed), return_when=asyncio.FIRST_COMPLETED)
            swallowed.cancel()
            self._swallowed.clear()

    async def _play(self) -> None:
        try:
            if not await self._perform():
                await asyncio.Event().wait()
        except asyncio.CancelledError:
            if not self._swallow:
                raise
            # The first cancel is swallowed wherever it lands; only a second one ends the run.
            self._swallow = False
            self._swallowed.set()
            await asyncio.Event().wait()

    async def _perform(self) -> bool:
        """Play the script; True when it emitted its final event, False when the run should hang."""
        for item in self._script:
            await self._demand()
            match item:
                case Do(action=action):
                    await action()
                case Pause(actions=actions):
                    for action in actions:
                        await action()
                        await self._ticks.release()
                case Fail(error=error):
                    self._emit(error)
                    return True
                case _:
                    self._emit(item)
                    if isinstance(item, Finished):
                        return True
        return False

    async def _demand(self) -> None:
        if not self._held:
            await self._wanted.get()
            self._held = True

    def _emit(self, item: RunEvent | Exception) -> None:
        self._held = False
        self._out.put_nowait(item)


class ScriptedRunner:
    """Starts one ScriptedRun per scripted attempt and records every call and any overlap."""

    def __init__(self, ticks: TickGate) -> None:
        self._ticks = ticks
        self._scripts: list[Sequence[ScriptItem]] = []
        self.calls: list[RunnerCall] = []
        self.runs: list[ScriptedRun] = []
        self.overlaps = 0
        self.swallow_first_cancel = False
        # What a run plays once the scripts run out; the default hangs until cancelled.
        self.unscripted: Sequence[ScriptItem] = ()

    def script(self, *scripts: Sequence[ScriptItem]) -> None:
        self._scripts.extend(scripts)

    async def start(
        self, claim: StepClaim, batch: Batch, context: Sequence[LoggedEntry]
    ) -> ScriptedRun:
        if any(not run.task.done() for run in self.runs):
            self.overlaps += 1
        self.calls.append(
            Started(tuple(item.seq for item in batch.waking), tuple(item.seq for item in context))
        )
        script = self._scripts.pop(0) if self._scripts else self.unscripted
        run = ScriptedRun(
            script, self._ticks, self.calls, swallow_first_cancel=self.swallow_first_cancel
        )
        self.runs.append(run)
        return run


@dataclass
class RecordingFrames:
    published: list[OutputFrame] = field(default_factory=list)
    conversations: set[str] = field(default_factory=set)

    async def publish(self, conversation_id: str, *frames: OutputFrame) -> None:
        self.published.extend(frames)
        self.conversations.add(conversation_id)


@dataclass(frozen=True)
class EffectCall:
    name: str
    argument: str | tuple[str, ...] | None = None


@dataclass
class RecordingEffects:
    calls: list[EffectCall] = field(default_factory=list)
    failing: frozenset[str] = frozenset()
    on_kick: Action | None = None

    async def kick(self, conversation_id: str, user_id: str) -> None:
        self._record(EffectCall("kick"))
        if self.on_kick is not None:
            await self.on_kick()

    async def cancel_work(
        self, conversation_id: str, user_id: str, cancel: CancelWork
    ) -> WorkCancelled:
        self._record(EffectCall("cancel_work", cancel.task_ids))
        return WorkCancelled()

    async def start_ack(self, conversation_id: str, user_id: str, message_id: str) -> None:
        self._record(EffectCall("start_ack", message_id))

    async def reset_workflow_threads(self, conversation_id: str) -> None:
        self._record(EffectCall("reset_workflow_threads"))

    def _record(self, call: EffectCall) -> None:
        self.calls.append(call)
        if call.name in self.failing:
            raise RuntimeError(f"{call.name} failed")


@dataclass
class RecordingAnalytics:
    """Records each event the runtime counts, with the context and dedupe it was sent under."""

    ended: list[tuple[str, ConversationAnalyticsEvent, AnalyticsContext, Dedupe]] = field(
        default_factory=list
    )

    def capture(
        self,
        user_id: str,
        event: ConversationAnalyticsEvent,
        context: AnalyticsContext,
        dedupe: Dedupe,
    ) -> None:
        self.ended.append((user_id, event, context, dedupe))


@dataclass
class ScriptedApprovals:
    """Resolves typed replies as the HIL resolver does: each approval its own decision, accepted once."""

    decision: ApprovalDecision | None = None
    # Per-approval decisions; an approval not named here takes decision.
    each: dict[str, ApprovalDecision] = field(default_factory=dict)
    asked: list[str] = field(default_factory=list)
    histories: list[list[MessageDict]] = field(default_factory=list)
    ports: RuntimePorts | None = None

    async def resolve(
        self, conversation_id: str, user_id: str, message_text: str, history: list[MessageDict]
    ) -> ApprovalDecision | None:
        self.asked.append(message_text)
        self.histories.append(history)
        if self.decision is None or self.ports is None:
            return self.decision
        state = await self.ports.log.state(conversation_id, user_id)
        pending = sorted(approval for item in state.work for approval in item.pending_approvals)
        decisions = [self.each.get(approval, self.decision) for approval in pending]
        for approval_id, decision in zip(pending, decisions, strict=True):
            entry = ApprovalDecided(
                id=f"approval:{approval_id}:decided",
                approval_id=approval_id,
                outcome=DECISION_OUTCOME[decision],
                decider=ApprovalDecider.USER,
            )
            await accept(self.ports, conversation_id, user_id, entry)
        return "approve" if "approve" in decisions else "deny"


CONVERSATION = "c1"
# A Mongo ObjectId: the step counts each reply on the user's analytics profile.
USER = "65f1a2b3c4d5e6f708192a3b"


class ScenarioLog(ConversationLog, Protocol):
    """A ConversationLog a test can pause at each call: pause(point) runs before the call."""

    pause: Callable[[str], Awaitable[None]]


@dataclass(frozen=True)
class LogUnderTest:
    log: ScenarioLog
    # Makes the current holder's liveness run out, as when its process dies.
    lapse: Callable[[], Awaitable[None]]


def in_memory_log(clock: FakeClock, conversation_id: str = CONVERSATION) -> LogUnderTest:
    log = InMemoryConversationLog(clock)

    async def lapse() -> None:
        log.lapse(conversation_id)

    return LogUnderTest(log=log, lapse=lapse)


@dataclass
class Runtime:
    """One conversation's ports wired to the doubles, over the in-memory log unless make_log says otherwise."""

    clock: FakeClock = field(default_factory=FakeClock)
    ticks: TickGate = field(default_factory=TickGate)
    frames: RecordingFrames = field(default_factory=RecordingFrames)
    effects: RecordingEffects = field(default_factory=RecordingEffects)
    approvals: ScriptedApprovals = field(default_factory=ScriptedApprovals)
    analytics: TurnAnalytics = field(default_factory=RecordingAnalytics)
    make_log: Callable[[FakeClock], LogUnderTest] = in_memory_log
    log: ScenarioLog = field(init=False)
    runner: ScriptedRunner = field(init=False)
    _lapse: Callable[[], Awaitable[None]] = field(init=False)

    def __post_init__(self) -> None:
        under_test = self.make_log(self.clock)
        self.log, self._lapse = under_test.log, under_test.lapse
        self.runner = ScriptedRunner(self.ticks)
        self.approvals.ports = self.ports

    async def lapse(self) -> None:
        await self._lapse()

    @property
    def ports(self) -> RuntimePorts:
        return RuntimePorts(
            log=self.log,
            runner=self.runner,
            frames=self.frames,
            effects=self.effects,
            approvals=self.approvals,
            analytics=self.analytics,
            clock=self.clock,
            tick=self.ticks.tick,
        )

    async def entries(self) -> list[LoggedEntry]:
        return list(await self.log.read_after(CONVERSATION, USER, 0))
