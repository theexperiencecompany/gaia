"""When the daily brief runs: 08:00 local, unless the user's quiet hours cover it."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.constants.briefing import DAILY_BRIEFING_WORKFLOW_KEY
from app.models.notification.notification_models import QuietHours, default_quiet_hours
from app.models.workflow_models import TriggerConfig, TriggerType
from app.services.briefing import schedule

_USER = "64f1c0ffee0000000000abcd"


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


def _workflow(cron: str) -> MagicMock:
    workflow = MagicMock(id="wf-brief")
    workflow.trigger_config = TriggerConfig(
        type=TriggerType.SCHEDULE, cron_expression=cron, timezone="Asia/Kolkata"
    )
    return workflow


class TestResyncDailyBriefingSchedule:
    async def test_new_quiet_hours_move_the_brief(self, monkeypatch: pytest.MonkeyPatch) -> None:
        find = AsyncMock(return_value=_workflow("0 8 * * *"))
        update = AsyncMock(return_value=MagicMock())
        monkeypatch.setattr(schedule.workflow_repository, "find_system_workflow", find)
        monkeypatch.setattr(schedule.WorkflowService, "update_workflow", update)

        await schedule.resync_daily_briefing_schedule(_USER, QuietHours(start_hour=0, end_hour=10))

        find.assert_awaited_once_with(_USER, DAILY_BRIEFING_WORKFLOW_KEY)
        workflow_id, request, user_id = update.await_args.args
        assert (workflow_id, user_id) == ("wf-brief", _USER)
        assert request.trigger_config.cron_expression == "0 10 * * *"
        assert request.trigger_config.timezone == "Asia/Kolkata"

    async def test_quiet_hours_that_leave_8_free_change_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        update = AsyncMock()
        monkeypatch.setattr(
            schedule.workflow_repository,
            "find_system_workflow",
            AsyncMock(return_value=_workflow("0 8 * * *")),
        )
        monkeypatch.setattr(schedule.WorkflowService, "update_workflow", update)

        await schedule.resync_daily_briefing_schedule(_USER, QuietHours(start_hour=23, end_hour=7))

        update.assert_not_awaited()

    async def test_a_user_without_the_brief_has_nothing_to_move(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        update = AsyncMock()
        monkeypatch.setattr(
            schedule.workflow_repository, "find_system_workflow", AsyncMock(return_value=None)
        )
        monkeypatch.setattr(schedule.WorkflowService, "update_workflow", update)

        await schedule.resync_daily_briefing_schedule(_USER, QuietHours(start_hour=0, end_hour=10))

        update.assert_not_awaited()

    async def test_a_brief_that_vanished_mid_update_fails_loud(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            schedule.workflow_repository,
            "find_system_workflow",
            AsyncMock(return_value=_workflow("0 8 * * *")),
        )
        monkeypatch.setattr(
            schedule.WorkflowService, "update_workflow", AsyncMock(return_value=None)
        )

        with pytest.raises(LookupError, match="wf-brief vanished while it was moved"):
            await schedule.resync_daily_briefing_schedule(
                _USER, QuietHours(start_hour=0, end_hour=10)
            )
