"""When the briefs run: the user's frequency and hour, pushed past quiet hours."""

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
    BriefingFrequency,
)
from app.constants.error_codes import BRIEF_DELIVERY_WORKFLOWS_EXIST
from app.constants.workflows import WorkflowDelivery
from app.db.repositories.briefings import briefing_repository
from app.db.repositories.users import user_repository
from app.db.repositories.workflows import workflow_repository
from app.models.briefing_models import BriefingSchedule
from app.models.quiet_hours_models import DEFAULT_QUIET_HOURS, QuietHours
from app.models.user_models import UserDocument
from app.models.workflow_models import TriggerConfig, TriggerType
from app.services.briefing import schedule
from app.services.workflow.service import WorkflowService
from shared.py.analytics import UserId
from shared.py.analytics.catalog.settings import (
    SettingsBriefingScheduleUpdated,
    SettingsBriefsOffBlocked,
    SettingsBriefsOffResolved,
)

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
            (DEFAULT_QUIET_HOURS, "0 8 * * *"),
            (QuietHours(enabled=True, start_hour=22, end_hour=8), "0 8 * * *"),
            (QuietHours(enabled=True, start_hour=13, end_hour=17), "0 8 * * *"),
            (QuietHours(enabled=True, start_hour=0, end_hour=10), "0 10 * * *"),
            (QuietHours(enabled=True, start_hour=23, end_hour=9), "0 9 * * *"),
            (QuietHours(enabled=True, start_hour=8, end_hour=11), "0 11 * * *"),
            (QuietHours(enabled=False, start_hour=0, end_hour=10), "0 8 * * *"),
        ],
        ids=[
            "default",
            "ends-at-8",
            "afternoon",
            "until-10",
            "past-midnight",
            "starts-at-8",
            "switched-off",
        ],
    )
    def test_the_brief_runs_at_8_or_when_quiet_hours_end(
        self, quiet_hours: QuietHours, cron: str
    ) -> None:
        assert schedule.daily_briefing_cron(BriefingSchedule(), quiet_hours) == cron

    @pytest.mark.parametrize(
        ("briefing", "cron"),
        [
            (BriefingSchedule(frequency=BriefingFrequency.WEEKDAYS), "0 8 * * 1-5"),
            (BriefingSchedule(hour=6), "0 8 * * *"),
            (BriefingSchedule(hour=9), "0 9 * * *"),
            (BriefingSchedule(frequency=BriefingFrequency.WEEKDAYS, hour=23), "0 8 * * 1-5"),
        ],
        ids=["weekdays", "inside-quiet-hours", "own-hour", "weekdays-late"],
    )
    def test_the_brief_runs_on_the_users_days_and_hour(
        self, briefing: BriefingSchedule, cron: str
    ) -> None:
        assert schedule.daily_briefing_cron(briefing, DEFAULT_QUIET_HOURS) == cron


class TestDailyBriefingHour:
    def test_quiet_hours_are_asked_about_the_users_hour_on_an_aware_clock(self) -> None:
        quiet_hours = MagicMock(spec=QuietHours)
        quiet_hours.end_after.return_value = datetime(1, 1, 1, 11, tzinfo=UTC)

        assert schedule.daily_briefing_hour(BriefingSchedule(hour=9), quiet_hours) == 11
        quiet_hours.end_after.assert_called_once_with(datetime(1, 1, 1, 9, tzinfo=UTC))


def _workflow(key: str, cron: str, timezone: str = _TZ, *, activated: bool = True) -> MagicMock:
    workflow = MagicMock(id=f"wf-{key}", system_workflow_key=key, activated=activated)
    workflow.trigger_config = TriggerConfig(
        type=TriggerType.SCHEDULE, cron_expression=cron, timezone=timezone
    )
    return workflow


def _user(
    quiet_hours: QuietHours,
    timezone: str = _TZ,
    frequency: BriefingFrequency = BriefingFrequency.DAILY,
) -> UserDocument:
    return UserDocument(
        id=_USER,
        timezone=timezone,
        quiet_hours=quiet_hours,
        briefing_schedule=BriefingSchedule(frequency=frequency),
    )


