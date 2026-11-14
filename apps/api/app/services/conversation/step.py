"""The conversation step: the one writer that answers a conversation's waking entries, in order."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
import contextlib
from dataclasses import dataclass, field, replace
import itertools
from typing import cast

from app.constants.chat import BOT_CONVERSATION_SOURCES, EMPTY_RESPONSE_FALLBACK
from app.constants.conversation import (
    CLASSIFIER_LOOKBACK_SEQS,
    RUNNER_ALIVE_BEATS_PER_TTL,
    RUNNER_ALIVE_TTL_SECONDS,
)
from app.constants.hil import HIL_ACK_APPROVED, HIL_ACK_DENIED
from app.models.chat_models import ReactionBy
from app.models.conversation_frame_models import (
    EntryFrame,
    EntryUpdatedFrame,
    FollowUpActionsEvent,
    MessageBoundaryEvent,
    ResponseEvent,
    RetractFrame,
    StreamPayload,
    ToolDataEvent,
    state_frame,
)
from app.models.conversation_log_models import (
    BargeIn,
    Batch,
    CommitReason,
    CommsPhase,
    ConversationState,
    Entry,
    IntegrationConnected,
    LoggedEntry,
    MergeGroup,
    Reaction,
    Reply,
    ReplySettled,
    StepClaim,
    StopRequested,
    UserMessage,
    Verdict,
    VisibleEntry,
    WakingEntry,
    WorkFinished,
    WorkflowFired,
)
from app.models.message_models import MessageDict
from app.services.conversation.log import publish_appended
from app.services.conversation.ports import (
    Answered,
    CancelReason,
    ClaimLost,
    CommsRun,
    Finished,
    ModelOutput,
    Reacted,
    Replied,
    RunEvent,
    RunOutcome,
    RuntimePorts,
    StepLimitReached,
    Streamed,
    Summarized,
    ToolsRan,
    Unsettled,
)
from app.services.conversation.reply_analytics import capture_reply_ended, spoken_context
from app.services.conversation.reply_text import ReplyText, bubble_deltas
from app.services.conversation.screen import handoff_call_id
from app.services.conversation.step_view import StepView
from app.services.conversation.todo_wake import nothing_to_report
from app.services.conversation.tool_cards import fold_cards
from app.services.conversation.tool_timeline import tool_timeline
from app.services.conversation.verdict import merge_group, quote_target, verdict
from app.utils.hot_path import first_text_gate, first_text_shown
from app.utils.liveness import keep_proving
from shared.py.analytics import Dedupe
from shared.py.analytics.catalog.chat import ChatTurnReacted
from shared.py.conversation_wire import (
    CardsDelta,
    FailureReason,
    FollowUpsDelta,
    ReplyDelta,
    ReplyDeltaFrame,
    ReplyOutcome,
    ToolDataEntry,
)
from shared.py.wide_events import log


class RunEndedUnfinished(Exception):
    """A comms run's events ended without a Finished event."""


@dataclass(frozen=True)
class _Quiet:
    """Committed, with nothing shown to the user yet."""

    reason: CommitReason


@dataclass(frozen=True)
class _Drafting:
    """Committed, having streamed only hand-offs, which the work's own bubble shows: the reply has no slot yet."""

    reply: Reply


@dataclass(frozen=True)
class _Showing:
    """Committed, and the user reads this reply's text in its slot: its content is the fold of every delta shown."""

    reply: Reply
    seq: int


@dataclass
class _Attempt:
    """One comms attempt: what it covers, how far it got, and which newer inputs could join it."""

    claim: StepClaim
    run_id: str
    reply_id: str
    batch: Batch
    covers: tuple[LoggedEntry, ...]
    # Highest seq examined for joiners.
    seen: int
    view: StepView
    # The log's head as the last verdict's hint read it: the view answers only while it reaches this.
    hint_head: int = 0
    progress: _Quiet | _Drafting | _Showing | None = None
    # Replies this attempt settled before absorbing a later message; each later one is a new segment.
    segment: int = 0
    # Waking entries after covers, of the batch's group, not past a Stop.
    joiners: tuple[LoggedEntry, ...] = ()
    # Joiners absorbed while text showed: their segment opens once the tool calls already shown return.
    absorbed: tuple[LoggedEntry, ...] = ()
    # A Stop or another group's input ended the run of joinable entries.
    closed: bool = False
    deltas: int = 0
    # The current segment's text as it streamed, which its bubbles are split from.
    text: ReplyText = field(default_factory=ReplyText)
    # The reply as settled once the answer was final; the run only adds follow-up suggestions after.
    answered: LoggedEntry | None = None

    @property
    def attempt_id(self) -> str:
        """Return the id the current reply segment streams and settles under."""
        return self.run_id if self.segment == 0 else f"{self.run_id}/{self.segment}"

    def settled_view(self) -> StepView | None:
        """Return the view when its newest entry is this attempt's own settle, so it holds everything through it."""
        newest = self.view.entries[-1].entry if self.view.entries else None
        return self.view if newest is not None and newest.id == _settle_id(self) else None

    @property
    def committed(self) -> CommitReason | None:
        """Return why the attempt is committed, or None while it can still restart."""
        if isinstance(self.progress, _Showing):
            return CommitReason.VISIBLE_TEXT
        if isinstance(self.progress, _Drafting):
            return CommitReason.MODEL_OUTPUT
        return self.progress.reason if self.progress is not None else None

    @property
    def group(self) -> MergeGroup:
        """Return the merge group of the attempt's inputs."""
        return merge_group(_waking(self.batch.waking[0]))

    @property
    def through(self) -> int:
        """Return the newest seq the attempt covers."""
        return self.covers[-1].seq


