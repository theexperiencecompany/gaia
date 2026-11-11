"""The referred friend's checkout gift: a single-use Dodo discount minted per billing cycle.

Checkout calls this for every session it mints. A friend who joined through a
link and has never paid gets their gift code instead of whatever code the
caller would have applied, because codes never stack and the referral wins.
"""

import asyncio
from dataclasses import dataclass

from dodopayments import APIConnectionError, APIError, APIStatusError, DodoPayments

from app.constants.referrals import GIFT_DISCOUNT_USAGE_LIMIT
from app.db.repositories.referrals import referral_repository
from app.db.repositories.subscriptions import subscription_repository
from app.models.payment_models import PlanDuration
from app.models.referral_models import ReferralDocument, ReferredFriendStatus
from app.services.referrals.availability import referrals_enabled
from app.services.referrals.offer import ProPlans, gift_terms
from shared.py.analytics.catalog.referrals import GiftMintFailureReason
from shared.py.wide_events import log


@dataclass(frozen=True)
class CheckoutGift:
    """A referred friend's gift for one checkout: the Dodo code, the plan it discounts, who referred them."""

    code: str
    duration: PlanDuration
    referrer_id: str


def gift_mint_failure_reason(error: APIError) -> GiftMintFailureReason:
    """Classify why Dodo would not mint a gift, for the event that counts failed mints."""
    if isinstance(error, APIConnectionError):
        return "provider_unreachable"
    if isinstance(error, APIStatusError):
        return "provider_rejected"
    return "provider_invalid_response"


async def pending_gift_referral(user_id: str) -> ReferralDocument | None:
    """Return the user's referral when they are owed a checkout gift: referred, never subscribed, referrals on."""
    referral = await referral_repository.get(user_id)
    if referral is None or referral.status is not ReferredFriendStatus.JOINED:
        return None
    if await subscription_repository.has_any_for_user(user_id):
        return None
    if not await referrals_enabled(user_id):
        return None
    return referral


async def gift_code_for_checkout(
    client: DodoPayments, referral: ReferralDocument, product_id: str, plans: ProPlans
) -> CheckoutGift | None:
    """Return the friend's gift for this product, minting its code on first checkout; None off the Pro plans."""
    plan = plans.for_product(product_id)
    if plan is None:
        return None
    existing = referral.gift_codes.get(plan.duration)
    if existing:
        return CheckoutGift(
            code=existing, duration=plan.duration, referrer_id=referral.referrer_user_id
        )

    terms = gift_terms(plans, plan.duration)
    discount = await asyncio.to_thread(
        client.discounts.create,
        amount=terms.basis_points,
        type="percentage",
        subscription_cycles=terms.cycles,
        usage_limit=GIFT_DISCOUNT_USAGE_LIMIT,
        restricted_to=[product_id],
        name=f"Referral gift {referral.friend_user_id} {plan.duration.value}",
    )
    stored = await referral_repository.set_gift_code(
        referral.friend_user_id, plan.duration, discount.code
    )
    winner = stored.gift_codes.get(plan.duration) if stored else None
    if winner != discount.code:
        # A concurrent checkout stored its code first; this one must not stay redeemable.
        await asyncio.to_thread(client.discounts.delete, discount.discount_id)
    log.set_ns("referral", gift_minted=plan.duration.value)
    if winner is None:
        return None
    return CheckoutGift(code=winner, duration=plan.duration, referrer_id=referral.referrer_user_id)
