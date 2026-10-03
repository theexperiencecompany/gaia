"""The Inbox Triage retirement: a dry run writes nothing, and no owner is left with neither feature."""

from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

from scripts.retire_inbox_triage import INBOX_TRIAGE_KEY, MigrationResult, run_migration

MODULE = "scripts.retire_inbox_triage"


def _workflow(workflow_id: str, user_id: str) -> MagicMock:
    w = MagicMock()
    w.id, w.user_id = workflow_id, user_id
    return w


def _seams(*workflows: MagicMock, desk_open: bool = True) -> dict[str, MagicMock]:
    workflow_repo = MagicMock()
    workflow_repo.find_live_system_workflows = AsyncMock(return_value=list(workflows))
    todo_repo = MagicMock()
    desk = MagicMock(completed=False) if desk_open else None
    todo_repo.find_latest_by_external_ref = AsyncMock(return_value=desk)
    return {
        "workflow_repository": workflow_repo,
        "todo_repository": todo_repo,
        "provision_inbox_desk": AsyncMock(),
        "WorkflowService.deactivate_workflow": AsyncMock(),
    }


async def _run(seams: dict[str, MagicMock], *, dry_run: bool) -> MigrationResult:
    with ExitStack() as stack:
        for name, seam in seams.items():
            stack.enter_context(patch(f"{MODULE}.{name}", seam))
        return await run_migration(dry_run=dry_run)


async def test_a_dry_run_reports_the_live_rows_and_writes_nothing() -> None:
    seams = _seams(_workflow("wf-1", "u-1"))

    result = await _run(seams, dry_run=True)

    seams["workflow_repository"].find_live_system_workflows.assert_awaited_once_with(
        INBOX_TRIAGE_KEY
    )
    assert [w.id for w in result.workflows] == ["wf-1"]
    seams["provision_inbox_desk"].assert_not_awaited()
    seams["WorkflowService.deactivate_workflow"].assert_not_awaited()


async def test_each_owner_gets_the_desk_before_their_row_is_retired() -> None:
    seams = _seams(_workflow("wf-1", "u-1"), _workflow("wf-2", "u-2"))
    calls = MagicMock()
    calls.attach_mock(seams["provision_inbox_desk"], "provision")
    calls.attach_mock(seams["WorkflowService.deactivate_workflow"], "retire")

    result = await _run(seams, dry_run=False)

    assert [c[0] for c in calls.mock_calls] == ["provision", "retire", "provision", "retire"]
    seams["WorkflowService.deactivate_workflow"].assert_any_await("wf-2", "u-2")
    assert (result.retired, result.desks_open, result.failures) == (2, 2, {})


async def test_a_desk_that_fails_to_open_keeps_its_row_live_and_the_run_going() -> None:
    seams = _seams(_workflow("wf-1", "u-1"), _workflow("wf-2", "u-2"))
    seams["provision_inbox_desk"].side_effect = [ConnectionError("mongo down"), None]

    result = await _run(seams, dry_run=False)

    seams["WorkflowService.deactivate_workflow"].assert_awaited_once_with("wf-2", "u-2")
    assert result.failures == {"u-1": "ConnectionError: mongo down"}
    assert result.retired == 1


async def test_a_row_that_fails_to_retire_does_not_stop_the_rows_behind_it() -> None:
    seams = _seams(_workflow("wf-1", "u-1"), _workflow("wf-2", "u-2"))
    seams["WorkflowService.deactivate_workflow"].side_effect = [ConnectionError("mongo down"), None]

    result = await _run(seams, dry_run=False)

    seams["WorkflowService.deactivate_workflow"].assert_any_await("wf-2", "u-2")
    assert result.failures == {"u-1": "ConnectionError: mongo down"}
    assert (result.retired, result.desks_open) == (1, 1)


async def test_an_owner_with_no_desk_keeps_their_row_live_for_a_rerun() -> None:
    """No open desk, no retirement: the old briefing is all they have."""
    seams = _seams(_workflow("wf-1", "u-1"), desk_open=False)

    result = await _run(seams, dry_run=False)

    seams["WorkflowService.deactivate_workflow"].assert_not_awaited()
    assert (result.retired, result.desks_open) == (0, 0)
    assert list(result.failures) == ["u-1"]


async def test_an_owner_who_stopped_their_desk_keeps_the_row_they_kept() -> None:
    """A stopped desk says no to the new briefing; the kept row stays live."""
    stopped = MagicMock(completed=True)
    seams = _seams(_workflow("wf-1", "u-1"))
    seams["todo_repository"].find_latest_by_external_ref = AsyncMock(return_value=stopped)

    result = await _run(seams, dry_run=False)

    seams["WorkflowService.deactivate_workflow"].assert_not_awaited()
    assert (result.retired, result.desks_open, result.desks_stopped) == (0, 0, 1)
    assert result.failures == {}
