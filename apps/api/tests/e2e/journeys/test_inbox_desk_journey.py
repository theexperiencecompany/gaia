"""Journey: connecting Gmail gives the user an Inbox desk, which opens a sub-task per thread to answer."""

from __future__ import annotations

import pytest

from tests.e2e._harness.tasks_driver import TasksDriver
from tests.e2e._harness.tasks_views import OpensReplyTask

pytestmark = pytest.mark.e2e

THREAD = "19a6c1f0d2e3b4a5"
REPLY = "Reply to Mads about the self-hosting licence"
BRIEFED = "One thread needs your reply: Mads, about the licence."


class TestTheInboxDesk:
    async def test_connecting_gmail_sets_up_one_desk(self, tasks: TasksDriver) -> None:
        assert await tasks.inbox_desk() is None

        await tasks.connect_app("gmail")
        await tasks.connect_app("gmail")

        desk = await tasks.inbox_desk()
        assert desk is not None and (desk.by_gaia, desk.done) == (True, False)
        assert desk.next_run is not None

    async def test_its_run_opens_a_sub_task_for_a_thread_needing_a_reply(
        self, tasks: TasksDriver
    ) -> None:
        await tasks.connect_app("gmail")
        desk = await tasks.inbox_desk()
        assert desk is not None

        await tasks.run_due(desk.id, OpensReplyTask(THREAD, REPLY, BRIEFED))

        (reply,) = await tasks.subtasks_of(desk.id)
        assert (reply.title, reply.by_gaia, reply.done) == (REPLY, True, False)
        assert BRIEFED in (await tasks.delivered())[-1].body
        still = await tasks.get(desk.id)
        assert still is not None and still.done is False and still.next_run is not None

    async def test_a_thread_already_open_gets_no_second_sub_task(self, tasks: TasksDriver) -> None:
        await tasks.connect_app("gmail")
        desk = await tasks.inbox_desk()
        assert desk is not None

        await tasks.run_due(desk.id, OpensReplyTask(THREAD, REPLY, BRIEFED))
        await tasks.run_due(desk.id, OpensReplyTask(THREAD, f"{REPLY}, again", BRIEFED))

        assert [t.title for t in await tasks.subtasks_of(desk.id)] == [REPLY]
