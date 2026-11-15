"""The referral page's overview and the invite landing's resolve, over mocked repositories and Dodo."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

from dodopayments.types import Discount
import pytest

from app.config.feature_flags import REFERRAL_COPY_FLAG, REFERRAL_LAYOUT_FLAG
from app.constants.error_codes import REFERRAL_SUBSCRIPTION_REQUIRED, REFERRALS_DISABLED
from app.constants.referrals import (
    REFERRALS_DISABLED_FIX,
    REFERRALS_DISABLED_MESSAGE,
    REFERRALS_DISABLED_WHY,
    SUBSCRIPTION_REQUIRED_FIX,
    SUBSCRIPTION_REQUIRED_MESSAGE,
    SUBSCRIPTION_REQUIRED_WHY,
    WORKFLOW_CREDITS_PER_MONTH,
    ReferralCopyVariant,
    ReferralLayoutVariant,
    ReferralSource,
)
from app.models.payment_models import PlanDuration
from app.models.referral_models import (
    ReferralCodeDocument,
    ReferralDocument,
    ReferralRevokeReason,
    ReferralRewardState,
    ReferredFriendStanding,
    ReferredFriendStatus,
)
from app.models.user_models import UserDocument
from app.schemas.referrals import (
    ReferralFriendGift,
    ReferralGiftResponse,
    ReferralMeResponse,
    ReferralResolveResponse,
    ReferralWorkflowMeter,
    ReferredFriend,
)
from app.services.payments.payment_service import payment_service
from app.services.referrals.codes import share_link
from app.services.referrals.offer import build_offer
from app.services.referrals.overview import friend_gift, get_referral_overview, land_on_invite
from app.utils.errors import AppError
from shared.py.analytics import UserId, prepare_capture
from shared.py.analytics.catalog.attribution import Actor, Attribution, EntrySurface, Trigger
from shared.py.analytics.catalog.auth import UserActive
from shared.py.analytics.catalog.referrals import ReferralLandingResolved
from shared.py.analytics.context import AnalyticsContext, analytics_context
from tests.factories import make_pro_plans
from tests.helpers import referrals_off_for

OVERVIEW = "app.services.referrals.overview"
PAYMENTS = "app.services.payments.payment_service"
JOINED = datetime(2026, 9, 1, tzinfo=UTC)
PAID = datetime(2026, 9, 3, tzinfo=UTC)
PLANS = make_pro_plans()
REFERRER = UserDocument(
    id="65f0c0ffee00000000000a01", first_name="Aryan", email="aryan@example.com"
)


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
    community_workflows: AsyncMock


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
        patch(
            f"{OVERVIEW}.workflow_repository.count_community_by_creator",
            AsyncMock(return_value=0),
        ) as community_workflows,
    ):
        yield Seams(
            load_user,
            subscription,
            ensure_code,
            listed,
            get_variant,
            find_by_ids,
            community_workflows,
        )


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
                status=ReferredFriendStanding.PAID if paid else ReferredFriendStanding.JOINED,
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
            workflow_meter=ReferralWorkflowMeter(
                subscribed=0, per_month=WORKFLOW_CREDITS_PER_MONTH, months_earned=0, published=0
            ),
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

    async def test_a_refunded_friend_shows_as_refunded_and_earns_no_month(
        self, seams: Seams
    ) -> None:
        refund = {"revoke_reason": ReferralRevokeReason.REFUND, "revoked_at": PAID}
        seams.list_for_referrer.return_value = [
            _referral("priya", ReferralRewardState.REVOKED).model_copy(update=refund),
            _referral("sam", ReferralRewardState.APPLIED).model_copy(update=refund),
            _referral("kim", ReferralRewardState.APPLIED),
        ]
        seams.find_by_ids.return_value = [
            UserDocument(id=uid, first_name=uid.title()) for uid in ("priya", "sam", "kim")
        ]

        overview = await get_referral_overview(REFERRER.id)

        assert [(f.first_name, f.status, f.paid_at) for f in overview.friends] == [
            ("Priya", ReferredFriendStanding.REFUNDED, None),
            ("Sam", ReferredFriendStanding.REFUNDED, None),
            ("Kim", ReferredFriendStanding.PAID, PAID),
        ]
        assert (overview.months_earned, overview.months_applied) == (1, 1)

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

    async def test_with_referrals_off_for_the_owner_the_page_is_a_coded_403_and_mints_no_code(
        self, seams: Seams
    ) -> None:
        with referrals_off_for(REFERRER.id), pytest.raises(AppError) as refused:
            await get_referral_overview(REFERRER.id)

        assert refused.value.status_code == 403
        assert refused.value.to_dict() == {
            "message": REFERRALS_DISABLED_MESSAGE,
            "why": REFERRALS_DISABLED_WHY,
            "fix": REFERRALS_DISABLED_FIX,
            "code": REFERRALS_DISABLED,
        }
        seams.ensure_code.assert_not_awaited()


OWNER = UserDocument(id=REFERRER.id, name="Aryan Randeriya", picture="https://p/a.png")
OWNER_CODE = ReferralCodeDocument(user_id=OWNER.id, code="aryan-k7f2", created_at=JOINED)


class TestResolve:
    @pytest.fixture
    def plans(self) -> Iterator[None]:
        with patch(f"{OVERVIEW}.payment_service.get_pro_plans", AsyncMock(return_value=PLANS)):
            yield

    @pytest.fixture
    def owned_code(self, plans: None) -> Iterator[AsyncMock]:
        with (
            patch(
                f"{OVERVIEW}.referral_code_repository.get_by_code",
                AsyncMock(return_value=OWNER_CODE),
            ),
            patch(f"{OVERVIEW}.user_repository.get", AsyncMock(return_value=OWNER)),
            patch(f"{OVERVIEW}.capture") as capture,
        ):
            yield capture

    async def test_a_landing_on_a_live_link_sets_the_cookie_and_is_recorded_on_its_owner(
        self, owned_code: AsyncMock
    ) -> None:
        landing = await land_on_invite("aryan-k7f2", ReferralCopyVariant.EARN, None)

        assert landing.resolved.valid is True
        assert landing.cookie is not None
        owned_code.assert_called_once_with(
            UserId(OWNER.id),
            ReferralLandingResolved(outcome="valid", landing_variant="earn", cookie_set=True),
        )

    @pytest.mark.usefixtures("plans")
    async def test_a_visitor_opening_a_link_never_marks_its_owner_active(self) -> None:
        """The landing is captured on the owner, under the anonymous visitor's request: it is not the owner using GAIA."""
        visitor = AnalyticsContext(
            attribution=Attribution(
                actor=Actor.USER, trigger=Trigger.INTERACTIVE, surface=EntrySurface.WEB
            )
        )
        with (
            patch(
                f"{OVERVIEW}.referral_code_repository.get_by_code",
                AsyncMock(return_value=OWNER_CODE),
            ),
            patch(f"{OVERVIEW}.user_repository.get", AsyncMock(return_value=OWNER)),
            patch("app.services.analytics_service._get_posthog_client", return_value=MagicMock()),
            patch(
                "app.services.analytics_service.prepare_capture", wraps=prepare_capture
            ) as prepared,
            patch("app.services.analytics_service.spawn_background_task"),
            analytics_context(visitor),
        ):
            await land_on_invite("aryan-k7f2", ReferralCopyVariant.GIFT, None)

        captured = [type(c.args[1]) for c in prepared.call_args_list]
        assert ReferralLandingResolved in captured
        assert UserActive not in captured

    async def test_with_referrals_off_for_its_owner_a_live_link_is_invalid_and_records_disabled(
        self, owned_code: AsyncMock
    ) -> None:
        with referrals_off_for(OWNER.id):
            landing = await land_on_invite("aryan-k7f2", None, None)

        assert landing.resolved == ReferralResolveResponse(valid=False, offer=build_offer(PLANS))
        assert landing.cookie is None
        owned_code.assert_called_once_with(
            UserId(OWNER.id),
            ReferralLandingResolved(outcome="disabled", landing_variant=None, cookie_set=False),
        )

    async def test_a_known_code_names_its_owner_and_carries_the_gift(self, plans: None) -> None:
        owner = UserDocument(
            id="65f0c0ffee00000000000a01", name="Aryan Randeriya", picture="https://p/a.png"
        )
        code_doc = ReferralCodeDocument(
            user_id="65f0c0ffee00000000000a01", code="aryan-k7f2", created_at=JOINED
        )
        with (
            patch(
                f"{OVERVIEW}.referral_code_repository.get_by_code",
                AsyncMock(return_value=code_doc),
            ) as get_by_code,
            patch(f"{OVERVIEW}.user_repository.get", AsyncMock(return_value=owner)) as get_user,
        ):
            landing = await land_on_invite("aryan-k7f2", None, None)

        assert landing.resolved == ReferralResolveResponse(
            valid=True,
            referrer_first_name="Aryan",
            referrer_picture="https://p/a.png",
            offer=build_offer(PLANS),
        )
        get_by_code.assert_awaited_once_with("aryan-k7f2")
        get_user.assert_awaited_once_with("65f0c0ffee00000000000a01")

    async def test_an_owner_without_a_picture_shows_none(self, plans: None) -> None:
        code_doc = ReferralCodeDocument(
            user_id="65f0c0ffee00000000000a01", code="aryan-k7f2", created_at=JOINED
        )
        with (
            patch(
                f"{OVERVIEW}.referral_code_repository.get_by_code",
                AsyncMock(return_value=code_doc),
            ),
            patch(
                f"{OVERVIEW}.user_repository.get",
                AsyncMock(
                    return_value=UserDocument(
                        id="65f0c0ffee00000000000a01", first_name="Aryan", picture=""
                    )
                ),
            ),
        ):
            landing = await land_on_invite("aryan-k7f2", None, None)
            assert landing.resolved.referrer_picture is None

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
            landing = await land_on_invite("gone-zzzz", None, None)

        assert landing.resolved == ReferralResolveResponse(valid=False, offer=build_offer(PLANS))
        assert landing.cookie is None
        assert get_user.await_count == int(owner_exists)


