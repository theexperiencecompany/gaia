"""The reply attempt lifecycle: streaming while open, then settled or failed by its ReplySettled."""

from app.models.conversation_lifecycle_models import (
    AttemptFailed,
    AttemptSettled,
    AttemptStreaming,
)
from app.models.conversation_log_models import Reply, ReplySettled
from shared.py.conversation_wire import ReplyOutcome


def opened(seq: int, entry: Reply) -> AttemptStreaming:
    """Open the reply at seq; its quote target is fixed here."""
    return AttemptStreaming(
        reply_id=entry.reply_id,
        attempt_id=entry.attempt_id,
        seq=seq,
        quote_target=entry.quote_target,
    )


def settled(entry: ReplySettled) -> AttemptSettled | AttemptFailed:
    """Return how the open reply the settle names ended."""
    if entry.failure is not None:
        return AttemptFailed(reply_id=entry.reply_id, reason=entry.failure)
    match entry.outcome:
        case (
            (
                ReplyOutcome.ANSWERED
                | ReplyOutcome.SILENT
                | ReplyOutcome.TRUNCATED
                | ReplyOutcome.INTERIM
                | ReplyOutcome.STOPPED
            ) as outcome
        ):
            return AttemptSettled(reply_id=entry.reply_id, outcome=outcome, answers=entry.answers)
        case ReplyOutcome.FAILED:
            # ReplySettled's validator pairs FAILED with a failure reason.
            raise AssertionError(f"reply {entry.reply_id} settled FAILED without a reason")
