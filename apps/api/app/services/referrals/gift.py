"""The referred friend's checkout gift: a single-use Dodo discount minted per billing cycle.

Checkout calls this for every session it mints. Codes never stack, so a friend
who joined through a link and has never paid gets whichever is worth more over
the plan's first year: their gift, or the code the caller would have applied.
"""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

from dodopayments import APIConnectionError, APIError, APIStatusError, DodoPayments
from dodopayments.types import Discount

from app.constants.referrals import (
    BASIS_POINTS_WHOLE,
    GIFT_DISCOUNT_USAGE_LIMIT,
    MONTHLY_CHARGES_PER_YEAR,
    YEARLY_CHARGES_PER_YEAR,
    ReferralSource,
)
from app.db.repositories.referrals import referral_repository
from app.db.repositories.subscriptions import subscription_repository
from app.models.payment_models import PlanDuration, PlanResponse
from app.models.referral_models import ReferralDocument, ReferredFriendStatus
from app.services.referrals.availability import referrals_enabled
from app.services.referrals.offer import GiftTerms, ProPlans, gift_terms
from shared.py.analytics.catalog.referrals import GiftMintFailureReason
from shared.py.wide_events import log

HTTP_SERVER_ERROR = 500
_FIRST_YEAR_CHARGES: dict[PlanDuration, int] = {
    PlanDuration.MONTHLY: MONTHLY_CHARGES_PER_YEAR,
    PlanDuration.YEARLY: YEARLY_CHARGES_PER_YEAR,
}


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


def is_refusal(error: APIStatusError) -> bool:
    """Whether Dodo turned the request down (a 4xx), rather than failing to answer it."""
    return error.status_code < HTTP_SERVER_ERROR


async def pending_gift_referral(user_id: str) -> ReferralDocument | None:
    """Return the user's referral when they are owed a checkout gift: invited, never subscribed, referrals on.

    A workflow's visitor is credited to its creator but carries no gift.
    """
    referral = await referral_repository.get(user_id)
    if referral is None or referral.status is not ReferredFriendStatus.JOINED:
        return None
    if referral.source is ReferralSource.WORKFLOW:
        return None
    if await subscription_repository.has_any_for_user(user_id):
        return None
    if not await referrals_enabled(user_id):
        return None
    return referral


def _first_year_value(plan: PlanResponse, basis_points: int, cycles: int | None) -> int:
    """Return what a percentage discount takes off this plan's first-year charges, in minor units."""
    charges = _FIRST_YEAR_CHARGES[plan.duration]
    discounted = charges if cycles is None else min(cycles, charges)
    return plan.amount * basis_points * discounted // BASIS_POINTS_WHOLE


def gift_value(plans: ProPlans, plan: PlanResponse) -> int:
    """Return what the friend's gift takes off this plan in its first year, in minor units."""
    terms = gift_terms(plans, plan.duration)
    return _first_year_value(plan, terms.basis_points, terms.cycles)


def code_value(discount: Discount, plan: PlanResponse) -> int:
    """Return what a promo code takes off this plan in its first year; 0 when it cannot apply to it."""
    now = datetime.now(UTC)
    if discount.restricted_to and plan.dodo_product_id not in discount.restricted_to:
        return 0
    if discount.expires_at is not None and discount.expires_at <= now:
        return 0
    if discount.usage_limit is not None and discount.times_used >= discount.usage_limit:
        return 0
    return _first_year_value(plan, discount.amount, discount.subscription_cycles)


async def _mint(
    client: DodoPayments, referral: ReferralDocument, plan: PlanResponse, terms: GiftTerms
) -> Discount:
    return await asyncio.to_thread(
        client.discounts.create,
        amount=terms.basis_points,
        type="percentage",
        subscription_cycles=terms.cycles,
        usage_limit=GIFT_DISCOUNT_USAGE_LIMIT,
        restricted_to=[plan.dodo_product_id],
        name=f"Referral gift {referral.friend_user_id} {plan.duration.value}",
    )


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

    discount = await _mint(client, referral, plan, gift_terms(plans, plan.duration))
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


async def renew_gift_code(
    client: DodoPayments, referral: ReferralDocument, refused: CheckoutGift, plans: ProPlans
) -> CheckoutGift:
    """Replace a gift code Dodo refused (used up, deleted, or minted for a product since replaced) with a fresh one."""
    plan = plans.monthly if refused.duration is PlanDuration.MONTHLY else plans.yearly
    discount = await _mint(client, referral, plan, gift_terms(plans, plan.duration))
    stored = await referral_repository.replace_gift_code(
        referral.friend_user_id, plan.duration, refused=refused.code, fresh=discount.code
    )
    winner = stored.gift_codes.get(plan.duration) if stored else None
    if winner != discount.code:
        # A concurrent checkout renewed it first; this one must not stay redeemable.
        await asyncio.to_thread(client.discounts.delete, discount.discount_id)
    log.set_ns("referral", gift_renewed=plan.duration.value)
    if winner is None:
        raise RuntimeError(f"referral {referral.friend_user_id} vanished while renewing its gift")
    return CheckoutGift(code=winner, duration=plan.duration, referrer_id=referral.referrer_user_id)
