"""Referral jobs: settling a referrer's rewards, and the sweep that finds months left pending."""

from datetime import UTC, datetime

from arq import Retry

from app.constants.log_tags import LogTag
from app.constants.referrals import (
    SETTLE_REWARDS_RETRY_DELAY,
    SETTLE_SWEEP_GRACE,
    SETTLE_SWEEP_MAX_REFERRALS_PER_RUN,
)
from app.db.repositories.referrals import referral_repository
from app.services.referrals.rewards import settle_rewards
from app.services.referrals.settlement_queue import queue_settlement
from app.workers.task_envelope import ArqJobContext
from shared.py.wide_events import log

RETRY_BACKOFF_BASE = 2


async def settle_referral_rewards_task(ctx: ArqJobContext, referrer_user_id: str) -> str:
    """Grant, bank, apply or take back every free month the referrer is owed; retried with backoff."""
    job_try = ctx.get("job_try", 1)
    log.set(user={"id": referrer_user_id}, referral={"operation": "settle_rewards"})
    try:
        settled = await settle_rewards(referrer_user_id)
    except Exception as e:
        defer = SETTLE_REWARDS_RETRY_DELAY * RETRY_BACKOFF_BASE ** (job_try - 1)
        log.warning(
            f"{LogTag.PAYMENT} Referral rewards not settled; retrying",
            error=str(e),
            error_type=type(e).__name__,
            defer_seconds=defer.total_seconds(),
        )
        raise Retry(defer=defer) from e
    log.set_ns("referral", rewards_settled=len(settled))
    return f"settle_referral_rewards {len(settled)}"


async def sweep_unsettled_referral_rewards(ctx: ArqJobContext) -> str:  # noqa: ARG001 -- ARQ injects ctx positionally into every registered task
    """Queue a settle job for every referrer whose friend's month is still pending past its own job's window.

    The safety net for a settle job that never got queued or ran out of
    retries; the per-referrer job id collapses onto one already waiting.
    """
    referrers = await referral_repository.list_referrers_unsettled(
        datetime.now(UTC) - SETTLE_SWEEP_GRACE, limit=SETTLE_SWEEP_MAX_REFERRALS_PER_RUN
    )
    for referrer_user_id in referrers:
        await queue_settlement(referrer_user_id)
    log.set(referral={"operation": "settle_sweep", "referrers_queued": len(referrers)})
    return f"sweep_unsettled_referral_rewards queued {len(referrers)}"