@dataclass(frozen=True)
class _Tick:
    """The tick fired before the run's next event."""


@dataclass(frozen=True)
class _Crashed:
    """The run raised."""

    error: Exception


@dataclass
class _Pump:
    """The run's event stream with at most one pull in flight across ticks."""

    events: AsyncIterator[RunEvent]
    pending: asyncio.Task[RunEvent] | None = None


_Ending = Verdict | Finished | _Crashed
_Signal = RunEvent | _Tick | _Crashed

_CANCEL_REASON: dict[Verdict, CancelReason] = {
    Verdict.RESTART: CancelReason.RESTART,
    Verdict.STOP: CancelReason.STOP,
    Verdict.TRUNCATE: CancelReason.TRUNCATE,
    Verdict.LOST: CancelReason.LOST,
}


async def advance(ports: RuntimePorts, conversation_id: str, user_id: str) -> None:
    """Answer the conversation's waking entries in order while holding its step, then release it."""
    claim = await ports.log.claim(conversation_id, user_id)
    if claim is None:
        return
    with contextlib.suppress(ClaimLost):
        await _hold(ports, claim)


async def _hold(ports: RuntimePorts, claim: StepClaim) -> None:
    """Serve batches until caught up, proving the claim alive from its own task the whole time."""
    beating = _keep_claim_alive(ports, claim)
    try:
        await _recover(ports, claim)
        known: StepView | None = None
        for number in itertools.count(1):
            served, known = await _serve(ports, claim, f"{claim.epoch}.{number}", known)
            if served:
                continue
            # Stopped first: a beat after the release deleted the key would cancel this step.
            beating.cancel()
            if await ports.log.release_if_caught_up(claim):
                return
            beating = _keep_claim_alive(ports, claim)
    except asyncio.CancelledError:
        if not beating.done() or beating.cancelled():
            raise
        # The beat cancelled this step: it could not prove its claim, so another may hold it now.
        cast("asyncio.Task[object]", asyncio.current_task()).uncancel()
        raise ClaimLost from None
    finally:
        beating.cancel()


def _keep_claim_alive(ports: RuntimePorts, claim: StepClaim) -> asyncio.Task[None]:
    every = RUNNER_ALIVE_TTL_SECONDS / RUNNER_ALIVE_BEATS_PER_TTL
    return keep_proving(
        lambda: ports.log.beat(claim),
        every=every,
        give_up_after=RUNNER_ALIVE_TTL_SECONDS - every,
        name="conversation_step_alive",
        what="conversation step",
        context={"conversation_id": claim.conversation_id, "epoch": str(claim.epoch)},
    )


async def _recover(ports: RuntimePorts, claim: StepClaim) -> None:
    """Republish what a dead holder may not have, then close the attempt it left open."""
    if not claim.took_over:
        # The last holder released cleanly: it published everything and left nothing open.
        return
    conversation_id = claim.conversation_id
    state = await ports.log.state(conversation_id, claim.user_id)
    for logged in await ports.log.read_after(conversation_id, claim.user_id, state.settled_through):
        await ports.frames.publish(
            conversation_id, EntryFrame(seq=logged.seq, at=logged.at, entry=logged.entry)
        )
    reply_id = state.open_reply
    if reply_id is None and _started_work_unseen(state):
        # Committed work is never redone silently: the dead attempt gets a failed reply too.
        attempt_id = f"{claim.epoch}.0"
        reply_id = f"r{attempt_id}"
        opened = Reply(id=f"{attempt_id}:reply", reply_id=reply_id, attempt_id=attempt_id)
        await _append(ports, claim, opened)
    if reply_id is not None:
        # Its inputs stay unsettled, so the next run answers them with this failure in its context.
        recovered = ReplySettled(
            id=f"{reply_id}:recovered:{claim.epoch}",
            reply_id=reply_id,
            outcome=ReplyOutcome.FAILED,
            answers=(),
            through=state.settled_through,
            quote_target=None,
            failure=FailureReason.SERVER_RESTART,
        )
        await _append(ports, claim, recovered)
    elif state.comms is not CommsPhase.IDLE:
        await _set_comms(ports, claim, CommsPhase.IDLE)


def _started_work_unseen(state: ConversationState) -> bool:
    """Return whether a dead attempt dispatched work for inputs no reply has answered yet."""
    return state.comms is not CommsPhase.IDLE and any(
        item.cause_through > state.settled_through for item in state.work
    )


