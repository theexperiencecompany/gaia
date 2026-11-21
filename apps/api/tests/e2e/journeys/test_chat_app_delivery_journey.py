"""Journey: a finished run reaches the user on their linked chat app, unless they turned delivery off."""

from __future__ import annotations

import pytest

from tests.e2e._harness.tasks_driver import TasksDriver
from tests.e2e._harness.tasks_views import Finishes, Reports

pytestmark = pytest.mark.e2e

DIGEST = "Three stories: a chip launch, a privacy ruling, a funding round."
CHECKED = "Slots opened for 3 December; nothing was booked."


class TestARepeatingTasksResult:
    async def test_reaches_telegram(self, tasks: TasksDriver) -> None:
        await tasks.link_chat_app("telegram")
        task = await tasks.create_repeating_task(
            "Morning digest", "Send me the news.", cron="0 8 * * *"
        )

        await tasks.run_due(task.id, Reports(DIGEST))

        (sent,) = tasks.messaged_on_chat_apps()
        assert (sent.channel, DIGEST in sent.body) == ("telegram", True)

    async def test_stays_quiet_when_delivery_is_off(self, tasks: TasksDriver) -> None:
        await tasks.link_chat_app("telegram")
        task = await tasks.create_repeating_task(
            "Morning digest", "Send me the news.", cron="0 8 * * *", notify=False
        )

        await tasks.run_due(task.id, Reports(DIGEST))

        assert tasks.messaged_on_chat_apps() == []
        assert await tasks.delivered() == []


class TestAGaiaTasksResult:
    async def test_reaches_discord(self, tasks: TasksDriver) -> None:
        await tasks.link_chat_app("discord")
        task = await tasks.hand_to_gaia("Check the visa slots")

        await tasks.run_due(task.id, Finishes(CHECKED))

        (sent,) = tasks.messaged_on_chat_apps()
        assert (sent.channel, CHECKED in sent.body) == ("discord", True)

    async def test_stays_quiet_when_delivery_is_off(self, tasks: TasksDriver) -> None:
        await tasks.link_chat_app("discord")
        task = await tasks.hand_to_gaia("Check the visa slots", notify=False)

        await tasks.run_due(task.id, Finishes(CHECKED))

        assert tasks.messaged_on_chat_apps() == []
        done = await tasks.get(task.id)
        assert done is not None and done.done is True
