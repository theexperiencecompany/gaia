"""The outcomes of a tracked todo run's delivery that the wiring test does not reach.

The delivered / silenced / reaction / delivery-off / error paths run end to end in
tests/integration/test_tracked_todo_run_delivery.py; these pin the rest.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.core.background import todo_run_delivery as trd
from app.agents.core.background.session import ExecutorRun, RunKind, TodoRun
from app.agents.core.background.todo_run_delivery import deliver_todo_run_result
from app.models.todo_models import TodoDocument
from app.models.user_models import AuthenticatedUser
from app.models.workflow_models import TriggerType

pytestmark = pytest.mark.unit

USER = AuthenticatedUser(user_id="user-1")
RUN = ExecutorRun(
    stream_id="s1",
    conversation_id="run-conv",
    user=USER,
    kind=RunKind.LIVE,
    task_id="t1",
    user_message_id=None,
)
SCHEDULED = TodoRun(todo_id="todo-1", trigger_type=TriggerType.SCHEDULED_TODO)


@dataclass
class _Seams:
    narrate: AsyncMock
    send: AsyncMock
    activity: AsyncMock
    capture: MagicMock

    def entry(self) -> str:
        return self.activity.await_args.kwargs["entry"]

    def props(self) -> dict[str, object]:
        return self.capture.call_args.args[2]


@contextmanager
def _seams(
    *, todo: TodoDocument | None, narrated: str = "Deploy failed.", sent_on: object = None
) -> Iterator[_Seams]:
    seams = _Seams(
        narrate=AsyncMock(return_value=narrated),
        send=AsyncMock(return_value=sent_on),
        activity=AsyncMock(return_value=True),
        capture=MagicMock(),
    )
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=todo)
    with (
        patch.object(trd, "narrate_executor_result", seams.narrate),
        patch.object(trd, "deliver_result_to_platforms", seams.send),
        patch.object(trd, "todo_repository", repo),
        patch.object(trd.tracked_todo_service, "append_activity_entry", seams.activity),
        patch.object(trd, "capture_event", seams.capture),
    ):
        yield seams


def _todo(**fields: object) -> TodoDocument:
    return TodoDocument(
        **{"id": "todo-1", "user_id": "user-1", "title": "Watch the deploy", **fields}
    )


class TestResultsThatReachNobody:
    async def test_a_failed_write_up_sends_nothing_and_is_recorded(self) -> None:
        with _seams(todo=_todo(), narrated="") as seams:
            await deliver_todo_run_result(RUN, SCHEDULED, "report", "final")

        seams.send.assert_not_awaited()
        assert "result not sent: it could not be written up" in seams.entry()
        assert seams.props()["outcome"] == "narration_failed"

    async def test_no_linked_chat_app_is_recorded_as_undelivered(self) -> None:
        """Counting an unlinked user's skipped delivery as sent hides the failure."""
        with _seams(todo=_todo(), sent_on=None) as seams:
            await deliver_todo_run_result(RUN, SCHEDULED, "report", "final")

        seams.send.assert_awaited_once()
        assert "no linked chat app accepted it" in seams.entry()
        assert seams.props()["outcome"] == "undelivered"
        assert seams.props()["delivered"] is False
        assert seams.props()["platform"] is None

    async def test_a_todo_deleted_mid_run_gets_nothing(self) -> None:
        with _seams(todo=None) as seams:
            await deliver_todo_run_result(RUN, SCHEDULED, "report", "final")

        seams.narrate.assert_not_awaited()
        seams.activity.assert_not_awaited()
        seams.capture.assert_not_called()


class TestAttribution:
    async def test_the_event_names_what_woke_the_run_and_whose_it_is(self) -> None:
        triggered = TodoRun(todo_id="todo-1", trigger_type=TriggerType.TODO_TRIGGER)
        with _seams(todo=_todo(recurrence="daily", user_id="user-9")) as seams:
            await deliver_todo_run_result(RUN, triggered, "report", "final")

        user_id, _event, props = seams.capture.call_args.args
        assert user_id == "user-9"
        assert props["trigger_type"] == TriggerType.TODO_TRIGGER.value
        assert props["recurring"] is True

    async def test_the_activity_entry_lands_on_the_todos_owner(self) -> None:
        with _seams(todo=_todo(user_id="user-9")) as seams:
            await deliver_todo_run_result(RUN, SCHEDULED, "a\nlong\nreport", "final")

        kwargs = seams.activity.await_args.kwargs
        assert (kwargs["todo_id"], kwargs["user_id"]) == ("todo-1", "user-9")
        assert "(summary='a long report')" in kwargs["entry"]
