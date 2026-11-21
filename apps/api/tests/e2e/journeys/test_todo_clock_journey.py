"""Journey: a to-do comes round on the user's own clock: quiet hours, their zone, and DST."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from tests.e2e._harness.tasks_driver import TasksDriver

pytestmark = pytest.mark.e2e

KOLKATA = ZoneInfo("Asia/Kolkata")
NEW_YORK = ZoneInfo("America/New_York")
#: The first Monday after US clocks go forward in 2027 (Sunday 14 March).
AFTER_SPRING_FORWARD = datetime(2027, 3, 16, tzinfo=UTC)


def _next_at(hour: int, *, after: datetime) -> datetime:
    """Return the first whole hour, in UTC, strictly after after."""
    moment = datetime.combine(after.date(), time(hour), tzinfo=UTC)
    return moment if moment > after else moment + timedelta(days=1)


class TestANudgeInQuietHours:
    async def test_waits_for_the_morning_and_is_sent_once(self, tasks: TasksDriver) -> None:
        await tasks.keep_quiet_hours(start_hour=22, end_hour=8)
        due = _next_at(23, after=datetime.now(UTC) + timedelta(hours=1))
        todo = await tasks.create_todo("Lock the shed", due=due)

        await tasks.pass_time_until(due + timedelta(minutes=10))
        assert [d for d in await tasks.delivered() if todo.title in d.title] == []

        morning = _next_at(8, after=due)
        await tasks.pass_time_until(morning + timedelta(minutes=10))
        assert len([d for d in await tasks.delivered() if todo.title in d.title]) == 1


class TestARepeatingTodoOnTheUsersClock:
    async def test_it_comes_round_at_their_hour_wherever_they_live(
        self, tasks: TasksDriver
    ) -> None:
        await tasks.live_in("Asia/Kolkata")
        yoga = await tasks.create_todo("Morning yoga", repeat="0 9 * * *")
        assert yoga.due is not None and yoga.due.astimezone(KOLKATA).hour == 9

        await tasks.live_in("America/New_York")
        await tasks.complete(yoga.id)
        await tasks.pass_time_until(yoga.due + timedelta(minutes=1))

        moved = await tasks.get(yoga.id)
        assert moved is not None and moved.done is False
        assert moved.due is not None and moved.due.astimezone(NEW_YORK).hour == 9

    async def test_it_keeps_its_hour_when_the_clocks_go_forward(self, tasks: TasksDriver) -> None:
        await tasks.live_in("America/New_York")
        standup = await tasks.create_todo("Plan the week", repeat="0 9 * * 1")
        assert standup.due is not None and standup.due.hour == 14  # 09:00 EST

        await tasks.pass_time_until(AFTER_SPRING_FORWARD)

        after = await tasks.get(standup.id)
        assert after is not None and after.due is not None
        assert after.due > AFTER_SPRING_FORWARD
        assert (after.due.astimezone(NEW_YORK).hour, after.due.hour) == (9, 13)  # 09:00 EDT
