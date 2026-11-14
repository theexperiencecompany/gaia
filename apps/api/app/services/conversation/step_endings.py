"""How an attempt ends: a finished, failed, restarted, stopped, spoken-over or lost run, and its follow-ups."""

from collections.abc import Awaitable, Callable, Sequence

from app.models.chat_models import ReactionBy
from app.models.conversation_log_models import (
    BargeIn,
    CommsPhase,
    LoggedEntry,
    Reaction,
    Reply,
    StepClaim,
    UserMessage,
    Verdict,
)
from app.services.conversation.ports import (
    CancelReason,
    ClaimLost,
    CommsRun,
    Finished,
    Reacted,
    Replied,
    RunOutcome,
    RuntimePorts,
    StepLimitReached,
)
from app.services.conversation.reply_analytics import spoken_context
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
    put_reply,
    retract_attempt,
    set_comms,
    settle_inputs,
    settle_segment_if_passed,
)
from shared.py.analytics import Dedupe
from shared.py.analytics.catalog.chat import ChatTurnReacted
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
    # A run that ended on its own settles what was shown above the inputs handed after it and
    # answers those below; a cancelled one ends the shown segment as cancelled, leaving them open.
    if not isinstance(ending, Verdict):
        await settle_segment_if_passed(ports, attempt)
    match ending:
        case Finished(outcome=outcome) if attempt.answered is not None:
            await _add_follow_ups(ports, attempt, attempt.answered, outcome)
        case Finished(outcome=outcome):
            await finish_run(ports, attempt, outcome)
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
    await settle_inputs(
        ports,
        attempt.claim,
        attempt.covers,
        settled_entry(attempt, ReplyOutcome.STOPPED, (), state.stopped_through, None),
        attempt.view,
    )


async def _truncate(ports: RuntimePorts, attempt: Attempt) -> None:
    """Note how much of the reply the user heard before speaking over it; it still answered its inputs."""
    progress = attempt.progress
    if isinstance(progress, Drafting):
        await conclude(ports, attempt, progress.reply, ReplyOutcome.TRUNCATED)
        return
    if not isinstance(progress, Showing) or attempt.slot is None:
        await retract_attempt(ports, attempt)
        return
    after = await ports.log.read_after(
        attempt.claim.conversation_id, attempt.claim.user_id, attempt.slot
    )
    barges = [
        logged.entry
        for logged in after
        if isinstance(logged.entry, BargeIn) and logged.entry.reply_id == attempt.reply_id
    ]
    shown = progress.reply.text
    heard = min(barges[-1].heard_through, len(shown)) if barges else len(shown)
    await conclude(ports, attempt, _heard(progress.reply, heard), ReplyOutcome.TRUNCATED)


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


async def finish_run(ports: RuntimePorts, attempt: Attempt, outcome: RunOutcome) -> LoggedEntry:
    """Settle a finished run and return its stored reply; a reaction-only answer settles silently with no visible bubble."""
    if isinstance(outcome, Reacted):
        await _react(ports, attempt, outcome.emoji)
    reply, settled_as, failure = final_reply(attempt, outcome)
    return await conclude(ports, attempt, reply, settled_as, failure)


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


async def _react(ports: RuntimePorts, attempt: Attempt, emoji: str) -> None:
    messages = [logged.entry for logged in attempt.covers if isinstance(logged.entry, UserMessage)]
    if not messages:
        return
    message = messages[-1]
    reaction = Reaction(emoji=emoji, by=ReactionBy.CHAT_MODEL)
    amended = await amend_seen(ports, attempt, message.model_copy(update={"reaction": reaction}))
    ports.analytics.capture(
        attempt.claim.user_id,
        ChatTurnReacted(emoji=emoji),
        spoken_context(message),
        Dedupe(key=f"reacted:{message.id}:{emoji}", occurred_at=amended.at),
    )


async def fail_attempt(ports: RuntimePorts, attempt: Attempt, error: Exception) -> None:
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
    await conclude(ports, attempt, base_reply(attempt), ReplyOutcome.FAILED, failure)
