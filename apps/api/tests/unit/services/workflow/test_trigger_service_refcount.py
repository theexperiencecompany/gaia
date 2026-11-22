"""Reference counting before a Composio trigger is deleted.

Composio upserts identical configs onto one trigger instance, so a workflow, a tracked
todo and a task routinely share an id. Counting one consumer alone deletes another's
live trigger — silently, and only noticed when something stops firing. That is what
the summed count exists to prevent.
"""

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from unittest.mock import AsyncMock, patch

import pytest

from app.services.workflow.trigger_service import TriggerService

pytestmark = pytest.mark.unit

_MOD = "app.services.workflow.trigger_service"
_WORKFLOW_COUNT = f"{_MOD}.workflow_repository.count_trigger_references"
_TODO_COUNT = f"{_MOD}.todo_repository.count_trigger_references"
_TASK_COUNT = f"{_MOD}.task_repository.count_trigger_references"


@contextmanager
def _counts(*, workflow: AsyncMock, todo: AsyncMock, task: AsyncMock) -> Iterator[None]:
    with ExitStack() as stack:
        stack.enter_context(patch(_WORKFLOW_COUNT, workflow))
        stack.enter_context(patch(_TODO_COUNT, todo))
        stack.enter_context(patch(_TASK_COUNT, task))
        yield


def _none() -> AsyncMock:
    return AsyncMock(return_value=0)


class TestGetTriggersSafeToDelete:
    async def test_safe_when_no_consumer_references_it(self) -> None:
        with _counts(workflow=_none(), todo=_none(), task=_none()):
            assert await TriggerService.get_triggers_safe_to_delete(["ti_1"]) == ["ti_1"]

    async def test_not_safe_when_only_a_todo_references_it(self) -> None:
        with _counts(workflow=_none(), todo=AsyncMock(return_value=1), task=_none()):
            assert await TriggerService.get_triggers_safe_to_delete(["ti_1"]) == []

    async def test_not_safe_when_only_a_workflow_references_it(self) -> None:
        with _counts(workflow=AsyncMock(return_value=1), todo=_none(), task=_none()):
            assert await TriggerService.get_triggers_safe_to_delete(["ti_1"]) == []

    async def test_not_safe_when_only_a_task_references_it(self) -> None:
        with _counts(workflow=_none(), todo=_none(), task=AsyncMock(return_value=1)):
            assert await TriggerService.get_triggers_safe_to_delete(["ti_1"]) == []

    async def test_each_exclusion_reaches_only_its_own_repository(self) -> None:
        workflow_count, todo_count, task_count = _none(), _none(), _none()
        with _counts(workflow=workflow_count, todo=todo_count, task=task_count):
            await TriggerService.get_triggers_safe_to_delete(
                ["ti_1"],
                excluding_workflow_id="wf-1",
                excluding_todo_id="todo-1",
                excluding_task_id="task-1",
            )

        # Each repository is asked about the same concrete trigger id positionally —
        # dropping or nulling it would count references for the wrong (or no) trigger.
        assert workflow_count.await_args.args == ("ti_1",)
        assert workflow_count.await_args.kwargs == {"excluding_workflow_id": "wf-1"}
        assert todo_count.await_args.args == ("ti_1",)
        assert todo_count.await_args.kwargs == {"excluding_todo_id": "todo-1"}
        assert task_count.await_args.args == ("ti_1",)
        assert task_count.await_args.kwargs == {"excluding_task_id": "task-1"}

    async def test_only_unreferenced_ids_come_back(self) -> None:
        with _counts(workflow=_none(), todo=AsyncMock(side_effect=[0, 2, 0]), task=_none()):
            safe = await TriggerService.get_triggers_safe_to_delete(["ti_1", "ti_2", "ti_3"])

        assert safe == ["ti_1", "ti_3"]

    async def test_a_count_failure_keeps_the_trigger_rather_than_deleting_blind(self) -> None:
        with _counts(
            workflow=AsyncMock(side_effect=Exception("mongo down")), todo=_none(), task=_none()
        ):
            assert await TriggerService.get_triggers_safe_to_delete(["ti_1"]) == []
