"""How an attempt ends: a finished, failed, restarted, stopped, spoken-over or lost run, and its follow-ups."""

from collections.abc import Awaitable, Callable, Sequence

from app.agents.core.comms_ledger import answer_sole, still_open
from app.models.conversation_log_models import (
    BargeIn,
    CommsPhase,
    LoggedEntry,
    Reply,
    StepClaim,
    Verdict,
)
from app.services.conversation.ports import (
    CancelReason,
    ClaimLost,
    CommsRun,
    Finished,
    Replied,
    RunOutcome,
    RuntimePorts,
    StepLimitReached,
)
from app.services.conversation.step_attempt import (
    Attempt,
    Drafting,
    Showing,
    base_reply,
    final_reply,
    settled_entry,
)
from app.services.conversation.step_pump import Crashed, Ending
from app.services.conversation.step_writes import (
    amend_entry,
    amend_seen,
    conclude,
    end_above,
    end_interim,
    put_reply,
    retract_attempt,
    set_comms,
    settle_inputs,
    settle_passed,
)
from shared.py.conversation_wire import (
    FailureReason,
    ReplyOutcome,
)
from shared.py.wide_events import log

_CANCEL_REASON: dict[Verdict, CancelReason] = {
    Verdict.RESTART: CancelReason.RESTART,
    Verdict.STOP: CancelReason.STOP,
    Verdict.TRUNCATE: CancelReason.TRUNCATE,
    Verdict.LOST: CancelReason.LOST,
}


async def end_attempt(ports: RuntimePorts, attempt: Attempt, run: CommsRun, ending: Ending) -> None:
    # A crashed run settles what its tools closed first; a cancelled one ends the shown segment
    # as cancelled, leaving its messages open.
    if isinstance(ending, Crashed):
        await settle_passed(ports, attempt)
    match ending:
        case Finished() if attempt.continuing:
            pass
        case Finished(outcome=outcome) if attempt.answered is not None:
            await _add_follow_ups(ports, attempt, attempt.answered, outcome)
        case Finished(outcome=outcome):
            attempt.answered = await finish_run(ports, attempt, outcome)
        case Crashed(error=error) if attempt.answered is not None:
            await run.cancel(CancelReason.LOST)
            log.warning(
                "comms run failed after its reply settled; no follow-up suggestions",
                error_type=type(error).__name__,
                conversation_id=attempt.claim.conversation_id,
            )
        case Crashed(error=error):
            await run.cancel(CancelReason.LOST)
            await fail_attempt(ports, attempt, error)
        case Verdict():
            await run.cancel(_CANCEL_REASON[ending])
            await _AFTER_CANCEL[ending](ports, attempt)


async def _restart(ports: RuntimePorts, attempt: Attempt) -> None:
    """Withdraw the uncommitted attempt; the next loop builds a bigger batch."""
    await retract_attempt(ports, attempt)


async def _stop(ports: RuntimePorts, attempt: Attempt) -> None:
    """Keep what was shown as a stopped reply, or withdraw an attempt that showed nothing."""
    progress = attempt.progress
    if not isinstance(progress, Showing | Drafting):
        await retract_attempt(ports, attempt)
        await set_comms(ports, attempt.claim, CommsPhase.IDLE)
        return
    await put_reply(ports, attempt, progress.reply)
    state = await ports.log.state(attempt.claim.conversation_id, attempt.claim.user_id)
    attempt.covers = attempt.unanswered
    await settle_inputs(
        ports,
        attempt.claim,
        attempt.covers,
        settled_entry(attempt, ReplyOutcome.STOPPED, (), state.stopped_through, None),
        # The Stop was logged by its sender, so the view is already behind the log.
        None,
    )


async def _truncate(ports: RuntimePorts, attempt: Attempt) -> None:
    """Note how much of the reply the user heard before speaking over it; it still answered its inputs.

    A reply that sits above an input handed below it ends interim first, as any settle does.
    """
    match attempt.progress, attempt.slot:
        case Drafting(), _:
            pass
        case Showing(reply=reply), int(slot):
            after = await ports.log.read_after(
                attempt.claim.conversation_id, attempt.claim.user_id, slot
            )
            barges = [
                logged.entry
                for logged in after
                if isinstance(logged.entry, BargeIn) and logged.entry.reply_id == attempt.reply_id
            ]
            heard = min(barges[-1].heard_through, len(reply.text)) if barges else len(reply.text)
            attempt.progress = Showing(reply=_heard(reply, heard))
        case _:
            await retract_attempt(ports, attempt)
            return
    covers = attempt.unanswered
    await end_above(ports, attempt, covers)
    await conclude(ports, attempt, base_reply(attempt), ReplyOutcome.TRUNCATED, covers)


def _heard(reply: Reply, heard_through: int) -> Reply:
    """Return the reply noting what the user heard; its shown text never shrinks."""
    return reply.model_copy(update={"heard_through": heard_through})