@dataclass
class Seams:
    find: AsyncMock
    update: AsyncMock
    was_delivered: AsyncMock
    activate: AsyncMock
    deactivate: AsyncMock
    is_paid: AsyncMock
    capture: MagicMock


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
        activate=AsyncMock(return_value=MagicMock()),
        deactivate=AsyncMock(return_value=MagicMock()),
        is_paid=AsyncMock(return_value=True),
        capture=MagicMock(),
    )
    monkeypatch.setattr(WorkflowService, "activate_workflow", s.activate)
    monkeypatch.setattr(WorkflowService, "deactivate_workflow", s.deactivate)
    monkeypatch.setattr(schedule, "is_paid", s.is_paid)
    monkeypatch.setattr(schedule, "capture", s.capture)
    monkeypatch.setattr(workflow_repository, "find_system_workflows", s.find)
    monkeypatch.setattr(WorkflowService, "update_workflow", s.update)
    monkeypatch.setattr(briefing_repository, "was_delivered", s.was_delivered)
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
        await schedule.resync_briefing_schedules(
            _user(QuietHours(enabled=True, start_hour=0, end_hour=10))
        )

        seams.find.assert_awaited_once_with(
            _USER, (DAILY_BRIEFING_WORKFLOW_KEY, WEEKLY_DIGEST_WORKFLOW_KEY)
        )
        assert _moves(seams.update) == {"wf-daily_briefing": ("0 10 * * *", _TZ, _TODAY_START)}
        assert seams.update.await_args.args[2] == _USER

    async def test_a_new_timezone_moves_both_briefs_onto_it(self, seams: Seams) -> None:
        await schedule.resync_briefing_schedules(
            _user(DEFAULT_QUIET_HOURS, timezone="America/New_York")
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

        await schedule.resync_briefing_schedules(
            _user(QuietHours(enabled=True, start_hour=0, end_hour=10))
        )

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
            _user(DEFAULT_QUIET_HOURS, timezone="America/New_York")
        )

        assert list(_moves(seams.update)) == ["wf-weekly_digest"]

    async def test_a_user_with_only_the_weekly_recap_has_it_moved(self, seams: Seams) -> None:
        seams.find.return_value = [_workflow(WEEKLY_DIGEST_WORKFLOW_KEY, WEEKLY_DIGEST_CRON)]

        await schedule.resync_briefing_schedules(
            _user(DEFAULT_QUIET_HOURS, timezone="America/New_York")
        )

        assert list(_moves(seams.update)) == ["wf-weekly_digest"]

    async def test_quiet_hours_that_leave_8_free_change_nothing(self, seams: Seams) -> None:
        await schedule.resync_briefing_schedules(
            _user(QuietHours(enabled=True, start_hour=23, end_hour=7))
        )

        seams.update.assert_not_awaited()

    async def test_a_user_without_the_briefs_has_nothing_to_move(self, seams: Seams) -> None:
        seams.find.return_value = []

        await schedule.resync_briefing_schedules(
            _user(QuietHours(enabled=True, start_hour=0, end_hour=10))
        )

        seams.update.assert_not_awaited()

    async def test_a_brief_that_vanished_mid_update_fails_loud(self, seams: Seams) -> None:
        seams.update.return_value = None

        with pytest.raises(LookupError, match="wf-daily_briefing vanished while it was moved"):
            await schedule.resync_briefing_schedules(
                _user(QuietHours(enabled=True, start_hour=0, end_hour=10))
            )


def _switched(mock: AsyncMock) -> list[str]:
    return [call.args[0] for call in mock.await_args_list]


class TestTheFrequencySwitchesTheBriefs:
    async def test_weekdays_keeps_both_briefs_and_moves_the_daily_to_monday_to_friday(
        self, seams: Seams
    ) -> None:
        await schedule.resync_briefing_schedules(
            _user(DEFAULT_QUIET_HOURS, frequency=BriefingFrequency.WEEKDAYS)
        )

        assert _moves(seams.update) == {"wf-daily_briefing": ("0 8 * * 1-5", _TZ, _TODAY_START)}
        seams.activate.assert_not_awaited()
        seams.deactivate.assert_not_awaited()

    async def test_weekly_only_switches_off_the_daily_brief_alone(self, seams: Seams) -> None:
        await schedule.resync_briefing_schedules(
            _user(DEFAULT_QUIET_HOURS, frequency=BriefingFrequency.WEEKLY_ONLY)
        )

        assert _switched(seams.deactivate) == ["wf-daily_briefing"]
        assert seams.deactivate.await_args.args[1] == _USER
        seams.activate.assert_not_awaited()

    async def test_off_switches_off_both_briefs(self, seams: Seams) -> None:
        await schedule.resync_briefing_schedules(
            _user(DEFAULT_QUIET_HOURS, frequency=BriefingFrequency.OFF)
        )

        assert _switched(seams.deactivate) == ["wf-daily_briefing", "wf-weekly_digest"]

    async def test_daily_switches_the_briefs_back_on_for_a_paying_user(self, seams: Seams) -> None:
        seams.find.return_value = [
            _workflow(DAILY_BRIEFING_WORKFLOW_KEY, "0 8 * * *", activated=False),
            _workflow(WEEKLY_DIGEST_WORKFLOW_KEY, WEEKLY_DIGEST_CRON, activated=False),
        ]

        await schedule.resync_briefing_schedules(_user(DEFAULT_QUIET_HOURS))

        assert _switched(seams.activate) == ["wf-daily_briefing", "wf-weekly_digest"]
        seams.is_paid.assert_awaited_with(_USER)

    async def test_a_free_users_briefs_stay_off(self, seams: Seams) -> None:
        seams.is_paid.return_value = False
        seams.find.return_value = [
            _workflow(DAILY_BRIEFING_WORKFLOW_KEY, "0 8 * * *", activated=False),
        ]

        await schedule.resync_briefing_schedules(_user(DEFAULT_QUIET_HOURS))

        seams.activate.assert_not_awaited()

    async def test_a_brief_that_vanished_mid_switch_fails_loud(self, seams: Seams) -> None:
        seams.deactivate.return_value = None

        with pytest.raises(LookupError, match="wf-daily_briefing vanished while it was switched"):
            await schedule.resync_briefing_schedules(
                _user(DEFAULT_QUIET_HOURS, frequency=BriefingFrequency.OFF)
            )


