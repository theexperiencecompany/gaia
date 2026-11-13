"""How a settled reply is counted: once, as chat:message_completed or chat:message_cancelled.

A reply counts only when it answers a user message, under that message's analytics context
and on its id, the stream_id its chat:message_submitted carried.
"""

from collections.abc import Sequence
from datetime import datetime

from app.constants.chat import BOT_CONVERSATION_SOURCES, ConversationSource
from app.models.conversation_log_models import (
    LoggedEntry,
    Reply,
    ReplyOutcome,
    ReplySettled,
    UserMessage,
    WorkStarted,
)
from app.services.analytics_service import capture
from shared.py.analytics import Dedupe, UserId
from shared.py.analytics.catalog.attribution import Actor, Attribution, EntrySurface, Trigger
from shared.py.analytics.catalog.chat import ChatMessageCancelled, ChatMessageCompleted
from shared.py.analytics.context import AnalyticsContext, analytics_context

# A truncated reply is one the user spoke over: it still answered them.
_TURN_END: dict[ReplyOutcome, type[ChatMessageCompleted | ChatMessageCancelled]] = {
    ReplyOutcome.ANSWERED: ChatMessageCompleted,
    ReplyOutcome.TRUNCATED: ChatMessageCompleted,
    ReplyOutcome.STOPPED: ChatMessageCancelled,
}


def spoken_context(message: UserMessage) -> AnalyticsContext:
    """Return the analytics context of what a user message causes: the user, on its surface and session."""
    if message.voice:
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
    user_id: str,
    conversation_id: str,
    covers: Sequence[LoggedEntry],
    settled: ReplySettled,
    settled_at: datetime,
    since: Sequence[LoggedEntry],
) -> None:
    """Count a reply settle that answered or stopped a user message; since is the log after covers[0]."""
    said = [(logged, logged.entry) for logged in covers if isinstance(logged.entry, UserMessage)]
    if settled.outcome not in _TURN_END or not said:
        return
    asked, message = said[-1]
    shown = next(
        (
            logged.at
            for logged in since
            if isinstance(logged.entry, Reply) and logged.entry.reply_id == settled.reply_id
        ),
        None,
    )
    event = _TURN_END[settled.outcome](
        stream_id=message.id,
        conversation_id=conversation_id,
        is_new_conversation=covers[0].seq == 1,
        delegated=any(
            isinstance(logged.entry, WorkStarted) and logged.entry.cause_through >= covers[0].seq
            for logged in since
        ),
        # Another reply settled after the message arrived: it waited for that one.
        queued=any(
            isinstance(logged.entry, ReplySettled)
            and logged.entry.reply_id != settled.reply_id
            and logged.seq > asked.seq
            for logged in since
        ),
        ttft_ms=None if shown is None else _ms(asked.at, shown),
        e2e_full_ms=_ms(asked.at, settled_at),
        source=message.surface.value,
    )
    with analytics_context(spoken_context(message)):
        capture(UserId(user_id), event, Dedupe(key=settled.id, occurred_at=settled_at))
