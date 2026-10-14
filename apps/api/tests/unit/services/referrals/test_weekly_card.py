"""When chat surfaces the Monday recap card: the user's own Monday, for a week with work in it."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.config.feature_flags import REFERRAL_COPY_FLAG
from app.constants.referrals import ReferralCopyVariant, ReferralNudge
from app.models.user_models import UserDocument
from app.schemas.referrals import ReferralWeeklyCardResponse
from app.schemas.usage import TimeSavedSummary
from app.services.referrals.codes import share_link
from app.services.referrals.nudges import rendered_by_client
from app.services.referrals.weekly_card import claim_weekly_card, weekly_card_due

MODULE = "app.services.referrals.weekly_card"
USER = UserDocument(id="64a0000000000000000000a1", name="Aryan", timezone="Asia/Kolkata")

# Sunday 20:00 UTC is already Monday in Kolkata (+05:30) and still Sunday in New York.
SUNDAY_EVENING_UTC = datetime(2026, 10, 18, 20, 0, tzinfo=UTC)
MONDAY_NOON_UTC = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
# Tuesday 03:00 UTC is still Monday evening in Los Angeles (-07:00).
TUESDAY_EARLY_UTC = datetime(2026, 10, 20, 3, 0, tzinfo=UTC)
MONDAY = date(2026, 10, 19)


def _stats(minutes_saved: int) -> TimeSavedSummary:
    return TimeSavedSummary(
        window_start=datetime(2026, 10, 12, tzinfo=UTC),
        window_end=datetime(2026, 10, 19, tzinfo=UTC),
        actions=minutes_saved,
        workflow_runs=0,
        minutes_saved=minutes_saved,
    )


def test_the_card_is_due_only_on_a_monday() -> None:
    assert weekly_card_due(MONDAY, _stats(30)) is True
    assert weekly_card_due(date(2026, 10, 18), _stats(30)) is False


def test_a_week_with_nothing_saved_never_shows_the_card() -> None:
    assert weekly_card_due(MONDAY, _stats(0)) is False


def test_a_single_minute_saved_is_a_week_worth_showing() -> None:
    assert weekly_card_due(MONDAY, _stats(1)) is True


@dataclass
class Seams:
    load_user: AsyncMock
    subscribed: AsyncMock
    ensure_code: AsyncMock
    time_saved: AsyncMock
    variant: AsyncMock
    pitch: AsyncMock


@pytest.fixture
def seams() -> Iterator[Seams]:
    with (
        patch(f"{MODULE}.load_user", AsyncMock(return_value=USER)) as load_user,
        patch(f"{MODULE}.require_referrer_subscription", AsyncMock()) as subscribed,
        patch(f"{MODULE}.ensure_code", AsyncMock(return_value="aryan-k7f2")) as ensure_code,
        patch(f"{MODULE}.get_time_saved", AsyncMock(return_value=_stats(30))) as time_saved,
        patch(
            f"{MODULE}.get_variant", AsyncMock(return_value=ReferralCopyVariant.TIME_BACK)
        ) as variant,
        patch(f"{MODULE}.send_pitch", AsyncMock(return_value=True)) as pitch,
    ):
        yield Seams(load_user, subscribed, ensure_code, time_saved, variant, pitch)


class TestClaimWeeklyCard:
    async def test_a_due_card_that_wins_the_week_shows_with_the_link(self, seams: Seams) -> None:
        card = await claim_weekly_card(USER.id, MONDAY_NOON_UTC)

        assert card == ReferralWeeklyCardResponse(
            show=True,
            stats=_stats(30),
            code="aryan-k7f2",
            share_link=share_link("aryan-k7f2"),
            copy_variant=ReferralCopyVariant.TIME_BACK,
        )
        seams.load_user.assert_awaited_once_with(USER.id)
        seams.subscribed.assert_awaited_once_with(USER.id)
        seams.ensure_code.assert_awaited_once_with(USER)
        seams.time_saved.assert_awaited_once_with(USER.id, MONDAY)
        seams.variant.assert_awaited_once_with(REFERRAL_COPY_FLAG, USER.id)
        seams.pitch.assert_awaited_once_with(
            USER.id, ReferralNudge.WEEKLY_STATS_CARD, rendered_by_client
        )

    async def test_a_card_not_due_never_spends_the_week(self, seams: Seams) -> None:
        tuesday = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)

        card = await claim_weekly_card(USER.id, tuesday)

        assert card.show is False
        seams.pitch.assert_not_awaited()

    async def test_a_due_card_that_loses_the_week_stays_hidden(self, seams: Seams) -> None:
        seams.pitch.return_value = False

        assert (await claim_weekly_card(USER.id, MONDAY_NOON_UTC)).show is False


@pytest.mark.parametrize(
    ("timezone", "now"),
    [
        ("Asia/Kolkata", SUNDAY_EVENING_UTC),
        ("America/Los_Angeles", TUESDAY_EARLY_UTC),
        (None, MONDAY_NOON_UTC),
    ],
)
async def test_a_local_monday_on_any_utc_day_recaps_the_same_week(
    seams: Seams, timezone: str | None, now: datetime
) -> None:
    seams.load_user.return_value = USER.model_copy(update={"timezone": timezone})

    card = await claim_weekly_card(USER.id, now)

    assert card.show is True
    seams.time_saved.assert_awaited_once_with(USER.id, MONDAY)


@pytest.mark.parametrize(
    ("timezone", "now"),
    [("America/New_York", SUNDAY_EVENING_UTC), (None, SUNDAY_EVENING_UTC)],
)
async def test_a_local_sunday_hides_the_card_and_keeps_the_week(
    seams: Seams, timezone: str | None, now: datetime
) -> None:
    seams.load_user.return_value = USER.model_copy(update={"timezone": timezone})

    assert (await claim_weekly_card(USER.id, now)).show is False
    seams.pitch.assert_not_awaited()
