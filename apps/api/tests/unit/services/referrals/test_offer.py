"""The friend's gift priced from the catalogue: monthly halves two charges, yearly takes one month off."""

from datetime import UTC, datetime

import pytest

from app.models.payment_models import PlanDuration, PlanResponse, PlanTier
from app.services.referrals.offer import (
    GiftTerms,
    ProPlans,
    build_offer,
    gift_terms,
    yearly_discount_basis_points,
)
from app.utils.errors import AppError

NOW = datetime(2026, 10, 14, tzinfo=UTC)


def _plan(duration: PlanDuration, amount: int, currency: str = "USD") -> PlanResponse:
    return PlanResponse(
        id=f"plan_{duration.value}",
        dodo_product_id=f"pdt_{duration.value}",
        name="Pro",
        plan_type=PlanTier.PRO,
        amount=amount,
        currency=currency,
        duration=duration,
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


def _plans(monthly: int = 3000, yearly: int = 27000, currency: str = "USD") -> ProPlans:
    return ProPlans(
        monthly=_plan(PlanDuration.MONTHLY, monthly, currency),
        yearly=_plan(PlanDuration.YEARLY, yearly, currency),
    )


def test_the_offer_reads_off_the_live_prices() -> None:
    offer = build_offer(_plans())

    assert offer.model_dump() == {
        "currency": "USD",
        "monthly_regular_minor": 3000,
        "monthly_intro_minor": 1500,
        "intro_cycles": 2,
        "yearly_regular_minor": 27000,
        "yearly_discount_minor": 3000,
    }


@pytest.mark.parametrize(
    ("monthly", "yearly"), [(3000, 27000), (1500, 18000), (999, 9990), (3000, 36000)]
)
def test_the_yearly_gift_is_never_worth_more_than_the_monthly_one(
    monthly: int, yearly: int
) -> None:
    offer = build_offer(_plans(monthly, yearly))
    monthly_gift = offer.intro_cycles * (offer.monthly_regular_minor - offer.monthly_intro_minor)

    assert offer.yearly_discount_minor <= monthly_gift
    assert yearly_discount_basis_points(_plans(monthly, yearly)) * yearly <= monthly * 10_000


def test_dodo_gets_half_off_two_cycles_monthly_and_one_cycle_yearly() -> None:
    plans = _plans()

    assert gift_terms(plans, PlanDuration.MONTHLY) == GiftTerms(basis_points=5000, cycles=2)
    assert gift_terms(plans, PlanDuration.YEARLY) == GiftTerms(basis_points=1111, cycles=1)


def test_a_product_resolves_to_its_plan_and_anything_else_to_none() -> None:
    plans = _plans()

    assert plans.for_product("pdt_yearly") is plans.yearly
    assert plans.for_product("pdt_max_monthly") is None


def test_a_free_or_mixed_currency_catalogue_refuses_to_price_a_gift() -> None:
    with pytest.raises(AppError):
        _plans(monthly=0)
    with pytest.raises(AppError):
        build_offer(
            ProPlans(
                monthly=_plan(PlanDuration.MONTHLY, 3000, "USD"),
                yearly=_plan(PlanDuration.YEARLY, 27000, "EUR"),
            )
        )
