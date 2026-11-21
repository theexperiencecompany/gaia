"""Journey: GAIA asks the user a question mid-task, then acts on the answer or on the silence."""

from __future__ import annotations

import pytest

from tests.e2e._harness.tasks_driver import TasksDriver
from tests.e2e._harness.tasks_views import Asks, Finishes, KeepsHolding, NoReply, Reports

pytestmark = pytest.mark.e2e

TITLE = "Book a table for Friday's team dinner"
QUESTION = "Which do you prefer for Friday: the Thai place at 7 or the Italian place at 8?"
ANSWER = "The Thai place, please."
GAVE_UP = "No answer came; leaving the dinner unbooked."
CHOSEN = "Booked the Thai place for 7 on Friday, table for six."


async def _asked(tasks: TasksDriver, if_no_reply: NoReply, default: str | None = None) -> str:
    task = await tasks.hand_to_gaia(TITLE)
    await tasks.run_due(task.id, Asks(QUESTION, if_no_reply, default))
    return task.id


class TestGaiaAsksAndTheUserAnswers:
    async def test_the_question_reaches_the_user_and_the_answer_finishes_the_task(
        self, tasks: TasksDriver
    ) -> None:
        task_id = await _asked(tasks, NoReply.ASK_AGAIN)

        (asked,) = await tasks.delivered()
        assert QUESTION in asked.body
        waiting = await tasks.get(task_id)
        assert waiting is not None and waiting.done is False

        await tasks.answer(task_id, ANSWER, then=Finishes(CHOSEN))

        # The task's chat holds the question, the user's answer, and what came of it, in order.
        chat = [(line.by_user, line.text) for line in await tasks.chat(task_id)]
        assert chat[0] == (False, QUESTION)
        assert chat.index((True, ANSWER)) < chat.index((False, CHOSEN)) == len(chat) - 1
        done = await tasks.get(task_id)
        assert done is not None and done.done is True


class TestNobodyAnswers:
    async def test_gaia_asks_once_more(self, tasks: TasksDriver) -> None:
        task_id = await _asked(tasks, NoReply.ASK_AGAIN)

        await tasks.run_due(task_id, Asks(QUESTION, NoReply.HOLD))

        assert [QUESTION in d.body for d in await tasks.delivered()] == [True, True]
        still = await tasks.get(task_id)
        assert still is not None and still.done is False

    async def test_gaia_goes_ahead_with_the_default(self, tasks: TasksDriver) -> None:
        task_id = await _asked(tasks, NoReply.PROCEED, default="book the Thai place at 7")

        await tasks.run_due(task_id, Finishes(CHOSEN))

        done = await tasks.get(task_id)
        assert done is not None and done.done is True
        assert CHOSEN in (await tasks.delivered())[-1].body

    async def test_gaia_holds_through_its_checks_then_closes_the_task(
        self, tasks: TasksDriver
    ) -> None:
        task_id = await _asked(tasks, NoReply.HOLD)

        for _ in range(3):
            await tasks.run_due(task_id, KeepsHolding("Still waiting on your choice."))
            still = await tasks.get(task_id)
            assert still is not None and still.done is False
        await tasks.run_due(task_id, Reports(GAVE_UP))

        closed = await tasks.get(task_id)
        assert closed is not None and closed.done is True
        assert GAVE_UP in (await tasks.delivered())[-1].body
        assert await tasks.run_due(task_id) == []
