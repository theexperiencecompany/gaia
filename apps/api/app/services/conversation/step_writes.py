"""The step's writes: log appends, amends and settles, the comms phase, and the frames clients follow."""

from collections.abc import Sequence

from app.agents.core.comms_ledger import Closure, drain, still_open
from app.models.chat_models import ReactionBy
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
    Reaction,
    Reply,
    ReplySettled,
    StepClaim,
    UserMessage,
)
from app.services.conversation.log import publish_appended
from app.services.conversation.placement import owed
from app.services.conversation.ports import (
    RuntimePorts,
)
from app.services.conversation.reply_analytics import capture_reply_ended, spoken_context
from app.services.conversation.reply_text import ReplyText, screen_bubbles
from app.services.conversation.step_attempt import (
    Attempt,
    Quiet,
    Showing,
    base_reply,
    quote_in,
    settled_entry,
)
from app.services.conversation.step_view import StepView
from shared.py.analytics import Dedupe
from shared.py.analytics.catalog.chat import ChatTurnReacted
from shared.py.conversation_wire import (
    BubblesDelta,
    BubbleTextDelta,
    FailureReason,
    ReplyDelta,
    ReplyDeltaFrame,
    ReplyOutcome,
)


async def settle_passed(ports: RuntimePorts, attempt: Attempt) -> LoggedEntry | None:
    """Settle what the run closed since the last model-written signal, then end a reply inputs were handed below; return the reply the closures settled."""
    closures = drain(attempt.ledger)
    settled = await _settle_named(ports, attempt, closures) if closures else None
    if attempt.split:
        await end_interim(ports, attempt)
    return settled


async def end_above(ports: RuntimePorts, attempt: Attempt, covers: Sequence[LoggedEntry]) -> None:
    """End the open reply as interim when it sits above an input covers holds: a reply never answers one below it."""
    if attempt.slot is None:
        return
    if any(logged.seq > attempt.slot for logged in covers):  # pragma: no mutate — slot is no input
        await end_interim(ports, attempt)


async def end_interim(ports: RuntimePorts, attempt: Attempt) -> None:
    """End the shown reply naming no message; nothing it covered counts answered."""
    if isinstance(attempt.progress, Showing):
        await conclude(ports, attempt, base_reply(attempt), ReplyOutcome.INTERIM, ())
        next_segment(attempt)


async def _settle_named(
    ports: RuntimePorts, attempt: Attempt, closures: Sequence[Closure]
) -> LoggedEntry | None:
    """Settle the open segment as answering exactly the messages the closing tools named.

    The settle that closes the last owed message also answers every other input handed
    (finished work, a fire), so a reply that delivers a result with an answer is one reply.
    """
    named = {seq for closure in closures for seq in closure.seqs}
    for closure in closures:
        if closure.emoji is not None:
            await react_on(ports, attempt, closure.reacted, closure.emoji)
    if not named:
        return None
    await end_above(ports, attempt, [logged for logged in attempt.handed if logged.seq in named])
    riders = () if still_open(attempt.ledger) else _riders(attempt)
    covers = tuple(logged for logged in attempt.handed if logged.seq in named or logged in riders)
    reply = base_reply(attempt)
    worded = bool(reply.text or reply.tool_data)
    stored = await conclude(
        ports, attempt, reply, ReplyOutcome.ANSWERED if worded else ReplyOutcome.SILENT, covers
    )
    next_segment(attempt)
    return stored


def _riders(attempt: Attempt) -> tuple[LoggedEntry, ...]:
    """Return the unanswered inputs no closing tool names: everything but owed user messages."""
    owing = owed(attempt.handed)
    return tuple(logged for logged in attempt.unanswered if logged.seq not in owing)


def next_segment(attempt: Attempt) -> None:
    """Count the settled segment's inputs answered and start the next segment, unopened."""
    attempt.answered_seqs |= {logged.seq for logged in attempt.covers}
    attempt.covers = ()
    attempt.segment += 1
    attempt.reply_id = f"r{attempt.attempt_id}"
    attempt.progress = Quiet(reason=CommitReason.MODEL_OUTPUT)
    attempt.slot = None
    attempt.split = False  # pragma: no mutate — read only as truthy
    attempt.deltas = 0
    attempt.text = ReplyText()
    attempt.shown = ()