async def _serve(
    ports: RuntimePorts, claim: StepClaim, attempt_id: str, known: StepView | None
) -> tuple[bool, StepView | None]:
    """Answer the oldest waking batch; False when nothing waking is left. Also returns the view the next serve may start from."""
    conversation_id = claim.conversation_id
    # Nothing a Stop covered reaches a run, even what no run ever saw.
    unsettled = await _unsettled(ports, claim, known)
    state = unsettled.state
    entries = await _cut_spoken_over(ports, claim, unsettled.entries)
    view = StepView(
        state=state, after=max(state.settled_through, state.stopped_through), entries=entries
    )
    pending = [logged for logged in entries if logged.seq in state.unsettled_waking]
    if not pending:
        return False, None
    if await _answered_as_approval(ports, claim, state, pending[0], attempt_id):
        return True, None
    batch = _batch(pending)
    attempt = _Attempt(
        claim=claim,
        run_id=attempt_id,
        reply_id=f"r{attempt_id}",
        batch=batch,
        covers=batch.waking,
        seen=batch.end,
        view=view,
        hint_head=state.head,
    )
    if await nothing_to_report(ports.log, conversation_id, claim.user_id, batch):
        # The run said so itself, and its todo lets it: nothing is shown, its report stays on its WorkFinished.
        await _conclude(ports, attempt, _empty_reply(attempt), ReplyOutcome.SILENT)
        return True, attempt.settled_view()
    if isinstance(batch.waking[0].entry, WorkflowFired) and not state.work:
        # Under this claim no comms run writes the threads, and no live work runs on the executor's.
        await ports.effects.reset_workflow_threads(conversation_id)
    # Everything since the last settled input that no batch carries: notes, stops, a dead attempt.
    context = [
        logged
        for logged in entries
        if logged not in batch.waking and logged.seq not in state.unsettled_waking
    ]
    with first_text_gate():
        await _run_attempt(ports, attempt, context)
    return True, attempt.settled_view()


async def _unsettled(ports: RuntimePorts, claim: StepClaim, known: StepView | None) -> Unsettled:
    """Answer from the view the last attempt settled while the hint shows nothing logged after it, else read."""
    if known is not None:
        hint = await ports.log.hint(claim.conversation_id, claim.user_id)
        since = max(known.state.settled_through, known.state.stopped_through)
        entries = known.entries_after(since, hint.head)
        if entries is not None:
            return Unsettled(state=known.state, entries=entries)
    return await ports.log.unsettled(claim.conversation_id, claim.user_id)


def _batch(pending: Sequence[LoggedEntry]) -> Batch:
    """Take the oldest pending input and every pending input after it in its merge group, unbroken.

    A workflow fire is answered on its own: it merges with nothing, not even another fire.
    """
    group = merge_group(_waking(pending[0]))
    joined: tuple[LoggedEntry, ...]
    if group is MergeGroup.BACKGROUND:
        joined = (pending[0],)
    else:
        joined = tuple(
            itertools.takewhile(lambda logged: merge_group(_waking(logged)) is group, pending)
        )
    return Batch(start=joined[0].seq, end=joined[-1].seq, waking=joined, first_at=joined[0].at)


def _waking(logged: LoggedEntry) -> WakingEntry:
    entry = logged.entry
    if isinstance(entry, UserMessage | WorkflowFired | WorkFinished | IntegrationConnected):
        return entry
    raise TypeError(f"seq {logged.seq} is a {entry.kind}, not a waking entry")


async def _turns_before(ports: RuntimePorts, claim: StepClaim, seq: int) -> list[MessageDict]:
    """Return the user messages and shown replies logged shortly before seq, as chat turns."""
    since = max(0, seq - 1 - CLASSIFIER_LOOKBACK_SEQS)
    entries = await ports.log.read_after(claim.conversation_id, claim.user_id, since)
    turns: list[MessageDict] = []
    for logged in entries:
        match logged.entry:
            case UserMessage(text=text) if logged.seq < seq:
                turns.append({"role": "user", "content": text})
            case Reply(text=text) if logged.seq < seq and text:
                turns.append({"role": "assistant", "content": text})
    return turns


async def _answered_as_approval(
    ports: RuntimePorts,
    claim: StepClaim,
    state: ConversationState,
    first: LoggedEntry,
    attempt_id: str,
) -> bool:
    """Settle a button-less surface's typed answer to pending approvals with a text ack, no run."""
    message = first.entry
    awaiting = sorted(approval for item in state.work for approval in item.pending_approvals)
    if not (
        isinstance(message, UserMessage)
        and message.surface in BOT_CONVERSATION_SOURCES
        and awaiting
    ):
        return False
    history = await _turns_before(ports, claim, first.seq)
    # The resolver logs each approval's own decision; the step only acknowledges the reply.
    decision = await ports.approvals.resolve(
        claim.conversation_id, claim.user_id, message.text, history
    )
    if decision is None:
        return False
    text = HIL_ACK_APPROVED if decision == "approve" else HIL_ACK_DENIED
    ack = Reply(
        id=f"{attempt_id}:reply", reply_id=f"r{attempt_id}", attempt_id=attempt_id, text=text
    )
    shown = await _append(ports, claim, ack)
    answers = (message.id,)
    settled = ReplySettled(
        id=f"{attempt_id}:settled",
        reply_id=ack.reply_id,
        outcome=ReplyOutcome.ANSWERED,
        answers=answers,
        through=first.seq,
        quote_target=await _quote(ports, claim, answers, first.seq - 1, shown.seq),
    )
    await _settle(ports, claim, (first,), settled, None)
    return True


