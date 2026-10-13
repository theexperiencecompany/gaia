"""The week-one bot DM: one pitch after a good first week, on the user's one chat platform."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.referrals import ReferralNudge
from app.models.chat_models import ConversationSource
from app.models.payment_models import PlanDuration, PlanResponse, PlanTier
from app.models.user_models import UserDocument
from app.services.delivery.chat_channel import ChatChannel
from app.services.outbound_delivery import OutboundResult
from app.services.referrals.codes import share_link
from app.services.referrals.offer import ProPlans
from app.services.referrals.week_one import send_week_one_dms

USER_ID = "6812f0b3c9a14e2b7d5a91cc"
NOW = datetime(2026, 10, 14, 10, 0, tzinfo=UTC)
MODULE = "app.services.referrals.week_one"
TELEGRAM = ChatChannel(source=ConversationSource.TELEGRAM, platform_user_id="tg-1")


def _plan(duration: PlanDuration, amount: int) -> PlanResponse:
    return PlanResponse(
        id=duration.value,
        dodo_product_id=f"pdt_{duration.value}",
        name="Pro",
        plan_type=PlanTier.PRO,
        amount=amount,
        currency="USD",
        duration=duration,
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


PLANS = ProPlans(
    monthly=_plan(PlanDuration.MONTHLY, 3000), yearly=_plan(PlanDuration.YEARLY, 27000)
)


def _user(days_since_signup: int = 7) -> UserDocument:
    return UserDocument(
        id=USER_ID,
        email="aryan@example.com",
        first_name="Aryan",
        created_at=NOW - timedelta(days=days_since_signup, hours=1),
    )


def _active_days(count: int) -> dict[str, int]:
    return {(NOW - timedelta(days=d)).strftime("%Y-%m-%d"): 3 for d in range(count)}


async def _deliver_now(_user_id: str, _nudge: ReferralNudge, deliver) -> bool:
    return await deliver()


@dataclass
class Seams:
    candidates: AsyncMock
    activity: AsyncMock
    channel: AsyncMock
    pitch: AsyncMock
    publish: AsyncMock


@pytest.fixture
def seams() -> Iterator[Seams]:
    with (
        patch(f"{MODULE}.datetime") as clock,
        patch(f"{MODULE}.is_within_local_daytime", return_value=True),
        patch(
            f"{MODULE}.user_repository.find_nurture_candidates",
            AsyncMock(return_value=[_user()]),
        ) as candidates,
        patch(
            f"{MODULE}.usage_daily_repository.counts_since",
            AsyncMock(return_value=_active_days(4)),
        ) as activity,
        patch(f"{MODULE}.resolve_chat_channel", AsyncMock(return_value=TELEGRAM)) as channel,
        patch(f"{MODULE}.send_pitch", AsyncMock(side_effect=_deliver_now)) as pitch,
        patch(
            f"{MODULE}.publish_outbound_message",
            AsyncMock(return_value=OutboundResult.PUBLISHED),
        ) as publish,
        patch(f"{MODULE}.ensure_code", AsyncMock(return_value="aryan-k7f2")),
        patch(f"{MODULE}.payment_service.get_pro_plans", AsyncMock(return_value=PLANS)),
    ):
        clock.now.return_value = NOW
        yield Seams(candidates, activity, channel, pitch, publish)


async def test_a_good_first_week_gets_one_forwardable_dm(seams: Seams) -> None:
    assert await send_week_one_dms() == "week-one referral dms: sent 1 of 1 candidates"

    assert seams.pitch.await_args.args[:2] == (USER_ID, ReferralNudge.WEEK_ONE_DM)
    platform, user_id, parts = seams.publish.await_args.args
    assert (platform, user_id) == (ConversationSource.TELEGRAM, USER_ID)
    pitch, forwardable = parts
    assert "$15/month for their first 2 months" in pitch
    assert forwardable.endswith(share_link("aryan-k7f2"))
    assert "$15/month for your first 2 months" in forwardable


async def test_the_week_is_read_from_the_last_seven_days(seams: Seams) -> None:
    await send_week_one_dms()
    seams.activity.assert_awaited_once_with(USER_ID, "2026-10-08")


@pytest.mark.parametrize("active_days", [0, 3])
async def test_a_quiet_week_is_not_pitched(seams: Seams, active_days: int) -> None:
    seams.activity.return_value = _active_days(active_days)
    await send_week_one_dms()
    seams.pitch.assert_not_awaited()


@pytest.mark.parametrize("days_since_signup", [6, 10])
async def test_only_days_seven_to_nine_after_signup(seams: Seams, days_since_signup: int) -> None:
    seams.candidates.return_value = [_user(days_since_signup)]
    await send_week_one_dms()
    seams.pitch.assert_not_awaited()


async def test_a_user_with_no_chat_platform_gets_nothing(seams: Seams) -> None:
    seams.channel.return_value = None
    await send_week_one_dms()
    seams.pitch.assert_not_awaited()


async def test_an_unpublished_dm_does_not_count_as_sent(seams: Seams) -> None:
    seams.publish.return_value = OutboundResult.SKIPPED
    assert await send_week_one_dms() == "week-one referral dms: sent 0 of 1 candidates"


async def test_one_users_failure_does_not_stop_the_rest(seams: Seams) -> None:
    second = _user().model_copy(update={"id": "6812f0b3c9a14e2b7d5a91cd"})
    seams.candidates.return_value = [_user(), second]
    seams.channel.side_effect = [RuntimeError("mongo blip"), TELEGRAM]
    with patch(f"{MODULE}.log", MagicMock()) as log:
        assert await send_week_one_dms() == "week-one referral dms: sent 1 of 2 candidates"
    log.error.assert_called_once()