async def react_on(ports: RuntimePorts, attempt: Attempt, seqs: Sequence[int], emoji: str) -> None:
    """Put the chat model's reaction on each named message."""
    for logged in attempt.handed:
        message = logged.entry
        if logged.seq not in seqs or not isinstance(message, UserMessage):
            continue
        reaction = Reaction(emoji=emoji, by=ReactionBy.CHAT_MODEL)
        amended = await amend_seen(
            ports, attempt, message.model_copy(update={"reaction": reaction})
        )
        ports.analytics.capture(
            attempt.claim.user_id,
            ChatTurnReacted(emoji=emoji),
            spoken_context(message),
            Dedupe(key=f"reacted:{message.id}:{emoji}", occurred_at=amended.at),
        )


async def publish_delta(ports: RuntimePorts, attempt: Attempt, change: ReplyDelta) -> None:
    if isinstance(change, BubbleTextDelta | BubblesDelta):
        attempt.shown = attempt.bubbles(ports.links)
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
    covers: Sequence[LoggedEntry],
    failure: FailureReason | None = None,
) -> LoggedEntry:
    """Save the reply's final content, settle it as answering exactly covers, and return it."""
    attempt.covers = tuple(covers)
    stored = await put_reply(ports, attempt, reply)
    answers, quote = await _answers_and_quote(ports, attempt, stored.seq)
    if settled_as is ReplyOutcome.SILENT:
        quote = None
    settled = settled_entry(attempt, settled_as, answers, attempt.through, quote, failure)
    await settle_inputs(ports, attempt.claim, attempt.covers, settled, attempt.view)
    attempt.last_settle = settled.id
    return stored


async def _answers_and_quote(
    ports: RuntimePorts,
    attempt: Attempt,
    reply_seq: int,
    state: ConversationState | None = None,
    covers: Sequence[LoggedEntry] | None = None,
) -> tuple[tuple[str, ...], str | None]:
    """Answer every covered input, plus the user messages that caused covered finished work."""
    covers = attempt.covers if covers is None else covers
    if not covers:
        return (), None
    if state is None:
        state = await _state(ports, attempt)
    covered = {logged.seq for logged in covers}
    work = [item for item in state.finished_work if item.seq in covered]
    ids = [logged.entry.id for logged in covers]
    answers = tuple(dict.fromkeys([*ids, *(cause for item in work for cause in item.answers)]))
    since = min([covers[0].seq, *(item.cause_from for item in work)]) - 1
    known = attempt.view.entries_after(since, max(attempt.hint_head, reply_seq - 1))
    if known is None:
        known = await ports.log.read_after(
            attempt.claim.conversation_id, attempt.claim.user_id, since
        )
    return answers, quote_in(answers, reply_seq, known)


async def put_reply(ports: RuntimePorts, attempt: Attempt, reply: Reply) -> LoggedEntry:
    """Store the segment's final reply; once it is shown, clients are carried to the stored text."""
    if not isinstance(attempt.progress, Showing):
        return await append_opening(ports, attempt, await opening_reply(ports, attempt, reply))
    settled = screen_bubbles(reply.text, attempt.claim.conversation_id, ports.links)
    if settled != attempt.shown:
        await publish_delta(ports, attempt, BubblesDelta(bubbles=settled))
    return await amend_seen(ports, attempt, reply)


async def append_opening(ports: RuntimePorts, attempt: Attempt, reply: Reply) -> LoggedEntry:
    """Open the current segment's reply: the seq it takes is its slot, and never changes."""
    opened = await _append_seen(ports, attempt, reply)
    attempt.slot = opened.seq
    return opened


async def opening_reply(ports: RuntimePorts, attempt: Attempt, reply: Reply) -> Reply:
    """Stamp the reply about to open with the message it quotes, as if it took the next seq."""
    state = await _state(ports, attempt)
    # What the reply will answer is named only when it settles: until then it quotes as answering
    # every input still unanswered, and its settle carries the final quote.
    _, quote = await _answers_and_quote(
        ports, attempt, state.head + 1, state, attempt.covers or attempt.unanswered
    )
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
    """Settle a reply on the inputs it covered, and count it the first time it lands; view takes the settle in.

    A settle that covers nothing (a reply ended interim) answered no one, so nothing is counted.
    """
    appended = await ports.log.append_fenced(claim, settled)
    await publish_appended(ports.frames, claim.conversation_id, appended)
    if appended.duplicate:
        return
    if view is not None:
        view.appended(appended)
    if not covers:
        return
    known = None if view is None else view.entries_after(covers[0].seq, appended.logged.seq)
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
