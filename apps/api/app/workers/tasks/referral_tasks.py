"""Apply a resubscribed referrer's banked free months, queued by the billing reducer on activation."""

from arq import Retry

from app.constants.log_tags import LogTag
from app.constants.referrals import APPLY_BANKED_MONTHS_RETRY_DELAY
from app.services.referrals.rewards import apply_banked_months
from app.workers.task_envelope import ArqJobContext
from shared.py.wide_events import log

RETRY_BACKOFF_BASE = 2


async def apply_banked_referral_months_task(ctx: ArqJobContext, user_id: str) -> str:
    """Move the user's billing date forward for every free month they banked while unsubscribed."""
    job_try = ctx.get("job_try", 1)
    log.set(user={"id": user_id}, referral={"operation": "apply_banked_months"})
    try:
        applied = await apply_banked_months(user_id)
    except Exception as e:
        defer = APPLY_BANKED_MONTHS_RETRY_DELAY * RETRY_BACKOFF_BASE ** (job_try - 1)
        log.warning(
            f"{LogTag.PAYMENT} Banked referral months not applied; retrying",
            error=str(e),
            error_type=type(e).__name__,
            defer_seconds=defer.total_seconds(),
        )
        raise Retry(defer=defer) from e
    log.set_ns("referral", months_applied=applied)
    return f"apply_banked_referral_months {applied}"