async def _run_attempt(
    ports: RuntimePorts, attempt: _Attempt, context: Sequence[LoggedEntry]
) -> None:
    """Run one comms attempt to its end; the run is certainly dead when this returns or raises."""
    attempt.view.phase_set(await _set_comms(ports, attempt.claim, CommsPhase.THINKING))
    try:
        run = await ports.runner.start(attempt.claim, attempt.batch, context)
    except Exception as error:  # a run that cannot start fails its inputs like one that crashed
        await _fail(ports, attempt, error)
        return
    try:
        ending = await _watch(ports, attempt, run)
    except ClaimLost:
        await run.cancel(CancelReason.LOST)
        if not isinstance(attempt.progress, _Showing):
            await _retract(ports, attempt)
        raise
    except Exception as error:  # a store or stream failure mid-attempt fails it, under the claim
        await run.cancel(CancelReason.LOST)
        await _fail(ports, attempt, error)
        return
    except BaseException:
        await run.cancel(CancelReason.LOST)
        raise
    try:
        await _end(ports, attempt, run, ending)
    except ClaimLost:
        raise
    except Exception as error:  # settling failed part-way: its idempotent ids let _fail finish it
        await _fail(ports, attempt, error)


async def _watch(ports: RuntimePorts, attempt: _Attempt, run: CommsRun) -> _Ending:
    """Consume the run's events, checking the verdict on each and on every tick."""
    pump = _Pump(events=run.events())
    try:
        while True:
            signal = await _next_signal(pump, ports.tick)
            if attempt.answered is not None:
                # Settled: later inputs are the next attempt's, so only the run's end matters.
                if isinstance(signal, Finished | _Crashed):
                    return signal
                continue
            if isinstance(signal, ModelOutput | Summarized):
                # Already checkpointed when its event arrives: this event can never be restarted.
                _commit_quietly(attempt)
            decision = await _decide(ports, attempt)
            if decision is not Verdict.CONTINUE:
                return decision
            if isinstance(signal, Finished):
                await _open_absorbed_segment(ports, attempt)
            if isinstance(signal, Finished | _Crashed):
                return signal
            if isinstance(signal, Answered):
                await _open_absorbed_segment(ports, attempt)
                attempt.answered = await _finish(ports, attempt, signal.outcome)
            elif not isinstance(signal, _Tick):
                await _handle(ports, attempt, run, signal)
    finally:
        await _close(pump)


async def _next_signal(pump: _Pump, tick: Callable[[], Awaitable[None]]) -> _Signal:
    """Race the run's next event against the tick; the pull survives a tick, the tick never outlives the race."""
    if pump.pending is None:
        pump.pending = asyncio.ensure_future(_pull(pump.events))
    ticking = asyncio.ensure_future(tick())
    try:
        await asyncio.wait((pump.pending, ticking), return_when=asyncio.FIRST_COMPLETED)
    finally:
        await _end_task(ticking)
    if not pump.pending.done():
        return _Tick()
    pulled, pump.pending = pump.pending, None
    error = pulled.exception()
    if error is None:
        return pulled.result()
    if isinstance(error, Exception):
        return _Crashed(error=error)
    raise error


async def _pull(events: AsyncIterator[RunEvent]) -> RunEvent:
    try:
        return await anext(events)
    except StopAsyncIteration:
        raise RunEndedUnfinished from None


async def _end_task(task: asyncio.Future[None]) -> None:
    """Cancel task if still running, wait for it, and raise what it raised."""
    if not task.done():
        task.cancel()
    await asyncio.wait((task,))
    if not task.cancelled():
        task.result()


async def _close(pump: _Pump) -> None:
    if pump.pending is not None:
        pump.pending.cancel()
        await asyncio.wait((pump.pending,))
        pump.pending = None


async def _decide(ports: RuntimePorts, attempt: _Attempt) -> Verdict:
    """Read the hint and decide, counting only newer inputs that would join this attempt."""
    hint = await ports.log.hint(attempt.claim.conversation_id, attempt.claim.user_id)
    attempt.hint_head = hint.head
    if hint.head > attempt.seen and not attempt.closed:
        await _look_for_joiners(ports, attempt)
    joinable_head = attempt.joiners[-1].seq if attempt.joiners else attempt.batch.end
    return verdict(
        committed=attempt.committed,
        batch=attempt.batch,
        hint=hint.model_copy(update={"head": joinable_head}),
        claim=attempt.claim,
        now=ports.clock(),
    )


async def _look_for_joiners(ports: RuntimePorts, attempt: _Attempt) -> None:
    conversation_id = attempt.claim.conversation_id
    # Entries before state: everything read is already folded into the state read after it.
    entries = await ports.log.read_after(conversation_id, attempt.claim.user_id, attempt.seen)
    state = await ports.log.state(conversation_id, attempt.claim.user_id)
    for logged in entries:
        attempt.seen = logged.seq
        if isinstance(logged.entry, StopRequested):
            attempt.closed = True
        elif logged.seq in state.unsettled_waking:
            joinable = attempt.group is MergeGroup.INTERACTIVE
            if not joinable or merge_group(_waking(logged)) is not attempt.group:
                attempt.closed = True
            else:
                attempt.joiners = (*attempt.joiners, logged)
        if attempt.closed:
            return


