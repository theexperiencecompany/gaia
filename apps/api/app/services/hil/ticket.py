"""The wake that turns an approval into a redeem: the one text every continuation carries."""

from datetime import UTC, datetime

from app.models.hil_models import ApprovalLedgerDocument


def approval_ticket(row: ApprovalLedgerDocument) -> str:
    """Return the ticket for an approved row: its id, its age, and the execute call that honors it."""
    age = "unknown age"
    if row.created_at is not None:
        elapsed_minutes = int((datetime.now(UTC) - row.created_at).total_seconds()) // 60
        hours, minutes = divmod(elapsed_minutes, 60)
        age = f"{hours}h{minutes}m old"
    return (
        f"APPROVAL_READY {row.approval_id}: the user approved {row.summary} "
        f'({age}). Run it now with execute(tool_name="approve", '
        f'data={{"id": "{row.approval_id}"}}) and continue with its result. '
        "If it is no longer needed, say so instead of running it."
    )
