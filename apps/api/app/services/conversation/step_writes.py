"""The step's writes: log appends, amends and settles, the comms phase, and the frames clients follow."""

from collections.abc import Sequence

from app.models.conversation_frame_models import (
    EntryUpdatedFrame,
    RetractFrame,
    state_frame,
)
from app.models.conversation_log_models import (
    CommitReason,
    CommsPhase,
    ConversationState,
    Entry,
    LoggedEntry,
    Reply,
    ReplySettled,
    StepClaim,
    UserMessage,
)
from app.services.conversation.log import publish_appended
from app.services.conversation.placement import open_slot
from app.services.conversation.ports import (
    RuntimePorts,
)
from app.services.conversation.reply_analytics import capture_reply_ended
from app.services.conversation.reply_text import ReplyText
from app.services.conversation.step_attempt import (
    Attempt,
    Quiet,
    Showing,
    base_reply,
    quote_in,
    reply_bubbles,
    settled_entry,
)
from app.services.conversation.step_view import StepView
from shared.py.conversation_wire import (
    BubblesDelta,
    BubbleTextDelta,
    FailureReason,
    ReplyDelta,
    ReplyDeltaFrame,
    ReplyOutcome,
)


async def settle_segment_if_passed(ports: RuntimePorts, attempt: Attempt) -> None:
    """Settle the open segment where it stands once inputs handed after its slot wait; the next segment answers them below."""
    if len(attempt.placed) == attempt.segment + 1:
        return
    await conclude(ports, attempt, base_reply(attempt), ReplyOutcome.ANSWERED)
    attempt.segment += 1
    attempt.reply_id = f"r{attempt.attempt_id}"
    attempt.progress = Quiet(reason=CommitReason.MODEL_OUTPUT)
    attempt.deltas = 0
    attempt.text = ReplyText()
    attempt.shown = ()


async def publish_delta(ports: RuntimePorts, attempt: Attempt, change: ReplyDelta) -> None:
    if isinstance(change, BubbleTextDelta | BubblesDelta):
        attempt.shown = attempt.text.bubbles
    delta = ReplyDeltaFrame(
        attempt_id=attempt.attempt_id,
        reply_id=attempt.reply_id,
        index=attempt.deltas,
        payload=change,
    )
    attempt.deltas += 1
    await ports.frames.publish(attempt.claim.conversation_id, delta)


async def conclude(
    ports: RuntimePorts,
    attempt: Attempt,
    reply: Reply,
    settled_as: ReplyOutcome,
    failure: FailureReason | None = None,
) -> LoggedEntry:
    """Save the reply's final content, settle it as answering everything the attempt covered, and return it."""
    stored = await put_reply(ports, attempt, reply)
    answers, quote = await _answers_and_quote(ports, attempt, stored.seq)
    if settled_as is ReplyOutcome.SILENT:
        quote = None
    await settle_inputs(
        ports,
        attempt.claim,
        attempt.covers,
        settled_entry(attempt, settled_as, answers, attempt.through, quote, failure),
        attempt.view,
    )
    return stored


async def _answers_and_quote(
    ports: RuntimePorts,
    attempt: Attempt,
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
    return answers, quote_in(answers, reply_seq, known)


async def quoted_target(
    ports: RuntimePorts,
    claim: StepClaim,
    answers: tuple[str, ...],
    first: LoggedEntry,
    reply_seq: int,
) -> str | None:
    """Return what the reply quotes of the entries from first, the oldest input it answers."""
    after = await ports.log.read_after(claim.conversation_id, claim.user_id, first.seq)
    return quote_in(answers, reply_seq, [first, *after])


async def put_reply(ports: RuntimePorts, attempt: Attempt, reply: Reply) -> LoggedEntry:
    """Store the segment's final reply; once it is shown, clients are carried to the stored text."""
    if not isinstance(attempt.progress, Showing):
        return await append_opening(ports, attempt, await opening_reply(ports, attempt, reply))
    if reply_bubbles(reply.text) != attempt.shown:
        await publish_delta(ports, attempt, BubblesDelta(bubbles=reply_bubbles(reply.text)))
    return await amend_seen(ports, attempt, reply)


async def append_opening(ports: RuntimePorts, attempt: Attempt, reply: Reply) -> LoggedEntry:
    """Open the current segment's reply: the seq it takes is its slot, and never changes."""
    opened = await _append_seen(ports, attempt, reply)
    attempt.slots = open_slot(attempt.slots, attempt.segment, opened.seq)
    return opened


async def opening_reply(ports: RuntimePorts, attempt: Attempt, reply: Reply) -> Reply:
    """Stamp the reply about to open with the message it quotes, as if it took the next seq."""
    state = await _state(ports, attempt)
    _, quote = await _answers_and_quote(ports, attempt, state.head + 1, state)
    return reply.model_copy(update={"quote_target": quote})


async def _state(ports: RuntimePorts, attempt: Attempt) -> ConversationState:
    """Return the state from the attempt's view while nothing newer was logged, else read it."""
    known = attempt.view.state_at(attempt.hint_head)
    if known is not None:
        return known
    return await ports.log.state(attempt.claim.conversation_id, attempt.claim.user_id)


async def _append_seen(ports: RuntimePorts, attempt: Attempt, entry: Entry) -> LoggedEntry:
    """Append under the attempt's claim and take the entry into its view."""
    appended = await ports.log.append_fenced(attempt.claim, entry)
    await publish_appended(ports.frames, attempt.claim.conversation_id, appended)
    attempt.view.appended(appended)
    return appended.logged


async def append_entry(ports: RuntimePorts, claim: StepClaim, entry: Entry) -> LoggedEntry:
    appended = await ports.log.append_fenced(claim, entry)
    await publish_appended(ports.frames, claim.conversation_id, appended)
    return appended.logged


async def settle_inputs(
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


async def amend_seen(
    ports: RuntimePorts, attempt: Attempt, entry: Reply | UserMessage
) -> LoggedEntry:
    """Amend under the attempt's claim and take the new content into its view."""
    amended = await amend_entry(ports, attempt.claim, entry)
    attempt.view.amended(amended)
    return amended


async def amend_entry(
    ports: RuntimePorts, claim: StepClaim, entry: Reply | UserMessage
) -> LoggedEntry:
    amended = await ports.log.amend(claim, entry)
    await ports.frames.publish(
        claim.conversation_id, EntryUpdatedFrame(seq=amended.seq, entry=amended.entry)
    )
    return amended


async def set_comms(ports: RuntimePorts, claim: StepClaim, phase: CommsPhase) -> ConversationState:
    state = await ports.log.set_comms(claim, phase)
    await ports.frames.publish(claim.conversation_id, state_frame(state))
    return state


async def retract_attempt(ports: RuntimePorts, attempt: Attempt) -> None:
    await ports.frames.publish(
        attempt.claim.conversation_id, RetractFrame(attempt_id=attempt.attempt_id)
    )
