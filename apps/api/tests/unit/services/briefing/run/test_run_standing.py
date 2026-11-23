"""Where the reader stands: the idle ladder, the first week, a lighter cadence."""

from __future__ import annotations

from datetime import timedelta

import pytest
from tests.briefing_run_world import (
    DAY_START,
    DORMANT_SINCE,
    IDLE_SINCE,
    NOW,
    ORCHESTRATED,
    SLOT_MINUTE,
    TZ,
    USER,
    YESTERDAY,
    World,
    brief_work,
    dormant,
    held,
    idle_day,
    idle_days,
    setup_block,
    situation,
    stored_brief,
    winback,
)

from app.constants.briefing import (
    FIRST_WEEK_DAYS,
    IDLE_DORMANT_DAYS,
    BriefForm,
    BriefingFrequency,
    BriefingKind,
    WindDown,
)
from app.models.brief_models import PendingBriefItemDocument
from app.models.brief_settings_models import BriefingSchedule
from app.models.briefing_state_models import (
    BriefingStateDocument,
    BriefingWindDown,
)
from app.models.user_models import UserDocument
from app.services.briefing.clock import resolve_clock
from app.services.briefing.daily import DailyStanding, stand_daily
from app.services.briefing.goals import StatedGoal
from app.services.briefing.lookback import Lookback
from app.services.briefing.pipeline import run_brief
from app.services.briefing.wind_down import ladder_state
from app.services.briefing.work import TrackedWork

pytestmark = pytest.mark.usefixtures("fake_redis")


class TestWhereTheDailyStarts:
    async def test_after_yesterdays_brief_the_look_back_starts_there_and_it_is_not_the_first(
        self, world: World
    ) -> None:
        standing = await stand_daily(world.user, world.state, resolve_clock(TZ))

        assert isinstance(standing, DailyStanding)
        assert (standing.lookback, standing.is_first) == (
            Lookback(last=YESTERDAY, since=DAY_START),
            False,
        )

    async def test_after_a_skipped_day_the_look_back_starts_at_the_last_brief(
        self, world: World
    ) -> None:
        world.briefs.clear()
        earlier = stored_brief("2026-10-12", BriefForm.EDITION)
        world.briefs[earlier.id] = earlier

        standing = await stand_daily(world.user, world.state, resolve_clock(TZ))

        assert isinstance(standing, DailyStanding)
        assert standing.lookback == Lookback(last=earlier, since=DAY_START - timedelta(days=1))


class TestTheIdleLadder:
    """Nothing to report escalates to a warning, then one goodbye, then dormancy."""

    async def test_a_dormant_user_who_came_back_is_woken_and_briefed(self, world: World) -> None:
        dormant(world)
        world.user.last_active_at = DORMANT_SINCE

        await run_brief(USER, BriefingKind.DAILY)

        assert world.today() is not None
        # Woken, the ladder starts again from nothing: today is the first idle day, not the fourth.
        assert ladder_state(world.state).wound_down_since is None
        assert idle_days(world) == 1

    async def test_a_woken_user_asked_for_a_goal_two_days_ago_is_not_asked_again(
        self, world: World
    ) -> None:
        dormant(world)
        assert world.state.wind_down is not None
        world.state.wind_down.goal_asked_at = NOW - timedelta(days=2)
        world.goals = []
        world.user.last_active_at = NOW - timedelta(hours=1)

        await run_brief(USER, BriefingKind.DAILY)

        assert ladder_state(world.state).goal_asked_at == NOW - timedelta(days=2)
        assert situation(world).goal_asked_recently is True

    @pytest.mark.parametrize(
        ("work", "held", "has_goal", "idle"),
        [
            (TrackedWork(), [], False, True),
            (brief_work(), [], False, False),
            (TrackedWork(), [held("h1", "Digest", "first")], False, False),
            (TrackedWork(), [], True, False),
        ],
    )
    async def test_a_day_is_idle_only_with_no_work_no_held_results_and_no_goal(
        self,
        world: World,
        work: TrackedWork,
        held: list[PendingBriefItemDocument],
        has_goal: bool,
        idle: bool,
    ) -> None:
        world.held = held
        goals = [StatedGoal("Ship v2")] if has_goal else []
        world.goals = goals
        world.track(work)

        await run_brief(USER, BriefingKind.DAILY)

        assert idle_days(world) == int(idle)

    @pytest.mark.parametrize(
        ("has_goal", "asked_days_ago", "asks"),
        [
            (True, None, True),
            (True, 2, False),
            (True, 7, True),
            (False, None, True),
            (False, 2, False),
            (False, 7, True),
        ],
        ids=[
            "goal-never-asked",
            "goal-asked-two-days-ago",
            "goal-asked-a-week-ago",
            "no-goal-never-asked",
            "no-goal-asked-two-days-ago",
            "no-goal-asked-a-week-ago",
        ],
    )
    async def test_the_goal_is_asked_about_or_for_once_a_week_and_each_ask_is_recorded(
        self,
        world: World,
        has_goal: bool,
        asked_days_ago: int | None,
        asks: bool,
    ) -> None:
        asked_at = None if asked_days_ago is None else NOW - timedelta(days=asked_days_ago)
        world.user = UserDocument(id=USER, timezone=TZ, email="a@b.c")
        world.state = BriefingStateDocument(
            user_id=USER, wind_down=BriefingWindDown(goal_asked_at=asked_at)
        )
        goals = [StatedGoal("Ship v2")] if has_goal else []
        world.goals = goals
        world.user.last_active_at = NOW - timedelta(hours=1)

        await run_brief(USER, BriefingKind.DAILY)

        assert situation(world).goal_asked_recently is not asks
        assert ladder_state(world.state).goal_asked_at == (NOW if asks else asked_at)

    @pytest.mark.parametrize(("idle_days", "stage"), [(2, WindDown.WARN), (3, WindDown.FINAL)])
    async def test_the_idle_streak_sets_the_wind_down_and_the_goodbye_goes_dormant(
        self, world: World, idle_days: int, stage: WindDown
    ) -> None:
        idle_day(world, idle_days)

        await run_brief(USER, BriefingKind.DAILY)

        assert situation(world).wind_down == stage
        wound_down_since = ladder_state(world.state).wound_down_since
        assert wound_down_since == (NOW if stage is WindDown.FINAL else None)

    async def test_the_wind_down_message_is_pushed_even_on_an_empty_day(self, world: World) -> None:
        idle_day(world, 2)
        world.calendar = []

        await run_brief(USER, BriefingKind.DAILY)

        request = world.notify.await_args.args[0]
        assert [c.channel_type for c in request.channels] == ORCHESTRATED
        world.post.assert_awaited_once()

    async def test_a_long_streak_with_work_to_report_does_not_wind_down(self, world: World) -> None:
        world.state.wind_down = BriefingWindDown(idle_days=4, date="2026-10-13")
        world.track(brief_work())

        await run_brief(USER, BriefingKind.DAILY)

        assert situation(world).wind_down is None
        assert idle_days(world) == 0
        assert ladder_state(world.state).wound_down_since is None

    @pytest.mark.parametrize(("idle_days", "voiced_winback"), [(0, True), (3, False)])
    async def test_a_winback_is_voiced_unless_the_brief_is_winding_down(
        self,
        world: World,
        idle_days: int,
        voiced_winback: bool,
    ) -> None:
        winback(world)
        idle_day(world, idle_days)

        await run_brief(USER, BriefingKind.DAILY)

        assert situation(world).winback is voiced_winback
        assert world.stored().mood == "winback"

    async def test_a_users_first_brief_is_voiced_as_their_first(self, world: World) -> None:
        world.briefs_read([])

        await run_brief(USER, BriefingKind.DAILY)

        assert situation(world).is_first_briefing is True


