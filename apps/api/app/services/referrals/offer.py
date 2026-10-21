"""The friend's gift, priced from the live Pro catalogue: what the copy says and what Dodo discounts."""

from dataclasses import dataclass

from app.constants.referrals import (
    BASIS_POINTS_WHOLE,
    FRIEND_MONTHLY_DISCOUNT_BASIS_POINTS,
    FRIEND_MONTHLY_INTRO_CYCLES,
    FRIEND_YEARLY_DISCOUNT_CYCLES,
    PRO_PLAN_MISSING_MESSAGE,
    PRO_PLAN_MISSING_WHY,
)
from app.models.payment_models import PlanDuration, PlanResponse
from app.schemas.referrals import ReferralOffer
from app.utils.errors import AppError


@dataclass(frozen=True)
class ProPlans:
    """The purchasable Pro plan for each billing cycle."""

    monthly: PlanResponse
    yearly: PlanResponse

    def __post_init__(self) -> None:
        if self.monthly.amount <= 0 or self.yearly.amount <= 0:
            raise AppError(
                message=PRO_PLAN_MISSING_MESSAGE,
                why=PRO_PLAN_MISSING_WHY,
                meta={"monthly": self.monthly.amount, "yearly": self.yearly.amount},
            )

    def for_product(self, product_id: str) -> PlanResponse | None:
        """Return the Pro plan this Dodo product is, or None for any other product."""
        return next(
            (plan for plan in (self.monthly, self.yearly) if plan.dodo_product_id == product_id),
            None,
        )


@dataclass(frozen=True)
class GiftTerms:
    """One Dodo percentage discount: how much, and for how many billing cycles."""

    basis_points: int
    cycles: int


def _apply_basis_points(amount_minor: int, basis_points: int) -> int:
    return round(amount_minor * basis_points / BASIS_POINTS_WHOLE)


def yearly_discount_basis_points(plans: ProPlans) -> int:
    """Return the percentage, in basis points, that takes one monthly price off a year.

    Floored, so the yearly gift is never worth more than the monthly one.
    """
    return plans.monthly.amount * BASIS_POINTS_WHOLE // plans.yearly.amount


def gift_terms(plans: ProPlans, duration: PlanDuration) -> GiftTerms:
    """Return the discount a friend's code carries on this billing cycle."""
    if duration is PlanDuration.MONTHLY:
        return GiftTerms(FRIEND_MONTHLY_DISCOUNT_BASIS_POINTS, FRIEND_MONTHLY_INTRO_CYCLES)
    return GiftTerms(yearly_discount_basis_points(plans), FRIEND_YEARLY_DISCOUNT_CYCLES)


def build_offer(plans: ProPlans) -> ReferralOffer:
    """Price the gift in the catalogue's currency, the same way Dodo will discount it."""
    if plans.monthly.currency != plans.yearly.currency:
        raise AppError(
            message=PRO_PLAN_MISSING_MESSAGE,
            why="the monthly and yearly Pro plans are priced in different currencies",
            meta={"monthly": plans.monthly.currency, "yearly": plans.yearly.currency},
        )
    monthly = plans.monthly.amount
    yearly = plans.yearly.amount
    return ReferralOffer(
        currency=plans.monthly.currency,
        monthly_regular_minor=monthly,
        monthly_intro_minor=monthly
        - _apply_basis_points(monthly, FRIEND_MONTHLY_DISCOUNT_BASIS_POINTS),
        intro_cycles=FRIEND_MONTHLY_INTRO_CYCLES,
        yearly_regular_minor=yearly,
        yearly_discount_minor=_apply_basis_points(yearly, yearly_discount_basis_points(plans)),
    )
