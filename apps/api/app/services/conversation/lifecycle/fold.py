"""Advance every lifecycle by one accepted log entry; the head keeps only what is still live."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import NamedTuple

from app.models.conversation_lifecycle_models import (
    Approval,
    ApprovalCancelled,
    ApprovalWithdrawn,
    AttemptFailed,
    AttemptSettled,
    InputOrigin,
    Lifecycles,
    Message,
    ReplyAttempt,
    WithdrawReason,
    WorkRun,
)
from app.models.conversation_log_models import (
    ApprovalDecided,
    ApprovalRequested,
    Entry,
    IntegrationConnected,
    LoggedEntry,
    Reply,
    ReplySettled,
    StopRequested,
    UserMessage,
    WorkFinished,
    WorkflowFired,
    WorkStarted,
)
from app.services.conversation.lifecycle import approvals, attempt, messages, runs


@dataclass(frozen=True)
class Window:
    """Every member a run of log entries touched, by id, in its last status; head is what stays live."""

    head: Lifecycles
    messages: Mapping[str, Message] = field(default_factory=dict)
    attempts: Mapping[str, ReplyAttempt] = field(default_factory=dict)
    approvals: Mapping[str, Approval] = field(default_factory=dict)
    runs: Mapping[str, WorkRun] = field(default_factory=dict)


class _Step(NamedTuple):
    """One entry's transitions before the head drops what ended; ended is the attempt it settled."""

    moved: Lifecycles
    ended: AttemptSettled | AttemptFailed | None


def advance(lifecycles: Lifecycles, seq: int, entry: Entry) -> Lifecycles:
    """Return the lifecycles after the entry the log accepted at seq."""
    return _live(_step(lifecycles, seq, entry).moved)


def fold_window(start: Lifecycles, entries: Sequence[LoggedEntry]) -> Window:
    """Fold consecutive accepted entries from start, keeping each member's terminal status too.

    Everything an entry causes is logged after it, so a window opening at an entry's seq
    holds every status that entry and its work reach.
    """
    head = start
    messages = {message.id: message for message in start.messages}
    attempts: dict[str, ReplyAttempt] = {}
    if start.attempt is not None:
        attempts[start.attempt.reply_id] = start.attempt
    approvals = {approval.approval_id: approval for approval in start.approvals}
    runs = {run.task_id: run for run in start.runs}
    for logged in entries:
        moved, ended = _step(head, logged.seq, logged.entry)
        messages |= {message.id: message for message in moved.messages}
        approvals |= {approval.approval_id: approval for approval in moved.approvals}
        runs |= {run.task_id: run for run in moved.runs}
        if moved.attempt is not None:
            attempts[moved.attempt.reply_id] = moved.attempt
        if ended is not None:
            attempts[ended.reply_id] = ended
        head = _live(moved)
    return Window(head=head, messages=messages, attempts=attempts, approvals=approvals, runs=runs)


def _step(lifecycles: Lifecycles, seq: int, entry: Entry) -> _Step:
    return _Step(moved=_moved(lifecycles, seq, entry), ended=_ended_attempt(lifecycles, entry))


def _ended_attempt(lifecycles: Lifecycles, entry: Entry) -> AttemptSettled | AttemptFailed | None:
    """Return how the open reply ended when entry settles it."""
    match entry:
        case ReplySettled(imported=False) if lifecycles.attempt is not None:
            return attempt.settled(entry)
    return None


def _moved(lifecycles: Lifecycles, seq: int, entry: Entry) -> Lifecycles:
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
    return current


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
