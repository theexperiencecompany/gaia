"""set_briefing_schedule: the agent's lever on how often briefs come, through the real tool."""

from unittest.mock import AsyncMock, patch

import pytest

from app.agents.tools import account_tools
from app.constants.briefing import BriefingFrequency
from app.models.briefing_models import BriefingSchedule
from app.models.user_models import UserDocument

MODULE = "app.agents.tools.account_tools"
CONFIG = {"metadata": {"user_id": "user-1"}}


def _user(schedule: BriefingSchedule) -> UserDocument:
    return UserDocument(id="user-1", briefing_schedule=schedule)


@pytest.fixture(autouse=True)
def _quiet():
    with patch("app.agents.tools.core.mutations.log"):
        yield


@pytest.mark.unit
class TestSetBriefingSchedule:
    async def test_it_sets_the_frequency_and_hour_and_confirms_what_changed(self) -> None:
        wanted = BriefingSchedule(frequency=BriefingFrequency.WEEKDAYS, hour=9)
        with (
            patch(
                f"{MODULE}.user_repository.get",
                new=AsyncMock(return_value=_user(BriefingSchedule())),
            ),
            patch(
                f"{MODULE}.briefing_schedule.set_briefing_schedule",
                new=AsyncMock(return_value=_user(wanted)),
            ) as setter,
        ):
            result = await account_tools.set_briefing_schedule.ainvoke(
                {"frequency": "weekdays", "hour": 9}, config=CONFIG
            )

        setter.assert_awaited_once_with("user-1", wanted, via="agent")
        assert result == (
            "Briefing schedule updated: a daily brief Monday to Friday at 09:00, "
            "plus the Sunday evening weekly digest."
        )

    async def test_omitting_the_hour_keeps_the_one_already_set(self) -> None:
        current = BriefingSchedule(hour=10)
        wanted = BriefingSchedule(frequency=BriefingFrequency.WEEKLY_ONLY, hour=10)
        with (
            patch(f"{MODULE}.user_repository.get", new=AsyncMock(return_value=_user(current))),
            patch(
                f"{MODULE}.briefing_schedule.set_briefing_schedule",
                new=AsyncMock(return_value=_user(wanted)),
            ) as setter,
        ):
            result = await account_tools.set_briefing_schedule.ainvoke(
                {"frequency": "weekly_only"}, config=CONFIG
            )

        setter.assert_awaited_once_with("user-1", wanted, via="agent")
        assert result.endswith("only the Sunday evening weekly digest, no daily brief.")

    async def test_an_unknown_frequency_is_refused_before_anything_changes(self) -> None:
        with (
            patch(f"{MODULE}.briefing_schedule.set_briefing_schedule", new=AsyncMock()) as setter,
            pytest.raises(ValueError, match="frequency"),
        ):
            await account_tools.set_briefing_schedule.ainvoke(
                {"frequency": "hourly"}, config=CONFIG
            )

        setter.assert_not_awaited()
