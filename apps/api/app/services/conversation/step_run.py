"""One attempt's run: started on its batch, watched delta by delta, and judged against new entries."""

from collections.abc import Sequence

from app.agents.core.comms_ledger import close_ledger, open_ledger, owe, still_open
from app.constants.conversation import STILL_OPEN_LINE, STILL_OPEN_NOTE, STILL_OPEN_QUOTE_CHARS
from app.models.conversation_frame_models import (
    MessageBoundaryEvent,
    ResponseEvent,
    StreamPayload,
)
from app.models.conversation_log_models import (
    CommitReason,
    CommsPhase,
    LoggedEntry,
    MergeGroup,
    StopRequested,
    UserMessage,
    Verdict,
)
from app.services.conversation.placement import owed
from app.services.conversation.ports import (
    Answered,
    CancelReason,
    ClaimLost,
    CommsRun,
    Finished,
    ModelOutput,
    RuntimePorts,
    Streamed,
    Summarized,
)
from app.services.conversation.step_attempt import (
    Attempt,
    Drafting,
    Quiet,
    Showing,
    base_reply,
    folded_reply,
    is_text,
    is_visible,
    reply_deltas,
    waking_entry,
)
from app.services.conversation.step_endings import end_attempt, fail_attempt, finish_run
from app.services.conversation.step_pump import Crashed, Ending, Pump, Tick, close_pump, next_signal
from app.services.conversation.step_writes import (
    append_opening,
    opening_reply,
    publish_delta,
    retract_attempt,
    set_comms,
    settle_passed,
)
from app.services.conversation.verdict import merge_group, verdict
from app.utils.hot_path import first_text_shown


async def run_attempt(
    ports: RuntimePorts, attempt: Attempt, context: Sequence[LoggedEntry]
) -> None:
    """Run one comms attempt to its end, in a second run when the first ends owing messages; every run is dead when this returns."""
    attempt.view.phase_set(await set_comms(ports, attempt.claim, CommsPhase.THINKING))
    open_ledger(attempt.ledger, owed(attempt.batch.waking))
    try:
        note = None
        while True:
            if not await _run_once(ports, attempt, context, note) or not attempt.continuing:
                return
            attempt.continuing = False
            attempt.answered = None
            note = still_open_note(attempt)
    finally:
        close_ledger(attempt.ledger)


async def _run_once(
    ports: RuntimePorts, attempt: Attempt, context: Sequence[LoggedEntry], note: str | None
) -> bool:
    """Run one graph run of the attempt; False when it ended the attempt failed."""
    try:
        run = await ports.runner.start(attempt.claim, attempt.batch, context, attempt.ledger, note)
    except Exception as error:  # a run that cannot start fails its inputs like one that crashed
        await fail_attempt(ports, attempt, error)
        return False
    try:
        ending = await _watch(ports, attempt, run)
    except ClaimLost:
        await run.cancel(CancelReason.LOST)
        if not isinstance(attempt.progress, Showing):
            await retract_attempt(ports, attempt)
        raise
    except Exception as error:  # a store or stream failure mid-attempt fails it, under the claim
        await run.cancel(CancelReason.LOST)
        await settle_passed(ports, attempt)
        await fail_attempt(ports, attempt, error)
        return False
    except BaseException:
        await run.cancel(CancelReason.LOST)
        raise
    try:
        await end_attempt(ports, attempt, run, ending)
    except ClaimLost:
        raise
    except (
        Exception
    ) as error:  # settling failed part-way: its idempotent ids let fail_attempt finish it
        await fail_attempt(ports, attempt, error)
        return False
    return True


def still_open_note(attempt: Attempt) -> str:
    """Return the note telling the run which messages it still owes."""
    owing = still_open(attempt.ledger)
    lines = [
        STILL_OPEN_LINE.format(seq=logged.seq, text=logged.entry.text[:STILL_OPEN_QUOTE_CHARS])
        for logged in attempt.handed
        if logged.seq in owing and isinstance(logged.entry, UserMessage)
    ]
    return STILL_OPEN_NOTE.format(messages="\n".join(lines))


