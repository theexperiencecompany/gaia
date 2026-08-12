"""Unit tests for app.services.workflow.execution_service — wide-event contract."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.workflow.execution_service import complete_execution, create_execution
from shared.py.wide_events import log

_MOD = "app.services.workflow.execution_service"


@pytest.mark.unit
class TestExecutionWideEventFields:
    # These carry no regression marker any more. They pinned a whole-dict
    # `log.set(workflow={...})` erasing the namespace — which erased trigger_type
    # from 34,247 of 34,413 production workflow fires. #995 has since fixed that
    # at the root: `log.set` now merges a namespace instead of replacing it, so
    # the bug no longer exists on base and these correctly pass there. They stay
    # as gap-fill coverage that this specific path accumulates across
    # create -> complete, which the generic merge fix does not assert.
    async def test_completing_an_execution_keeps_the_trigger_type_the_caller_stamped(self):
        """Fields stamped by the caller survive the completion write."""
        log.reset()
        log.set_ns("workflow", id="wf_1", trigger_type="schedule", steps_count=3)

        with patch(
            f"{_MOD}.workflow_executions_repository.complete",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(workflow_id="wf_1", duration_seconds=1.5),
        ):
            assert await complete_execution(execution_id="exec_1", status="success") is True

        workflow = log.get()["workflow"]
        assert workflow["trigger_type"] == "schedule"
        assert workflow["steps_count"] == 3
        assert workflow["status"] == "success"
        assert workflow["duration_ms"] == 1500

    async def test_creating_an_execution_keeps_the_steps_count_the_caller_stamped(self):
        log.reset()
        log.set_ns("workflow", id="wf_1", steps_count=3)

        execution = SimpleNamespace(execution_id="exec_1")
        with patch(
            f"{_MOD}.workflow_executions_repository.create",
            new_callable=AsyncMock,
            return_value=execution,
        ):
            await create_execution(workflow_id="wf_1", user_id="u1", trigger_type="integration")

        workflow = log.get()["workflow"]
        assert workflow["steps_count"] == 3
        assert workflow["trigger_type"] == "integration"
        assert workflow["execution_id"] == "exec_1"
