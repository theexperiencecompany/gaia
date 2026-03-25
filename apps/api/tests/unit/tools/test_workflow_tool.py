"""Unit tests for app.agents.tools.workflow_tool."""

from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Pre-import to break circular dependency chain:
# workflow_tool -> workflow_utils -> workflow.subagent_output -> workflow.__init__ -> service -> workflow_utils
import app.services.workflow.service  # noqa: F401

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_USER_ID = "507f1f77bcf86cd799439011"

MODULE = "app.agents.tools.workflow_tool"
SHARED_MODULE = "app.agents.tools.workflow_shared_tools"


def _make_config(
    user_id: str = FAKE_USER_ID,
    thread_id: str = "thread-123",
    user_name: str = "Test User",
    user_time: str = "2026-03-20T10:00:00+00:00",
    user_timezone: str = "+05:30",
) -> Dict[str, Any]:
    """Return a minimal RunnableConfig with configurable fields."""
    return {
        "configurable": {
            "user_id": user_id,
            "thread_id": thread_id,
            "user_name": user_name,
            "user_time": user_time,
            "user_timezone": user_timezone,
        },
        "metadata": {"user_id": user_id},
    }


def _make_config_no_user() -> Dict[str, Any]:
    """Config with no user_id."""
    return {"configurable": {}, "metadata": {}}


def _writer_mock() -> MagicMock:
    return MagicMock()


def _make_parsed_result(
    mode: str = "finalized",
    draft: Any = None,
    message: str | None = None,
    parse_error: str | None = None,
) -> MagicMock:
    """Create a mock ParsedSubagentResult."""
    result = MagicMock()
    result.mode = mode
    result.draft = draft
    result.message = message
    result.parse_error = parse_error
    return result


def _make_draft(
    title: str = "Test Workflow",
    trigger_type: str = "manual",
    direct_create: bool = False,
) -> MagicMock:
    """Create a mock FinalizedOutput draft."""
    draft = MagicMock()
    draft.title = title
    draft.trigger_type = trigger_type
    draft.direct_create = direct_create
    draft.to_stream_payload.return_value = {"workflow_draft": {"title": title}}
    return draft


def _make_workflow_mock(**overrides: Any) -> MagicMock:
    """Create a mock workflow object."""
    defaults: Dict[str, Any] = {
        "id": "wf-1",
        "title": "My Workflow",
        "description": "A workflow",
        "trigger_config": MagicMock(type="manual"),
        "activated": True,
        "steps": [MagicMock(), MagicMock()],
        "total_executions": 5,
    }
    defaults.update(overrides)
    mock = MagicMock()
    for key, val in defaults.items():
        setattr(mock, key, val)
    mock.model_dump.return_value = {k: v for k, v in defaults.items()}
    return mock