async def _watch(ports: RuntimePorts, attempt: Attempt, run: CommsRun) -> Ending:
    """Consume the run's events, checking the verdict on each and on every tick."""
    pump = Pump(events=run.events())
    try:
        while True:
            signal = await next_signal(pump, ports.tick)
            if attempt.answered is not None or attempt.continuing:
                # Settled, or going on in another run: later inputs are the next attempt's.
                if isinstance(signal, Finished | Crashed):
                    return signal
                continue
            if isinstance(signal, ModelOutput | Summarized):
                # Already checkpointed when its event arrives: this event can never be restarted.
                _commit_quietly(attempt)
            decision = await _decide(ports, attempt)
            if decision is not Verdict.CONTINUE:
                return decision
            if isinstance(signal, Finished | Crashed):
                return signal
            if isinstance(signal, Answered):
                attempt.answered = await finish_run(ports, attempt, run, signal.outcome)
            elif not isinstance(signal, Tick | Summarized):
                await _handle(ports, attempt, run, signal)
    finally:
        await close_pump(pump)


async def _decide(ports: RuntimePorts, attempt: Attempt) -> Verdict:
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


async def _look_for_joiners(ports: RuntimePorts, attempt: Attempt) -> None:
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
            if not joinable or merge_group(waking_entry(logged)) is not attempt.group:
                attempt.closed = True
            else:
                attempt.joiners = (*attempt.joiners, logged)
        if attempt.closed:
            return


async def _handle(
    ports: RuntimePorts,
    attempt: Attempt,
    run: CommsRun,
    event: Streamed | ModelOutput,
) -> None:
    # A model output or summary was committed as it arrived, before the verdict.
    match event:
        case ModelOutput(has_tool_calls=has_tool_calls):
            await settle_passed(ports, attempt)
            if has_tool_calls and attempt.joiners:
                await run.absorb(attempt.joiners)
                owe(attempt.ledger, owed(attempt.joiners))
                attempt.handed = (*attempt.handed, *attempt.joiners)
                attempt.joiners = ()
                # The open reply sits above them: it can answer none, so it ends before more shows.
                attempt.split = isinstance(attempt.progress, Showing)
        case Streamed(payload=payload, by_model=by_model):
            # What a running tool shows stays beside its call, above inputs handed since.
            if by_model:
                await settle_passed(ports, attempt)
            await _show(ports, attempt, payload)


def _commit_quietly(attempt: Attempt) -> None:
    if attempt.progress is None:
        attempt.progress = Quiet(reason=CommitReason.MODEL_OUTPUT)


async def _show(ports: RuntimePorts, attempt: Attempt, payload: StreamPayload) -> None:
    """Stream the delta; the reply's entry opens holding its first visible delta, so it appears below everything shown before it.

    A hand-off alone opens nothing: the work's bubble, at its WorkStarted, shows it.
    """
    before = base_reply(attempt)
    if isinstance(payload, ResponseEvent | MessageBoundaryEvent):
        attempt.text = attempt.text.take(payload)
    folded = folded_reply(before, payload, attempt.text)
    showing = isinstance(attempt.progress, Showing)
    if not showing and is_visible(payload):
        folded = await opening_reply(ports, attempt, folded)
        opened = await append_opening(ports, attempt, folded)
        showing = True
        if opened.seq == attempt.seen + 1:
            # Its own entry: no need to read the log for joiners the next verdict.
            attempt.seen = opened.seq
        if is_text(payload):
            first_text_shown()
    attempt.progress = Showing(reply=folded) if showing else Drafting(reply=folded)
    for change in reply_deltas(before, folded, payload, attempt.shown, attempt.text.bubbles):
        await publish_delta(ports, attempt, change)