async def _handle(
    ports: RuntimePorts,
    attempt: _Attempt,
    run: CommsRun,
    event: Streamed | Summarized | ModelOutput | ToolsRan,
) -> None:
    match event:
        case Summarized():
            _commit_quietly(attempt)
        case ModelOutput(has_tool_calls=has_tool_calls):
            _commit_quietly(attempt)
            if has_tool_calls and attempt.joiners:
                await run.absorb(attempt.joiners)
                if isinstance(attempt.progress, _Showing):
                    attempt.absorbed = (*attempt.absorbed, *attempt.joiners)
                else:
                    attempt.covers = (*attempt.covers, *attempt.joiners)
                attempt.joiners = ()
        case ToolsRan():
            await _open_absorbed_segment(ports, attempt)
        case Streamed(payload=payload):
            await _show(ports, attempt, payload)


def _commit_quietly(attempt: _Attempt) -> None:
    if attempt.progress is None:
        attempt.progress = _Quiet(reason=CommitReason.MODEL_OUTPUT)


async def _open_absorbed_segment(ports: RuntimePorts, attempt: _Attempt) -> None:
    """Settle the text the user already read where it stands; the rest answers below the absorbed messages."""
    if not attempt.absorbed:
        return
    await _conclude(ports, attempt, _base_reply(attempt), ReplyOutcome.ANSWERED)
    attempt.covers, attempt.absorbed = attempt.absorbed, ()
    attempt.segment += 1
    attempt.reply_id = f"r{attempt.attempt_id}"
    attempt.progress = _Quiet(reason=CommitReason.MODEL_OUTPUT)
    attempt.deltas = 0
    attempt.text = ReplyText()


async def _show(ports: RuntimePorts, attempt: _Attempt, payload: StreamPayload) -> None:
    """Stream the delta; the reply's entry opens holding its first visible delta, so it appears below everything shown before it.

    A hand-off alone opens nothing: the work's bubble, at its WorkStarted, shows it.
    """
    before = _base_reply(attempt)
    bubbles_before = attempt.text.bubbles
    if isinstance(payload, ResponseEvent | MessageBoundaryEvent):
        attempt.text = attempt.text.take(payload)
    folded = _fold(before, payload, attempt.text)
    if not isinstance(attempt.progress, _Showing) and _is_visible(payload):
        folded = await _opening_reply(ports, attempt, folded)
        opened = await _append_seen(ports, attempt, folded)
        attempt.progress = _Showing(reply=folded, seq=opened.seq)
        if opened.seq == attempt.seen + 1:
            # Its own entry: no need to read the log for joiners the next verdict.
            attempt.seen = opened.seq
        if _is_text(payload):
            first_text_shown()
    shown = attempt.progress
    attempt.progress = (
        replace(shown, reply=folded) if isinstance(shown, _Showing) else _Drafting(reply=folded)
    )
    for change in _reply_deltas(before, folded, payload, bubbles_before, attempt.text.bubbles):
        delta = ReplyDeltaFrame(
            attempt_id=attempt.attempt_id,
            reply_id=attempt.reply_id,
            index=attempt.deltas,
            payload=change,
        )
        attempt.deltas += 1
        await ports.frames.publish(attempt.claim.conversation_id, delta)


def _reply_deltas(
    before: Reply,
    folded: Reply,
    payload: StreamPayload,
    shown: tuple[str, ...],
    bubbles: tuple[str, ...],
) -> list[ReplyDelta]:
    """Return what a client shows changing: bubble text, the follow-ups, or the cards and their timeline."""
    match payload:
        case ResponseEvent() | MessageBoundaryEvent():
            return [*bubble_deltas(shown, bubbles)]
        case FollowUpActionsEvent():
            return [FollowUpsDelta(follow_up_actions=folded.follow_up_actions)]
    cards = _own_cards(folded)
    if cards == _own_cards(before):
        return []
    return [CardsDelta(tool_data=cards, timeline=tool_timeline(cards))]


def _own_cards(reply: Reply) -> tuple[ToolDataEntry, ...]:
    """Return the cards the reply shows; a hand-off shows on its work."""
    return tuple(card for card in reply.tool_data if handoff_call_id(card) is None)


async def _end(ports: RuntimePorts, attempt: _Attempt, run: CommsRun, ending: _Ending) -> None:
    match ending:
        case Finished(outcome=outcome) if attempt.answered is not None:
            await _add_follow_ups(ports, attempt, attempt.answered, outcome)
        case Finished(outcome=outcome):
            await _finish(ports, attempt, outcome)
        case _Crashed(error=error) if attempt.answered is not None:
            await run.cancel(CancelReason.LOST)
            log.warning(
                "comms run failed after its reply settled; no follow-up suggestions",
                error_type=type(error).__name__,
                conversation_id=attempt.claim.conversation_id,
            )
        case _Crashed(error=error):
            await run.cancel(CancelReason.LOST)
            await _fail(ports, attempt, error)
        case Verdict():
            await run.cancel(_CANCEL_REASON[ending])
            await _AFTER_CANCEL[ending](ports, attempt)


