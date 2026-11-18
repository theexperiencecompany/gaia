"""A quiet day and a quiet week: the plain note, and the days it stays silent."""

from __future__ import annotations

from datetime import timedelta

import pytest
from tests.briefing_run_world import (
    CHART,
    DIGEST_REPORT,
    EVENT,
    NOW,
    PROGRESS,
    USER,
    World,
    completions,
    composed,
    expected_note,
    held,
    idle_day,
    own,
    own_open,
    quiet_day,
    shown_before,
    skipped,
    stored_brief,
    tracked,
    weekly_reply,
    with_block,
)

from app.constants.briefing import (
    IDLE_DORMANT_DAYS,
    WEEKLY_KICKER,
    BriefForm,
    BriefingFrequency,
    BriefingKind,
    BriefingRunOutcome,
)
from app.constants.notifications import (
    NotificationKind,
)
from app.models.brief_composition_models import BriefComposition
from app.models.brief_payload_models import (
    BriefingMood,
    UnreadSource,
)
from app.models.brief_pool_models import GoalOrigin
from app.models.brief_settings_models import BriefingSchedule
from app.models.brief_view_models import BriefNoteNotification
from app.models.scout_models import (
    ScoutSkipReason,
)
from app.services.briefing.calendar_read import CalendarGap
from app.services.briefing.goals import StatedGoal
from app.services.briefing.pipeline import run_brief
from app.services.briefing.quiet_note import QuietFacts
from app.services.briefing.wind_down import ladder_state
from app.services.briefing.work import TrackedWork
from shared.py.analytics import UserId
from shared.py.analytics.catalog.briefings import BriefingSent

pytestmark = pytest.mark.usefixtures("fake_redis")


