"""The waking input lifecycle: open, handed off, answered, failed or stopped."""

from collections.abc import Collection

from app.models.conversation_lifecycle_models import (
    InputOrigin,
    Message,
    MessageAnswered,
    MessageFailed,
    MessageHandedOff,
    MessageOpen,
    MessageStatus,
    MessageStopped,
    WorkResult,
)
from app.models.conversation_log_models import ReplySettled
from shared.py.conversation_wire import ReplyOutcome

Messages = tuple[Message, ...]


def opened(
    messages: Messages,
    seq: int,
    entry_id: str,
    origin: InputOrigin,
    result: WorkResult | None = None,
) -> Messages:
    """Open the input logged at seq."""
    return (
        *messages,
        Message(seq=seq, id=entry_id, origin=origin, status=MessageOpen(), result=result),
    )


def handed_off(messages: Messages, answers: Collection[str], task_id: str) -> Messages:
    """Hand the named live user messages to task_id: the reply reporting it answers them."""
    return tuple(
        _moved(message, MessageHandedOff(task_id=task_id))
        if message.live and message.origin is InputOrigin.USER and message.id in answers
        else message
        for message in messages
    )


def settled(messages: Messages, entry: ReplySettled) -> Messages:
    """Close what the settle names, and every other input it rides past; STOPPED and INTERIM close nothing."""
    status = _settled_status(entry)
    if status is None:
        return messages
    return tuple(
        _moved(message, status) if _closed_by(message, entry) else message for message in messages
    )


def stopped(messages: Messages, stop_seq: int, covers: int) -> Messages:
    """Stop every live input logged at or before covers."""
    return tuple(
        _moved(message, MessageStopped(stop_seq=stop_seq)) if message.seq <= covers else message
        for message in messages
    )


def _settled_status(entry: ReplySettled) -> MessageStatus | None:
    if entry.failure is not None:
        return MessageFailed(reply_id=entry.reply_id, reason=entry.failure)
    match entry.outcome:
        case ReplyOutcome.ANSWERED | ReplyOutcome.SILENT | ReplyOutcome.TRUNCATED as outcome:
            return MessageAnswered(reply_id=entry.reply_id, outcome=outcome)
    return None


def _closed_by(message: Message, entry: ReplySettled) -> bool:
    """Return whether the settle closes message: a user message by name, any other input by position."""
    if message.id in entry.answers:
        return True
    return message.origin is not InputOrigin.USER and message.seq <= entry.through


def _moved(message: Message, status: MessageStatus) -> Message:
    return message.model_copy(update={"status": status}) if message.live else message