async def _restart(ports: RuntimePorts, attempt: _Attempt) -> None:
    """Withdraw the uncommitted attempt; the next loop builds a bigger batch."""
    await _retract(ports, attempt)


async def _stop(ports: RuntimePorts, attempt: _Attempt) -> None:
    """Keep what was shown as a stopped reply, or withdraw an attempt that showed nothing."""
    progress = attempt.progress
    if not isinstance(progress, _Showing | _Drafting):
        await _retract(ports, attempt)
        await _set_comms(ports, attempt.claim, CommsPhase.IDLE)
        return
    await _put_reply(ports, attempt, progress.reply)
    state = await ports.log.state(attempt.claim.conversation_id, attempt.claim.user_id)
    await _settle(
        ports,
        attempt.claim,
        attempt.covers,
        _settled(attempt, ReplyOutcome.STOPPED, (), state.stopped_through, None),
        attempt.view,
    )


async def _truncate(ports: RuntimePorts, attempt: _Attempt) -> None:
    """Cut the reply to what the user heard before speaking over it; it still answered its inputs."""
    progress = attempt.progress
    if isinstance(progress, _Drafting):
        await _conclude(ports, attempt, progress.reply, ReplyOutcome.TRUNCATED)
        return
    if not isinstance(progress, _Showing):
        await _retract(ports, attempt)
        return
    after = await ports.log.read_after(
        attempt.claim.conversation_id, attempt.claim.user_id, progress.seq
    )
    barges = [
        logged.entry
        for logged in after
        if isinstance(logged.entry, BargeIn) and logged.entry.reply_id == attempt.reply_id
    ]
    shown = progress.reply.text
    heard = min(barges[-1].heard_through, len(shown)) if barges else len(shown)
    await _conclude(ports, attempt, _heard_part(progress.reply, heard), ReplyOutcome.TRUNCATED)


def _heard_part(reply: Reply, heard_through: int) -> Reply:
    return reply.model_copy(
        update={"text": reply.text[:heard_through], "heard_through": heard_through}
    )


async def _cut_spoken_over(
    ports: RuntimePorts, claim: StepClaim, entries: Sequence[LoggedEntry]
) -> list[LoggedEntry]:
    """Cut each settled reply the user spoke over to what they heard; a barge-in that cut nothing off is ignored."""
    replies = {
        logged.entry.reply_id: logged for logged in entries if isinstance(logged.entry, Reply)
    }
    for logged in entries:
        barge = logged.entry
        if not isinstance(barge, BargeIn) or barge.reply_id not in replies:
            continue
        reply = replies[barge.reply_id].entry
        if (
            isinstance(reply, Reply)
            and reply.heard_through is None
            and barge.heard_through < len(reply.text)
        ):
            replies[barge.reply_id] = await _amend(
                ports, claim, _heard_part(reply, barge.heard_through)
            )
    cut = {logged.seq: logged for logged in replies.values()}
    return [cut.get(logged.seq, logged) for logged in entries]


async def _lose(ports: RuntimePorts, attempt: _Attempt) -> None:
    """Write nothing more: the new holder recovers whatever this attempt left; live work never logged is withdrawn."""
    if not isinstance(attempt.progress, _Showing):
        await _retract(ports, attempt)
    raise ClaimLost


_AFTER_CANCEL: dict[Verdict, Callable[[RuntimePorts, _Attempt], Awaitable[None]]] = {
    Verdict.RESTART: _restart,
    Verdict.STOP: _stop,
    Verdict.TRUNCATE: _truncate,
    Verdict.LOST: _lose,
}


async def _finish(ports: RuntimePorts, attempt: _Attempt, outcome: RunOutcome) -> LoggedEntry:
    """Settle a finished run and return its stored reply; a reaction-only answer settles silently with no visible bubble."""
    if isinstance(outcome, Reacted):
        await _react(ports, attempt, outcome.emoji)
    reply, settled_as = _final_reply(attempt, outcome)
    return await _conclude(ports, attempt, reply, settled_as)


async def _add_follow_ups(
    ports: RuntimePorts, attempt: _Attempt, settled: LoggedEntry, outcome: RunOutcome
) -> None:
    """Add the suggestions the run made after its reply settled, as an update to that reply."""
    reply = settled.entry
    if not isinstance(outcome, Replied) or not outcome.follow_up_actions:
        return
    if not isinstance(reply, Reply) or not reply.text:
        return
    await _amend_seen(
        ports, attempt, reply.model_copy(update={"follow_up_actions": outcome.follow_up_actions})
    )