class TestAQuietDay:
    async def test_a_quiet_day_sends_its_note_and_no_edition(self, world: World) -> None:
        """Founder decision: a day with nothing placed and nothing on the calendar sends a plain note."""
        quiet_day(world)
        bags_before = dict(world.bags)

        assert await run_brief(USER, BriefingKind.DAILY) is BriefingRunOutcome.SENT

        world.render.assert_not_awaited()
        world.voice.assert_not_awaited()
        payload = world.stored()
        assert payload.form is BriefForm.QUIET_NOTE
        assert payload.message == expected_note(BriefingKind.DAILY, QuietFacts(calendar=None))
        assert world.today().edition is None
        request = world.notify.await_args.args[0]
        assert request.details == BriefNoteNotification(kind=NotificationKind.BRIEFING_NOTE)
        assert request.content.rich_content is None
        assert [c.channel_type for c in request.channels] == ["inapp", "email"]
        posted = world.post.await_args.kwargs
        assert (posted["text"], posted["image"]) == (payload.message, None)
        world.brief_message.assert_awaited_once_with(USER, payload.message, None)
        assert world.capture.call_args.args[1].form == "quiet_note"
        assert world.bags == bags_before

    async def test_the_note_says_what_the_run_could_not_read_and_what_is_overdue(
        self, world: World
    ) -> None:
        quiet_day(world)
        world.calendar = CalendarGap.UNAVAILABLE
        world.scouts = [skipped("GitHub", ScoutSkipReason.SIGNED_OUT), skipped("Notion")]
        # Seventy past due, every one already shown as it stands: nothing new to place.
        overdue = own_open(70, overdue=70)
        world.todos.add(*overdue)
        shown_before(world, *(d.id or "" for d in overdue), times=2)
        unread = [
            UnreadSource(app="GitHub", reason=ScoutSkipReason.SIGNED_OUT),
            UnreadSource(app="Notion", reason=ScoutSkipReason.FAILED),
        ]

        await run_brief(USER, BriefingKind.DAILY)

        payload = world.stored()
        assert payload.message == expected_note(
            BriefingKind.DAILY,
            QuietFacts(calendar=CalendarGap.UNAVAILABLE, overdue=70, unread=unread),
        )
        assert payload.sources_unavailable == unread

    async def test_a_quiet_note_accounts_for_the_held_results_it_carries(
        self, world: World
    ) -> None:
        quiet_day(world)
        world.held = [held("h1", "Paper digest", DIGEST_REPORT)]
        world.composer.side_effect = None
        world.composer.return_value = BriefComposition(blocks=[])

        assert await run_brief(USER, BriefingKind.DAILY) is BriefingRunOutcome.SENT

        assert world.stored().form is BriefForm.QUIET_NOTE
        assert world.pending.consumed == [["h1"]]

    @pytest.mark.parametrize(
        ("blocked", "form"),
        [(["b1"], BriefForm.QUIET_NOTE), (["b1", "b2"], BriefForm.EDITION)],
        ids=["only-repeats", "something-new-beside-repeats"],
    )
    async def test_a_day_holding_only_what_earlier_briefs_showed_is_quiet(
        self, world: World, blocked: list[str], form: BriefForm
    ) -> None:
        """Replay: the same three undated todos were drawn as a fresh edition day after day."""
        quiet_day(world)
        titles = {"b1": "Approve the Acme MSA", "b2": "Reply to Daniel"}
        world.track(TrackedWork(blocked=[tracked(t, titles[t]) for t in blocked]))
        shown_before(world, "b1", times=2)

        await run_brief(USER, BriefingKind.DAILY)

        assert world.stored().form is form

    async def test_a_day_of_repeats_whose_chart_shows_what_moved_is_an_edition(
        self, world: World
    ) -> None:
        quiet_day(world)
        world.track(TrackedWork(blocked=[tracked("b1", "Approve the Acme MSA")]))
        shown_before(world, "b1", times=2)
        # Done inside the chart's week but before yesterday's brief: no item, only a figure.
        world.todos.add(
            *completions([tracked("c1", "Investor update", completed_at=NOW - timedelta(days=3))])
        )
        world.composer.side_effect = with_block(
            composed({"Waiting": ["Approve the Acme MSA"]}), CHART
        )

        await run_brief(USER, BriefingKind.DAILY)

        assert world.stored().form is BriefForm.EDITION

    async def test_a_day_with_an_event_is_an_edition_not_a_note(self, world: World) -> None:
        quiet_day(world)
        world.calendar = [EVENT]

        await run_brief(USER, BriefingKind.DAILY)

        payload = world.stored()
        assert payload.form is BriefForm.EDITION
        assert [e.title for e in payload.calendar] == ["Sequoia"]
        world.render.assert_awaited_once()

    @pytest.mark.parametrize(
        "before",
        [
            [BriefForm.QUIET_NOTE],
            [BriefForm.QUIET_NOTE, BriefForm.QUIET_NOTE, BriefForm.EDITION],
        ],
        ids=["the day after a quiet note", "a quiet streak"],
    )
    async def test_a_quiet_day_after_a_quiet_note_sends_nothing(
        self, world: World, before: list[BriefForm]
    ) -> None:
        """Founder: one quiet note says it is quiet; the days after it stay silent until something real."""
        quiet_day(world)
        days = ["2026-10-13", "2026-10-12", "2026-10-11"]
        world.briefs_read([stored_brief(day, form) for day, form in zip(days, before)])

        assert await run_brief(USER, BriefingKind.DAILY) is BriefingRunOutcome.SILENT

        # Nothing is stored, so a silent day can never count toward the winback streak.
        world.nothing_sent()
        assert world.states.calls_to("record_goal_question") == []

    async def test_a_quiet_weekly_before_it_does_not_silence_the_daily(self, world: World) -> None:
        quiet_day(world)
        world.briefs_read(
            [
                stored_brief("2026-10-13", BriefForm.QUIET_NOTE, BriefingKind.WEEKLY),
                stored_brief("2026-10-13", BriefForm.EDITION),
            ]
        )

        assert await run_brief(USER, BriefingKind.DAILY) is BriefingRunOutcome.SENT
        assert world.stored().form is BriefForm.QUIET_NOTE


