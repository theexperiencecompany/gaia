"""The friend's checkout gift: who is owed one, and minting exactly one live code per billing cycle."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.payment_models import PlanDuration
from app.models.referral_models import ReferralDocument, ReferredFriendStatus
from app.services.referrals.gift import CheckoutGift, gift_code_for_checkout, pending_gift_referral
from tests.factories import make_pro_plans
from tests.helpers import captured_wide_event

NOW = datetime(2026, 10, 14, tzinfo=UTC)
GIFT = "app.services.referrals.gift"
FRIEND_ID = "65f0c0ffee00000000000f01"


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

    @pytest.mark.usefixtures("referrals_off")
    async def test_with_referrals_off_a_joined_friend_is_owed_no_new_gift(self) -> None:
        with (
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
