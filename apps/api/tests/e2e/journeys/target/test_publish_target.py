"""Target: the community page shows a publish or an unpublish the moment it happens."""

from __future__ import annotations

import pytest

from tests.e2e._harness.tasks_driver import TasksDriver

pytestmark = [pytest.mark.e2e, pytest.mark.tasks_target]

TITLE = "Weekly invoice chaser"
BRIEF = "Every Monday, list unpaid invoices older than 30 days and draft a polite reminder."


class TestTheCommunityPageIsCurrent:
    async def test_a_task_published_after_the_page_was_seen_is_listed(
        self, tasks: TasksDriver
    ) -> None:
        task = await tasks.create_repeating_task(TITLE, BRIEF, cron="0 9 * * 1")
        assert TITLE not in await tasks.community_templates()

        await tasks.publish(task.id)

        assert TITLE in await tasks.community_templates()

    async def test_an_unpublished_task_leaves_the_page_at_once(self, tasks: TasksDriver) -> None:
        task = await tasks.create_repeating_task(TITLE, BRIEF, cron="0 9 * * 1")
        await tasks.publish(task.id)
        assert TITLE in await tasks.community_templates()

        await tasks.unpublish(task.id)

        assert TITLE not in await tasks.community_templates()
