"""How a settled reply is counted: once, as chat:message_completed or chat:message_cancelled.

A reply counts only when it answers a user message, under that message's analytics context
and on its id, the stream_id its chat:message_submitted carried. A settle that covers finished
background work also counts chat:background_update_resolved: a message, or silence.

The same settle feeds the chat_turn_total, chat_ttft_seconds and chat_e2e_ack_seconds series,
which also count a failed turn.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.constants.chat import BOT_CONVERSATION_SOURCES, ConversationSource
from app.models.conversation_log_models import (
    LoggedEntry,
    Reply,
    ReplySettled,
    StepClaim,
    UserMessage,
    WorkFinished,
    WorkStarted,
)
from app.services.conversation.ports import Appended, TurnAnalytics
from app.services.latency_metrics import (
    ChatTurnStatus,
    observe_chat_e2e_ack,
    observe_chat_ttft,
    observe_chat_turn_total,
)
from shared.py.analytics import Dedupe
from shared.py.analytics.catalog.attribution import Actor, Attribution, EntrySurface, Trigger
from shared.py.analytics.catalog.chat import (
    ChatBackgroundUpdateResolved,
    ChatMessageCancelled,
    ChatMessageCompleted,
)
from shared.py.analytics.context import AnalyticsContext
from shared.py.conversation_wire import ReplyOutcome

# A truncated reply is one the user spoke over: it still answered them.
_TURN_END: dict[ReplyOutcome, type[ChatMessageCompleted | ChatMessageCancelled]] = {
    ReplyOutcome.ANSWERED: ChatMessageCompleted,
    ReplyOutcome.TRUNCATED: ChatMessageCompleted,
    ReplyOutcome.STOPPED: ChatMessageCancelled,
}
# A silent settle answered its message with no words, as an emoji reaction does.
_TURN_STATUS: dict[ReplyOutcome, ChatTurnStatus] = {
    ReplyOutcome.ANSWERED: ChatTurnStatus.OK,
    ReplyOutcome.TRUNCATED: ChatTurnStatus.OK,
    ReplyOutcome.SILENT: ChatTurnStatus.OK,
    ReplyOutcome.FAILED: ChatTurnStatus.ERROR,
    ReplyOutcome.STOPPED: ChatTurnStatus.CANCELLED,
}
_WORK_RESOLVED: dict[ReplyOutcome, Literal["message", "silence"]] = {
    ReplyOutcome.ANSWERED: "message",
    ReplyOutcome.SILENT: "silence",
}

#: Work that finished, or an integration the work waited on, wakes comms with no one asking.
UNPROMPTED = AnalyticsContext(
    attribution=Attribution(actor=Actor.AGENT, trigger=Trigger.SYSTEM, surface=EntrySurface.WORKER)
)


def spoken_context(message: UserMessage) -> AnalyticsContext:
    """Return the analytics context of what a user message causes: the user, on its surface and session."""
    if message.surface is ConversationSource.VOICE:
        surface = EntrySurface.VOICE
    elif message.surface in BOT_CONVERSATION_SOURCES:
        surface = EntrySurface.BOT
    elif message.surface is ConversationSource.DESKTOP:
        surface = EntrySurface.DESKTOP
    else:
        surface = EntrySurface.WEB
    return AnalyticsContext(
        attribution=Attribution(actor=Actor.USER, trigger=Trigger.INTERACTIVE, surface=surface),
        posthog_session_id=message.posthog_session_id,
    )


def _ms(since: datetime, until: datetime) -> float:
    return round((until - since).total_seconds() * 1000.0, 2)


def capture_reply_ended(
    analytics: TurnAnalytics,
    claim: StepClaim,
    covers: Sequence[LoggedEntry],
    settled: ReplySettled,
    settled_at: datetime,
    since: Sequence[LoggedEntry],
) -> None:
    """Count a reply settle that answered, failed or stopped a user message, and the finished work it resolved; since is the log after covers[0]."""
    if settled.outcome in _TURN_STATUS:
        _capture_answered(analytics, claim, covers, settled, settled_at, since)
    if settled.outcome in _WORK_RESOLVED and any(
        isinstance(logged.entry, WorkFinished) for logged in covers
    ):
        said = [logged.entry for logged in covers if isinstance(logged.entry, UserMessage)]
        analytics.capture(
            claim.user_id,
            ChatBackgroundUpdateResolved(outcome=_WORK_RESOLVED[settled.outcome]),
            spoken_context(said[-1]) if said else UNPROMPTED,
            Dedupe(key=settled.id, occurred_at=settled_at),
        )


def _capture_answered(
    analytics: TurnAnalytics,
    claim: StepClaim,
    covers: Sequence[LoggedEntry],
    settled: ReplySettled,
    settled_at: datetime,
    since: Sequence[LoggedEntry],
) -> None:
    shown = next(
        (
            logged.at
            for logged in since
            if isinstance(logged.entry, Reply) and logged.entry.reply_id == settled.reply_id
        ),
        None,
    )
    _capture_turn_end(
        analytics,
        settled.outcome,
        claim.user_id,
        claim.conversation_id,
        _TurnEnd(covers, since, settled.id, settled_at, shown, settled.reply_id),
    )


def capture_unanswered_stop(
    analytics: TurnAnalytics,
    user_id: str,
    conversation_id: str,
    appended: Appended,
    logged: Sequence[LoggedEntry],
) -> None:
    """Count the user messages a Stop settled before any reply showed; logged is the log after the earliest.

    A Stop that lands while a reply is showing is counted where the step settles that reply.
    """
    stopped = stopped_waking(appended)
    if appended.duplicate or appended.previous.open_reply is not None or not stopped:
        return
    covers = [entry for entry in logged if entry.seq in stopped]
    stop = appended.logged
    since = [entry for entry in logged if entry.seq > covers[0].seq]
    _capture_turn_end(
        analytics,
        ReplyOutcome.STOPPED,
        user_id,
        conversation_id,
        _TurnEnd(covers, since, stop.entry.id, stop.at, None, None),
    )


def stopped_waking(appended: Appended) -> set[int]:
    """Return the seqs of the inputs this append settled without an answer: what a Stop dropped."""
    return set(appended.previous.unsettled_waking) - set(appended.state.unsettled_waking)


@dataclass(frozen=True)
class _TurnEnd:
    """The inputs a turn ended on, the log after the first, and the entry that ended it."""

    covers: Sequence[LoggedEntry]
    since: Sequence[LoggedEntry]
    ended_by: str
    ended_at: datetime
    shown: datetime | None
    reply_id: str | None


def _observe_turn_end(
    surface: ConversationSource, status: ChatTurnStatus, ttft_ms: float | None, e2e_full_ms: float
) -> None:
    observe_chat_turn_total(source=surface, status=status)
    observe_chat_e2e_ack(e2e_full_ms / 1000.0, source=surface, status=status)
    if ttft_ms is not None:
        observe_chat_ttft(ttft_ms / 1000.0, source=surface, status=status)


def _capture_turn_end(
    analytics: TurnAnalytics,
    outcome: ReplyOutcome,
    user_id: str,
    conversation_id: str,
    end: _TurnEnd,
) -> None:
    said = [
        (logged, logged.entry) for logged in end.covers if isinstance(logged.entry, UserMessage)
    ]
    if not said:
        return
    asked, message = said[-1]
    first = end.covers[0].seq
    ttft_ms = None if end.shown is None else _ms(asked.at, end.shown)
    e2e_full_ms = _ms(asked.at, end.ended_at)
    _observe_turn_end(message.surface, _TURN_STATUS[outcome], ttft_ms, e2e_full_ms)
    event_type = _TURN_END.get(outcome)
    if event_type is None:
        return
    event = event_type(
        stream_id=message.id,
        conversation_id=conversation_id,
        is_new_conversation=first == 1,
        delegated=any(
            isinstance(logged.entry, WorkStarted) and logged.entry.cause_through >= first
            for logged in end.since
        ),
        # Another reply settled after the message arrived: it waited for that one.
        queued=any(
            isinstance(logged.entry, ReplySettled)
            and logged.entry.reply_id != end.reply_id
            # Equivalent under mutation as >=: the entry at asked.seq is the message itself.
            and logged.seq > asked.seq  # pragma: no mutate
            for logged in end.since
        ),
        ttft_ms=ttft_ms,
        e2e_full_ms=e2e_full_ms,
        source=message.surface.value,
    )
    analytics.capture(
        user_id, event, spoken_context(message), Dedupe(key=end.ended_by, occurred_at=end.ended_at)
    )
