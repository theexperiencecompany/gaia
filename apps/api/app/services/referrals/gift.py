"""The referred friend's checkout gift: a single-use Dodo discount minted per billing cycle.

Checkout calls this for every session it mints. A friend who joined through a
link and has never paid gets their gift code instead of whatever code the
caller would have applied, because codes never stack and the referral wins.
"""

import asyncio

from dodopayments import DodoPayments

from app.constants.referrals import GIFT_DISCOUNT_USAGE_LIMIT
from app.db.repositories.referrals import referral_repository
from app.db.repositories.subscriptions import subscription_repository
from app.models.referral_models import ReferralDocument, ReferredFriendStatus
from app.services.referrals.offer import ProPlans, gift_terms
from shared.py.wide_events import log


async def pending_gift_referral(user_id: str) -> ReferralDocument | None:
    """Return the user's referral when they are owed a checkout gift: referred, and never subscribed."""
    referral = await referral_repository.get(user_id)
    if referral is None or referral.status is not ReferredFriendStatus.JOINED:
        return None
    if await subscription_repository.has_any_for_user(user_id):
        return None
    return referral


async def gift_code_for_checkout(
    client: DodoPayments, referral: ReferralDocument, product_id: str, plans: ProPlans
) -> str | None:
    """Return the friend's gift code for this product, minting it on first checkout; None off the Pro plans."""
    plan = plans.for_product(product_id)
    if plan is None:
        return None
    existing = referral.gift_codes.get(plan.duration)
    if existing:
        return existing

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
    return winner
