"""The conversation step: the one writer that answers a conversation's waking entries, in order."""

import asyncio
from collections.abc import Sequence
import contextlib
import itertools
from typing import cast

from app.constants.chat import BOT_CONVERSATION_SOURCES
from app.constants.conversation import (
    CLASSIFIER_LOOKBACK_SEQS,
    RUNNER_ALIVE_BEATS_PER_TTL,
    RUNNER_ALIVE_TTL_SECONDS,
)
from app.models.conversation_frame_models import (
    EntryFrame,
)
from app.models.conversation_log_models import (
    Batch,
    CommsPhase,
    ConversationState,
    LoggedEntry,
    MergeGroup,
    Reply,
    ReplySettled,
    StepClaim,
    UserMessage,
    WorkflowFired,
)
from app.models.message_models import MessageDict
from app.services.conversation.ports import (
    ClaimLost,
    RuntimePorts,
    Unsettled,
)
from app.services.conversation.step_attempt import Attempt, empty_reply, waking_entry
from app.services.conversation.step_endings import cut_spoken_over
from app.services.conversation.step_run import run_attempt
from app.services.conversation.step_view import StepView
from app.services.conversation.step_writes import (
    append_entry,
    conclude,
    quoted_target,
    set_comms,
    settle_inputs,
)
from app.services.conversation.todo_wake import nothing_to_report
from app.services.conversation.verdict import merge_group
from app.utils.hot_path import first_text_gate
from app.utils.liveness import keep_proving
from shared.py.conversation_wire import (
    FailureReason,
    ReplyOutcome,
)


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
        cast(asyncio.Task[object], asyncio.current_task()).uncancel()
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
        await append_entry(ports, claim, opened)
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
        await append_entry(ports, claim, recovered)
    elif state.comms is not CommsPhase.IDLE:
        await set_comms(ports, claim, CommsPhase.IDLE)


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
    entries = await cut_spoken_over(ports, claim, unsettled.entries)
    view = StepView(
        state=state, after=max(state.settled_through, state.stopped_through), entries=entries
    )
    pending = [logged for logged in entries if logged.seq in state.unsettled_waking]
    if not pending:
        return False, None
    if await _answered_as_approval(ports, claim, state, pending[0], attempt_id):
        return True, None
    batch = _batch(pending)
    attempt = Attempt(
        claim=claim,
        run_id=attempt_id,
        reply_id=f"r{attempt_id}",
        batch=batch,
        handed=batch.waking,
        ledger=f"{conversation_id}:{attempt_id}",
        seen=batch.end,
        view=view,
        hint_head=state.head,
    )
    if await nothing_to_report(ports.log, conversation_id, claim.user_id, batch):
        # The run said so itself, and its todo lets it: nothing is shown, its report stays on its WorkFinished.
        attempt.covers = batch.waking
        await conclude(ports, attempt, empty_reply(attempt), ReplyOutcome.SILENT)
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
        await run_attempt(ports, attempt, context)
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
    group = merge_group(waking_entry(pending[0]))
    joined: tuple[LoggedEntry, ...]
    if group is MergeGroup.BACKGROUND:
        joined = (pending[0],)
    else:
        joined = tuple(
            itertools.takewhile(lambda logged: merge_group(waking_entry(logged)) is group, pending)
        )
    return Batch(start=joined[0].seq, end=joined[-1].seq, waking=joined, first_at=joined[0].at)


async def _turns_before(ports: RuntimePorts, claim: StepClaim, seq: int) -> list[MessageDict]:
    """Return the user messages and shown replies logged shortly before seq, as chat turns."""
    since = max(0, seq - 1 - CLASSIFIER_LOOKBACK_SEQS)
    entries = await ports.log.read_after(claim.conversation_id, claim.user_id, since)
    turns: list[MessageDict] = []
    for logged in itertools.takewhile(lambda logged: logged.seq < seq, entries):
        match logged.entry:
            case UserMessage(text=text):
                turns.append({"role": "user", "content": text})
            case Reply(text=text) if text:
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
    text = await ports.approvals.resolve(
        claim.conversation_id, claim.user_id, message.text, history
    )
    if text is None:
        return False
    ack = Reply(
        id=f"{attempt_id}:reply", reply_id=f"r{attempt_id}", attempt_id=attempt_id, text=text
    )
    shown = await append_entry(ports, claim, ack)
    answers = (message.id,)
    settled = ReplySettled(
        id=f"{attempt_id}:settled",
        reply_id=ack.reply_id,
        outcome=ReplyOutcome.ANSWERED,
        answers=answers,
        through=first.seq,
        quote_target=await quoted_target(ports, claim, answers, first, shown.seq),
    )
    await settle_inputs(ports, claim, (first,), settled, None)
    return True