# ---------------------------------------------------------------------------
# Tests: create_workflow
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateWorkflow:
    """Tests for the create_workflow tool."""

    async def test_new_mode_draft_sent(self) -> None:
        """New mode successfully returns draft_sent status."""
        from app.agents.tools.workflow_tool import create_workflow

        draft = _make_draft()
        parsed = _make_parsed_result(mode="finalized", draft=draft)

        with (
            patch(f"{MODULE}.get_stream_writer") as mock_writer_factory,
            patch(f"{MODULE}.parse_subagent_response", return_value=parsed),
            patch(f"{MODULE}.WorkflowSubagentRunner") as mock_runner,
        ):
            mock_writer_factory.return_value = _writer_mock()
            mock_runner.execute = AsyncMock(return_value="subagent output")

            result = await create_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                user_request="send me a summary every morning",
                mode="new",
            )

        assert result["success"] is True
        assert result["data"]["status"] == "draft_sent"
        draft.to_stream_payload.assert_called_once()

    async def test_new_mode_clarifying(self) -> None:
        """Clarifying mode returns the question for the user."""
        from app.agents.tools.workflow_tool import create_workflow

        parsed = _make_parsed_result(
            mode="clarifying", message="What time should it run?"
        )

        with (
            patch(f"{MODULE}.get_stream_writer") as mock_writer_factory,
            patch(f"{MODULE}.parse_subagent_response", return_value=parsed),
            patch(f"{MODULE}.WorkflowSubagentRunner") as mock_runner,
        ):
            mock_writer_factory.return_value = _writer_mock()
            mock_runner.execute = AsyncMock(return_value="output")

            result = await create_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                user_request="create a workflow",
                mode="new",
            )

        assert result["success"] is True
        assert result["data"]["status"] == "clarifying"
        assert "What time should it run?" in result["data"]["question"]

    async def test_new_mode_parse_error(self) -> None:
        """Parse error from subagent is handled gracefully."""
        from app.agents.tools.workflow_tool import create_workflow

        parsed = _make_parsed_result(mode="parse_error", parse_error="Invalid JSON")

        with (
            patch(f"{MODULE}.get_stream_writer") as mock_writer_factory,
            patch(f"{MODULE}.parse_subagent_response", return_value=parsed),
            patch(f"{MODULE}.WorkflowSubagentRunner") as mock_runner,
        ):
            mock_writer_factory.return_value = _writer_mock()
            mock_runner.execute = AsyncMock(return_value="output")

            result = await create_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                user_request="create workflow",
                mode="new",
            )

        assert result["success"] is False
        assert result["error"] == "parse_error"

    async def test_new_mode_empty_request(self) -> None:
        """Empty user_request returns missing_request error."""
        from app.agents.tools.workflow_tool import create_workflow

        with patch(f"{MODULE}.get_stream_writer") as mock_writer_factory:
            mock_writer_factory.return_value = _writer_mock()

            result = await create_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                user_request="",
                mode="new",
            )

        assert result["success"] is False
        assert result["error"] == "missing_request"

    async def test_invalid_mode(self) -> None:
        """Invalid mode returns error."""
        from app.agents.tools.workflow_tool import create_workflow

        with patch(f"{MODULE}.get_stream_writer") as mock_writer_factory:
            mock_writer_factory.return_value = _writer_mock()

            result = await create_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                user_request="test",
                mode="invalid",
            )

        assert result["success"] is False
        assert result["error"] == "invalid_mode"

    async def test_from_conversation_no_thread(self) -> None:
        """from_conversation mode without thread_id returns error."""
        from app.agents.tools.workflow_tool import create_workflow

        config = _make_config()
        config["configurable"]["thread_id"] = ""

        with patch(f"{MODULE}.get_stream_writer") as mock_writer_factory:
            mock_writer_factory.return_value = _writer_mock()

            result = await create_workflow.coroutine(  # type: ignore[attr-defined]
                config=config,
                user_request="save this",
                mode="from_conversation",
            )

        assert result["success"] is False
        assert result["error"] == "no_context"

    async def test_from_conversation_extraction_fails(self) -> None:
        """from_conversation returns error when context extraction fails."""
        from app.agents.tools.workflow_tool import create_workflow

        with (
            patch(f"{MODULE}.get_stream_writer") as mock_writer_factory,
            patch(f"{MODULE}.WorkflowContextExtractor") as mock_extractor,
        ):
            mock_writer_factory.return_value = _writer_mock()
            mock_extractor.extract_from_thread = AsyncMock(return_value=None)

            result = await create_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                user_request="save this",
                mode="from_conversation",
            )

        assert result["success"] is False
        assert result["error"] == "extraction_failed"

    async def test_subagent_exception(self) -> None:
        """Subagent runner exception returns error."""
        from app.agents.tools.workflow_tool import create_workflow

        with (
            patch(f"{MODULE}.get_stream_writer") as mock_writer_factory,
            patch(f"{MODULE}.WorkflowSubagentRunner") as mock_runner,
        ):
            mock_writer_factory.return_value = _writer_mock()
            mock_runner.execute = AsyncMock(side_effect=Exception("Runner crashed"))

            result = await create_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                user_request="make a workflow",
                mode="new",
            )

        assert result["success"] is False
        assert result["error"] == "subagent_failed"

    async def test_direct_creation_success(self) -> None:
        """Direct creation of simple workflows bypasses confirmation."""
        from app.agents.tools.workflow_tool import create_workflow

        draft = _make_draft(direct_create=True)
        parsed = _make_parsed_result(mode="finalized", draft=draft)
        direct_result = {"success": True, "data": {"id": "wf-new"}}

        with (
            patch(f"{MODULE}.get_stream_writer") as mock_writer_factory,
            patch(f"{MODULE}.parse_subagent_response", return_value=parsed),
            patch(f"{MODULE}.WorkflowSubagentRunner") as mock_runner,
            patch(f"{MODULE}.can_create_directly", return_value=True),
            patch(
                f"{MODULE}.create_workflow_directly",
                new_callable=AsyncMock,
                return_value=direct_result,
            ),
        ):
            mock_writer_factory.return_value = _writer_mock()
            mock_runner.execute = AsyncMock(return_value="output")

            result = await create_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                user_request="run daily at 9am",
                mode="new",
            )

        assert result == direct_result

    async def test_direct_creation_fallback_to_draft(self) -> None:
        """When direct creation fails, falls back to streaming draft."""
        from app.agents.tools.workflow_tool import create_workflow

        draft = _make_draft(direct_create=True)
        parsed = _make_parsed_result(mode="finalized", draft=draft)

        with (
            patch(f"{MODULE}.get_stream_writer") as mock_writer_factory,
            patch(f"{MODULE}.parse_subagent_response", return_value=parsed),
            patch(f"{MODULE}.WorkflowSubagentRunner") as mock_runner,
            patch(f"{MODULE}.can_create_directly", return_value=True),
            patch(
                f"{MODULE}.create_workflow_directly",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            writer = _writer_mock()
            mock_writer_factory.return_value = writer
            mock_runner.execute = AsyncMock(return_value="output")

            result = await create_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                user_request="run daily",
                mode="new",
            )

        assert result["success"] is True
        assert result["data"]["status"] == "draft_sent"
        draft.to_stream_payload.assert_called_once()


# ---------------------------------------------------------------------------
# Tests: get_workflow
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetWorkflow:
    """Tests for the get_workflow tool."""

    async def test_happy_path(self) -> None:
        """Successfully retrieves a workflow."""
        from app.agents.tools.workflow_tool import get_workflow

        workflow = _make_workflow_mock()

        with (
            patch(f"{MODULE}.get_stream_writer") as mock_writer_factory,
            patch(f"{MODULE}.WorkflowService") as mock_service,
        ):
            writer = _writer_mock()
            mock_writer_factory.return_value = writer
            mock_service.get_workflow = AsyncMock(return_value=workflow)

            result = await get_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                workflow_id="wf-1",
            )

        assert result["success"] is True

    async def test_not_found(self) -> None:
        """Returns error when workflow not found."""
        from app.agents.tools.workflow_tool import get_workflow

        with (
            patch(f"{MODULE}.get_stream_writer") as mock_writer_factory,
            patch(f"{MODULE}.WorkflowService") as mock_service,
        ):
            mock_writer_factory.return_value = _writer_mock()
            mock_service.get_workflow = AsyncMock(return_value=None)

            result = await get_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                workflow_id="wf-nonexistent",
            )

        assert result["success"] is False
        assert result["error"] == "not_found"

    async def test_service_error(self) -> None:
        """Service exception returns fetch_failed error."""
        from app.agents.tools.workflow_tool import get_workflow

        with (
            patch(f"{MODULE}.get_stream_writer") as mock_writer_factory,
            patch(f"{MODULE}.WorkflowService") as mock_service,
        ):
            mock_writer_factory.return_value = _writer_mock()
            mock_service.get_workflow = AsyncMock(side_effect=Exception("DB timeout"))

            result = await get_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                workflow_id="wf-1",
            )

        assert result["success"] is False
        assert result["error"] == "fetch_failed"


