"""Reference counting before a Composio trigger is deleted.

Composio upserts identical configs onto one trigger instance, so a workflow and a
tracked todo routinely share an id. Counting one consumer alone deletes the
other's live trigger — silently, and only noticed when something stops firing.
That is what the summed count exists to prevent.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.workflow.trigger_service import TriggerService

pytestmark = pytest.mark.unit

_WORKFLOW_COUNT = (
    "app.services.workflow.trigger_service.workflow_repository.count_trigger_references"
)
_TODO_COUNT = "app.services.workflow.trigger_service.todo_repository.count_trigger_references"


class TestGetTriggersSafeToDelete:
    async def test_safe_when_neither_consumer_references_it(self) -> None:
        with (
            patch(_WORKFLOW_COUNT, AsyncMock(return_value=0)),
            patch(_TODO_COUNT, AsyncMock(return_value=0)),
        ):
            assert await TriggerService.get_triggers_safe_to_delete(["ti_1"]) == ["ti_1"]

    async def test_not_safe_when_only_a_todo_references_it(self) -> None:
        with (
            patch(_WORKFLOW_COUNT, AsyncMock(return_value=0)),
            patch(_TODO_COUNT, AsyncMock(return_value=1)),
        ):
            assert await TriggerService.get_triggers_safe_to_delete(["ti_1"]) == []

    async def test_not_safe_when_only_a_workflow_references_it(self) -> None:
        with (
            patch(_WORKFLOW_COUNT, AsyncMock(return_value=1)),
            patch(_TODO_COUNT, AsyncMock(return_value=0)),
        ):
            assert await TriggerService.get_triggers_safe_to_delete(["ti_1"]) == []

    async def test_each_exclusion_reaches_only_its_own_repository(self) -> None:
        workflow_count = AsyncMock(return_value=0)
        todo_count = AsyncMock(return_value=0)
        with patch(_WORKFLOW_COUNT, workflow_count), patch(_TODO_COUNT, todo_count):
            await TriggerService.get_triggers_safe_to_delete(
                ["ti_1"], excluding_workflow_id="wf-1", excluding_todo_id="todo-1"
            )

        # Each repository is asked about the same concrete trigger id positionally —
        # dropping or nulling it would count references for the wrong (or no) trigger.
        assert workflow_count.await_args.args == ("ti_1",)
        assert workflow_count.await_args.kwargs == {"excluding_workflow_id": "wf-1"}
        assert todo_count.await_args.args == ("ti_1",)
        assert todo_count.await_args.kwargs == {"excluding_todo_id": "todo-1"}

    async def test_only_unreferenced_ids_come_back(self) -> None:
        with (
            patch(_WORKFLOW_COUNT, AsyncMock(return_value=0)),
            patch(_TODO_COUNT, AsyncMock(side_effect=[0, 2, 0])),
        ):
            safe = await TriggerService.get_triggers_safe_to_delete(["ti_1", "ti_2", "ti_3"])

        assert safe == ["ti_1", "ti_3"]

    async def test_a_count_failure_keeps_the_trigger_rather_than_deleting_blind(self) -> None:
        with (
            patch(_WORKFLOW_COUNT, AsyncMock(side_effect=Exception("mongo down"))),
            patch(_TODO_COUNT, AsyncMock(return_value=0)),
        ):
            assert await TriggerService.get_triggers_safe_to_delete(["ti_1"]) == []
