"""Regression tests: workflow tools must emit JSON-serializable payloads.

The workflow tools hand ``workflow.model_dump()`` (python mode — native
datetimes) to the LLM as a tool result and to the stream writer as an SSE
frame. Both consumers plain ``json.dumps`` the payload, so any datetime
raises ``TypeError: Object of type datetime is not JSON serializable`` — in
the background/bot path from *inside* the tool's try-block, which surfaces as
a tool error the agent then retries forever.

Same defect class already documented for search_reminders_tool in
scripts/evals/data/capability/reminders_extra.yaml; the codebase convention
(todo_tool.py, workflow_tasks.py) is ``model_dump(mode="json")``.
"""

from datetime import UTC, datetime, timedelta
import json
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.runnables.config import RunnableConfig
import pytest

from app.models.workflow_models import TriggerConfig, TriggerType, WorkflowWithIntegrations

MODULE = "app.agents.tools.workflow_tool"
UTILS_MODULE = "app.utils.workflow_utils"

FAKE_USER_ID = "507f1f77bcf86cd799439011"


def _make_config() -> RunnableConfig:
    return {
        "configurable": {
            "user_id": FAKE_USER_ID,
            "thread_id": "thread-123",
            "user_timezone": "+05:30",
        },
        "metadata": {"user_id": FAKE_USER_ID},
    }


def _make_real_workflow() -> WorkflowWithIntegrations:
    """A real model instance carrying every datetime the tools serialize."""
    return WorkflowWithIntegrations(
        user_id=FAKE_USER_ID,
        title="Daily digest",
        description="Send the digest",
        prompt="Send the digest",
        steps=[],
        trigger_config=TriggerConfig(
            type=TriggerType.SCHEDULE,
            enabled=True,
            cron_expression="0 16 * * *",
            timezone="Asia/Kolkata",
            next_run=datetime.now(UTC) + timedelta(hours=5),
        ),
        scheduled_at=datetime.now(UTC) + timedelta(hours=5),
        last_executed_at=datetime.now(UTC) - timedelta(days=1),
        created_at=datetime.now(UTC) - timedelta(days=30),
        updated_at=datetime.now(UTC) - timedelta(hours=1),
    )


def _assert_json_safe(payload: object) -> None:
    """The exact operation every consumer of these payloads performs."""
    json.dumps(payload)


@pytest.mark.unit
class TestWorkflowToolPayloadsAreJsonSafe:
    async def test_get_workflow_tool_result_is_json_safe(self) -> None:
        from app.agents.tools.workflow_tool import get_workflow

        workflow = _make_real_workflow()
        expected_payload = workflow.model_dump(mode="json")
        with (
            patch(f"{MODULE}.get_stream_writer") as mock_writer_factory,
            patch(f"{MODULE}.WorkflowService") as mock_service,
        ):
            writer = MagicMock()
            mock_writer_factory.return_value = writer
            mock_service.get_workflow = AsyncMock(return_value=workflow)

            result = await get_workflow.ainvoke(
                {"workflow_id": "wf-1"},
                config=_make_config(),
            )

        # The rate-limiting decorator adds its own _rate_limit_info key;
        # everything else must be exactly the JSON-safe payload.
        assert result["success"] is True
        assert result["data"] == expected_payload
        assert writer.call_args.args[0] == {
            "workflow_data": {"action": "get", "workflow": expected_payload}
        }

    async def test_pause_workflow_stream_frame_is_json_safe(self) -> None:
        from app.agents.tools.workflow_tool import pause_workflow

        workflow = _make_real_workflow()
        expected_payload = workflow.model_dump(mode="json")
        with (
            patch(f"{MODULE}.get_stream_writer") as mock_writer_factory,
            patch(f"{MODULE}.WorkflowService") as mock_service,
        ):
            writer = MagicMock()
            mock_writer_factory.return_value = writer
            mock_service.deactivate_workflow = AsyncMock(return_value=workflow)

            result = await pause_workflow.ainvoke(
                {"workflow_id": "wf-1"},
                config=_make_config(),
            )

        assert result["success"] is True
        assert writer.call_args.args[0] == {
            "workflow_data": {"action": "paused", "workflow": expected_payload}
        }

    async def test_resume_workflow_stream_frame_is_json_safe(self) -> None:
        from app.agents.tools.workflow_tool import resume_workflow

        workflow = _make_real_workflow()
        expected_payload = workflow.model_dump(mode="json")
        with (
            patch(f"{MODULE}.get_stream_writer") as mock_writer_factory,
            patch(f"{MODULE}.WorkflowService") as mock_service,
        ):
            writer = MagicMock()
            mock_writer_factory.return_value = writer
            mock_service.activate_workflow = AsyncMock(return_value=workflow)

            result = await resume_workflow.ainvoke(
                {"workflow_id": "wf-1"},
                config=_make_config(),
            )

        assert result["success"] is True
        assert writer.call_args.args[0] == {
            "workflow_data": {"action": "resumed", "workflow": expected_payload}
        }

    async def test_apply_workflow_edit_stream_frame_is_json_safe(self) -> None:
        from app.services.workflow.subagent_output import FinalizedOutput
        from app.utils.workflow_utils import apply_workflow_edit

        current = _make_real_workflow()
        updated = _make_real_workflow()
        updated.title = "Renamed digest"
        draft = FinalizedOutput(
            type="finalized",
            title="Renamed digest",
            description=current.description,
            prompt=current.prompt,
            trigger_type="scheduled",
            cron_expression=current.trigger_config.cron_expression,
        )
        writer = MagicMock()
        expected_payload = updated.model_dump(mode="json")

        with patch("app.services.workflow.service.WorkflowService") as mock_service:
            mock_service.update_workflow = AsyncMock(return_value=updated)

            result = await apply_workflow_edit(
                draft=draft,
                workflow=current,
                user_id=FAKE_USER_ID,
                writer=writer,
            )

        assert result["success"] is True
        assert writer.call_args.args[0] == {
            "workflow_data": {"action": "updated", "workflow": expected_payload}
        }

    async def test_create_directly_uses_prompt_not_description_as_instructions(self) -> None:
        """create_workflow_directly builds the execution instructions from the
        draft's prompt, falling back to its description only when absent."""
        from app.services.workflow.subagent_output import FinalizedOutput
        from app.utils.workflow_utils import create_workflow_directly

        workflow = _make_real_workflow()
        draft = FinalizedOutput(
            type="finalized",
            title="Manual thing",
            description="A short display blurb",
            prompt="The detailed execution instructions.",
            trigger_type="manual",
            direct_create=True,
        )

        with patch("app.services.workflow.service.WorkflowService") as mock_service:
            mock_service.create_workflow = AsyncMock(return_value=workflow)

            result = await create_workflow_directly(
                draft=draft, user_id=FAKE_USER_ID, writer=MagicMock()
            )

        assert result is not None
        request = mock_service.create_workflow.await_args.kwargs["request"]
        assert request.prompt == "The detailed execution instructions."