class TestTheFirstWeek:
    """A new account's first week helps it get value instead of winding down."""

    async def test_a_first_week_account_never_climbs_the_idle_ladder(self, world: World) -> None:
        world.user.created_at = NOW - timedelta(days=FIRST_WEEK_DAYS, seconds=-1)
        idle_day(world, IDLE_DORMANT_DAYS)

        await run_brief(USER, BriefingKind.DAILY)

        assert idle_days(world) == 0
        assert (situation(world).wind_down, situation(world).first_week) == (None, True)
        assert ladder_state(world.state).wound_down_since is None

    async def test_the_ladder_runs_once_the_first_week_is_over(self, world: World) -> None:
        world.user.created_at = NOW - timedelta(days=FIRST_WEEK_DAYS)
        idle_day(world, IDLE_DORMANT_DAYS)

        await run_brief(USER, BriefingKind.DAILY)

        assert idle_days(world) == IDLE_DORMANT_DAYS
        assert (situation(world).wind_down, situation(world).first_week) == (
            WindDown.FINAL,
            False,
        )
        assert ladder_state(world.state).wound_down_since == NOW

    @pytest.mark.parametrize(
        ("apps", "line"),
        [
            (["Gmail", "Notion"], "Apps they've connected: Gmail, Notion."),
            ([], "Apps they've connected: none yet."),
        ],
    )
    async def test_a_first_week_brief_sees_the_apps_actually_connected(
        self, world: World, apps: list[str], line: str
    ) -> None:
        world.user.created_at = NOW - timedelta(days=1)
        world.connect(*apps)

        await run_brief(USER, BriefingKind.DAILY)

        assert setup_block(world) == line

    async def test_an_older_account_is_shown_no_setup(self, world: World) -> None:
        world.user.created_at = NOW - timedelta(days=30)
        world.connect("Gmail")

        await run_brief(USER, BriefingKind.DAILY)

        assert setup_block(world) == ""


class TestTheLighterCadenceOffer:
    """A user who stopped coming back is offered fewer briefs, with their real cadence."""

    async def test_an_idle_user_is_offered_a_lighter_cadence_beside_their_cadence(
        self, world: World
    ) -> None:
        world.user.last_active_at = IDLE_SINCE
        world.state.schedule = BriefingSchedule(frequency=BriefingFrequency.WEEKDAYS, hour=9)

        await run_brief(USER, BriefingKind.DAILY)

        assert situation(world).offer_lighter_cadence is True
        [cadence] = setup_block(world).splitlines()
        assert cadence.startswith(
            f"Their briefs now: a daily brief Monday to Friday at 9:{SLOT_MINUTE} AM"
        )

    async def test_a_first_week_idle_user_sees_their_cadence_and_apps_on_separate_lines(
        self, world: World
    ) -> None:
        world.user.last_active_at = IDLE_SINCE
        world.user.created_at = NOW - timedelta(days=1)
        world.connect("Gmail")

        await run_brief(USER, BriefingKind.DAILY)

        assert setup_block(world).splitlines() == [
            f"Their briefs now: a daily brief every day at 8:{SLOT_MINUTE} AM, plus the weekly "
            f"digest on Sunday at 5:{SLOT_MINUTE} PM.",
            "Apps they've connected: Gmail.",
        ]

    async def test_an_active_user_is_not(self, world: World) -> None:
        await run_brief(USER, BriefingKind.DAILY)

        assert (situation(world).offer_lighter_cadence, setup_block(world)) == (False, "")