def _final_reply(attempt: _Attempt, outcome: RunOutcome) -> tuple[Reply, ReplyOutcome]:
    """Save what was shown; a run's Replied content is used only when it streamed nothing."""
    filled = _base_reply(attempt)
    if isinstance(outcome, Replied) and not isinstance(attempt.progress, _Showing | _Drafting):
        filled = filled.model_copy(
            update={
                "text": outcome.text,
                "tool_data": outcome.tool_data,
                "follow_up_actions": outcome.follow_up_actions,
            }
        )
    if filled.text or filled.tool_data:
        return filled, ReplyOutcome.ANSWERED
    if isinstance(outcome, Reacted) or not _asked(attempt):
        return filled, ReplyOutcome.SILENT
    # A user who asked never gets nothing back.
    return filled.model_copy(update={"text": EMPTY_RESPONSE_FALLBACK}), ReplyOutcome.ANSWERED


def _asked(attempt: _Attempt) -> bool:
    return any(isinstance(logged.entry, UserMessage) for logged in attempt.covers)


async def _react(ports: RuntimePorts, attempt: _Attempt, emoji: str) -> None:
    messages = [logged.entry for logged in attempt.covers if isinstance(logged.entry, UserMessage)]
    if not messages:
        return
    message = messages[-1]
    reaction = Reaction(emoji=emoji, by=ReactionBy.CHAT_MODEL)
    amended = await _amend_seen(ports, attempt, message.model_copy(update={"reaction": reaction}))
    ports.analytics.capture(
        attempt.claim.user_id,
        ChatTurnReacted(emoji=emoji),
        spoken_context(message),
        Dedupe(key=f"reacted:{message.id}:{emoji}", occurred_at=amended.at),
    )


async def _fail(ports: RuntimePorts, attempt: _Attempt, error: Exception) -> None:
    """Settle the attempt failed with what was shown, so the user sees a failed bubble, not silence."""
    log.error(
        "comms run failed",
        error=str(error),
        error_type=type(error).__name__,
        conversation_id=attempt.claim.conversation_id,
        attempt_id=attempt.attempt_id,
    )
    failure = (
        FailureReason.STEP_LIMIT
        if isinstance(error, StepLimitReached)
        else FailureReason.MODEL_ERROR
    )
    await _conclude(ports, attempt, _base_reply(attempt), ReplyOutcome.FAILED, failure)


async def _conclude(
    ports: RuntimePorts,
    attempt: _Attempt,
    reply: Reply,
    settled_as: ReplyOutcome,
    failure: FailureReason | None = None,
) -> LoggedEntry:
    """Save the reply's final content, settle it as answering everything the attempt covered, and return it."""
    stored = await _put_reply(ports, attempt, reply)
    answers, quote = await _answers_and_quote(ports, attempt, stored.seq)
    if settled_as is ReplyOutcome.SILENT:
        quote = None
    await _settle(
        ports,
        attempt.claim,
        attempt.covers,
        _settled(attempt, settled_as, answers, attempt.through, quote, failure),
        attempt.view,
    )
    return stored


def _settle_id(attempt: _Attempt) -> str:
    return f"{attempt.attempt_id}:settled"


def _settled(
    attempt: _Attempt,
    outcome: ReplyOutcome,
    answers: tuple[str, ...],
    through: int,
    quote: str | None,
    failure: FailureReason | None = None,
) -> ReplySettled:
    return ReplySettled(
        id=_settle_id(attempt),
        reply_id=attempt.reply_id,
        outcome=outcome,
        answers=answers,
        through=through,
        quote_target=quote,
        failure=failure,
        narrates=_narrated(attempt),
    )


async def _answers_and_quote(
    ports: RuntimePorts,
    attempt: _Attempt,
    reply_seq: int,
    state: ConversationState | None = None,
) -> tuple[tuple[str, ...], str | None]:
    """Answer every covered input, plus the user messages that caused covered finished work."""
    if state is None:
        state = await _state(ports, attempt)
    covered = {logged.seq for logged in attempt.covers}
    work = [item for item in state.finished_work if item.seq in covered]
    ids = [logged.entry.id for logged in attempt.covers]
    answers = tuple(dict.fromkeys([*ids, *(cause for item in work for cause in item.answers)]))
    since = min([attempt.covers[0].seq, *(item.cause_through for item in work)]) - 1
    known = attempt.view.entries_after(since, max(attempt.hint_head, reply_seq - 1))
    if known is None:
        known = await ports.log.read_after(
            attempt.claim.conversation_id, attempt.claim.user_id, since
        )
    return answers, _quote_in(answers, reply_seq, known)


async def _quote(
    ports: RuntimePorts, claim: StepClaim, answers: tuple[str, ...], since: int, reply_seq: int
) -> str | None:
    entries = await ports.log.read_after(claim.conversation_id, claim.user_id, since)
    return _quote_in(answers, reply_seq, entries)


def _quote_in(
    answers: tuple[str, ...], reply_seq: int, entries: Sequence[LoggedEntry]
) -> str | None:
    visible = [_visible(logged) for logged in entries]
    return quote_target(answers, reply_seq, [item for item in visible if item is not None])


def _visible(logged: LoggedEntry) -> VisibleEntry | None:
    match logged.entry:
        case UserMessage(id=message_id):
            return VisibleEntry(seq=logged.seq, id=message_id, is_user_message=True)
        case Reply(reply_id=reply_id, text=text, tool_data=tool_data) if text or tool_data:
            return VisibleEntry(seq=logged.seq, id=reply_id, is_user_message=False)
    return None


