"""Unit tests for TriggerService.resync_user_workflow_triggers (reconnect self-heal)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.workflow_models import (
    TriggerConfig,
    TriggerType,
    WorkflowDocument,
)
from app.services.workflow.trigger_service import TriggerService

MODULE = "app.services.workflow.trigger_service"


def _wf(wf_id: str, trigger_name: str, ids: list[str] | None) -> WorkflowDocument:
    return WorkflowDocument(
        id=wf_id,
        user_id="user1",
        title="wf",
        prompt="p",
        steps=[],
        trigger_config=TriggerConfig(
            type=TriggerType.INTEGRATION,
            trigger_name=trigger_name,
            enabled=True,
            composio_trigger_ids=ids,
        ),
    )


def _repo_returning(workflows: list[WorkflowDocument]) -> MagicMock:
    """A stand-in for workflow_repository — the resync's find + repoint seam."""
    repo = MagicMock()
    repo.find_active_integration_workflows = AsyncMock(return_value=workflows)
    repo.set_composio_trigger_ids = AsyncMock()
    return repo


@pytest.mark.asyncio
class TestResyncUserWorkflowTriggers:
    async def test_repoints_ids_and_unregisters_old(self):
        repo = _repo_returning([_wf("wf1", "gmail_poll_inbox", ["ti_old"])])
        with (
            patch(f"{MODULE}.workflow_repository", repo),
            patch.object(TriggerService, "register_triggers", AsyncMock(return_value=["ti_new"])),
            patch.object(TriggerService, "unregister_triggers", AsyncMock()) as unreg,
        ):
            await TriggerService.resync_user_workflow_triggers("user1", ["gmail_poll_inbox"])

        repo.set_composio_trigger_ids.assert_awaited_once_with("wf1", ["ti_new"])
        unreg.assert_awaited_once_with("user1", "gmail_poll_inbox", ["ti_old"], "wf1")

    async def test_no_trigger_names_is_a_noop(self):
        repo = _repo_returning([])
        with patch(f"{MODULE}.workflow_repository", repo):
            await TriggerService.resync_user_workflow_triggers("user1", [])
        repo.find_active_integration_workflows.assert_not_awaited()
        repo.set_composio_trigger_ids.assert_not_awaited()

    async def test_account_level_empty_ids_skips_update(self):
        """gmail_new_message registration returns [] — nothing to repoint."""
        repo = _repo_returning([_wf("wf1", "gmail_new_message", None)])
        with (
            patch(f"{MODULE}.workflow_repository", repo),
            patch.object(TriggerService, "register_triggers", AsyncMock(return_value=[])),
            patch.object(TriggerService, "unregister_triggers", AsyncMock()) as unreg,
        ):
            await TriggerService.resync_user_workflow_triggers("user1", ["gmail_new_message"])
        repo.set_composio_trigger_ids.assert_not_awaited()
        unreg.assert_not_awaited()

    async def test_unchanged_ids_skip_update(self):
        repo = _repo_returning([_wf("wf1", "gmail_poll_inbox", ["ti_same"])])
        with (
            patch(f"{MODULE}.workflow_repository", repo),
            patch.object(TriggerService, "register_triggers", AsyncMock(return_value=["ti_same"])),
            patch.object(TriggerService, "unregister_triggers", AsyncMock()) as unreg,
        ):
            await TriggerService.resync_user_workflow_triggers("user1", ["gmail_poll_inbox"])
        repo.set_composio_trigger_ids.assert_not_awaited()
        unreg.assert_not_awaited()

    async def test_one_failure_does_not_block_the_rest(self):
        repo = _repo_returning(
            [
                _wf("wf_bad", "gmail_poll_inbox", ["ti_a"]),
                _wf("wf_good", "gmail_poll_inbox", ["ti_b"]),
            ]
        )
        register = AsyncMock(side_effect=[RuntimeError("composio down"), ["ti_new"]])
        with (
            patch(f"{MODULE}.workflow_repository", repo),
            patch.object(TriggerService, "register_triggers", register),
            patch.object(TriggerService, "unregister_triggers", AsyncMock()),
        ):
            await TriggerService.resync_user_workflow_triggers("user1", ["gmail_poll_inbox"])

        repo.set_composio_trigger_ids.assert_awaited_once_with("wf_good", ["ti_new"])
