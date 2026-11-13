"""The conversation step: the one writer that answers a conversation's waking entries, in order."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
import contextlib
from dataclasses import dataclass, replace
import itertools
from typing import cast

from langgraph.errors import GraphRecursionError

from app.constants.chat import BOT_CONVERSATION_SOURCES, EMPTY_RESPONSE_FALLBACK
from app.constants.conversation import (
    CLASSIFIER_LOOKBACK_SEQS,
    RUNNER_ALIVE_BEATS_PER_TTL,
    RUNNER_ALIVE_TTL_SECONDS,
)
from app.constants.hil import HIL_ACK_APPROVED, HIL_ACK_DENIED
from app.models.chat_models import ImageData, ReactionBy
from app.models.conversation_frame_models import (
    EntryFrame,
    EntryUpdatedFrame,
    FollowUpActionsEvent,
    ReplyDeltaFrame,
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
    FailureReason,
    IntegrationConnected,
    LoggedEntry,
    MergeGroup,
    Reaction,
    Reply,
    ReplyOutcome,
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
from app.models.tool_data_models import ToolDataEntry
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
    Streamed,
    Summarized,
)
from app.services.conversation.reply_analytics import capture_reply_ended
from app.services.conversation.reply_files import reply_files
from app.services.conversation.todo_wake import nothing_to_report
from app.services.conversation.verdict import merge_group, quote_target, verdict
from app.utils.liveness import keep_proving
from shared.py.wide_events import log


class RunEndedUnfinished(Exception):
    """A comms run's events ended without a Finished event."""


@dataclass(frozen=True)
class _Quiet:
    """Committed, with nothing shown to the user yet."""

    reason: CommitReason


@dataclass(frozen=True)
class _Showing:
    """Committed, and the user sees this reply: its content is the fold of every delta shown."""

    reply: Reply
    seq: int


@dataclass
class _Attempt:
    """One comms attempt: what it covers, how far it got, and which newer inputs could join it."""

    claim: StepClaim
    attempt_id: str
    reply_id: str
    batch: Batch
    covers: tuple[LoggedEntry, ...]
    # Highest seq examined for joiners.
    seen: int
    progress: _Quiet | _Showing | None = None
    # Waking entries after covers, of the batch's group, not past a Stop.
    joiners: tuple[LoggedEntry, ...] = ()
    # A Stop or another group's input ended the run of joinable entries.
    closed: bool = False
    deltas: int = 0
    # The cards and image of the work whose reply this is (reply_id = task_id); the reply opens with them.
    work_cards: tuple[ToolDataEntry, ...] = ()
    work_image: ImageData | None = None
    # The reply as settled once the answer was final; the run only adds follow-up suggestions after.
    answered: LoggedEntry | None = None

    @property
    def committed(self) -> CommitReason | None:
        """Return why the attempt is committed, or None while it can still restart."""
        if isinstance(self.progress, _Showing):
            return CommitReason.VISIBLE_TEXT
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
        for number in itertools.count(1):
            if await _serve(ports, claim, f"{claim.epoch}.{number}"):
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
    conversation_id = claim.conversation_id
    state = await ports.log.state(conversation_id, claim.user_id)
    if claim.took_over:
        for logged in await ports.log.read_after(
            conversation_id, claim.user_id, state.settled_through
        ):
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


