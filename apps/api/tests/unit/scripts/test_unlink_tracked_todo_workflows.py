"""Unit tests for the tracked-todo workflow unlink migration.

A production run is safe only if --dry-run (the default) never writes and
--execute deletes exactly the workflows generated for each todo, never one
the user built and linked themselves.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from scripts.unlink_tracked_todo_workflows import run_migration

MODULE = "scripts.unlink_tracked_todo_workflows"
USER = "user-1"


def _todo(todo_id: str, workflow_id: str) -> MagicMock:
    todo = MagicMock()
    todo.id = todo_id
    todo.user_id = USER
    todo.workflow_id = workflow_id
    return todo


def _workflow(*, is_todo_workflow: bool, source_todo_id: str | None) -> MagicMock:
    workflow = MagicMock()
    workflow.is_todo_workflow = is_todo_workflow
    workflow.source_todo_id = source_todo_id
    return workflow


def _seams(workflows: dict[str, MagicMock | None]) -> tuple[MagicMock, MagicMock, AsyncMock]:
    """One page holding a generated link, a user-built link and a dangling link, then an empty page."""
    todo_repo = MagicMock()
    todo_repo.list_tracked_with_workflow = AsyncMock(
        side_effect=[
            [_todo("t-gen", "wf-gen"), _todo("t-own", "wf-own"), _todo("t-gone", "wf-gone")],
            [],
        ]
    )
    todo_repo.clear_workflow_id = AsyncMock()
    workflow_repo = MagicMock()
    workflow_repo.get_for_user = AsyncMock(side_effect=lambda wf_id, user_id: workflows[wf_id])
    delete = AsyncMock(return_value=True)
    return todo_repo, workflow_repo, delete


WORKFLOWS = {
    "wf-gen": _workflow(is_todo_workflow=True, source_todo_id="t-gen"),
    "wf-own": _workflow(is_todo_workflow=False, source_todo_id=None),
    "wf-gone": None,
}


async def _run(*, dry_run: bool) -> tuple[MagicMock, AsyncMock, object]:
    todo_repo, workflow_repo, delete = _seams(WORKFLOWS)
    with (
        patch(f"{MODULE}.todo_repository", todo_repo),
        patch(f"{MODULE}.workflow_repository", workflow_repo),
        patch(f"{MODULE}.WorkflowService.delete_workflow", delete),
    ):
        result = await run_migration(dry_run=dry_run)
    return todo_repo, delete, result


async def test_a_dry_run_writes_nothing() -> None:
    todo_repo, delete, result = await _run(dry_run=True)

    delete.assert_not_awaited()
    todo_repo.clear_workflow_id.assert_not_awaited()
    assert [(link.todo_id, link.deletes_workflow) for link in result.linked] == [
        ("t-gen", True),
        ("t-own", False),
        ("t-gone", False),
    ]


async def test_execute_deletes_only_the_workflow_generated_for_the_todo() -> None:
    todo_repo, delete, result = await _run(dry_run=False)

    delete.assert_awaited_once_with("wf-gen", USER)
    assert result.workflows_deleted == 1
    assert [c.args[0] for c in todo_repo.clear_workflow_id.await_args_list] == [
        "t-gen",
        "t-own",
        "t-gone",
    ]
    assert all(c.kwargs["user_id"] == USER for c in todo_repo.clear_workflow_id.await_args_list)


async def test_a_workflow_generated_for_another_todo_is_not_deleted() -> None:
    todo_repo, workflow_repo, delete = _seams(
        {**WORKFLOWS, "wf-gen": _workflow(is_todo_workflow=True, source_todo_id="t-other")}
    )
    with (
        patch(f"{MODULE}.todo_repository", todo_repo),
        patch(f"{MODULE}.workflow_repository", workflow_repo),
        patch(f"{MODULE}.WorkflowService.delete_workflow", delete),
    ):
        await run_migration(dry_run=False)

    delete.assert_not_awaited()