class TestAQuietWeek:
    async def test_an_empty_week_sends_the_quiet_note_and_never_an_edition(
        self, world: World
    ) -> None:
        world.calendar = []
        world.todos.rows.clear()

        assert await run_brief(USER, BriefingKind.WEEKLY) is BriefingRunOutcome.SENT

        world.composer.assert_not_awaited()
        world.voice.assert_not_awaited()
        world.render.assert_not_awaited()
        payload = world.stored()
        assert world.today(BriefingKind.WEEKLY) is not None
        assert (payload.form, payload.kicker) == (BriefForm.QUIET_NOTE, WEEKLY_KICKER)
        assert payload.message == expected_note(BriefingKind.WEEKLY, QuietFacts(calendar=None))

    @pytest.mark.regression
    async def test_a_weekly_only_readers_last_empty_digest_says_goodbye_before_winding_down(
        self, world: World
    ) -> None:
        """Regression: a weekly-only loop stopped silently after its third empty digest."""
        world.state.schedule = BriefingSchedule(frequency=BriefingFrequency.WEEKLY_ONLY)
        world.calendar = []
        world.todos.rows.clear()
        idle_day(world, IDLE_DORMANT_DAYS)
        world.replies = [weekly_reply()]

        assert await run_brief(USER, BriefingKind.WEEKLY) is BriefingRunOutcome.SENT

        assert world.stored().form is BriefForm.EDITION
        assert "This is the goodbye brief." in world.voice.call_args.args[1]
        assert world.delivered_to(BriefingKind.WEEKLY)
        assert ladder_state(world.state).wound_down_since == NOW

    async def test_a_week_whose_goal_work_sat_stuck_is_recapped_never_quiet(
        self, world: World
    ) -> None:
        """Replay: a quiet week dropped the stalled growth goal the old weekly recapped."""
        world.calendar = []
        world.todos.rows.clear()
        goal = StatedGoal("Launch Atlas", GoalOrigin.MEMORY, terms=("Atlas",))
        world.goals = [goal]
        world.todos.add(
            own("a2", "Atlas pricing", updated_at=NOW - timedelta(days=9)),
            own("a3", "Atlas press list", updated_at=NOW - timedelta(days=2)),
        )
        world.composer.side_effect = lambda schema, _prompt, **_k: schema.model_validate(
            {"blocks": [PROGRESS]}
        )
        world.replies = [weekly_reply()]

        await run_brief(USER, BriefingKind.WEEKLY)

        assert world.stored().form is BriefForm.EDITION
        assert world.pool is not None
        [atlas] = world.pool.goals
        assert (atlas.statement, atlas.open, atlas.stalled) == (
            "Launch Atlas",
            2,
            ["Atlas pricing"],
        )

    async def test_a_quiet_week_note_goes_on_from_the_last_edition_and_is_counted(
        self, world: World
    ) -> None:
        world.calendar = CalendarGap.UNAVAILABLE
        world.todos.rows.clear()
        # A todo past due is due news, so a quiet week holds only their undated backlog.
        world.todos.add(own("u9", "Sort the garage"))
        edition = stored_brief("2026-10-05", BriefForm.EDITION, BriefingKind.WEEKLY)
        world.briefs_read(
            [stored_brief("2026-10-07", BriefForm.QUIET_NOTE, BriefingKind.WEEKLY), edition]
        )

        await run_brief(USER, BriefingKind.WEEKLY)

        payload = world.stored()
        assert payload.message == expected_note(
            BriefingKind.WEEKLY,
            QuietFacts(
                calendar=CalendarGap.UNAVAILABLE, overdue=0, still_quiet=True, last_edition=edition
            ),
        )
        assert (payload.lede, payload.caption, payload.template_family) == ("", "", None)
        channels = world.delivered_to(BriefingKind.WEEKLY)
        assert channels
        assert world.capture.call_args.args == (
            UserId(USER),
            BriefingSent(
                kind=BriefingKind.WEEKLY,
                form="quiet_note",
                family=None,
                mood=BriefingMood.IDLE,
                item_count=0,
                channel_count=len(channels),
                signal_count=0,
                stamp_collected=False,
                block_kinds=[],
                chart_count=0,
                pool_item_count=1,
                series_count=0,
                source_count=0,
            ),
        )
