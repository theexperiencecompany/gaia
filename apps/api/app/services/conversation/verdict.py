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
    answers: Sequence[str], reply_seq: int, tail: Sequence[tuple[int, str]]
) -> str | None:
    """Return the newest answered entry's id when an unanswered entry sits among the reply's tail, else None."""
    answered = set(answers)
    span = [(seq, entry_id) for seq, entry_id in tail if seq < reply_seq]
    newest = max(((seq, entry_id) for seq, entry_id in span if entry_id in answered), default=None)
    if newest is None:
        return None
    oldest_answered = min(seq for seq, entry_id in span if entry_id in answered)
    interrupted = any(entry_id not in answered for seq, entry_id in span if seq > oldest_answered)
    return newest[1] if interrupted else None