def _percent_off(*, basis_points: int, cycles: int | None) -> Discount:
    return Discount(
        amount=basis_points,
        business_id="biz_1",
        code="SAVE20",
        created_at=JOINED,
        discount_id="dsc_paywall",
        restricted_to=[],
        times_used=0,
        type="percentage",
        subscription_cycles=cycles,
    )


@contextmanager
def _paywall_code(discount: Discount | None) -> Iterator[None]:
    """Configure the code every Pro checkout applies, as Dodo reports it."""
    with (
        patch(f"{PAYMENTS}.settings.PAYWALL_DISCOUNT_CODE", "SAVE20"),
        patch.object(payment_service, "client", MagicMock(), create=True),
        patch(f"{PAYMENTS}.find_discount", AsyncMock(return_value=discount)),
    ):
        yield


class TestFriendGift:
    @pytest.fixture
    def owed(self) -> Iterator[AsyncMock]:
        referral = ReferralDocument(
            friend_user_id="64a0000000000000000000f1",
            referrer_user_id=OWNER.id,
            code="aryan-k7f2",
            joined_at=JOINED,
            created_at=JOINED,
            updated_at=JOINED,
        )
        with (
            patch(f"{OVERVIEW}.pending_gift_referral", AsyncMock(return_value=referral)) as owed,
            patch(f"{OVERVIEW}.user_repository.get", AsyncMock(side_effect={OWNER.id: OWNER}.get)),
            patch(f"{OVERVIEW}.payment_service.get_pro_plans", AsyncMock(return_value=PLANS)),
        ):
            yield owed

    async def test_a_friend_owed_a_gift_sees_who_sent_it_and_its_price(
        self, owed: AsyncMock
    ) -> None:
        with patch(f"{PAYMENTS}.settings.PAYWALL_DISCOUNT_CODE", None):
            result = await friend_gift("64a0000000000000000000f1")

        owed.assert_awaited_once_with("64a0000000000000000000f1")
        assert result == ReferralGiftResponse(
            gift=ReferralFriendGift(
                referrer_first_name="Aryan",
                referrer_picture="https://p/a.png",
                offer=build_offer(PLANS),
                billing_cycles=[PlanDuration.MONTHLY, PlanDuration.YEARLY],
            )
        )

    @pytest.mark.usefixtures("owed")
    async def test_the_gift_is_priced_only_on_the_cycles_checkout_applies_it(self) -> None:
        # 20% off one charge: less than half off two months, more than a month off a year.
        with _paywall_code(_percent_off(basis_points=2000, cycles=1)):
            result = await friend_gift("64a0000000000000000000f1")

        assert result.gift is not None
        assert result.gift.billing_cycles == [PlanDuration.MONTHLY]

    @pytest.mark.usefixtures("owed")
    async def test_a_paywall_code_worth_more_on_every_cycle_leaves_no_gift_to_show(
        self,
    ) -> None:
        with _paywall_code(_percent_off(basis_points=2000, cycles=None)):
            assert await friend_gift("64a0000000000000000000f1") == ReferralGiftResponse(gift=None)

    @pytest.mark.usefixtures("owed")
    async def test_a_paywall_code_dodo_does_not_know_never_hides_the_gift(self) -> None:
        with _paywall_code(None):
            result = await friend_gift("64a0000000000000000000f1")

        assert result.gift is not None
        assert result.gift.billing_cycles == [PlanDuration.MONTHLY, PlanDuration.YEARLY]

    async def test_anyone_owed_no_gift_gets_none_and_no_price_lookup(self) -> None:
        with (
            patch(f"{OVERVIEW}.pending_gift_referral", AsyncMock(return_value=None)),
            patch(f"{OVERVIEW}.payment_service.get_pro_plans", AsyncMock()) as plans,
        ):
            assert await friend_gift("64a0000000000000000000f1") == ReferralGiftResponse(gift=None)

        plans.assert_not_awaited()


