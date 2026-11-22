"""Journey: what the old tracked-todo tools let GAIA do, done with the task tools.

A task about one email thread wakes on that thread only and is never doubled; a task
can be put on repeat, given an end, pointed at earlier tasks and marked waiting on a
reply, which an unblock clears. Asserted on the tasks and what wakes them.
"""

from __future__ import annotations

import pytest

from tests.e2e._harness.tasks_driver import TasksDriver

pytestmark = pytest.mark.e2e

THREAD = "thread-r1"


class TestATaskAboutAThread:
    async def test_mail_on_its_thread_wakes_it_and_the_thread_gets_one_task(
        self, tasks: TasksDriver
    ) -> None:
        await tasks.connect_app("gmail")
        said = await tasks.gaia_uses(
            "create_task",
            title="Get the landlord's answer on the deposit",
            assignee="gaia",
            waiting_on="event",
            next_check="3d",
            gmail_thread_id=THREAD,
        )
        task_id = said.split("(id ")[1].split(")")[0]

        again = await tasks.gaia_uses(
            "create_task",
            title="Chase the landlord",
            assignee="gaia",
            waiting_on="event",
            next_check="3d",
            gmail_thread_id=THREAD,
        )
        await tasks.new_email(
            subject="Re: deposit", sender="landlord@example.com", delivery_id="r1"
        )
        await tasks.new_email(subject="Lunch?", sender="friend@example.com", delivery_id="r2")

        assert task_id in again
        assert [t.title for t in await tasks.open_list() if t.title == "Chase the landlord"] == []
        assert await tasks.woken_by_events(task_id) == 1

    async def test_a_thread_task_needs_gmail_connected(self, tasks: TasksDriver) -> None:
        said = await tasks.gaia_uses(
            "create_task",
            title="Get the landlord's answer",
            assignee="gaia",
            waiting_on="event",
            next_check="3d",
            gmail_thread_id=THREAD,
        )

        assert said.startswith("Error") and await tasks.open_list() == []


class TestChangingWhatATaskIs:
    async def test_a_to_do_put_on_repeat_comes_back_on_its_schedule(
        self, tasks: TasksDriver
    ) -> None:
        todo = await tasks.create_todo("Water the plants")

        await tasks.gaia_uses("update_task", task_id=todo.id, repeat="daily")

        assert await tasks.has_run_armed(todo.id)

    async def test_a_gaia_task_marked_waiting_on_a_reply_is_blocked_until_cleared(
        self, tasks: TasksDriver
    ) -> None:
        done = await tasks.hand_to_gaia("Renew the car insurance")
        task = await tasks.hand_to_gaia("Book the MOT")

        await tasks.gaia_uses(
            "update_task",
            task_id=task.id,
            flags=["waiting_for_reply"],
            references=[done.id],
            expires_at="2099-01-01T00:00:00+00:00",
        )
        blocked = await tasks.get(task.id)
        shown = await tasks.gaia_uses("get_task", task_id=task.id)
        await tasks.gaia_uses("update_task", task_id=task.id, flags=[])
        cleared = await tasks.get(task.id)
        refused = await tasks.gaia_uses("update_task", task_id=task.id, flags=["failed"])

        assert blocked is not None and blocked.blocked is True
        assert done.id in shown and "waiting_for_reply" in shown
        assert cleared is not None and cleared.blocked is False
        assert refused.startswith("Error")
