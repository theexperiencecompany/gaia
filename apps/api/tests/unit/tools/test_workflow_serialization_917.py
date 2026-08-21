"""Regression tests for #917's class — workflow payloads carried native datetimes.

``get/pause/resume_workflow``, ``apply_workflow_edit``, and the workflow tool
returns serialized ``Workflow`` models in python mode, whose ``BaseScheduledTask``
base always carries ``created_at``/``updated_at`` native datetimes. The
stream-writer payload is JSON-encoded with stdlib ``json.dumps`` downstream
(``redis_writer.py``), so every emission crashed with "Object of type datetime
is not JSON serializable", and ``get_workflow``'s return value degraded to
Python reprs inside the ToolMessage. These tests pin the boundary contract:
whatever crosses into a stream frame or a tool return is JSON-safe.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.runnables.config import RunnableConfig
import pytest

from app.agents.tools.workflow_tool import (
    get_workflow,
    pause_workflow,
    resume_workflow,
)
from app.models.workflow_models import TriggerConfig, TriggerType, Workflow

FAKE_USER_ID = "507f1f77bcf86cd799439011"
MODULE = "app.agents.tools.workflow_tool"


def _cfg() -> RunnableConfig:
    return {
        "configurable": {
            "user_id": FAKE_USER_ID,
            "thread_id": "thread-123",
            "user_timezone": "+05:30",
        },
        "metadata": {"user_id": FAKE_USER_ID},
    }


def _workflow() -> Workflow:
    """A real document — its python-mode dump carries native datetimes."""
    return Workflow(
        user_id=FAKE_USER_ID,
        title="Morning digest",
        steps=[],
        trigger_config=TriggerConfig(
            type=TriggerType.SCHEDULE,
            cron_expression="0 9 * * *",
            next_run=datetime.now(UTC) + timedelta(hours=12),
        ),
        scheduled_at=datetime.now(UTC) + timedelta(hours=12),
    )


def _writer_mock() -> MagicMock:
    return MagicMock()


def _emitted_payloads(writer_mock: MagicMock) -> list[dict[str, Any]]:
    return [call.args[0] for call in writer_mock.call_args_list if call.args]


@pytest.fixture(autouse=True)
def _no_rate_limiting():
    """Keep the rate-limit mock scoped to this module's tests."""
    with patch(
        "app.decorators.rate_limiting.tiered_limiter.check_and_increment",
        new_callable=AsyncMock,
        return_value={},
    ):
        yield


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.regression
class TestWorkflowToolSerialization917:
    async def test_get_workflow_emits_json_safe_frames(self) -> None:
        doc = _workflow()
        expected = doc.model_dump(mode="json")
        writer = _writer_mock()
        with (
            patch(f"{MODULE}.get_stream_writer", return_value=writer),
            patch(f"{MODULE}.WorkflowService") as mock_service,
        ):
            mock_service.get_workflow = AsyncMock(return_value=doc)

            result = await get_workflow.ainvoke({"workflow_id": "wf_1"}, config=_cfg())

        assert _emitted_payloads(writer) == [
            {"workflow_data": {"action": "get", "workflow": expected}}
        ]
        # The rate-limiting wrapper may append its own top-level keys; the tool's
        # own contract is success + the JSON-safe payload.
        assert result["success"] is True
        assert result["data"] == expected

    async def test_pause_workflow_emits_json_safe_frames(self) -> None:
        doc = _workflow()
        expected = doc.model_dump(mode="json")
        writer = _writer_mock()
        with (
            patch(f"{MODULE}.get_stream_writer", return_value=writer),
            patch(f"{MODULE}.WorkflowService") as mock_service,
        ):
            mock_service.deactivate_workflow = AsyncMock(return_value=doc)

            result = await pause_workflow.ainvoke({"workflow_id": "wf_1"}, config=_cfg())

        assert result["data"] == {
            "workflow_id": doc.id,
            "title": doc.title,
            "activated": doc.activated,
        }
        assert _emitted_payloads(writer) == [
            {"workflow_data": {"action": "paused", "workflow": expected}}
        ]

    async def test_resume_workflow_emits_json_safe_frames(self) -> None:
        doc = _workflow()
        expected = doc.model_dump(mode="json")
        writer = _writer_mock()
        with (
            patch(f"{MODULE}.get_stream_writer", return_value=writer),
            patch(f"{MODULE}.WorkflowService") as mock_service,
        ):
            mock_service.activate_workflow = AsyncMock(return_value=doc)

            result = await resume_workflow.ainvoke({"workflow_id": "wf_1"}, config=_cfg())

        assert result["data"] == {
            "workflow_id": doc.id,
            "title": doc.title,
            "activated": doc.activated,
        }
        assert _emitted_payloads(writer) == [
            {"workflow_data": {"action": "resumed", "workflow": expected}}
        ]

    async def test_apply_workflow_edit_emits_json_safe_frames(self) -> None:
        from app.services.workflow.subagent_output import FinalizedOutput
        from app.utils.workflow_utils import apply_workflow_edit

        workflow = _workflow()
        draft = FinalizedOutput(
            type="finalized",
            title="Morning digest — edited",
            description="digest",
            prompt="prompt",
            trigger_type="scheduled",
            cron_expression="0 9 * * *",
        )
        updated = _workflow()
        writer = _writer_mock()
        # Patch the concrete defining module, not the package re-export: the
        # mutants/ workdir copies modules in an order where resolving
        # app.services.workflow.WorkflowService as a package attribute can fail.
        with patch(
            "app.services.workflow.service.WorkflowService.update_workflow",
            new_callable=AsyncMock,
        ) as mock_update:
            mock_update.return_value = updated

            await apply_workflow_edit(
                draft=draft, workflow=workflow, user_id=FAKE_USER_ID, writer=writer
            )

        mock_update.assert_awaited_once()
        assert _emitted_payloads(writer) == [
            {"workflow_data": {"action": "updated", "workflow": updated.model_dump(mode="json")}}
        ]