# ---------------------------------------------------------------------------
# Tests: execute_workflow
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExecuteWorkflow:
    """Tests for the execute_workflow tool."""

    async def test_happy_path(self) -> None:
        """Successfully starts workflow execution."""
        from app.agents.tools.workflow_tool import execute_workflow

        exec_result = MagicMock()
        exec_result.execution_id = "exec-1"
        exec_result.message = "Workflow started"

        with (
            patch(f"{MODULE}.get_stream_writer") as mock_writer_factory,
            patch(f"{MODULE}.WorkflowService") as mock_service,
        ):
            writer = _writer_mock()
            mock_writer_factory.return_value = writer
            mock_service.execute_workflow = AsyncMock(return_value=exec_result)

            result = await execute_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                workflow_id="wf-1",
            )

        assert result["success"] is True
        assert result["data"]["execution_id"] == "exec-1"

    async def test_execution_failure(self) -> None:
        """Execution failure returns error."""
        from app.agents.tools.workflow_tool import execute_workflow

        with (
            patch(f"{MODULE}.get_stream_writer") as mock_writer_factory,
            patch(f"{MODULE}.WorkflowService") as mock_service,
        ):
            mock_writer_factory.return_value = _writer_mock()
            mock_service.execute_workflow = AsyncMock(
                side_effect=Exception("Workflow disabled")
            )

            result = await execute_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                workflow_id="wf-1",
            )

        assert result["success"] is False
        assert result["error"] == "execution_failed"


