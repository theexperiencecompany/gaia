"""The reply attempt lifecycle: streaming while open; its ReplySettled entry is how it ended."""

from app.models.conversation_lifecycle_models import AttemptStreaming
from app.models.conversation_log_models import Reply


def opened(seq: int, entry: Reply) -> AttemptStreaming:
    """Open the reply at seq; its quote target is fixed here."""
    return AttemptStreaming(
        reply_id=entry.reply_id,
        attempt_id=entry.attempt_id,
        seq=seq,
        quote_target=entry.quote_target,
    )
