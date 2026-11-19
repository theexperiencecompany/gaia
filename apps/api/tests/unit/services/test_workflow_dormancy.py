"""Resuming the workflows paused while their owner was dormant."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.models.scheduler_models import DeactivationReason
from app.services.workflow.dormancy import resume_dormancy_paused_workflows

_MOD = "app.services.workflow.dormancy"


def _workflow(workflow_id: str) -> SimpleNamespace:
    return SimpleNamespace(id=workflow_id)


@pytest.mark.unit
class TestResumeDormancyPausedWorkflows:
    async def test_only_dormancy_paused_workflows_are_resumed(self):
        find_paused = AsyncMock(return_value=[_workflow("wf_a")])
        activate = AsyncMock()
        with (
            patch(f"{_MOD}.workflow_repository.find_paused_for_reason", find_paused),
            patch(f"{_MOD}.WorkflowService.activate_workflow", activate),
        ):
            resumed = await resume_dormancy_paused_workflows("u1")

        assert resumed == 1
        # The reason is what keeps a user's own deactivation out of the result set.
        find_paused.assert_awaited_once_with("u1", DeactivationReason.USER_DORMANT)
        activate.assert_awaited_once_with("wf_a", "u1")

    async def test_a_workflow_that_cannot_be_reactivated_is_skipped(self):
        """A disconnected integration must not block the user's other workflows."""
        activate = AsyncMock(side_effect=[ValueError("Connect Gmail to enable this."), None])
        with (
            patch(
                f"{_MOD}.workflow_repository.find_paused_for_reason",
                new_callable=AsyncMock,
                return_value=[_workflow("wf_a"), _workflow("wf_b")],
            ),
            patch(f"{_MOD}.WorkflowService.activate_workflow", activate),
        ):
            resumed = await resume_dormancy_paused_workflows("u1")

        assert resumed == 1

    async def test_nothing_paused_is_a_no_op(self):
        activate = AsyncMock()
        with (
            patch(
                f"{_MOD}.workflow_repository.find_paused_for_reason",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(f"{_MOD}.WorkflowService.activate_workflow", activate),
        ):
            resumed = await resume_dormancy_paused_workflows("u1")

        assert resumed == 0
        activate.assert_not_awaited()
