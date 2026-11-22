"""A weekly digest run: the week recapped, the week ahead voiced, pushed to every channel."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import call

import pytest
from tests.briefing_run_world import (
    DATE,
    DORMANT_SINCE,
    FRIDAY_PITCH,
    LOGIN,
    NOW,
    TODAY_START,
    TZ,
    USER,
    WEEK_AHEAD_END,
    WEEK_START,
    World,
    a_full_week,
    completions,
    composed,
    dormant,
    fact_id,
    own,
    own_open,
    remembered,
    scouted,
    skipped,
    stored_brief,
    tracked,
    weekly_reply,
)
from tests.helpers import captured_wide_event

from app.agents.llm.client import metered_config
from app.constants.briefing import (
    MAX_VOICE_ATTEMPTS,
    WEEKLY_KICKER,
    BriefForm,
    BriefingKind,
    BriefingRunOutcome,
)
from app.constants.desk_buckets import DeskBucket
from app.constants.notifications import (
    NotificationKind,
)
from app.constants.todos import TodoCompleter
from app.models.brief_composition_models import SectionBlock
from app.models.brief_payload_models import (
    BriefingTallies,
)
from app.models.brief_slot_models import CountName
from app.models.calendar_models import GoogleCalendarEventDateTime, GoogleCalendarEventResource
from app.models.email_verdict_models import EmailVerdictDocument
from app.models.scout_models import (
    ScoutSkipReason,
)
from app.models.short_link_models import ShortLinkTargetType
from app.services.briefing.facts import WEEK_AHEAD
from app.services.briefing.pipeline import run_brief
from app.services.briefing.prose import reader_block
from app.services.briefing.wind_down import ladder_state
from app.services.briefing.work import TrackedWork

pytestmark = pytest.mark.usefixtures("fake_redis")


class TestAWeeklyDigest:
    async def test_the_digest_is_stored_and_delivered_as_weekly_and_always_pushed(
        self, world: World
    ) -> None:
        world.replies = [weekly_reply()]

        assert await run_brief(USER, BriefingKind.WEEKLY) is BriefingRunOutcome.SENT

        payload = world.stored()
        # Masthead, date and mood come from code, whatever the model wrote.
        assert (payload.kicker, payload.date, payload.mood) == (WEEKLY_KICKER, DATE, "weekly")
        assert world.today(BriefingKind.WEEKLY) is not None
        assert payload.template_family == "weekly"
        # Code counts the week by day, Monday first: the user's Gym, done today, a Wednesday.
        assert payload.week is not None
        assert [(d.you, d.gaia) for d in payload.week.days] == [(0, 0)] * 2 + [(1, 0)] + [
            (0, 0)
        ] * 4
        # The tallies count the week's completions themselves: the user's one todo.
        assert payload.tallies == BriefingTallies(done_by_you=1, done_by_gaia=0)
        assert payload.headline == "A good week"
        request = world.notify.await_args.args[0]
        assert request.details.kind == NotificationKind.BRIEFING_WEEKLY
        assert request.content.body == payload.message == "Gym"
        # The recap is always pushed: it reaches the chat app, not only the in-app page.
        assert world.post.await_args.kwargs["origin"] == "weekly brief"
        assert world.pending.consumed == []

    async def test_code_builds_the_sections_from_the_weeks_candidates(self, world: World) -> None:
        """Regression: the model wrote the whole weekly payload, its sections and items included."""
        a_full_week(world)
        world.replies = [weekly_reply()]
        world.composer.side_effect = composed(
            {
                "Needs you": ["CRM sync failed"],
                "You finished": ["Send the deck"],
                "GAIA's work": ["Investor deck"],
            }
        )

        await run_brief(USER, BriefingKind.WEEKLY)

        payload = world.stored()
        assert [(s.title, [(i.text, i.kind) for i in s.items]) for s in payload.sections] == [
            ("Needs you", [("CRM sync failed", "failed")]),
            ("You finished", [("Send the deck", "lookback")]),
            ("GAIA's work", [("Investor deck", "lookback")]),
        ]
        assert payload.message == "CRM sync failed\nSend the deck\nInvestor deck\nPitch to Accel"
        assert payload.week is not None
        assert (payload.week.days[2].you, payload.week.days[2].gaia) == (1, 1)
        assert payload.week.ahead == [FRIDAY_PITCH]
        assert payload.sources_read == ["Google Calendar"]
        assert {c.args[1] for c in world.executions.calls_to("list_since")} == {WEEK_START}

    async def test_the_weekly_reads_this_users_week_ahead_once(self, world: World) -> None:
        await run_brief(USER, BriefingKind.WEEKLY)

        # One read: this week from Monday, then the seven local days from tomorrow to 22 Oct.
        world.fetch_calendar.assert_awaited_once_with(
            USER, WEEK_START, datetime(2026, 10, 21, 18, 30, tzinfo=UTC)
        )

    async def test_a_lead_the_weekly_edition_cannot_draw_moves_to_the_briefs_page(
        self, world: World
    ) -> None:
        a_full_week(world)
        world.replies = [weekly_reply()]
        world.composer.side_effect = composed(
            {"GAIA's work": ["Investor deck"]}, lead=("CRM sync failed", "I can rerun it.")
        )

        await run_brief(USER, BriefingKind.WEEKLY)

        payload = world.stored()
        assert payload.undrawn == [SectionBlock(kind="lead", section=0)]
        assert payload.blocks == [SectionBlock(kind="items", section=1)]
        assert [s.items[0].text for s in payload.sections] == ["CRM sync failed", "Investor deck"]

    async def test_a_digest_that_leaves_out_its_lead_is_sent_back_then_led_by_its_plain_line(
        self, world: World
    ) -> None:
        a_full_week(world)
        world.composer.side_effect = composed(
            {"GAIA's work": ["Investor deck"]}, lead=("CRM sync failed", "I can rerun it.")
        )
        world.replies = [weekly_reply(message="Good week.")]

        await run_brief(USER, BriefingKind.WEEKLY)

        assert world.writing is not None
        assert world.writing.lead == fact_id(world.writing, "CRM sync failed")
        assert world.voice.await_count == MAX_VOICE_ATTEMPTS
        assert world.stored().message == "- CRM sync failed\n\nGood week."

    async def test_the_week_ahead_is_voiced_by_its_days_facts(self, world: World) -> None:
        a_full_week(world)
        world.replies = [
            weekly_reply(
                lede="Then [[fact:<fact of Pitch to Accel>]] on Friday at "
                "[[fact:<fact of Pitch to Accel>.time]]."
            )
        ]

        await run_brief(USER, BriefingKind.WEEKLY)

        assert world.fact_sources is not None and world.fact_sources.span is WEEK_AHEAD
        assert world.stored().lede == "Then Pitch to Accel on Friday at 3:00 PM."

    async def test_a_frequency_word_its_facts_carry_is_kept(self, world: World) -> None:
        world.todos.rows.clear()
        world.todos.add(*completions(user=[own("u1", "Send the usual deck")]))
        world.replies = [weekly_reply(lede="The usual deck went out.")]

        await run_brief(USER, BriefingKind.WEEKLY)

        assert world.voice.await_count == 1
        assert world.stored().lede == "The usual deck went out."

    async def test_the_weekly_is_sent_back_for_a_line_a_recent_daily_printed(
        self, world: World
    ) -> None:
        """The weekly passed no recent lines and the daily read only dailies."""
        world.briefs_read([stored_brief("2026-10-13", BriefForm.EDITION, headline="A good week")])
        world.replies = [weekly_reply(), weekly_reply(headline="A full week")]

        await run_brief(USER, BriefingKind.WEEKLY)

        assert world.briefings.calls_to("list_recent") == [call(USER, limit=5)]
        assert world.writing is not None and world.writing.recent.headlines == ["A good week"]
        assert world.voice.await_count == 2
        assert world.stored().headline == "A full week"

    async def test_gaias_week_is_recapped_from_its_own_work_and_mail_alone(
        self, world: World
    ) -> None:
        finished = [
            tracked(f"g{n}", f"Research {n}", updated_at=NOW - timedelta(days=1)) for n in range(6)
        ]
        world.todos.rows.clear()
        world.todos.add(*completions(finished))
        # Meeting hours and the last day's mail sort are not GAIA's week: neither is counted.
        world.fetch_calendar.side_effect = lambda *_: [
            GoogleCalendarEventResource(
                summary="Board",
                start=GoogleCalendarEventDateTime(dateTime="2026-10-13T10:00:00+05:30"),
                end=GoogleCalendarEventDateTime(dateTime="2026-10-13T11:00:00+05:30"),
            )
        ]
        world.verdicts.rows = [
            EmailVerdictDocument(
                user_id=USER, message_id="m1", answers={}, bucket=DeskBucket.REPLY, created_at=NOW
            )
        ]
        world.replies = [weekly_reply(lede="I finished [[series:gaia_finished.total]] tasks.")]

        await run_brief(USER, BriefingKind.WEEKLY)

        assert world.fact_sources is not None and world.fact_sources.recap is not None
        assert [s.id for s in world.fact_sources.recap.series] == ["gaia_finished"]
        assert world.stored().lede == "I finished 6 tasks."

    async def test_every_read_is_this_users_over_the_week_and_the_week_ahead(
        self, world: World
    ) -> None:
        a_full_week(world)
        world.scouts = [*scouted(LOGIN), skipped("Notion")]
        world.briefs_read(
            [stored_brief("2026-10-13", BriefForm.EDITION, message="Priya replied overnight.")]
        )
        world.memory = [remembered("ENG-12", "In Progress")]
        world.todos.add(
            own("o1", "File the VAT return", due_date=NOW + timedelta(days=1), updated_at=NOW)
        )
        world.replies = [
            weekly_reply(
                message="[The deck](fact:<fact of Investor deck>) is done. "
                "[[fact:<fact of Investor deck>]] shipped, "
                "[Priya](fact:<fact of Fix the login redirect>) waits."
            )
        ]

        await run_brief(USER, BriefingKind.WEEKLY)

        assert world.voice.await_args.kwargs["config"] == metered_config(USER)
        assert world.reminders.calls_to("find_scheduled_between") == [
            call(USER, TODAY_START, WEEK_AHEAD_END)
        ]
        assert world.todos.calls_to("list_open_user_todos") == [call(USER, limit=0)]
        seen = world.memories.calls_to("record_seen")
        assert seen and all(c.args[0] == USER and c.args[2] == NOW for c in seen)
        assert world.pool is not None
        assert world.pool.context.recent_openings == ["Priya replied overnight."]
        prompt_args = world.weekly_prompt.call_args.kwargs
        assert prompt_args["date_local"] == DATE
        assert prompt_args["blocks"].reader == reader_block(world.user)
        assert prompt_args["blocks"].signals
        assert [(c.signal.title, c.memory) for _, c in world.signals if c.signal] == [
            (LOGIN.title, remembered("ENG-12", "In Progress"))
        ]
        assert world.writing is not None
        counts = world.writing.values.counts
        assert counts[CountName.OPEN_TODOS] == 1
        assert CountName.OVERDUE_TODOS not in counts
        assert world.fact("File the VAT return").time == "Thu Oct 15"
        world.mint.assert_any_await(USER, ShortLinkTargetType.TODO_DELIVERABLE, "g1")
        payload = world.stored()
        assert [(u.app, u.reason) for u in payload.sources_unavailable] == [
            ("Notion", ScoutSkipReason.FAILED)
        ]
        assert payload.week is not None and payload.week.ahead == [FRIDAY_PITCH]
        assert world.capture.call_args.args[1].signal_count == 1
        [login] = [r for r in world.memory if r.external_id == LOGIN.external_id]
        assert (login.times_shown, login.last_shown) == (2, NOW)

    async def test_what_waits_on_the_user_reaches_the_weekly_and_is_remembered_as_shown(
        self, world: World
    ) -> None:
        """The weekly read only failed runs, completions and the calendar, and scouts with no signals."""
        world.track(TrackedWork(blocked=[tracked("b1", "Approve the Priya reply")]))
        world.scouts = scouted(LOGIN)
        world.todos.add(*own_open(80, overdue=70))
        world.composer.side_effect = composed(
            {"Needs you": ["Approve the Priya reply", LOGIN.title]}
        )
        world.replies = [weekly_reply(lede="Two things wait on you.")]

        await run_brief(USER, BriefingKind.WEEKLY)

        assert world.fact("Approve the Priya reply").kind is not None
        assert world.fact(LOGIN.title).title == LOGIN.title
        assert world.writing is not None
        assert world.writing.values.counts[CountName.OVERDUE_TODOS] == 70
        shown = {r.external_id: r.times_shown for r in world.memory}
        assert (shown["todo:b1"], shown[LOGIN.external_id]) == (1, 1)

    async def test_the_week_is_read_for_this_user_from_monday_in_one_window(
        self, world: World
    ) -> None:
        deck = tracked("g0", "Deck", canvas_content="# Deck\nFinal numbers in")
        gaia = [deck, *[tracked(f"g{i}", f"G{i}") for i in range(1, 16)]]
        completed = completions(gaia, [own(f"u{i}", f"U{i}") for i in range(16)])
        world.todos.rows.clear()
        world.todos.add(*completed)
        world.replies = [weekly_reply()]
        world.composer.side_effect = composed({"This week": ["Deck", "U15"]})

        async with captured_wide_event() as event:
            await run_brief(USER, BriefingKind.WEEKLY)

        # The sections, the prose, the tallies and the week's days read the same completions.
        payload = world.stored()
        assert payload.tallies == BriefingTallies(done_by_you=16, done_by_gaia=16)
        assert payload.week is not None
        assert (payload.week.days[2].you, payload.week.days[2].gaia) == (16, 16)
        assert world.pool is not None
        finished = {c.title: c.finished_by for c in world.pool.items.values()}
        assert (finished["Deck"], finished["U15"]) == (TodoCompleter.GAIA, TodoCompleter.USER)
        # The week's series run Monday to today, the calendar's among them.
        assert (
            call(USER, WEEK_START, datetime(2026, 10, 21, 18, 30, tzinfo=UTC))
            in world.fetch_calendar.await_args_list
        )
        assert world.todos.calls_to("list_completed_since") == [call(USER, since=WEEK_START)]
        assert (payload.hue, payload.generated_at) == (79, "7:05 AM")
        assert (
            event["brief_composition"]["pool_items"],
            event["brief_composition"]["items"],
            event["brief_composition"]["uncomposed"],
        ) == (32, 2, 30)
        assert len(payload.uncomposed) == 30

    async def test_the_goals_and_the_pool_are_the_users_and_the_weeks(self, world: World) -> None:
        world.replies = [weekly_reply()]
        world.user.name = "Ada Lovelace"
        world.calendar = [FRIDAY_PITCH]

        await run_brief(USER, BriefingKind.WEEKLY)

        assert {c.args for c in world.executions.calls_to("list_since")} == {(USER, WEEK_START)}
        assert world.composer.await_args.kwargs["config"] == metered_config(USER)
        assert world.pool is not None
        context = world.pool.context
        assert (context.reader, str(context.clock.tz), context.calendar) == ("Ada", TZ, 1)
        assert context.calendar_span == WEEK_AHEAD.words
        assert world.weekly_prompt.call_args.kwargs["blocks"].goal == "- Ship v2"
        payload = world.stored()
        assert [b.kind for b in payload.blocks] == ["items"]
        assert payload.uncomposed == []

    @pytest.mark.parametrize("came_back", [False, True])
    async def test_a_dormant_loop_wakes_only_on_the_users_own_activity_never_the_digest(
        self, world: World, came_back: bool
    ) -> None:
        dormant(world)
        world.replies = [weekly_reply()]
        world.user.last_active_at = DORMANT_SINCE + timedelta(days=1 if came_back else -1)

        outcome = await run_brief(USER, BriefingKind.WEEKLY)

        assert outcome is (BriefingRunOutcome.SENT if came_back else BriefingRunOutcome.DORMANT)
        assert (ladder_state(world.state).wound_down_since is None) is came_back
        assert (world.today() is not None) is came_back
