"""The one-time heads-up before a pro user's monthly allowance runs out."""

from app.constants.cache import COST_BUDGET_NEAR_NOTIFIED_KEY
from app.constants.llm import MONTHLY_BUDGET_TTL_SECONDS
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.services.cost_budget import format_reset_date, monthly_allowance_window
from app.services.outbox.intake import submit
from app.services.outbox.models import NoticeOutcome, ProducerKind, SubjectKind
from app.services.outbox.system_notices import system_notice
from shared.py.wide_events import log


async def notify_monthly_heads_up_once(user_id: str) -> None:
    """File the heads-up the first time a month enters the heads-up band (Redis SET NX gate)."""
    try:
        client = redis_cache.redis
        if client is None:
            return
        window, reset_at = await monthly_allowance_window(user_id)
        key = COST_BUDGET_NEAR_NOTIFIED_KEY.format(user_id=user_id, window=window)
        if not await client.set(key, "1", nx=True, ex=MONTHLY_BUDGET_TTL_SECONDS):
            return
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
                    "When it runs out, chat, workflows and tracked todos pause until "
                    f"{reset}, when it resets.",
                ],
            )
        )
    except Exception as e:
        log.warning(
            f"{LogTag.AGENT} Monthly heads-up notice failed",
            error=str(e),
            error_type=type(e).__name__,
        )
