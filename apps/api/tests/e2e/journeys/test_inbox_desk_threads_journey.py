"""Journey: the Inbox desk keeps one task per thread, takes a closed thread back, and exists once."""

from __future__ import annotations

import pytest

from tests.e2e._harness.tasks_driver import TasksDriver
from tests.e2e._harness.tasks_views import NeedsApproval, OpensReplyTask, Reports

pytestmark = pytest.mark.e2e

THREAD = "19a6c1f0d2e3b4a5"
REPLY = "Reply to Mads about the self-hosting licence"
BRIEFED = "One thread needs your reply: Mads, about the licence."
ALERT = "Mads · licence terms · needs your answer today"


async def _desk(tasks: TasksDriver) -> str:
    await tasks.connect_app("gmail")
    desk = await tasks.inbox_desk()
    assert desk is not None
    return desk.id


class TestOneTaskPerThread:
    async def test_a_thread_gaia_already_follows_gets_no_reply_task_from_the_desk(
        self, tasks: TasksDriver
    ) -> None:
        desk = await _desk(tasks)
        said = await tasks.gaia_uses(
            "create_task",
            title="Chase Mads for the licence terms",
            assignee="gaia",
            gmail_thread_id=THREAD,
            waiting_on="event",
            next_check="3d",
        )
        assert "Task created" in said, said

        await tasks.run_due(desk, OpensReplyTask(THREAD, REPLY, BRIEFED))

        assert await tasks.subtasks_of(desk) == []
        following = [t.title for t in await tasks.open_list() if t.by_gaia and t.id != desk]
        assert following == ["Chase Mads for the licence terms"]

    async def test_a_closed_threads_task_is_reopened_when_the_thread_comes_back(
        self, tasks: TasksDriver
    ) -> None:
        desk = await _desk(tasks)
        await tasks.run_due(desk, OpensReplyTask(THREAD, REPLY, BRIEFED))
        (reply,) = await tasks.subtasks_of(desk)
        await tasks.complete(reply.id)

        await tasks.run_due(desk, OpensReplyTask(THREAD, f"{REPLY}, again", BRIEFED))

        (back,) = await tasks.subtasks_of(desk)
        assert (back.id, back.title, back.done) == (reply.id, f"{REPLY}, again", False)
        assert back.next_run is not None


class TestTheReplyTask:
    async def test_its_run_works_the_thread_and_waits_on_the_users_approval_under_the_desk(
        self, tasks: TasksDriver
    ) -> None:
        desk = await _desk(tasks)
        await tasks.run_due(desk, OpensReplyTask(THREAD, REPLY, BRIEFED))
        assert tasks.last_run_was_shown("INBOX DESK:")
        (reply,) = await tasks.subtasks_of(desk)
        await tasks.ask_before_acting()

        await tasks.run_due(reply.id, NeedsApproval("Approve the draft to Mads?"))

        assert tasks.last_run_was_shown(f"EMAIL THREAD: this task owns Gmail thread {THREAD}")
        (waiting,) = await tasks.subtasks_of(desk)
        assert waiting.pending_approval and await tasks.approval_asked(reply.id)
        await tasks.approve(reply.id, "Drafted the reply to Mads.")
        assert await tasks.approved_actions_taken(reply.id) == 1

    async def test_what_cannot_wait_for_the_briefing_reaches_the_user_itself(
        self, tasks: TasksDriver
    ) -> None:
        desk = await _desk(tasks)
        await tasks.run_due(desk, OpensReplyTask(THREAD, REPLY, BRIEFED))
        (reply,) = await tasks.subtasks_of(desk)

        await tasks.run_due(reply.id, Reports(ALERT))

        assert ALERT in (await tasks.delivered())[-1].body


class TestOneDeskPerUser:
    async def test_gmail_connecting_as_the_plan_starts_sets_up_one_desk(
        self, tasks: TasksDriver
    ) -> None:
        await tasks.gmail_connects_as_the_plan_starts()

        desk = await tasks.inbox_desk()
        assert desk is not None and desk.next_run is not None

    async def test_a_desk_the_user_stopped_is_not_set_up_again(self, tasks: TasksDriver) -> None:
        desk = await _desk(tasks)
        await tasks.complete(desk)

        await tasks.app_disconnects("gmail")
        await tasks.connect_app("gmail")

        again = await tasks.inbox_desk()
        assert again is not None and (again.id, again.done) == (desk, True)
