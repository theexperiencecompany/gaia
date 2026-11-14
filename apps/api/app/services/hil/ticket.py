"""The wake that turns an approval into a redeem: the one text every continuation carries."""

from app.models.hil_models import ApprovalLedgerDocument
from app.utils.timezone import age_since


def approval_ticket(row: ApprovalLedgerDocument) -> str:
    """Return the ticket for an approved row: its id, its age, and the execute call that honors it."""
    age = "unknown age" if row.created_at is None else f"{age_since(row.created_at)} old"
    return (
        f"APPROVAL_READY {row.approval_id}: the user approved {row.summary} "
        f'({age}). Run it now with execute(tool_name="approve", '
        f'data={{"id": "{row.approval_id}"}}) and continue with its result. '
        "If it is no longer needed, say so instead of running it."
    )
