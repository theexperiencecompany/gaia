"""The old approval words and the outcome, decider and action each one now reads as.

The approval vocabulary rewrite applies these to stored records and cards; the entries
migration and its verify apply the card map to an embedded array's cards, so the log reads
the same whichever of the two migrations ran first.
"""

from __future__ import annotations

from collections.abc import Mapping

from shared.py.approvals import ActionResult, ApprovalDecider, ApprovalOutcome

APPROVED, DENIED = ApprovalOutcome.APPROVED, ApprovalOutcome.DENIED
USER, AUTO = ApprovalDecider.USER, ApprovalDecider.AUTO

#: Approval record status -> (outcome, decider). abandoned was written by a Stop or a moved-on reply.
RECORD_STATUSES: dict[str, tuple[ApprovalOutcome | None, ApprovalDecider | None]] = {
    "pending": (None, None),
    "approved": (APPROVED, USER),
    "denied": (DENIED, USER),
    "timeout": (ApprovalOutcome.EXPIRED, None),
    "abandoned": (ApprovalOutcome.CANCELLED, None),
    "auto_approved": (APPROVED, AUTO),
}
#: Card status -> (outcome, decider, action): the record's words plus the ledger's.
CARD_STATUSES: dict[
    str, tuple[ApprovalOutcome | None, ApprovalDecider | None, ActionResult | None]
] = {
    **{status: (outcome, decider, None) for status, (outcome, decider) in RECORD_STATUSES.items()},
    "cancelled": (ApprovalOutcome.CANCELLED, None, None),
    "revoked": (ApprovalOutcome.WITHDRAWN, None, None),
    "executed": (APPROVED, USER, ActionResult.EXECUTED),
    "failed": (APPROVED, USER, ActionResult.FAILED),
    "unknown": (APPROVED, USER, ActionResult.UNKNOWN),
}


def current_card_data(data: Mapping[str, object]) -> dict[str, object]:
    """Return an approval card's payload with an old status as the outcome, decider and action it names.

    A status this map does not know is left for the vocabulary verify to report.
    """
    status = data.get("status")
    if not isinstance(status, str) or status not in CARD_STATUSES:
        return dict(data)
    outcome, decider, action = CARD_STATUSES[status]
    kept = {key: value for key, value in data.items() if key != "status"}
    return {
        **kept,
        "outcome": None if outcome is None else outcome.value,
        "decider": None if decider is None else decider.value,
        "action": None if action is None else action.value,
    }
