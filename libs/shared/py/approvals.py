"""Approval domain types: how an approval ended, who decided it, and what the approved action did.

The persisted conversation log and the analytics catalog both read these; the catalog imports them from here.
"""

from enum import StrEnum
from typing import Literal


class ApprovalOutcome(StrEnum):
    """How an approval ended; an approval with no outcome is still pending."""

    APPROVED = "approved"
    DENIED = "denied"
    # Nobody answered before it ran out of time.
    EXPIRED = "expired"
    # The user stopped the work or moved on before deciding.
    CANCELLED = "cancelled"
    # GAIA closed the request itself: the agent withdrew it, or the run it held is gone.
    WITHDRAWN = "withdrawn"


class ApprovalDecider(StrEnum):
    """Who approved or denied: the user, or auto mode's intent judge."""

    USER = "user"
    AUTO = "auto"


class ActionResult(StrEnum):
    """What happened to an approved action; none until it starts."""

    EXECUTING = "executing"
    EXECUTED = "executed"
    FAILED = "failed"
    # The run died mid-call, so whether the action landed cannot be known; never retried.
    UNKNOWN = "unknown"


#: The outcomes a user or auto mode decides; the rest the system assigns.
DecidedOutcome = Literal[ApprovalOutcome.APPROVED, ApprovalOutcome.DENIED]
DECIDED_OUTCOMES: frozenset[ApprovalOutcome] = frozenset(
    {ApprovalOutcome.APPROVED, ApprovalOutcome.DENIED}
)
#: How an approval ends when nobody decided it.
UndecidedOutcome = Literal[
    ApprovalOutcome.EXPIRED, ApprovalOutcome.CANCELLED, ApprovalOutcome.WITHDRAWN
]
