"""What a run reads, for whom and over which window, and what it records."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import call

from prometheus_client import REGISTRY
import pytest
from tests.briefing_run_world import (
    CHART,
    DATE,
    DAY_START,
    DIGEST_REPORT,
    NOW,
    ORCHESTRATED,
    USER,
    World,
    brief_work,
    completions,
    composed,
    delivered,
    held,
    idle_days,
    own,
    stored_brief,
    with_block,
)
from tests.helpers import captured_wide_event

from app.agents.prompts.briefing_prompts import VoiceSituation
from app.constants.briefing import BriefForm, BriefingKind
from app.models.brief_payload_models import BriefingMood
from app.models.notification.notification_models import (
    ChannelDeliveryStatus,
    NotificationStatus,
)
from app.models.todo_models import ExternalRefSource
from app.services.briefing.pipeline import run_brief
from shared.py.analytics import UserId
from shared.py.analytics.catalog.briefings import BriefingSent

pytestmark = pytest.mark.usefixtures("fake_redis")


class TestTheDailyRunReads:
    """Every read is scoped to the user and the last local day."""

    async def test_the_producers_read_this_user_since_the_last_local_day(
        self, world: World
    ) -> None:
        world.held = [held("h1", "Paper digest", DIGEST_REPORT)]

        await run_brief(USER, BriefingKind.DAILY)

        assert world.approvals.calls_to("list_pending_for_user") == [call(USER)]
        assert world.hil.calls_to("list_pending_for_user") == [call(USER, NOW)]
        executions = world.executions.calls_to("list_since")
        assert executions and {c.args for c in executions} == {(USER, DAY_START)}
        assert {c.args[0] for c in world.todos.calls_to("find_latest_by_external_ref")} == {USER}

    @pytest.mark.parametrize(
        ("sent_days_ago", "since"),
        [
            # Friday's brief, read on Monday: the weekend is in the look-back.
            (3, NOW - timedelta(days=3)),
            # Back after three weeks: the look-back stops at a week.
            (21, DAY_START - timedelta(days=6)),
        ],
    )
    async def test_the_look_back_starts_at_the_last_brief_within_a_week(
        self, world: World, sent_days_ago: int, since: datetime
    ) -> None:
        sent = NOW - timedelta(days=sent_days_ago)
        last = stored_brief(sent.date().isoformat(), BriefForm.EDITION)
        world.briefs_read([last.model_copy(update={"created_at": sent})])
        world.todos.rows.clear()
        world.todos.add(
            *completions(
                user=[
                    own("in", "Done after it", completed_at=since + timedelta(minutes=1)),
                    own("out", "Done before it", completed_at=since - timedelta(minutes=1)),
                ]
            )
        )

        await run_brief(USER, BriefingKind.DAILY)

        lookback = world.voice_prompt.call_args.kwargs["blocks"].lookback
        assert "The user finished: Done after it" in lookback
        assert "Done before it" not in lookback
        assert world.stored().tallies.done_by_you == 1

    async def test_every_read_is_for_this_user_and_the_last_local_day(self, world: World) -> None:
        await run_brief(USER, BriefingKind.DAILY)

        assert world.briefings.calls_to("get_before_date") == [
            call(USER, kind=BriefingKind.DAILY, before_date=DATE)
        ]
        assert world.briefings.calls_to("has_daily_briefing") == [call(USER)]
        assert call(USER, limit=10, kind=BriefingKind.DAILY) in world.briefings.calls_to(
            "list_recent"
        )
        # One read of what got done, from the series window's first day (before the look-back).
        assert world.todos.calls_to("list_completed_since") == [
            call(USER, since=datetime(2026, 10, 7, 18, 30, tzinfo=UTC))
        ]
        assert world.pending.calls_to("list_for_user") == [call(USER, sort=[("created_at", 1)])]
        [replies] = world.conversations.calls_to("list_bot_replies_since")
        assert replies.args == (USER, DAY_START)
        prompt_args = world.voice_prompt.call_args.kwargs
        assert prompt_args["date_local"] == DATE
        blocks = prompt_args["blocks"]
        assert (blocks.goal, blocks.replies) == (
            "- Ship v2",
            "No replies since the last brief.",
        )
        # The look-back reads the run's own read of what got done: the user's Gym.
        assert "The user finished: Gym" in blocks.lookback
        assert prompt_args["situation"] == VoiceSituation()
        # An active day for a reader off the ladder leaves it off.
        assert idle_days(world) == 0

    async def test_the_pool_reads_this_users_week_ending_today(self, world: World) -> None:
        await run_brief(USER, BriefingKind.DAILY)

        # Seven local days ending today: 8 Oct, Kolkata midnight, to the midnight after 14 Oct.
        week_start = datetime(2026, 10, 7, 18, 30, tzinfo=UTC)
        world.fetch_calendar.assert_awaited_once_with(
            USER, week_start, datetime(2026, 10, 14, 18, 30, tzinfo=UTC)
        )
        assert world.todos.calls_to("list_completed_since") == [call(USER, since=week_start)]
        assert world.todos.calls_to("list_external_ref_activity_since") == [
            call(USER, ExternalRefSource.GMAIL_THREAD, since=week_start)
        ]
        assert world.executions.calls_to("list_run_moments_since") == [
            call(USER, week_start, exclude_workflow_ids=[])
        ]
        assert world.verdicts.calls_to("list_since") == [call(USER, since=NOW - timedelta(days=1))]


class TestWhatARunRecords:
    async def test_the_wide_event_tags_the_run_and_records_its_pool_and_where_it_went(
        self, world: World
    ) -> None:
        world.track(brief_work())

        async with captured_wide_event() as event:
            await run_brief(USER, BriefingKind.DAILY)

        assert (event["component"], event["operation"], event["user_id"]) == (
            "briefing",
            "run_brief",
            USER,
        )
        assert event["brief_composition"]["pool_items"] == 3
        briefing = event["briefing"]
        assert briefing["channels"] == [*ORCHESTRATED, "telegram"]
        assert (briefing["pushed"], briefing["form"]) == (True, "edition")
        assert (briefing["kind"], briefing["outcome"]) == ("daily", "sent")

    async def test_an_email_wanted_and_not_sent_is_a_warning(self, world: World) -> None:
        world.notify.return_value = SimpleNamespace(
            channels=[
                delivered("inapp"),
                ChannelDeliveryStatus(channel_type="email", status=NotificationStatus.FAILED),
            ]
        )

        async with captured_wide_event() as event:
            await run_brief(USER, BriefingKind.DAILY)

        assert [w["msg"] for w in event["warnings"]].count("briefing.email_not_sent") == 1

    async def test_every_run_is_counted_by_kind_and_how_it_ended(self, world: World) -> None:
        def count(outcome: str) -> float:
            labels = {"kind": "daily", "outcome": outcome}
            return REGISTRY.get_sample_value("gaia_brief_run_total", labels) or 0.0

        sent, failed = count("sent"), count("failed")
        await run_brief(USER, BriefingKind.DAILY)
        world.briefs.clear()
        world.notify.side_effect = RuntimeError("orchestrator down")
        with pytest.raises(RuntimeError, match="orchestrator down"):
            await run_brief(USER, BriefingKind.DAILY)

        assert (count("sent") - sent, count("failed") - failed) == (1.0, 1.0)

    async def test_only_channels_that_reached_the_user_are_recorded_and_counted(
        self, world: World
    ) -> None:
        world.chat = None
        world.notify.return_value = SimpleNamespace(
            channels=[
                delivered("inapp"),
                ChannelDeliveryStatus(channel_type="email", status=NotificationStatus.FAILED),
                ChannelDeliveryStatus(
                    channel_type="telegram", status=NotificationStatus.DELIVERED, skipped=True
                ),
            ]
        )

        await run_brief(USER, BriefingKind.DAILY)

        assert world.delivered_to() == ["inapp"]
        assert world.capture.call_args.args[1].channel_count == 1

    async def test_a_sent_brief_reports_one_event_counting_what_it_holds(
        self, world: World
    ) -> None:
        world.todos.rows.clear()
        world.track(brief_work())

        await run_brief(USER, BriefingKind.DAILY)

        payload = world.stored()
        assert world.delivered_to() == [*ORCHESTRATED, "telegram"]
        world.capture.assert_called_once_with(
            UserId(USER),
            BriefingSent(
                kind=BriefingKind.DAILY,
                form="edition",
                family=payload.template_family,
                mood=BriefingMood.PACKED,
                item_count=2,
                channel_count=3,
                signal_count=0,
                stamp_collected=payload.new_stamp is not None,
                block_kinds=["items", "items"],
                chart_count=0,
                pool_item_count=3,
                series_count=1,
                source_count=1,
            ),
        )

    async def test_a_chart_in_the_brief_is_counted_among_its_blocks(self, world: World) -> None:
        world.track(brief_work())
        world.composer.side_effect = with_block(
            composed({"Waiting": ["Approve the Priya reply"]}), CHART
        )

        await run_brief(USER, BriefingKind.DAILY)

        event = world.capture.call_args.args[1]
        assert (event.block_kinds, event.chart_count) == (["items", "chart"], 1)