async def _serve(ports: RuntimePorts, claim: StepClaim, attempt_id: str) -> bool:
    """Answer the oldest waking batch; return False when nothing waking is left."""
    conversation_id = claim.conversation_id
    state = await ports.log.state(conversation_id, claim.user_id)
    # Nothing a Stop covered reaches a run, even what no run ever saw.
    since = max(state.settled_through, state.stopped_through)
    entries = await ports.log.read_after(conversation_id, claim.user_id, since)
    entries = await _cut_spoken_over(ports, claim, entries)
    pending = [logged for logged in entries if logged.seq in state.unsettled_waking]
    if not pending:
        return False
    if await _answered_as_approval(ports, claim, state, pending[0], attempt_id):
        return True
    batch = _batch(pending)
    reply_id = _reply_id(batch, entries, attempt_id)
    work = _answered_work(batch, reply_id)
    attempt = _Attempt(
        claim=claim,
        attempt_id=attempt_id,
        reply_id=reply_id,
        batch=batch,
        covers=batch.waking,
        seen=batch.end,
        work_cards=work.tool_data if work else (),
        work_image=work.image if work else None,
    )
    if await nothing_to_report(ports.log, conversation_id, claim.user_id, batch):
        # The run said so itself, and its todo lets it: nothing is shown, its report stays on its WorkFinished.
        unshown = _empty_reply(attempt).model_copy(update={"tool_data": ()})
        await _conclude(ports, attempt, unshown, ReplyOutcome.SILENT)
        return True
    if isinstance(batch.waking[0].entry, WorkflowFired) and not state.work:
        # Under this claim no comms run writes the threads, and no live work runs on the executor's.
        await ports.effects.reset_workflow_threads(conversation_id)
    # Everything since the last settled input that no batch carries: notes, stops, a dead attempt.
    context = [
        logged
        for logged in entries
        if logged not in batch.waking and logged.seq not in state.unsettled_waking
    ]
    await _run_attempt(ports, attempt, context)
    return True


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


def _reply_id(batch: Batch, entries: Sequence[LoggedEntry], attempt_id: str) -> str:
    """Answer finished work in the task's own reply, so its cards and its answer are one entry."""
    used = {logged.entry.reply_id for logged in entries if isinstance(logged.entry, Reply)}
    tasks = (
        logged.entry.task_id for logged in batch.waking if isinstance(logged.entry, WorkFinished)
    )
    return next((task for task in tasks if task not in used), f"r{attempt_id}")


def _answered_work(batch: Batch, reply_id: str) -> WorkFinished | None:
    """Return the finished work this reply answers in its own reply, whose cards and image it opens with."""
    return next(
        (
            logged.entry
            for logged in batch.waking
            if isinstance(logged.entry, WorkFinished) and logged.entry.task_id == reply_id
        ),
        None,
    )


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
    await _settle(ports, claim, (first,), settled)
    return True


async def _run_attempt(
    ports: RuntimePorts, attempt: _Attempt, context: Sequence[LoggedEntry]
) -> None:
    """Run one comms attempt to its end; the run is certainly dead when this returns or raises."""
    await _set_comms(ports, attempt.claim, CommsPhase.THINKING)
    try:
        run = await ports.runner.start(attempt.claim, attempt.batch, context)
    except Exception as error:  # a run that cannot start fails its inputs like one that crashed
        await _fail(ports, attempt, error)
        return
    try:
        ending = await _watch(ports, attempt, run)
    except ClaimLost:
        await run.cancel(CancelReason.LOST)
        if attempt.progress is None:
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
            if isinstance(signal, Finished | _Crashed):
                return signal
            if isinstance(signal, Answered):
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
    event: Streamed | Summarized | ModelOutput,
) -> None:
    match event:
        case Summarized():
            _commit_quietly(attempt)
        case ModelOutput(has_tool_calls=has_tool_calls):
            _commit_quietly(attempt)
            if has_tool_calls and attempt.joiners:
                await run.absorb(attempt.joiners)
                attempt.covers = (*attempt.covers, *attempt.joiners)
                attempt.joiners = ()
        case Streamed(payload=payload):
            await _show(ports, attempt, payload)


def _commit_quietly(attempt: _Attempt) -> None:
    if attempt.progress is None:
        attempt.progress = _Quiet(reason=CommitReason.MODEL_OUTPUT)


