"""The friend's checkout gift: who is owed one, and minting exactly one live code per billing cycle."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from dodopayments import APIConnectionError, APIError, APIResponseValidationError, APIStatusError
from dodopayments.types import Discount
import httpx
import pytest
import time_machine

from app.models.payment_models import PlanDuration
from app.models.referral_models import ReferralDocument, ReferredFriendStatus
from app.services.referrals.gift import (
    CheckoutGift,
    code_value,
    gift_code_for_checkout,
    gift_mint_failure_reason,
    gift_value,
    is_refusal,
    pending_gift_referral,
    renew_gift_code,
)
from shared.py.analytics.catalog.referrals import GiftMintFailureReason
from tests.factories import make_pro_plans
from tests.helpers import captured_wide_event, referrals_off_for

NOW = datetime(2026, 10, 14, tzinfo=UTC)
GIFT = "app.services.referrals.gift"
FRIEND_ID = "65f0c0ffee00000000000f01"
DODO_REQUEST = httpx.Request("POST", "https://dodo.test/discounts")


def _referral(
    status: ReferredFriendStatus = ReferredFriendStatus.JOINED,
    gift_codes: dict[PlanDuration, str] | None = None,
) -> ReferralDocument:
    return ReferralDocument(
        friend_user_id=FRIEND_ID,
        referrer_user_id="referrer-1",
        code="aryan-k7f2",
        status=status,
        joined_at=NOW,
        gift_codes=gift_codes or {},
        created_at=NOW,
        updated_at=NOW,
    )


def _dodo(code: str = "GIFT-NEW") -> MagicMock:
    client = MagicMock()
    client.discounts.create.return_value = SimpleNamespace(code=code, discount_id="dsc_new")
    return client


def _answered(status: int) -> APIStatusError:
    return APIStatusError(
        "dodo answered", response=httpx.Response(status, request=DODO_REQUEST), body=None
    )


class TestHowDodoFailed:
    @pytest.mark.parametrize(
        ("error", "reason"),
        [
            (APIConnectionError(request=DODO_REQUEST), "provider_unreachable"),
            (_answered(422), "provider_rejected"),
            (
                APIResponseValidationError(httpx.Response(200, request=DODO_REQUEST), body=None),
                "provider_invalid_response",
            ),
        ],
        ids=["unreachable", "rejected", "unparseable-answer"],
    )
    def test_a_failed_mint_is_counted_by_how_dodo_failed(
        self, error: APIError, reason: GiftMintFailureReason
    ) -> None:
        assert gift_mint_failure_reason(error) == reason

    @pytest.mark.parametrize(
        ("status", "refused"), [(422, True), (500, False)], ids=["4xx", "first-5xx"]
    )
    def test_only_a_4xx_is_dodo_refusing_the_request(self, status: int, refused: bool) -> None:
        assert is_refusal(_answered(status)) is refused


class TestPendingGiftReferral:
    async def test_a_joined_friend_who_never_subscribed_is_owed_the_gift(self) -> None:
        referral = _referral()
        with (
            patch(f"{GIFT}.referral_repository.get", AsyncMock(return_value=referral)) as get,
            patch(
                f"{GIFT}.subscription_repository.has_any_for_user", AsyncMock(return_value=False)
            ) as has_any,
        ):
            assert await pending_gift_referral(FRIEND_ID) is referral

        get.assert_awaited_once_with(FRIEND_ID)
        has_any.assert_awaited_once_with(FRIEND_ID)

    @pytest.mark.parametrize(
        ("referral", "ever_subscribed"),
        [
            (None, False),
            (_referral(status=ReferredFriendStatus.PAID), False),
            (_referral(), True),
        ],
        ids=["never-referred", "already-paid", "subscribed-before"],
    )
    async def test_anyone_else_is_owed_nothing(
        self, referral: ReferralDocument | None, ever_subscribed: bool
    ) -> None:
        with (
            patch(f"{GIFT}.referral_repository.get", AsyncMock(return_value=referral)),
            patch(
                f"{GIFT}.subscription_repository.has_any_for_user",
                AsyncMock(return_value=ever_subscribed),
            ),
        ):
            assert await pending_gift_referral(FRIEND_ID) is None

    async def test_with_referrals_off_for_the_friend_they_are_owed_no_new_gift(self) -> None:
        with (
            referrals_off_for(FRIEND_ID),
            patch(f"{GIFT}.referral_repository.get", AsyncMock(return_value=_referral())),
            patch(
                f"{GIFT}.subscription_repository.has_any_for_user", AsyncMock(return_value=False)
            ),
        ):
            assert await pending_gift_referral(FRIEND_ID) is None


class TestGiftCodeForCheckout:
    async def test_a_first_checkout_mints_a_single_use_code_restricted_to_the_product(
        self,
    ) -> None:
        client, referral = _dodo(), _referral()
        stored = _referral(gift_codes={PlanDuration.MONTHLY: "GIFT-NEW"})
        with patch(
            f"{GIFT}.referral_repository.set_gift_code", AsyncMock(return_value=stored)
        ) as set_code:
            async with captured_wide_event() as event:
                code = await gift_code_for_checkout(
                    client, referral, "pdt_monthly", make_pro_plans()
                )

        assert code == CheckoutGift(
            code="GIFT-NEW", duration=PlanDuration.MONTHLY, referrer_id="referrer-1"
        )
        client.discounts.create.assert_called_once_with(
            amount=5000,
            type="percentage",
            subscription_cycles=2,
            usage_limit=1,
            restricted_to=["pdt_monthly"],
            name=f"Referral gift {FRIEND_ID} monthly",
        )
        set_code.assert_awaited_once_with(FRIEND_ID, PlanDuration.MONTHLY, "GIFT-NEW")
        client.discounts.delete.assert_not_called()
        assert event["referral"]["gift_minted"] == "monthly"

    async def test_the_yearly_gift_takes_one_month_off_one_cycle(self) -> None:
        client = _dodo()
        stored = _referral(gift_codes={PlanDuration.YEARLY: "GIFT-NEW"})
        with patch(f"{GIFT}.referral_repository.set_gift_code", AsyncMock(return_value=stored)):
            assert await gift_code_for_checkout(
                client, _referral(), "pdt_yearly", make_pro_plans()
            ) == CheckoutGift(
                code="GIFT-NEW", duration=PlanDuration.YEARLY, referrer_id="referrer-1"
            )

        kwargs = client.discounts.create.call_args.kwargs
        assert (kwargs["amount"], kwargs["subscription_cycles"]) == (1111, 1)
        assert kwargs["name"] == f"Referral gift {FRIEND_ID} yearly"

    async def test_a_code_already_minted_for_the_cycle_is_reused(self) -> None:
        client = _dodo()
        referral = _referral(gift_codes={PlanDuration.MONTHLY: "GIFT-OLD"})

        assert await gift_code_for_checkout(
            client, referral, "pdt_monthly", make_pro_plans()
        ) == CheckoutGift(code="GIFT-OLD", duration=PlanDuration.MONTHLY, referrer_id="referrer-1")
        client.discounts.create.assert_not_called()

    async def test_a_product_off_the_pro_plans_gets_no_gift(self) -> None:
        client = _dodo()

        assert (
            await gift_code_for_checkout(client, _referral(), "pdt_max", make_pro_plans()) is None
        )
        client.discounts.create.assert_not_called()

    async def test_losing_a_mint_race_returns_the_winner_and_deletes_the_loser(self) -> None:
        client = _dodo("GIFT-LOSER")
        winner = _referral(gift_codes={PlanDuration.MONTHLY: "GIFT-WINNER"})
        with patch(f"{GIFT}.referral_repository.set_gift_code", AsyncMock(return_value=winner)):
            code = await gift_code_for_checkout(
                client, _referral(), "pdt_monthly", make_pro_plans()
            )

        assert code == CheckoutGift(
            code="GIFT-WINNER", duration=PlanDuration.MONTHLY, referrer_id="referrer-1"
        )
        client.discounts.delete.assert_called_once_with("dsc_new")

    async def test_a_referral_gone_mid_mint_returns_nothing_and_leaves_no_live_code(
        self,
    ) -> None:
        client = _dodo()
        with patch(f"{GIFT}.referral_repository.set_gift_code", AsyncMock(return_value=None)):
            assert (
                await gift_code_for_checkout(client, _referral(), "pdt_monthly", make_pro_plans())
                is None
            )

        client.discounts.delete.assert_called_once_with("dsc_new")


class TestRenewGiftCode:
    REFUSED = CheckoutGift(code="GIFT-OLD", duration=PlanDuration.MONTHLY, referrer_id="referrer-1")

    @pytest.mark.parametrize(
        ("duration", "product", "basis_points", "cycles"),
        [
            (PlanDuration.MONTHLY, "pdt_monthly", 5000, 2),
            (PlanDuration.YEARLY, "pdt_yearly", 1111, 1),
        ],
        ids=["monthly", "yearly"],
    )
    async def test_a_refused_code_is_swapped_for_a_fresh_one_on_its_cycles_terms(
        self, duration: PlanDuration, product: str, basis_points: int, cycles: int
    ) -> None:
        client = _dodo("GIFT-FRESH")
        refused = CheckoutGift(code="GIFT-OLD", duration=duration, referrer_id="referrer-1")
        stored = _referral(gift_codes={duration: "GIFT-FRESH"})
        with patch(
            f"{GIFT}.referral_repository.replace_gift_code", AsyncMock(return_value=stored)
        ) as replace:
            async with captured_wide_event() as event:
                renewed = await renew_gift_code(client, _referral(), refused, make_pro_plans())

        assert renewed == CheckoutGift(
            code="GIFT-FRESH", duration=duration, referrer_id="referrer-1"
        )
        replace.assert_awaited_once_with(
            FRIEND_ID, duration, refused="GIFT-OLD", fresh="GIFT-FRESH"
        )
        client.discounts.create.assert_called_once_with(
            amount=basis_points,
            type="percentage",
            subscription_cycles=cycles,
            usage_limit=1,
            restricted_to=[product],
            name=f"Referral gift {FRIEND_ID} {duration.value}",
        )
        client.discounts.delete.assert_not_called()
        assert event["referral"] == {"gift_renewed": duration.value}

    async def test_a_checkout_that_renewed_first_keeps_its_code_and_ours_is_deleted(self) -> None:
        client = _dodo("GIFT-LOSER")
        winner = _referral(gift_codes={PlanDuration.MONTHLY: "GIFT-WINNER"})
        with patch(f"{GIFT}.referral_repository.replace_gift_code", AsyncMock(return_value=winner)):
            renewed = await renew_gift_code(client, _referral(), self.REFUSED, make_pro_plans())

        assert renewed.code == "GIFT-WINNER"
        client.discounts.delete.assert_called_once_with("dsc_new")

    async def test_a_referral_gone_mid_renewal_fails_naming_it_and_leaves_no_live_code(
        self,
    ) -> None:
        client = _dodo("GIFT-FRESH")
        with (
            patch(f"{GIFT}.referral_repository.replace_gift_code", AsyncMock(return_value=None)),
            pytest.raises(RuntimeError, match=FRIEND_ID),
        ):
            await renew_gift_code(client, _referral(), self.REFUSED, make_pro_plans())

        client.discounts.delete.assert_called_once_with("dsc_new")


def _discount(**overrides: object) -> Discount:
    fields: dict[str, object] = {
        "amount": 2000,
        "business_id": "biz_1",
        "code": "PROMO",
        "created_at": NOW,
        "discount_id": "dsc_promo",
        "restricted_to": [],
        "times_used": 0,
        "type": "percentage",
        "subscription_cycles": None,
    }
    return Discount.model_validate({**fields, **overrides})


class TestWhichDiscountIsWorthMore:
    PLANS = make_pro_plans(monthly=3000, yearly=27000)

    def test_the_gift_is_worth_one_monthly_price_on_either_cycle(self) -> None:
        assert gift_value(self.PLANS, self.PLANS.monthly) == 3000
        assert gift_value(self.PLANS, self.PLANS.yearly) == 2999

    @pytest.mark.parametrize(
        ("overrides", "value"),
        [
            ({"amount": 2000, "subscription_cycles": None}, 7200),
            ({"amount": 2000, "subscription_cycles": 3}, 1800),
            ({"amount": 5000, "subscription_cycles": 24}, 18000),
            ({"restricted_to": ["pdt_yearly"]}, 0),
            ({"expires_at": datetime(2026, 1, 1, tzinfo=UTC)}, 0),
            ({"expires_at": NOW}, 0),
            ({"usage_limit": 5, "times_used": 5}, 0),
        ],
        ids=[
            "forever",
            "three-months",
            "capped-at-a-year",
            "other-product",
            "expired",
            "expiring-now",
            "used-up",
        ],
    )
    def test_a_code_is_valued_over_the_monthly_plans_first_year(
        self, overrides: dict[str, object], value: int
    ) -> None:
        with time_machine.travel(NOW, tick=False):
            assert code_value(_discount(**overrides), self.PLANS.monthly) == value

    def test_a_forever_code_on_the_yearly_plan_counts_one_charge(self) -> None:
        assert code_value(_discount(amount=1000), self.PLANS.yearly) == 2700
