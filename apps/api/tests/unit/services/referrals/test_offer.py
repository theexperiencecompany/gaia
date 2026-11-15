"""The friend's gift priced from the catalogue: monthly halves two charges, yearly takes one month off."""

import pytest

from app.constants.referrals import PRO_PLAN_MISSING_MESSAGE
from app.models.payment_models import PlanDuration
from app.services.referrals.offer import (
    GiftTerms,
    ProPlans,
    build_offer,
    gift_terms,
    yearly_discount_basis_points,
)
from app.utils.errors import AppError
from tests.factories import make_plan, make_pro_plans


def test_the_offer_reads_off_the_live_prices() -> None:
    offer = build_offer(make_pro_plans())

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
    offer = build_offer(make_pro_plans(monthly, yearly))
    monthly_gift = offer.intro_cycles * (offer.monthly_regular_minor - offer.monthly_intro_minor)

    assert offer.yearly_discount_minor <= monthly_gift
    assert (
        yearly_discount_basis_points(make_pro_plans(monthly, yearly)) * yearly <= monthly * 10_000
    )


def test_dodo_gets_half_off_two_cycles_monthly_and_one_cycle_yearly() -> None:
    plans = make_pro_plans()

    assert gift_terms(plans, PlanDuration.MONTHLY) == GiftTerms(basis_points=5000, cycles=2)
    assert gift_terms(plans, PlanDuration.YEARLY) == GiftTerms(basis_points=1111, cycles=1)


def test_a_product_resolves_to_its_plan_and_anything_else_to_none() -> None:
    plans = make_pro_plans()

    assert plans.for_product("pdt_yearly") is plans.yearly
    assert plans.for_product("pdt_max_monthly") is None


def test_a_free_catalogue_refuses_to_price_a_gift() -> None:
    with pytest.raises(AppError):
        make_pro_plans(monthly=0)


def test_a_mixed_currency_catalogue_refuses_with_both_currencies_named() -> None:
    with pytest.raises(AppError) as refused:
        build_offer(
            ProPlans(
                monthly=make_plan(PlanDuration.MONTHLY, 3000, "USD"),
                yearly=make_plan(PlanDuration.YEARLY, 27000, "EUR"),
            )
        )

    assert refused.value.status_code == 500
    assert refused.value.to_dict() == {
        "message": PRO_PLAN_MISSING_MESSAGE,
        "why": "the monthly and yearly Pro plans are priced in different currencies",
        "monthly": "USD",
        "yearly": "EUR",
    }
