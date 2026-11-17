"""The approval lifecycle: pending until decided, lapsed, withdrawn or cancelled."""

from collections.abc import Collection

from app.models.conversation_lifecycle_models import (
    Approval,
    ApprovalAmended,
    ApprovalApproved,
    ApprovalCancelled,
    ApprovalDenied,
    ApprovalExpired,
    ApprovalPending,
    ApprovalStatus,
    ApprovalWithdrawn,
    WithdrawReason,
)
from app.models.conversation_log_models import ApprovalDecided, ApprovalRequested
from shared.py.approvals import ApprovalOutcome

Approvals = tuple[Approval, ...]

#: Decisions the decision path hands on: it starts the work that carries them out or reports the skip.
#: A withdrawal is made by a live run (a revoke) or delivered to one (the sweep's, for a lost request).
CONTINUED_DECISIONS = frozenset(
    {
        ApprovalOutcome.APPROVED,
        ApprovalOutcome.DENIED,
        ApprovalOutcome.EXPIRED,
        ApprovalOutcome.WITHDRAWN,
    }
)


def requested(approvals: Approvals, entry: ApprovalRequested) -> Approvals:
    """Open the approval the run asked for."""
    asked = Approval(
        approval_id=entry.approval_id,
        owner=entry.task_id,
        number=entry.number,
        expires_at=entry.expires_at,
        status=ApprovalPending(),
    )
    return (*approvals, asked)


def decided(approvals: Approvals, entry: ApprovalDecided) -> Approvals:
    """Decide a pending approval, or record what running an approved one did."""
    return tuple(
        _decide(approval, entry) if approval.approval_id == entry.approval_id else approval
        for approval in approvals
    )


def closed_with(approvals: Approvals, owners: Collection[str], status: ApprovalStatus) -> Approvals:
    """Close the pending approvals of the runs that ended undecided."""
    return tuple(
        approval.model_copy(update={"status": status})
        if approval.pending and approval.owner in owners
        else approval
        for approval in approvals
    )


def pending_ids(approvals: Approvals, owner: str) -> tuple[str, ...]:
    """Return owner's pending approvals in the order it asked them."""
    return tuple(a.approval_id for a in approvals if a.pending and a.owner == owner)


def _decide(approval: Approval, entry: ApprovalDecided) -> Approval:
    status = approval.status
    if isinstance(status, ApprovalPending):
        return approval.model_copy(update={"status": _decision(entry)})
    if isinstance(status, ApprovalApproved | ApprovalAmended) and entry.action is not None:
        return approval.model_copy(
            update={"status": status.model_copy(update={"action": entry.action})}
        )
    return approval


def _decision(entry: ApprovalDecided) -> ApprovalStatus:
    """Return the status a decision gives; an approval with a note is the amended form until outcomes name it."""
    match entry.outcome:
        case ApprovalOutcome.APPROVED if entry.feedback:
            return ApprovalAmended(
                decider=entry.decider, change=entry.feedback, action=entry.action
            )
        case ApprovalOutcome.APPROVED:
            return ApprovalApproved(decider=entry.decider, action=entry.action)
        case ApprovalOutcome.DENIED:
            return ApprovalDenied(decider=entry.decider, request=entry.feedback or None)
        case ApprovalOutcome.EXPIRED:
            return ApprovalExpired()
        case ApprovalOutcome.WITHDRAWN:
            return ApprovalWithdrawn(reason=WithdrawReason.AGENT)
        case ApprovalOutcome.CANCELLED:
            return ApprovalCancelled()