# ---------------------------------------------------------------------------
# Tests: search_triggers (shared tool)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSearchTriggers:
    """Tests for the search_triggers shared tool."""

    async def test_happy_path(self) -> None:
        """Returns triggers with connected/not-connected counts."""
        from app.agents.tools.workflow_shared_tools import search_triggers

        with patch(f"{SHARED_MODULE}.TriggerSearchService") as mock_trigger_svc:
            mock_trigger_svc.search = AsyncMock(
                return_value=[
                    {"name": "calendar_event", "is_connected": True},
                    {"name": "slack_message", "is_connected": False},
                ]
            )

            result = await search_triggers.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                query="when I get a calendar event",
            )

        assert result["success"] is True
        assert result["data"]["connected_count"] == 1
        assert result["data"]["not_connected_count"] == 1

    async def test_search_failure(self) -> None:
        """Search failure returns error."""
        from app.agents.tools.workflow_shared_tools import search_triggers

        with patch(f"{SHARED_MODULE}.TriggerSearchService") as mock_trigger_svc:
            mock_trigger_svc.search = AsyncMock(
                side_effect=Exception("ChromaDB unavailable")
            )

            result = await search_triggers.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                query="test",
            )

        assert result["success"] is False
        assert result["error"] == "search_failed"


# ---------------------------------------------------------------------------
# Tests: list_workflows (shared tool)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListWorkflows:
    """Tests for the list_workflows shared tool."""

    async def test_happy_path(self) -> None:
        """Returns list of workflow summaries."""
        from app.agents.tools.workflow_shared_tools import list_workflows

        workflow = _make_workflow_mock()

        with (
            patch(f"{SHARED_MODULE}.get_stream_writer") as mock_writer_factory,
            patch(f"{SHARED_MODULE}.WorkflowService") as mock_service,
        ):
            writer = _writer_mock()
            mock_writer_factory.return_value = writer
            mock_service.list_workflows = AsyncMock(return_value=[workflow])

            result = await list_workflows.coroutine(config=_make_config())  # type: ignore[attr-defined]

        assert result["success"] is True
        assert result["data"]["total"] == 1
        assert len(result["data"]["workflows"]) == 1

    async def test_service_error(self) -> None:
        """Service error returns fetch_failed."""
        from app.agents.tools.workflow_shared_tools import list_workflows

        with (
            patch(f"{SHARED_MODULE}.get_stream_writer") as mock_writer_factory,
            patch(f"{SHARED_MODULE}.WorkflowService") as mock_service,
        ):
            mock_writer_factory.return_value = _writer_mock()
            mock_service.list_workflows = AsyncMock(
                side_effect=Exception("Connection refused")
            )

            result = await list_workflows.coroutine(config=_make_config())  # type: ignore[attr-defined]

        assert result["success"] is False
        assert result["error"] == "fetch_failed"