async def _show(ports: RuntimePorts, attempt: _Attempt, payload: StreamPayload) -> None:
    """Open the reply on the first visible delta, then stream the delta into it."""
    if not isinstance(attempt.progress, _Showing):
        reply = await _opening_reply(ports, attempt, _empty_reply(attempt))
        opened = await _append(ports, attempt.claim, reply)
        attempt.progress = _Showing(reply=reply, seq=opened.seq)
    shown = attempt.progress
    attempt.progress = replace(shown, reply=_fold(shown.reply, payload))
    delta = ReplyDeltaFrame(
        attempt_id=attempt.attempt_id,
        reply_id=attempt.reply_id,
        index=attempt.deltas,
        payload=payload,
    )
    attempt.deltas += 1
    await ports.frames.publish(attempt.claim.conversation_id, delta)


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
    if not isinstance(progress, _Showing):
        await _retract(ports, attempt)
        await _set_comms(ports, attempt.claim, CommsPhase.IDLE)
        return
    await _amend(ports, attempt.claim, progress.reply)
    state = await ports.log.state(attempt.claim.conversation_id, attempt.claim.user_id)
    await _settle(
        ports,
        attempt.claim,
        attempt.covers,
        _settled(attempt, ReplyOutcome.STOPPED, (), state.stopped_through, None),
    )


async def _truncate(ports: RuntimePorts, attempt: _Attempt) -> None:
    """Cut the reply to what the user heard before speaking over it; it still answered its inputs."""
    progress = attempt.progress
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
    """Write nothing more: the new holder recovers whatever this attempt left."""
    if attempt.progress is None:
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
    await _amend(
        ports,
        attempt.claim,
        reply.model_copy(update={"follow_up_actions": outcome.follow_up_actions}),
    )


def _final_reply(attempt: _Attempt, outcome: RunOutcome) -> tuple[Reply, ReplyOutcome]:
    """Save what was shown; a run's Replied content is used only when it streamed nothing."""
    filled = _base_reply(attempt)
    if isinstance(outcome, Replied) and not isinstance(attempt.progress, _Showing):
        filled = filled.model_copy(
            update={
                "text": outcome.text,
                "tool_data": (*attempt.work_cards, *outcome.tool_data),
                "follow_up_actions": outcome.follow_up_actions,
            }
        )
    # The work's own cards ride every write-up; only what the run said or showed makes it an answer.
    if filled.text or len(filled.tool_data) > len(attempt.work_cards):
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
    reaction = Reaction(emoji=emoji, by=ReactionBy.CHAT_MODEL)
    await _amend(ports, attempt.claim, messages[-1].model_copy(update={"reaction": reaction}))


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
        if isinstance(error, GraphRecursionError)
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
    )
    return stored


def _settled(
    attempt: _Attempt,
    outcome: ReplyOutcome,
    answers: tuple[str, ...],
    through: int,
    quote: str | None,
    failure: FailureReason | None = None,
) -> ReplySettled:
    return ReplySettled(
        id=f"{attempt.attempt_id}:settled",
        reply_id=attempt.reply_id,
        outcome=outcome,
        answers=answers,
        through=through,
        quote_target=quote,
        failure=failure,
    )


async def _answers_and_quote(
    ports: RuntimePorts, attempt: _Attempt, reply_seq: int
) -> tuple[tuple[str, ...], str | None]:
    """Answer every covered input, plus the user messages that caused covered finished work."""
    state = await ports.log.state(attempt.claim.conversation_id, attempt.claim.user_id)
    covered = {logged.seq for logged in attempt.covers}
    work = [item for item in state.finished_work if item.seq in covered]
    ids = [logged.entry.id for logged in attempt.covers]
    answers = tuple(dict.fromkeys([*ids, *(cause for item in work for cause in item.answers)]))
    since = min([attempt.covers[0].seq, *(item.cause_through for item in work)]) - 1
    return answers, await _quote(ports, attempt.claim, answers, since, reply_seq)


async def _quote(
    ports: RuntimePorts, claim: StepClaim, answers: tuple[str, ...], since: int, reply_seq: int
) -> str | None:
    entries = await ports.log.read_after(claim.conversation_id, claim.user_id, since)
    visible = [_visible(logged) for logged in entries]
    return quote_target(answers, reply_seq, [item for item in visible if item is not None])


