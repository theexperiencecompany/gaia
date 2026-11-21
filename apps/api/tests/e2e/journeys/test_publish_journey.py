"""Journey: the user publishes a repeating task as a template, then takes it down."""

from __future__ import annotations

import pytest

from tests.e2e._harness.tasks_driver import TasksDriver

pytestmark = pytest.mark.e2e

TITLE = "Weekly invoice chaser"
BRIEF = "Every Monday, list unpaid invoices older than 30 days and draft a polite reminder."


class TestPublishingATask:
    async def test_published_it_is_public_and_listed_then_unpublished_it_is_gone(
        self, tasks: TasksDriver
    ) -> None:
        task = await tasks.create_repeating_task(TITLE, BRIEF, cron="0 9 * * 1")

        ref = await tasks.publish(task.id)

        assert await tasks.public_template(ref) == TITLE
        assert await tasks.public_template(task.id) == TITLE
        assert TITLE in await tasks.community_templates()

        await tasks.unpublish(task.id)

        assert await tasks.public_template(ref) is None
        assert await tasks.public_template(task.id) is None

    async def test_an_unpublished_task_has_no_public_page(self, tasks: TasksDriver) -> None:
        task = await tasks.create_repeating_task(TITLE, BRIEF, cron="0 9 * * 1")

        assert await tasks.public_template(task.id) is None