def _visitor(friend_id: str, state: ReferralRewardState | None) -> ReferralDocument:
    return _referral(friend_id, state).model_copy(
        update={"source": ReferralSource.WORKFLOW, "workflow_id": "wf_digest"}
    )


class TestWorkflowMeter:
    async def test_paying_visitors_fill_the_meter_and_are_never_listed_as_friends(
        self, seams: Seams
    ) -> None:
        seams.list_for_referrer.return_value = [
            _referral("priya", ReferralRewardState.APPLIED),
            _visitor("v1", ReferralRewardState.METERED),
            _visitor("v2", ReferralRewardState.METERED),
            _visitor("v3", ReferralRewardState.APPLIED),
            _visitor("v4", ReferralRewardState.METERED),
            _visitor("v5", ReferralRewardState.METERED),
            _visitor("v6", None),
            _visitor("v7", ReferralRewardState.REVOKED),
        ]
        seams.find_by_ids.return_value = [UserDocument(id="priya", first_name="Priya")]

        overview = await get_referral_overview(REFERRER.id)

        assert overview.workflow_meter == ReferralWorkflowMeter(
            subscribed=2, per_month=WORKFLOW_CREDITS_PER_MONTH, months_earned=1, published=0
        )
        assert [friend.first_name for friend in overview.friends] == ["Priya"]
        seams.find_by_ids.assert_awaited_once_with(["priya"])
        assert overview.months_earned == 2

    async def test_a_banked_month_fills_the_meter_like_an_applied_one(self, seams: Seams) -> None:
        seams.list_for_referrer.return_value = [
            _visitor("v1", ReferralRewardState.APPLIED),
            _visitor("v2", ReferralRewardState.BANKED),
            *(_visitor(f"m{i}", ReferralRewardState.METERED) for i in range(5)),
        ]
        seams.find_by_ids.return_value = []

        overview = await get_referral_overview(REFERRER.id)

        assert overview.workflow_meter == ReferralWorkflowMeter(
            subscribed=1, per_month=WORKFLOW_CREDITS_PER_MONTH, months_earned=2, published=0
        )

    async def test_a_refunded_visitor_stops_counting_before_the_month_is_taken_back(
        self, seams: Seams
    ) -> None:
        refund = {"revoke_reason": ReferralRevokeReason.REFUND, "revoked_at": PAID}
        seams.list_for_referrer.return_value = [
            _visitor("v1", ReferralRewardState.METERED),
            _visitor("v2", ReferralRewardState.METERED).model_copy(update=refund),
            _visitor("v3", ReferralRewardState.REVOKED).model_copy(update=refund),
        ]
        seams.find_by_ids.return_value = []

        overview = await get_referral_overview(REFERRER.id)

        assert overview.workflow_meter == ReferralWorkflowMeter(
            subscribed=1, per_month=WORKFLOW_CREDITS_PER_MONTH, months_earned=0, published=0
        )

    async def test_a_creator_with_a_community_workflow_starts_on_an_empty_meter(
        self, seams: Seams
    ) -> None:
        seams.list_for_referrer.return_value = []
        seams.find_by_ids.return_value = []
        seams.community_workflows.return_value = 2

        overview = await get_referral_overview(REFERRER.id)

        assert overview.workflow_meter == ReferralWorkflowMeter(
            subscribed=0, per_month=WORKFLOW_CREDITS_PER_MONTH, months_earned=0, published=2
        )
        seams.community_workflows.assert_awaited_once_with(REFERRER.id)
