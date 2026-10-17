"""When the daily brief runs: 08:00 local, unless the user's quiet hours cover it."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
import time_machine

from app.constants.briefing import (
    DAILY_BRIEFING_WORKFLOW_KEY,
    WEEKLY_DIGEST_CRON,
    WEEKLY_DIGEST_WORKFLOW_KEY,
)
from app.models.notification.notification_models import QuietHours, default_quiet_hours
from app.models.user_models import UserDocument
from app.models.workflow_models import TriggerConfig, TriggerType
from app.services.briefing import schedule

_USER = "64f1c0ffee0000000000abcd"
_TZ = "Asia/Kolkata"
# 07:05 on 14 Oct in Kolkata.
_NOW = datetime(2026, 10, 14, 1, 35, tzinfo=UTC)
_TODAY_START = datetime(2026, 10, 13, 18, 30, tzinfo=UTC)
_TOMORROW_START = datetime(2026, 10, 14, 18, 30, tzinfo=UTC)


class TestDailyBriefingCron:
    @pytest.mark.parametrize(
        ("quiet_hours", "cron"),
        [
            (default_quiet_hours(), "0 8 * * *"),
            (QuietHours(start_hour=22, end_hour=8), "0 8 * * *"),
            (QuietHours(start_hour=13, end_hour=17), "0 8 * * *"),
            (QuietHours(start_hour=0, end_hour=10), "0 10 * * *"),
            (QuietHours(start_hour=23, end_hour=9), "0 9 * * *"),
            (QuietHours(start_hour=8, end_hour=11), "0 11 * * *"),
        ],
        ids=["default", "ends-at-8", "afternoon", "until-10", "past-midnight", "starts-at-8"],
    )
    def test_the_brief_runs_at_8_or_when_quiet_hours_end(
        self, quiet_hours: QuietHours, cron: str
    ) -> None:
        assert schedule.daily_briefing_cron(quiet_hours) == cron


def _workflow(key: str, cron: str, timezone: str = _TZ) -> MagicMock:
    workflow = MagicMock(id=f"wf-{key}", system_workflow_key=key)
    workflow.trigger_config = TriggerConfig(
        type=TriggerType.SCHEDULE, cron_expression=cron, timezone=timezone
    )
    return workflow


def _user(quiet_hours: QuietHours, timezone: str = _TZ) -> UserDocument:
    return UserDocument(id=_USER, timezone=timezone, quiet_hours=quiet_hours)


@dataclass
class Seams:
    find: AsyncMock
    update: AsyncMock
    was_delivered: AsyncMock


@pytest.fixture
def seams(monkeypatch: pytest.MonkeyPatch) -> Iterator[Seams]:
    s = Seams(
        find=AsyncMock(
            return_value=[
                _workflow(DAILY_BRIEFING_WORKFLOW_KEY, "0 8 * * *"),
                _workflow(WEEKLY_DIGEST_WORKFLOW_KEY, WEEKLY_DIGEST_CRON),
            ]
        ),
        update=AsyncMock(return_value=MagicMock()),
        was_delivered=AsyncMock(return_value=False),
    )
    monkeypatch.setattr(schedule.workflow_repository, "find_system_workflows", s.find)
    monkeypatch.setattr(schedule.WorkflowService, "update_workflow", s.update)
    monkeypatch.setattr(schedule.briefing_repository, "was_delivered", s.was_delivered)
    with time_machine.travel(_NOW, tick=False):
        yield s


def _moves(update: AsyncMock) -> dict[str, tuple[str | None, str | None, object]]:
    """Map each moved workflow to its new cron, timezone and next-run base."""
    return {
        call.args[0]: (
            call.args[1].trigger_config.cron_expression,
            call.args[1].trigger_config.timezone,
            call.kwargs["next_run_base"],
        )
        for call in update.await_args_list
    }


class TestResyncBriefingSchedules:
    async def test_new_quiet_hours_move_only_the_daily_brief(self, seams: Seams) -> None:
        await schedule.resync_briefing_schedules(_user(QuietHours(start_hour=0, end_hour=10)))

        seams.find.assert_awaited_once_with(
            _USER, (DAILY_BRIEFING_WORKFLOW_KEY, WEEKLY_DIGEST_WORKFLOW_KEY)
        )
        assert _moves(seams.update) == {"wf-daily_briefing": ("0 10 * * *", _TZ, _TODAY_START)}
        assert seams.update.await_args.args[2] == _USER

    async def test_a_new_timezone_moves_both_briefs_onto_it(self, seams: Seams) -> None:
        await schedule.resync_briefing_schedules(
            _user(default_quiet_hours(), timezone="America/New_York")
        )

        # 21:35 on the 13th in New York: that day, on that clock, is "today".
        new_york_today = datetime(2026, 10, 13, 4, 0, tzinfo=UTC)
        assert _moves(seams.update) == {
            "wf-daily_briefing": ("0 8 * * *", "America/New_York", new_york_today),
            "wf-weekly_digest": (WEEKLY_DIGEST_CRON, "America/New_York", new_york_today),
        }

    async def test_a_brief_already_delivered_today_is_counted_from_tomorrow(
        self, seams: Seams
    ) -> None:
        """A same-day move after today's brief went out never fires a second one."""
        seams.was_delivered.return_value = True

        await schedule.resync_briefing_schedules(_user(QuietHours(start_hour=0, end_hour=10)))

        seams.was_delivered.assert_awaited_once_with(_USER, "2026-10-14", "daily")
        assert _moves(seams.update)["wf-daily_briefing"][2] == _TOMORROW_START

    async def test_a_brief_already_in_place_does_not_stop_the_other_moving(
        self, seams: Seams
    ) -> None:
        seams.find.return_value = [
            _workflow(DAILY_BRIEFING_WORKFLOW_KEY, "0 8 * * *", timezone="America/New_York"),
            _workflow(WEEKLY_DIGEST_WORKFLOW_KEY, WEEKLY_DIGEST_CRON),
        ]

        await schedule.resync_briefing_schedules(
            _user(default_quiet_hours(), timezone="America/New_York")
        )

        assert list(_moves(seams.update)) == ["wf-weekly_digest"]

    async def test_a_user_with_only_the_weekly_recap_has_it_moved(self, seams: Seams) -> None:
        seams.find.return_value = [_workflow(WEEKLY_DIGEST_WORKFLOW_KEY, WEEKLY_DIGEST_CRON)]

        await schedule.resync_briefing_schedules(
            _user(default_quiet_hours(), timezone="America/New_York")
        )

        assert list(_moves(seams.update)) == ["wf-weekly_digest"]

    async def test_quiet_hours_that_leave_8_free_change_nothing(self, seams: Seams) -> None:
        await schedule.resync_briefing_schedules(_user(QuietHours(start_hour=23, end_hour=7)))

        seams.update.assert_not_awaited()

    async def test_a_user_without_the_briefs_has_nothing_to_move(self, seams: Seams) -> None:
        seams.find.return_value = []

        await schedule.resync_briefing_schedules(_user(QuietHours(start_hour=0, end_hour=10)))

        seams.update.assert_not_awaited()

    async def test_a_brief_that_vanished_mid_update_fails_loud(self, seams: Seams) -> None:
        seams.update.return_value = None

        with pytest.raises(LookupError, match="wf-daily_briefing vanished while it was moved"):
            await schedule.resync_briefing_schedules(_user(QuietHours(start_hour=0, end_hour=10)))
