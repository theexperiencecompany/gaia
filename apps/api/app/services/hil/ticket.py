"""The wake that turns an approval into a redeem: the one text every continuation carries."""

from app.models.conversation_log_models import ApprovalDecided
from app.models.hil_models import ApprovalLedgerDocument
from app.services.conversation.screen import decided_status
from app.utils.timezone import age_since
from shared.py.approvals import ApprovalStatus


def amend_instruction(row: ApprovalLedgerDocument) -> str:
    """Tell the work to redo a call approved with a change, naming the approval it amends."""
    return (
        f'make the call again with the change applied, as execute(tool_name="{row.tool_name}", '
        f'data=<the changed arguments>, amends="{row.approval_id}")'
    )


def approval_ticket(row: ApprovalLedgerDocument, decision: ApprovalDecided) -> str:
    """Return the ticket for the row decision approved: its id, its age, and the execute call that honors it.

    A yes with a change cannot run as stored, so its ticket hands the change to the work instead.
    """
    age = "unknown age" if row.created_at is None else f"{age_since(row.created_at)} old"
    if decided_status(decision) is ApprovalStatus.APPROVED_WITH_CHANGE:
        return (
            f"APPROVAL_READY {row.approval_id}: the user approved {row.summary} ({age}) "
            f"with a change: {decision.feedback!r}. Do not run the stored call, it lacks the change: "
            f"{amend_instruction(row)}, and continue with its result."
        )
    return (
        f"APPROVAL_READY {row.approval_id}: the user approved {row.summary} "
        f'({age}). Run it now with execute(tool_name="approve", '
        f'data={{"id": "{row.approval_id}"}}) and continue with its result. '
        "If it is no longer needed, say so instead of running it."
    )
