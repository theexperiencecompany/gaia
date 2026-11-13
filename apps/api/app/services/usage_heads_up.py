"""The heads-up before a pro user's monthly allowance runs out."""

from app.services.cost_budget import format_reset_date, monthly_allowance_window
from app.services.outbox.intake import submit
from app.services.outbox.models import NoticeOutcome, ProducerKind, SubjectKind
from app.services.outbox.system_notices import system_notice


async def notify_monthly_heads_up_once(user_id: str) -> None:
    """File the month's heads-up; it is named by the month, so filing it again is a no-op."""
    window, reset_at = await monthly_allowance_window(user_id)
    reset = format_reset_date(reset_at)
    await submit(
        system_notice(
            user_id=user_id,
            producer=ProducerKind.ACCOUNT,
            subject_kind=SubjectKind.ACCOUNT,
            kind="usage_heads_up",
            key=f"{user_id}:{window}",
            label="Your monthly usage allowance",
            outcome=NoticeOutcome.INFO,
            facts=[
                "Most of the user's monthly usage allowance is used.",
                f"When it runs out, chat, workflows and tracked todos pause until {reset}, "
                "when it resets.",
            ],
            display="You have used most of this month's usage allowance. When it runs out, chat, "
            f"workflows and tracked todos pause until {reset}, when it resets.",
        )
    )
