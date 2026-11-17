"""Advance every lifecycle by one accepted log entry; the head keeps only what is still live."""

from app.models.conversation_lifecycle_models import (
    ApprovalCancelled,
    ApprovalWithdrawn,
    InputOrigin,
    Lifecycles,
    WithdrawReason,
)
from app.models.conversation_log_models import (
    ApprovalDecided,
    ApprovalRequested,
    Entry,
    IntegrationConnected,
    Reply,
    ReplySettled,
    StopRequested,
    UserMessage,
    WorkFinished,
    WorkflowFired,
    WorkStarted,
)
from app.services.conversation.lifecycle import approvals, attempt, messages, runs


def advance(lifecycles: Lifecycles, seq: int, entry: Entry) -> Lifecycles:
    """Return the lifecycles after the entry the log accepted at seq."""
    current = lifecycles
    match entry:
        case UserMessage(first_contact=False, imported=False):
            current = _opened(current, seq, entry.id, InputOrigin.USER)
        case WorkflowFired():
            current = _opened(current, seq, entry.id, InputOrigin.WORKFLOW)
        case IntegrationConnected():
            current = _opened(current, seq, entry.id, InputOrigin.INTEGRATION)
        case StopRequested():
            current = _stopped(current, seq, entry)
        case WorkStarted():
            current = _started(current, entry)
        case ApprovalRequested():
            current = _asked(current, entry)
        case ApprovalDecided():
            current = _decided(current, entry)
        case WorkFinished():
            current = _finished(current, seq, entry)
        case Reply(imported=False):
            current = current.model_copy(update={"attempt": attempt.opened(seq, entry)})
        case ReplySettled(imported=False):
            current = _settled(current, entry)
    return _live(current)


def _opened(lifecycles: Lifecycles, seq: int, entry_id: str, origin: InputOrigin) -> Lifecycles:
    return lifecycles.model_copy(
        update={"messages": messages.opened(lifecycles.messages, seq, entry_id, origin)}
    )


def _stopped(lifecycles: Lifecycles, seq: int, entry: StopRequested) -> Lifecycles:
    covers = seq - 1 if entry.covers_through is None else entry.covers_through
    covered = {run.task_id for run in lifecycles.runs if run.cause_through <= covers}
    return lifecycles.model_copy(
        update={
            "messages": messages.stopped(lifecycles.messages, seq, covers),
            "approvals": approvals.closed_with(lifecycles.approvals, covered, ApprovalCancelled()),
            "runs": runs.stopped(lifecycles.runs, covers),
        }
    )


def _started(lifecycles: Lifecycles, entry: WorkStarted) -> Lifecycles:
    task_id = entry.joins or entry.task_id
    return lifecycles.model_copy(
        update={
            "messages": messages.handed_off(lifecycles.messages, entry.answers, task_id),
            "runs": runs.started(lifecycles.runs, entry),
        }
    )


def _asked(lifecycles: Lifecycles, entry: ApprovalRequested) -> Lifecycles:
    return lifecycles.model_copy(
        update={
            "approvals": approvals.requested(lifecycles.approvals, entry),
            "runs": runs.asked(lifecycles.runs, entry.task_id),
        }
    )


def _decided(lifecycles: Lifecycles, entry: ApprovalDecided) -> Lifecycles:
    before = next(
        (a for a in lifecycles.approvals if a.approval_id == entry.approval_id and a.pending), None
    )
    after = approvals.decided(lifecycles.approvals, entry)
    if before is None:
        return lifecycles.model_copy(update={"approvals": after})
    released = runs.decided(
        lifecycles.runs,
        before.owner,
        entry.approval_id,
        continued=entry.outcome in approvals.CONTINUED_DECISIONS,
        still_pending=bool(approvals.pending_ids(after, before.owner)),
    )
    return lifecycles.model_copy(update={"approvals": after, "runs": released})


def _finished(lifecycles: Lifecycles, seq: int, entry: WorkFinished) -> Lifecycles:
    owns_pending = bool(approvals.pending_ids(lifecycles.approvals, entry.task_id))
    ended, result = runs.finished(lifecycles.runs, entry, owns_pending=owns_pending)
    still_live = {run.task_id for run in ended if run.live}
    gone = {run.task_id for run in lifecycles.runs} - still_live
    closed = approvals.closed_with(
        lifecycles.approvals, gone, ApprovalWithdrawn(reason=WithdrawReason.RUN_ENDED)
    )
    opened = (
        lifecycles.messages
        if result is None
        else messages.opened(lifecycles.messages, seq, entry.id, InputOrigin.WORK_RESULT, result)
    )
    return lifecycles.model_copy(update={"messages": opened, "approvals": closed, "runs": ended})


def _settled(lifecycles: Lifecycles, entry: ReplySettled) -> Lifecycles:
    """End the open attempt; the settle entry itself is its settled or failed state."""
    return lifecycles.model_copy(
        update={"attempt": None, "messages": messages.settled(lifecycles.messages, entry)}
    )


def _live(lifecycles: Lifecycles) -> Lifecycles:
    """Keep the live members only, validated together: terminal ones are read back from the log."""
    live_runs = tuple(run for run in lifecycles.runs if run.live)
    owners = {run.task_id for run in live_runs}
    return Lifecycles(
        messages=tuple(message for message in lifecycles.messages if message.live),
        attempt=lifecycles.attempt,
        approvals=tuple(a for a in lifecycles.approvals if a.owner in owners),
        runs=live_runs,
    )