async def cut_spoken_over(
    ports: RuntimePorts, claim: StepClaim, entries: Sequence[LoggedEntry]
) -> list[LoggedEntry]:
    """Note what the user heard of each settled reply they spoke over; a barge-in that cut nothing off is ignored."""
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
            replies[barge.reply_id] = await amend_entry(
                ports, claim, _heard(reply, barge.heard_through)
            )
    cut = {logged.seq: logged for logged in replies.values()}
    return [cut.get(logged.seq, logged) for logged in entries]


async def _lose(ports: RuntimePorts, attempt: Attempt) -> None:
    """Write nothing more: the new holder recovers whatever this attempt left; live work never logged is withdrawn."""
    if not isinstance(attempt.progress, Showing):
        await retract_attempt(ports, attempt)
    raise ClaimLost


_AFTER_CANCEL: dict[Verdict, Callable[[RuntimePorts, Attempt], Awaitable[None]]] = {
    Verdict.RESTART: _restart,
    Verdict.STOP: _stop,
    Verdict.TRUNCATE: _truncate,
    Verdict.LOST: _lose,
}


async def finish_run(
    ports: RuntimePorts, attempt: Attempt, outcome: RunOutcome
) -> LoggedEntry | None:
    """Settle a run that ended on its own, or mark the attempt continuing while it owes messages.

    Words ending a run answer the one message open, unnamed. The first end that owes messages
    goes on in a run told which; a run that still owes them after that broke its contract, and
    they fail. Inputs no message answers settle with the last reply.
    """
    if attempt.split:
        await end_interim(ports, attempt)
    reply, worded = final_reply(attempt, outcome)
    if worded and not isinstance(attempt.progress, Showing):
        # Words the run said but never streamed are what this segment shows before it settles.
        attempt.progress = Drafting(reply=reply)
    named = await settle_passed(ports, attempt)
    if base_reply(attempt).text.strip() and answer_sole(attempt.ledger):
        # With one message open there is nothing to name: the words the run ended on answer it.
        named = await settle_passed(ports, attempt) or named
    owing = still_open(attempt.ledger)
    if owing and not attempt.reminded:
        attempt.reminded = True
        attempt.continuing = True
        return None
    if owing:
        log.error(
            "comms run still owed messages after it was told which",
            owed=list(owing),
            conversation_id=attempt.claim.conversation_id,
            attempt_id=attempt.attempt_id,
        )
        return await _settle_rest(ports, attempt, ReplyOutcome.FAILED, FailureReason.MODEL_ERROR)
    return await _settle_rest(ports, attempt) or named


async def _settle_rest(
    ports: RuntimePorts,
    attempt: Attempt,
    failed: ReplyOutcome | None = None,
    failure: FailureReason | None = None,
) -> LoggedEntry | None:
    """Settle the inputs still unanswered on the open segment; None when there is nothing to settle.

    Only a failure settles a message still owed: otherwise a closing tool names every one.
    """
    owing = still_open(attempt.ledger)
    covers = tuple(
        logged for logged in attempt.unanswered if failed is not None or logged.seq not in owing
    )
    await end_above(ports, attempt, covers)
    reply = base_reply(attempt)
    worded = bool(reply.text or reply.tool_data)
    if failed is not None:
        return await conclude(ports, attempt, reply, failed, covers, failure)
    if not covers:
        return await conclude(ports, attempt, reply, ReplyOutcome.INTERIM, ()) if worded else None
    return await conclude(
        ports, attempt, reply, ReplyOutcome.ANSWERED if worded else ReplyOutcome.SILENT, covers
    )


async def _add_follow_ups(
    ports: RuntimePorts, attempt: Attempt, settled: LoggedEntry, outcome: RunOutcome
) -> None:
    """Add the suggestions the run made after its reply settled, as an update to that reply."""
    reply = settled.entry
    if not isinstance(outcome, Replied) or not outcome.follow_up_actions:
        return
    if not isinstance(reply, Reply) or not reply.text:
        return
    await amend_seen(
        ports, attempt, reply.model_copy(update={"follow_up_actions": outcome.follow_up_actions})
    )


async def fail_attempt(ports: RuntimePorts, attempt: Attempt, error: Exception) -> None:
    """Settle what the failure cut short as failed, so the user sees why; no further run goes on with it.

    Cut short: inputs still unanswered, or a reply being written. With every input answered and
    nothing being written (a store error after a settled answer), nothing failed for the user.
    """
    attempt.continuing = False  # pragma: no mutate — read only as truthy
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
    if attempt.unanswered or isinstance(attempt.progress, Showing | Drafting):
        await _settle_rest(ports, attempt, ReplyOutcome.FAILED, failure)
    else:
        await _settle_rest(ports, attempt)