def _visible(logged: LoggedEntry) -> VisibleEntry | None:
    match logged.entry:
        case UserMessage(id=message_id):
            return VisibleEntry(seq=logged.seq, id=message_id, is_user_message=True)
        case Reply(reply_id=reply_id, text=text, tool_data=tool_data) if text or tool_data:
            return VisibleEntry(seq=logged.seq, id=reply_id, is_user_message=False)
    return None


def _fold(reply: Reply, payload: StreamPayload) -> Reply:
    """Return reply with one more shown delta folded in: text, a tool card, or follow-ups."""
    match payload:
        case ResponseEvent(response=response):
            return reply.model_copy(update={"text": reply.text + response})
        case ToolDataEvent(tool_data=card):
            return reply.model_copy(update={"tool_data": (*reply.tool_data, card)})
        case FollowUpActionsEvent(follow_up_actions=actions):
            return reply.model_copy(update={"follow_up_actions": tuple(actions)})
    return reply


def _empty_reply(attempt: _Attempt) -> Reply:
    return Reply(
        id=f"{attempt.attempt_id}:reply",
        reply_id=attempt.reply_id,
        attempt_id=attempt.attempt_id,
        tool_data=attempt.work_cards,
        image=attempt.work_image,
    )


def _base_reply(attempt: _Attempt) -> Reply:
    progress = attempt.progress
    return progress.reply if isinstance(progress, _Showing) else _empty_reply(attempt)


async def _put_reply(ports: RuntimePorts, attempt: _Attempt, reply: Reply) -> LoggedEntry:
    if isinstance(attempt.progress, _Showing):
        return await _amend(ports, attempt.claim, reply)
    return await _append(ports, attempt.claim, await _opening_reply(ports, attempt, reply))


async def _opening_reply(ports: RuntimePorts, attempt: _Attempt, reply: Reply) -> Reply:
    """Stamp the reply about to open with the message it quotes, as if it took the next seq."""
    state = await ports.log.state(attempt.claim.conversation_id, attempt.claim.user_id)
    _, quote = await _answers_and_quote(ports, attempt, state.head + 1)
    return reply.model_copy(update={"quote_target": quote})


async def _append(ports: RuntimePorts, claim: StepClaim, entry: Entry) -> LoggedEntry:
    appended = await ports.log.append_fenced(claim, entry)
    await publish_appended(ports.frames, claim.conversation_id, appended)
    return appended.logged


async def _settle(
    ports: RuntimePorts, claim: StepClaim, covers: Sequence[LoggedEntry], settled: ReplySettled
) -> None:
    """Settle a reply on the inputs it covered, and count it the first time it lands."""
    appended = await ports.log.append_fenced(claim, settled)
    await publish_appended(ports.frames, claim.conversation_id, appended)
    if appended.duplicate:
        return
    since = await ports.log.read_after(claim.conversation_id, claim.user_id, covers[0].seq)
    capture_reply_ended(
        claim.user_id, claim.conversation_id, covers, settled, appended.logged.at, since
    )
    replies = [
        logged.entry
        for logged in since
        if isinstance(logged.entry, Reply) and logged.entry.reply_id == settled.reply_id
    ]
    files = reply_files(replies[-1]) if replies else ()
    if files:
        await ports.effects.deliver_files(claim.conversation_id, claim.user_id, files)


async def _amend(ports: RuntimePorts, claim: StepClaim, entry: Reply | UserMessage) -> LoggedEntry:
    amended = await ports.log.amend(claim, entry)
    await ports.frames.publish(
        claim.conversation_id, EntryUpdatedFrame(seq=amended.seq, entry=amended.entry)
    )
    return amended


async def _set_comms(ports: RuntimePorts, claim: StepClaim, phase: CommsPhase) -> None:
    state = await ports.log.set_comms(claim, phase)
    await ports.frames.publish(claim.conversation_id, state_frame(state))


async def _retract(ports: RuntimePorts, attempt: _Attempt) -> None:
    await ports.frames.publish(
        attempt.claim.conversation_id, RetractFrame(attempt_id=attempt.attempt_id)
    )
