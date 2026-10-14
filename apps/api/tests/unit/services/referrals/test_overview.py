"""The referral page's overview and the invite landing's resolve, over mocked repositories and Dodo."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, call, patch

import pytest

from app.config.feature_flags import REFERRAL_COPY_FLAG, REFERRAL_LAYOUT_FLAG
from app.constants.error_codes import REFERRAL_SUBSCRIPTION_REQUIRED
from app.constants.referrals import (
    SUBSCRIPTION_REQUIRED_FIX,
    SUBSCRIPTION_REQUIRED_MESSAGE,
    SUBSCRIPTION_REQUIRED_WHY,
    ReferralCopyVariant,
    ReferralLayoutVariant,
)
from app.models.referral_models import (
    ReferralCodeDocument,
    ReferralDocument,
    ReferralRewardState,
    ReferredFriendStatus,
)
from app.models.user_models import UserDocument
from app.schemas.referrals import ReferralMeResponse, ReferralResolveResponse, ReferredFriend
from app.services.referrals.codes import share_link
from app.services.referrals.offer import build_offer
from app.services.referrals.overview import get_referral_overview, resolve_referral_code
from app.utils.errors import AppError
from tests.factories import make_pro_plans

OVERVIEW = "app.services.referrals.overview"
JOINED = datetime(2026, 9, 1, tzinfo=UTC)
PAID = datetime(2026, 9, 3, tzinfo=UTC)
PLANS = make_pro_plans()
REFERRER = UserDocument(id="referrer-1", first_name="Aryan", email="aryan@example.com")


def _referral(friend_id: str, state: ReferralRewardState | None) -> ReferralDocument:
    paid = state is not None
    return ReferralDocument(
        friend_user_id=friend_id,
        referrer_user_id=REFERRER.id,
        code="aryan-k7f2",
        status=ReferredFriendStatus.PAID if paid else ReferredFriendStatus.JOINED,
        joined_at=JOINED,
        paid_at=PAID if paid else None,
        reward_state=state,
        created_at=JOINED,
        updated_at=JOINED,
    )


@dataclass
class Seams:
    load_user: AsyncMock
    subscription: AsyncMock
    ensure_code: AsyncMock
    list_for_referrer: AsyncMock
    get_variant: AsyncMock
    find_by_ids: AsyncMock


@pytest.fixture
def seams() -> Iterator[Seams]:
    variants = {
        REFERRAL_COPY_FLAG: ReferralCopyVariant.TIME_BACK,
        REFERRAL_LAYOUT_FLAG: ReferralLayoutVariant.PROGRESS,
    }
    with (
        patch(f"{OVERVIEW}.load_user", AsyncMock(return_value=REFERRER)) as load_user,
        patch(
            f"{OVERVIEW}.subscription_repository.get_active_for_user",
            AsyncMock(return_value=SimpleNamespace(next_billing_date="2026-11-14T09:30:00")),
        ) as subscription,
        patch(f"{OVERVIEW}.ensure_code", AsyncMock(return_value="aryan-k7f2")) as ensure_code,
        patch(f"{OVERVIEW}.payment_service.get_pro_plans", AsyncMock(return_value=PLANS)),
        patch(f"{OVERVIEW}.referral_repository.list_for_referrer", AsyncMock()) as listed,
        patch(
            f"{OVERVIEW}.get_variant", AsyncMock(side_effect=lambda flag, _: variants[flag])
        ) as get_variant,
        patch(f"{OVERVIEW}.user_repository.find_by_ids", AsyncMock()) as find_by_ids,
    ):
        yield Seams(load_user, subscription, ensure_code, listed, get_variant, find_by_ids)


class TestOverview:
    async def test_the_page_shows_the_link_gift_months_and_friends_newest_first(
        self, seams: Seams
    ) -> None:
        seams.list_for_referrer.return_value = [
            _referral("priya", ReferralRewardState.APPLIED),
            _referral("sam", ReferralRewardState.BANKED),
            _referral("gone", ReferralRewardState.PENDING),
            _referral("alt", ReferralRewardState.SELF_REFERRAL),
            _referral("lee", None),
            _referral("kim", ReferralRewardState.APPLIED),
        ]
        seams.find_by_ids.return_value = [
            UserDocument(id=uid, first_name=uid.title())
            for uid in ("priya", "sam", "alt", "lee", "kim")
        ]

        overview = await get_referral_overview(REFERRER.id)

        def friend(first_name: str | None, paid: bool) -> ReferredFriend:
            return ReferredFriend(
                first_name=first_name,
                status=ReferredFriendStatus.PAID if paid else ReferredFriendStatus.JOINED,
                joined_at=JOINED,
                paid_at=PAID if paid else None,
            )

        assert overview == ReferralMeResponse(
            code="aryan-k7f2",
            share_link=share_link("aryan-k7f2"),
            offer=build_offer(PLANS),
            months_earned=4,
            months_applied=2,
            months_banked=1,
            next_billing_date=datetime(2026, 11, 14, 9, 30, tzinfo=UTC),
            friends=[
                friend("Priya", True),
                friend("Sam", True),
                friend(None, True),
                friend("Alt", True),
                friend("Lee", False),
                friend("Kim", True),
            ],
            copy_variant=ReferralCopyVariant.TIME_BACK,
            layout_variant=ReferralLayoutVariant.PROGRESS,
        )
        seams.load_user.assert_awaited_once_with(REFERRER.id)
        seams.subscription.assert_awaited_once_with(REFERRER.id)
        seams.ensure_code.assert_awaited_once_with(REFERRER)
        seams.list_for_referrer.assert_awaited_once_with(REFERRER.id)
        seams.find_by_ids.assert_awaited_once_with(["priya", "sam", "gone", "alt", "lee", "kim"])
        assert seams.get_variant.await_args_list == [
            call(REFERRAL_COPY_FLAG, REFERRER.id),
            call(REFERRAL_LAYOUT_FLAG, REFERRER.id),
        ]

    async def test_a_subscription_without_a_billing_date_shows_none(self, seams: Seams) -> None:
        seams.subscription.return_value = SimpleNamespace(next_billing_date=None)
        seams.list_for_referrer.return_value = []
        seams.find_by_ids.return_value = []

        overview = await get_referral_overview(REFERRER.id)

        assert overview.next_billing_date is None
        assert (overview.months_earned, overview.friends) == (0, [])

    async def test_without_an_active_subscription_the_page_is_a_coded_403(
        self, seams: Seams
    ) -> None:
        seams.subscription.return_value = None

        with pytest.raises(AppError) as refused:
            await get_referral_overview(REFERRER.id)

        assert refused.value.status_code == 403
        assert refused.value.to_dict() == {
            "message": SUBSCRIPTION_REQUIRED_MESSAGE,
            "why": SUBSCRIPTION_REQUIRED_WHY,
            "fix": SUBSCRIPTION_REQUIRED_FIX,
            "code": REFERRAL_SUBSCRIPTION_REQUIRED,
        }
        seams.ensure_code.assert_not_awaited()


class TestResolve:
    @pytest.fixture
    def plans(self) -> Iterator[None]:
        with patch(f"{OVERVIEW}.payment_service.get_pro_plans", AsyncMock(return_value=PLANS)):
            yield

    async def test_a_known_code_names_its_owner_and_carries_the_gift(self, plans: None) -> None:
        owner = UserDocument(id="referrer-1", name="Aryan Randeriya", picture="https://p/a.png")
        code_doc = ReferralCodeDocument(user_id="referrer-1", code="aryan-k7f2", created_at=JOINED)
        with (
            patch(
                f"{OVERVIEW}.referral_code_repository.get_by_code",
                AsyncMock(return_value=code_doc),
            ) as get_by_code,
            patch(f"{OVERVIEW}.user_repository.get", AsyncMock(return_value=owner)) as get_user,
        ):
            resolved = await resolve_referral_code("aryan-k7f2")

        assert resolved == ReferralResolveResponse(
            valid=True,
            referrer_first_name="Aryan",
            referrer_picture="https://p/a.png",
            offer=build_offer(PLANS),
        )
        get_by_code.assert_awaited_once_with("aryan-k7f2")
        get_user.assert_awaited_once_with("referrer-1")

    async def test_an_owner_without_a_picture_shows_none(self, plans: None) -> None:
        code_doc = ReferralCodeDocument(user_id="referrer-1", code="aryan-k7f2", created_at=JOINED)
        with (
            patch(
                f"{OVERVIEW}.referral_code_repository.get_by_code",
                AsyncMock(return_value=code_doc),
            ),
            patch(
                f"{OVERVIEW}.user_repository.get",
                AsyncMock(
                    return_value=UserDocument(id="referrer-1", first_name="Aryan", picture="")
                ),
            ),
        ):
            assert (await resolve_referral_code("aryan-k7f2")).referrer_picture is None

    @pytest.mark.parametrize("owner_exists", [False, True], ids=["unknown-code", "owner-deleted"])
    async def test_a_code_nobody_owns_is_invalid_but_still_shows_the_gift(
        self, plans: None, owner_exists: bool
    ) -> None:
        code_doc = (
            ReferralCodeDocument(user_id="gone", code="gone-zzzz", created_at=JOINED)
            if owner_exists
            else None
        )
        with (
            patch(
                f"{OVERVIEW}.referral_code_repository.get_by_code",
                AsyncMock(return_value=code_doc),
            ),
            patch(f"{OVERVIEW}.user_repository.get", AsyncMock(return_value=None)) as get_user,
        ):
            resolved = await resolve_referral_code("gone-zzzz")

        assert resolved == ReferralResolveResponse(valid=False, offer=build_offer(PLANS))
        assert get_user.await_count == int(owner_exists)
