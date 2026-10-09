"""Unit tests for the system-owned todo and workflow archive.

The report must never write, --apply must archive only the live system-owned
targets, and the explore templates "system" legitimately owns stay untouched.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId
import pytest
from scripts.archive_system_owned_runs import (
    ARCHIVE_SUMMARY,
    SYSTEM_OWNED_TODO_IDS,
    SYSTEM_OWNED_WORKFLOW_IDS,
    USER_OWNED_COLLECTIONS,
    run,
)

from app.constants.vfs import SYSTEM_USER_ID
from app.models.todo_models import TodoDocument, TodoUpdate
from app.models.workflow_models import (
    DeactivationReason,
    TriggerConfig,
    TriggerType,
    WorkflowDocument,
)

MODULE = "scripts.archive_system_owned_runs"


def _todo(todo_id: str, *, completed: bool = False) -> TodoDocument:
    return TodoDocument(
        id=todo_id,
        user_id=SYSTEM_USER_ID,
        title="Hourly Review Queue Alert",
        labels=["gaia-tracked"],
        recurrence="every_1h",
        completed=completed,
    )


def _workflow(workflow_id: str, *, activated: bool = True, is_explore: bool = False):
    return WorkflowDocument(
        id=workflow_id,
        user_id=SYSTEM_USER_ID,
        title="Todo: Hourly Review Queue Alert",
        prompt="Run it",
        steps=[],
        trigger_config=TriggerConfig(type=TriggerType.MANUAL, enabled=activated),
        activated=activated,
        is_explore=is_explore,
    )


@dataclass
class _Seams:
    todos: MagicMock
    workflows: MagicMock
    complete: AsyncMock
    deactivate: AsyncMock
    counted: dict[str, dict[str, object]]


@pytest.fixture
def seams() -> Iterator[_Seams]:
    todos = MagicMock()
    todos.get = AsyncMock(side_effect=lambda todo_id, user_id: _todo(todo_id))
    todos.update = AsyncMock()
    workflows = MagicMock()
    workflows.get_for_user = AsyncMock(side_effect=lambda wf_id, user_id: _workflow(wf_id))
    counted: dict[str, dict[str, object]] = {}

    def collection(name: str) -> MagicMock:
        async def count(query: dict[str, object]) -> int:
            counted[name] = query
            return 2 if name == "conversations" else 0

        return MagicMock(count_documents=AsyncMock(side_effect=count))

    complete = AsyncMock(return_value=True)
    deactivate = AsyncMock()
    with (
        patch(f"{MODULE}.todo_repository", todos),
        patch(f"{MODULE}.workflow_repository", workflows),
        patch(f"{MODULE}.get_async_collection", side_effect=collection),
        patch(f"{MODULE}.tracked_todo_service.complete_tracked_todo", complete),
        patch(f"{MODULE}.WorkflowService.deactivate_workflow", deactivate),
    ):
        yield _Seams(todos, workflows, complete, deactivate, counted)


class TestTheReport:
    async def test_a_dry_run_writes_nothing(self, seams: _Seams) -> None:
        todos, workflows, others = await run(apply=False)

        assert [state.id for state in todos if state.found] == list(SYSTEM_OWNED_TODO_IDS)
        assert [state.id for state in workflows if state.found] == list(SYSTEM_OWNED_WORKFLOW_IDS)
        seams.todos.update.assert_not_awaited()
        seams.complete.assert_not_awaited()
        seams.deactivate.assert_not_awaited()
        assert others["conversations"] == 2

    async def test_every_owned_collection_is_counted_but_skills(self, seams: _Seams) -> None:
        await run(apply=False)

        assert set(seams.counted) == set(USER_OWNED_COLLECTIONS)
        assert "skills" not in seams.counted

    async def test_templates_and_the_targets_are_left_out_of_the_other_rows(
        self, seams: _Seams
    ) -> None:
        await run(apply=False)

        assert seams.counted["workflows"] == {
            "user_id": SYSTEM_USER_ID,
            "is_explore": {"$ne": True},
            "_id": {"$nin": list(SYSTEM_OWNED_WORKFLOW_IDS)},
        }
        assert seams.counted["todos"]["_id"] == {
            "$nin": [ObjectId(todo_id) for todo_id in SYSTEM_OWNED_TODO_IDS]
        }


class TestApply:
    async def test_each_live_target_is_archived_with_its_schedule_cleared(
        self, seams: _Seams
    ) -> None:
        await run(apply=True)

        assert [c.args for c in seams.todos.update.await_args_list] == [
            (todo_id,) for todo_id in SYSTEM_OWNED_TODO_IDS
        ]
        assert all(
            c.kwargs == {"user_id": SYSTEM_USER_ID, "update": TodoUpdate(scheduled_at=None)}
            for c in seams.todos.update.await_args_list
        )
        assert [c.args for c in seams.complete.await_args_list] == [
            (todo_id, SYSTEM_USER_ID, ARCHIVE_SUMMARY) for todo_id in SYSTEM_OWNED_TODO_IDS
        ]
        assert [c.args for c in seams.deactivate.await_args_list] == [
            (wf_id, SYSTEM_USER_ID) for wf_id in SYSTEM_OWNED_WORKFLOW_IDS
        ]
        assert all(
            c.kwargs == {"reason": DeactivationReason.OWNER_NOT_FOUND}
            for c in seams.deactivate.await_args_list
        )

    async def test_an_explore_template_is_never_touched(self, seams: _Seams) -> None:
        template_id = SYSTEM_OWNED_WORKFLOW_IDS[0]
        seams.workflows.get_for_user = AsyncMock(
            side_effect=lambda wf_id, user_id: _workflow(wf_id, is_explore=wf_id == template_id)
        )

        await run(apply=True)

        assert template_id not in [c.args[0] for c in seams.deactivate.await_args_list]

    async def test_missing_and_already_archived_targets_are_skipped(self, seams: _Seams) -> None:
        gone, done = SYSTEM_OWNED_TODO_IDS[:2]
        seams.todos.get = AsyncMock(
            side_effect=lambda todo_id, user_id: (
                None if todo_id == gone else _todo(todo_id, completed=todo_id == done)
            )
        )

        await run(apply=True)

        archived = [c.args[0] for c in seams.complete.await_args_list]
        assert archived == list(SYSTEM_OWNED_TODO_IDS[2:])

    async def test_the_report_after_apply_is_read_back_from_the_database(
        self, seams: _Seams
    ) -> None:
        stuck_todo, stuck_workflow = SYSTEM_OWNED_TODO_IDS[0], SYSTEM_OWNED_WORKFLOW_IDS[0]
        completed: set[str] = set()
        deactivated: set[str] = set()

        async def complete(todo_id: str, user_id: str, summary: str) -> bool:
            if todo_id != stuck_todo:
                completed.add(todo_id)
            return todo_id != stuck_todo

        async def deactivate(wf_id: str, user_id: str, *, reason: DeactivationReason) -> None:
            if wf_id != stuck_workflow:
                deactivated.add(wf_id)

        seams.complete.side_effect = complete
        seams.deactivate.side_effect = deactivate
        seams.todos.get = AsyncMock(
            side_effect=lambda todo_id, user_id: _todo(todo_id, completed=todo_id in completed)
        )
        seams.workflows.get_for_user = AsyncMock(
            side_effect=lambda wf_id, user_id: _workflow(wf_id, activated=wf_id not in deactivated)
        )

        todos, workflows, _ = await run(apply=True)

        assert [state.id for state in todos if not state.archived] == [stuck_todo]
        assert [state.id for state in workflows if not state.archived] == [stuck_workflow]
