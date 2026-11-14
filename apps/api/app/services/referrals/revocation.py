"""Taking a free month back when the friend's first payment is refunded or disputed.

The webhook records the request and queues the referrer's settle job, which
takes the month back under the referrer's lock: a month on the bill moves the
bill back while that month has not begun yet, and a banked or undelivered
month is simply dropped.
"""

from datetime import UTC, datetime

import pendulum

from app.constants.referrals import REWARD_MONTHS_PER_FRIEND
from app.db.repositories.referrals import referral_repository
from app.models.referral_models import (
    ReferralDocument,
    ReferralRevokeReason,
    ReferralRewardState,
    ReferralUpdate,
)
from app.services.analytics_service import capture
from app.services.referrals.billing_date import live_billing_date, set_billing_date
from app.services.referrals.settlement_queue import queue_settlement
from app.utils.timezone import as_utc
from shared.py.analytics import Dedupe, UserId
from shared.py.analytics.catalog.referrals import ReferralRewardRevoked
from shared.py.wide_events import log


async def request_reward_revocation(payment_id: str, reason: ReferralRevokeReason) -> None:
    """Ask for the month a friend's first payment earned back, and queue its referrer's settle job."""
    referral = await referral_repository.request_revocation(
        payment_id, reason=reason, at=datetime.now(UTC)
    )
    if referral is None:
        # A redelivered refund re-queues a revocation the last job did not finish.
        referral = await referral_repository.get_by_payment_id(payment_id)
        if referral is None or not referral.revocation_owed:
            log.set_ns("referral", revoke="nothing_to_revoke")
            return
    log.set_ns("referral", revoke=reason.value, referrer_id=referral.referrer_user_id)
    await queue_settlement(referral.referrer_user_id, friend_user_id=referral.friend_user_id)


async def reclaim_reward(referral: ReferralDocument, dodo_subscription_id: str | None) -> None:
    """Take the referral's month back from wherever it went, then record the revocation."""
    prior, reason, asked_at = (
        referral.reward_state,
        referral.revoke_reason,
        as_utc(referral.revoked_at),
    )
    if prior is None or reason is None or asked_at is None:
        raise RuntimeError(f"referral {referral.friend_user_id} has no revocation to settle")
    reclaimed = await _take_month_back(referral, dodo_subscription_id)
    await referral_repository.update(
        referral.friend_user_id, ReferralUpdate(reward_state=ReferralRewardState.REVOKED)
    )
    log.set_ns("referral", revoked=reason.value, month_reclaimed=reclaimed)
    capture(
        UserId(referral.referrer_user_id),
        ReferralRewardRevoked(
            friend_id=referral.friend_user_id,
            reason=reason.value,
            prior_state=prior.value,
            reclaimed=reclaimed,
        ),
        dedupe=Dedupe(key=referral.friend_user_id, occurred_at=asked_at),
    )


async def _take_month_back(referral: ReferralDocument, dodo_subscription_id: str | None) -> bool:
    """Undo the month; False when the referrer keeps it, being already inside it or on a bill since ended."""
    if referral.reward_state in (ReferralRewardState.BANKED, ReferralRewardState.METERED):
        return True
    if dodo_subscription_id is None or referral.reward_subscription_id != dodo_subscription_id:
        # Never moved a bill, or moved one that has since ended with the month on it.
        return referral.reward_state is ReferralRewardState.PENDING
    if referral.reward_state is ReferralRewardState.PENDING and not await _grant_landed(
        referral, dodo_subscription_id
    ):
        return True
    return await _move_bill_back(referral, dodo_subscription_id)


async def _grant_landed(referral: ReferralDocument, dodo_subscription_id: str) -> bool:
    """Whether a pending month's move reached Dodo before its job was cut short."""
    target = as_utc(referral.reward_target_billing_date)
    return target is not None and await live_billing_date(dodo_subscription_id) >= target


async def _move_bill_back(referral: ReferralDocument, dodo_subscription_id: str) -> bool:
    """Move the bill back a month, to a date pinned so a retry lands on it again; False once the month began."""
    live = await live_billing_date(dodo_subscription_id)
    pinned = await referral_repository.pin_revoke_target(
        referral.friend_user_id,
        pendulum.instance(live).subtract(months=REWARD_MONTHS_PER_FRIEND),
    )
    target = as_utc(pinned.revoke_target_billing_date if pinned else None)
    if target is None:
        raise RuntimeError(f"referral {referral.friend_user_id} vanished mid-revocation")
    if live <= target:
        log.set_ns("referral", billing_date_already_moved_back=True)
        return True
    if target <= datetime.now(UTC):
        return False
    await set_billing_date(
        dodo_subscription_id,
        target,
        referrer_user_id=referral.referrer_user_id,
        audit="referral free month taken back",
    )
    return True