class TestSetBriefingSchedule:
    async def test_the_schedule_is_stored_the_briefs_moved_and_the_change_reported(
        self, seams: Seams, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stored = _user(DEFAULT_QUIET_HOURS, frequency=BriefingFrequency.WEEKLY_ONLY)
        store = AsyncMock()
        monkeypatch.setattr(user_repository, "set_briefing_schedule", store)
        get = AsyncMock(return_value=stored)
        monkeypatch.setattr(user_repository, "get", get)
        capture = MagicMock()
        monkeypatch.setattr(schedule, "capture", capture)
        log = MagicMock()
        monkeypatch.setattr(schedule, "log", log)
        wanted = BriefingSchedule(frequency=BriefingFrequency.WEEKLY_ONLY, hour=9)

        result = await schedule.set_briefing_schedule(_USER, wanted, via="agent")

        assert result is stored
        store.assert_awaited_once_with(_USER, wanted)
        get.assert_awaited_once_with(_USER)
        log.audit.assert_called_once_with(
            "briefing schedule updated",
            actor=_USER,
            frequency=BriefingFrequency.WEEKLY_ONLY,
            hour=9,
            via="agent",
        )
        assert _switched(seams.deactivate) == ["wf-daily_briefing"]
        capture.assert_called_once_with(
            UserId(_USER),
            SettingsBriefingScheduleUpdated(frequency="weekly_only", hour=9, via="agent"),
        )

    async def test_an_unknown_user_fails_loud_and_reports_nothing(
        self, seams: Seams, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(user_repository, "set_briefing_schedule", AsyncMock())
        monkeypatch.setattr(user_repository, "get", AsyncMock(return_value=None))
        capture = MagicMock()
        monkeypatch.setattr(schedule, "capture", capture)

        with pytest.raises(LookupError) as raised:
            await schedule.set_briefing_schedule(_USER, BriefingSchedule(), via="settings")

        assert str(raised.value) == f"Cannot schedule briefs for unknown user {_USER}"

        capture.assert_not_called()
        seams.update.assert_not_awaited()


class TestDescribeBriefingSchedule:
    @pytest.mark.parametrize(
        ("frequency", "hour", "text"),
        [
            (BriefingFrequency.DAILY, 9, "a daily brief every day at 09:00"),
            (BriefingFrequency.WEEKDAYS, 6, "a daily brief Monday to Friday at 08:00"),
            (BriefingFrequency.WEEKLY_ONLY, 9, "only the Sunday evening weekly digest"),
            (BriefingFrequency.OFF, 9, "no briefs at all"),
        ],
    )
    def test_it_names_the_briefs_and_the_hour_they_really_land(
        self, frequency: BriefingFrequency, hour: int, text: str
    ) -> None:
        user = UserDocument(briefing_schedule=BriefingSchedule(frequency=frequency, hour=hour))

        assert schedule.describe_briefing_schedule(user).startswith(text)


class TestTurningBriefsOff:
    @pytest.fixture
    def delivering(self, seams: Seams, monkeypatch: pytest.MonkeyPatch) -> MagicMock:
        monkeypatch.setattr(user_repository, "set_briefing_schedule", AsyncMock())
        monkeypatch.setattr(
            user_repository,
            "get",
            AsyncMock(return_value=_user(DEFAULT_QUIET_HOURS, frequency=BriefingFrequency.OFF)),
        )
        on_brief = MagicMock(id="wf-digest", title="Digest")
        find = AsyncMock(return_value=[on_brief])
        monkeypatch.setattr(workflow_repository, "find_brief_delivery_for_user", find)
        return find

    async def test_each_brief_workflow_moves_to_its_chosen_delivery_and_the_move_is_reported(
        self, seams: Seams, delivering: MagicMock
    ) -> None:
        await schedule.set_briefing_schedule(
            _USER,
            BriefingSchedule(frequency=BriefingFrequency.OFF),
            via="agent",
            workflow_deliveries={"wf-digest": WorkflowDelivery.SILENT},
        )

        delivering.assert_awaited_once_with(_USER)
        [call] = seams.update.await_args_list
        assert call.args[0] == "wf-digest"
        assert call.args[1].delivery is WorkflowDelivery.SILENT
        assert call.args[2] == _USER
        seams.capture.assert_any_call(
            UserId(_USER),
            SettingsBriefsOffResolved(moved_to_now=0, moved_to_silent=1, via="agent"),
        )

    async def test_a_brief_workflow_with_no_chosen_delivery_blocks_turning_briefs_off(
        self, seams: Seams, delivering: MagicMock
    ) -> None:
        with pytest.raises(schedule.BriefDeliveryWorkflowsError):
            await schedule.set_briefing_schedule(
                _USER, BriefingSchedule(frequency=BriefingFrequency.OFF), via="settings"
            )

        seams.update.assert_not_awaited()
        seams.capture.assert_called_once_with(
            UserId(_USER), SettingsBriefsOffBlocked(workflow_count=1, via="settings")
        )

    async def test_the_refusal_names_each_workflow_and_what_to_do_about_it(
        self, seams: Seams, delivering: MagicMock
    ) -> None:
        delivering.return_value = [
            MagicMock(id="wf-a", title="Digest"),
            MagicMock(id="wf-b", title="Standup"),
        ]

        with pytest.raises(schedule.BriefDeliveryWorkflowsError) as raised:
            await schedule.set_briefing_schedule(
                _USER, BriefingSchedule(frequency=BriefingFrequency.OFF), via="settings"
            )

        error = raised.value
        assert error.message == "2 workflows send their results to your brief"
        assert error.why == "With briefs off, their results would go nowhere"
        assert error.fix == (
            "Set Digest, Standup to Tell me now or Don't notify me, then turn briefs off"
        )
        assert error.status_code == 409
        assert error.code == BRIEF_DELIVERY_WORKFLOWS_EXIST
        assert error.public == {
            "workflows": [{"id": "wf-a", "title": "Digest"}, {"id": "wf-b", "title": "Standup"}]
        }

    async def test_one_blocking_workflow_is_named_in_the_singular(
        self, seams: Seams, delivering: MagicMock
    ) -> None:
        with pytest.raises(schedule.BriefDeliveryWorkflowsError) as raised:
            await schedule.set_briefing_schedule(
                _USER, BriefingSchedule(frequency=BriefingFrequency.OFF), via="settings"
            )

        assert raised.value.message == "1 workflow sends its results to your brief"

    async def test_a_workflow_that_vanished_mid_move_fails_loud(
        self, seams: Seams, delivering: MagicMock
    ) -> None:
        seams.update.return_value = None

        with pytest.raises(
            LookupError, match="^Workflow wf-digest vanished while it was moved off the brief$"
        ):
            await schedule.set_briefing_schedule(
                _USER,
                BriefingSchedule(frequency=BriefingFrequency.OFF),
                via="settings",
                workflow_deliveries={"wf-digest": WorkflowDelivery.NOW},
            )

    async def test_the_report_counts_the_workflows_moved_to_each_delivery(
        self, seams: Seams, delivering: MagicMock
    ) -> None:
        delivering.return_value = [
            MagicMock(id="wf-a", title="A"),
            MagicMock(id="wf-b", title="B"),
            MagicMock(id="wf-c", title="C"),
        ]

        await schedule.set_briefing_schedule(
            _USER,
            BriefingSchedule(frequency=BriefingFrequency.OFF),
            via="settings",
            workflow_deliveries={
                "wf-a": WorkflowDelivery.NOW,
                "wf-b": WorkflowDelivery.NOW,
                "wf-c": WorkflowDelivery.SILENT,
            },
        )

        seams.capture.assert_any_call(
            UserId(_USER),
            SettingsBriefsOffResolved(moved_to_now=2, moved_to_silent=1, via="settings"),
        )
