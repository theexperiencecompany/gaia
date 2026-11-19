"""set_briefing_schedule: the agent's lever on how often briefs come, through the real tool."""

from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.runnables import RunnableConfig
import pytest

from app.agents.tools import account_tools
from app.constants.briefing import BriefingFrequency
from app.constants.workflows import WorkflowDelivery
from app.models.brief_settings_models import BriefingSchedule
from app.models.user_models import UserDocument
from app.services.briefing.schedule import BriefDeliveryWorkflowsError
from app.workers.brief_slots import slot_minute
from tests.factories import make_user_id
from tests.helpers import captured_wide_event

MODULE = "app.agents.tools.account_tools"
USER_ID = make_user_id()
CONFIG = RunnableConfig(metadata={"user_id": USER_ID})
MINUTE = f"{slot_minute(USER_ID):02d}"


@pytest.fixture(autouse=True)
def paid():
    with patch("app.services.briefing.schedule.is_paid", new=AsyncMock(return_value=True)) as mock:
        yield mock


@pytest.fixture(autouse=True)
def user():
    with patch(
        f"{MODULE}.require_user", new=AsyncMock(return_value=UserDocument(id=USER_ID))
    ) as mock:
        yield mock


def _setter(stored: BriefingSchedule) -> AsyncMock:
    return AsyncMock(return_value=stored)


@pytest.mark.unit
class TestSetBriefingSchedule:
    async def test_it_sets_the_frequency_and_hour_and_confirms_what_changed(
        self, user: AsyncMock
    ) -> None:
        setter = _setter(BriefingSchedule(frequency=BriefingFrequency.WEEKDAYS, hour=9))
        with patch(f"{MODULE}.briefing_schedule.set_briefing_schedule", new=setter):
            async with captured_wide_event() as event:
                result = await account_tools.set_briefing_schedule.ainvoke(
                    {"frequency": "weekdays", "hour": 9}, config=CONFIG
                )

        setter.assert_awaited_once_with(
            USER_ID, BriefingFrequency.WEEKDAYS, "agent", hour=9, brief_workflows_to=None
        )
        user.assert_awaited_once_with(USER_ID)
        assert result == (
            f"Briefing schedule updated: a daily brief Monday to Friday at 9:{MINUTE} AM, "
            f"plus the weekly digest on Sunday at 5:{MINUTE} PM."
        )
        assert (event["tool"], event["surface"]) == (
            {"name": "set_briefing_schedule", "action": "mutate"},
            {"area": "briefing"},
        )

    async def test_a_free_user_is_told_the_briefs_stay_paused_until_pro(
        self, paid: AsyncMock
    ) -> None:
        paid.return_value = False
        setter = _setter(BriefingSchedule(frequency=BriefingFrequency.DAILY, hour=9))
        with patch(f"{MODULE}.briefing_schedule.set_briefing_schedule", new=setter):
            result = await account_tools.set_briefing_schedule.ainvoke(
                {"frequency": "daily", "hour": 9}, config=CONFIG
            )

        assert result == (
            f"Briefing schedule updated: a daily brief every day at 9:{MINUTE} AM, plus the "
            f"weekly digest on Sunday at 5:{MINUTE} PM. None of these run yet: briefs on a schedule need Pro, "
            "and the user is on the free plan."
        )
        paid.assert_awaited_once_with(USER_ID)

    async def test_omitting_the_hour_leaves_it_to_the_service_to_keep(self) -> None:
        setter = _setter(BriefingSchedule(frequency=BriefingFrequency.WEEKLY_ONLY, hour=10))
        with patch(f"{MODULE}.briefing_schedule.set_briefing_schedule", new=setter):
            result = await account_tools.set_briefing_schedule.ainvoke(
                {"frequency": "weekly_only"}, config=CONFIG
            )

        assert setter.await_args.kwargs["hour"] is None
        assert result.endswith(
            f"only the weekly digest on Sunday at 5:{MINUTE} PM, no daily brief."
        )

    @pytest.mark.regression
    async def test_turning_briefs_off_says_where_the_brief_workflows_go(self) -> None:
        setter = _setter(BriefingSchedule(frequency=BriefingFrequency.OFF))
        with patch(f"{MODULE}.briefing_schedule.set_briefing_schedule", new=setter):
            await account_tools.set_briefing_schedule.ainvoke(
                {"frequency": "off", "brief_workflows_to": "now"}, config=CONFIG
            )

        assert setter.await_args.kwargs["brief_workflows_to"] is WorkflowDelivery.NOW

    async def test_off_without_a_place_for_them_comes_back_as_what_to_ask(self) -> None:
        refused = BriefDeliveryWorkflowsError([MagicMock(id="wf-1", title="Digest")])
        with patch(
            f"{MODULE}.briefing_schedule.set_briefing_schedule",
            new=AsyncMock(side_effect=refused),
        ):
            result = await account_tools.set_briefing_schedule.ainvoke(
                {"frequency": "off"}, config=CONFIG
            )

        assert result == f"Error: {refused.message} Fix: {refused.fix}"

    async def test_an_unknown_frequency_is_refused_before_anything_changes(self) -> None:
        with (
            patch(f"{MODULE}.briefing_schedule.set_briefing_schedule", new=AsyncMock()) as setter,
            pytest.raises(ValueError, match="frequency"),
        ):
            await account_tools.set_briefing_schedule.ainvoke(
                {"frequency": "hourly"}, config=CONFIG
            )

        setter.assert_not_awaited()
