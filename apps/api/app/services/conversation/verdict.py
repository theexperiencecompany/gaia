"""Pure decisions for a running comms attempt: what to do when the log moves, and what a reply quotes."""

from collections.abc import Sequence
from datetime import datetime

from app.constants.conversation import RESTART_WINDOW
from app.models.conversation_log_models import (
    BargeIn,
    Batch,
    CommitReason,
    Entry,
    MergeGroup,
    PreemptHint,
    StepClaim,
    UserMessage,
    Verdict,
    VisibleEntry,
    WakingEntry,
    WorkFinished,
    WorkflowFired,
    WorkOutcome,
)


def merge_group(entry: WakingEntry) -> MergeGroup:
    """Return the group whose inputs may merge into one attempt with entry."""
    return MergeGroup.BACKGROUND if isinstance(entry, WorkflowFired) else MergeGroup.INTERACTIVE


def needs_reply(entry: Entry) -> bool:
    """Return whether entry wakes a step that owes it a reply."""
    if isinstance(entry, WorkFinished):
        return entry.outcome is not WorkOutcome.CANCELLED
    return isinstance(entry, UserMessage | BargeIn | WorkflowFired)


def verdict(
    *,
    committed: CommitReason | None,
    batch: Batch,
    hint: PreemptHint,
    claim: StepClaim,
    now: datetime,
) -> Verdict:
    """Decide the attempt's next move; the caller raises hint.head only for inputs of the batch's merge group."""
    if hint.epoch != claim.epoch:
        return Verdict.LOST
    if hint.stop_through >= batch.start:
        return Verdict.STOP
    if hint.barge_reply_id is not None:
        return Verdict.TRUNCATE
    if committed is None and hint.head > batch.end and now - batch.first_at < RESTART_WINDOW:
        return Verdict.RESTART
    return Verdict.CONTINUE


def quote_target(
    answers: Sequence[str], reply_seq: int, visible: Sequence[VisibleEntry]
) -> str | None:
    """Return the newest answered user message's id when an unanswered entry sits between it and the reply; visible is in seq order."""
    answered = set(answers)
    earlier = [item for item in visible if item.seq < reply_seq]
    asked = [
        index for index, item in enumerate(earlier) if item.is_user_message and item.id in answered
    ]
    if not asked:
        return None
    newest = asked[-1]
    interrupted = any(item.id not in answered for item in earlier[newest + 1 :])
    return earlier[newest].id if interrupted else None