def _is_text(payload: StreamPayload) -> bool:
    return isinstance(payload, ResponseEvent) and bool(payload.response)


def _is_visible(payload: StreamPayload) -> bool:
    if isinstance(payload, ToolDataEvent):
        return handoff_call_id(payload.tool_data) is None
    return _is_text(payload)


def _narrated(attempt: _Attempt) -> tuple[str, ...]:
    """Return the tasks whose finished work the attempt's reply answers."""
    return tuple(
        logged.entry.task_id for logged in attempt.covers if isinstance(logged.entry, WorkFinished)
    )


def _fold(reply: Reply, payload: StreamPayload, text: ReplyText) -> Reply:
    """Return reply with one more shown delta folded in: its text so far, follow-ups, or what its cards show."""
    match payload:
        case ResponseEvent() | MessageBoundaryEvent():
            return reply.model_copy(update={"text": text.text})
        case FollowUpActionsEvent(follow_up_actions=actions):
            return reply.model_copy(update={"follow_up_actions": tuple(actions)})
    cards = fold_cards([payload], seed=reply.tool_data).tool_data
    return reply if cards == reply.tool_data else reply.model_copy(update={"tool_data": cards})


def _empty_reply(attempt: _Attempt) -> Reply:
    return Reply(
        id=f"{attempt.attempt_id}:reply",
        reply_id=attempt.reply_id,
        attempt_id=attempt.attempt_id,
        narrates=_narrated(attempt),
    )


def _base_reply(attempt: _Attempt) -> Reply:
    progress = attempt.progress
    return progress.reply if isinstance(progress, _Showing | _Drafting) else _empty_reply(attempt)


async def _put_reply(ports: RuntimePorts, attempt: _Attempt, reply: Reply) -> LoggedEntry:
    if isinstance(attempt.progress, _Showing):
        return await _amend_seen(ports, attempt, reply)
    return await _append_seen(ports, attempt, await _opening_reply(ports, attempt, reply))


async def _opening_reply(ports: RuntimePorts, attempt: _Attempt, reply: Reply) -> Reply:
    """Stamp the reply about to open with the message it quotes, as if it took the next seq."""
    state = await _state(ports, attempt)
    _, quote = await _answers_and_quote(ports, attempt, state.head + 1, state)
    return reply.model_copy(update={"quote_target": quote})


async def _state(ports: RuntimePorts, attempt: _Attempt) -> ConversationState:
    """Return the state from the attempt's view while nothing newer was logged, else read it."""
    known = attempt.view.state_at(attempt.hint_head)
    if known is not None:
        return known
    return await ports.log.state(attempt.claim.conversation_id, attempt.claim.user_id)


async def _append_seen(ports: RuntimePorts, attempt: _Attempt, entry: Entry) -> LoggedEntry:
    """Append under the attempt's claim and take the entry into its view."""
    appended = await ports.log.append_fenced(attempt.claim, entry)
    await publish_appended(ports.frames, attempt.claim.conversation_id, appended)
    attempt.view.appended(appended)
    return appended.logged


async def _append(ports: RuntimePorts, claim: StepClaim, entry: Entry) -> LoggedEntry:
    appended = await ports.log.append_fenced(claim, entry)
    await publish_appended(ports.frames, claim.conversation_id, appended)
    return appended.logged


async def _settle(
    ports: RuntimePorts,
    claim: StepClaim,
    covers: Sequence[LoggedEntry],
    settled: ReplySettled,
    view: StepView | None,
) -> None:
    """Settle a reply on the inputs it covered, and count it the first time it lands; view takes the settle in."""
    appended = await ports.log.append_fenced(claim, settled)
    await publish_appended(ports.frames, claim.conversation_id, appended)
    if appended.duplicate:
        return
    known = None
    if view is not None:
        view.appended(appended)
        known = view.entries_after(covers[0].seq, appended.logged.seq)
    since = (
        known
        if known is not None
        else await ports.log.read_after(claim.conversation_id, claim.user_id, covers[0].seq)
    )
    capture_reply_ended(
        ports.analytics,
        claim,
        covers,
        settled,
        appended.logged.at,
        since,
    )


async def _amend_seen(
    ports: RuntimePorts, attempt: _Attempt, entry: Reply | UserMessage
) -> LoggedEntry:
    """Amend under the attempt's claim and take the new content into its view."""
    amended = await _amend(ports, attempt.claim, entry)
    attempt.view.amended(amended)
    return amended


async def _amend(ports: RuntimePorts, claim: StepClaim, entry: Reply | UserMessage) -> LoggedEntry:
    amended = await ports.log.amend(claim, entry)
    await ports.frames.publish(
        claim.conversation_id, EntryUpdatedFrame(seq=amended.seq, entry=amended.entry)
    )
    return amended


async def _set_comms(ports: RuntimePorts, claim: StepClaim, phase: CommsPhase) -> ConversationState:
    state = await ports.log.set_comms(claim, phase)
    await ports.frames.publish(claim.conversation_id, state_frame(state))
    return state


async def _retract(ports: RuntimePorts, attempt: _Attempt) -> None:
    await ports.frames.publish(
        attempt.claim.conversation_id, RetractFrame(attempt_id=attempt.attempt_id)
    )
