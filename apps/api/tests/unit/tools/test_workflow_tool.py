"""Unit tests for app.agents.tools.workflow_tool."""

from contextlib import ExitStack
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from app.constants.log_tags import LogTag
from app.models.workflow_models import WorkflowExecutionRequest

# Pre-import to break circular dependency chain:
# workflow_tool -> workflow_utils -> workflow.subagent_output -> workflow.__init__ -> service -> workflow_utils
import app.services.workflow.service  # noqa: F401

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_USER_ID = "507f1f77bcf86cd799439011"

MODULE = "app.agents.tools.workflow_tool"
SHARED_MODULE = "app.agents.tools.workflow_shared_tools"

EXPECTED_MISSING_REQUEST = {
    "success": False,
    "error": "missing_request",
    "message": "user_request is required. Pass the user's words describing what workflow they want.",
}
EXPECTED_EDIT_MISSING_REQUEST = {
    "success": False,
    "error": "missing_request",
    "message": "user_request is required — pass the user's change in their words.",
}


def _make_config(
    user_id: str = FAKE_USER_ID,
    thread_id: str = "thread-123",
    user_name: str = "Test User",
    user_timezone: str = "+05:30",
) -> dict[str, Any]:
    """Return a minimal RunnableConfig with configurable fields."""
    return {
        "configurable": {
            "user_id": user_id,
            "thread_id": thread_id,
            "user_name": user_name,
            "user_timezone": user_timezone,
        },
        "metadata": {"user_id": user_id},
    }


def _make_config_sparse() -> dict[str, Any]:
    """Config carrying only user_id — every other configurable falls back."""
    return {
        "configurable": {"user_id": FAKE_USER_ID},
        "metadata": {"user_id": FAKE_USER_ID},
    }


def _make_config_no_user() -> dict[str, Any]:
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
    defaults: dict[str, Any] = {
        "id": "wf-1",
        "title": "My Workflow",
        "description": "A workflow",
        "trigger_config": MagicMock(type=MagicMock(value="manual")),
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


def _envelope(result: dict[str, Any]) -> dict[str, Any]:
    """The tool's own response envelope, minus the rate-limiter metadata key.

    `with_rate_limiting` injects `_rate_limit_info` into the returned dict when
    the limiter runs; it is decorator bookkeeping, not part of the tool's
    contract, so exact-equality asserts compare the envelope without it.
    """
    return {k: v for k, v in result.items() if k != "_rate_limit_info"}


class _ToolSeams:
    """Context manager applying workflow_tool's standard seams.

    Patches the stream writer, WorkflowService, WorkflowSubagentRunner, and
    parse_subagent_response for the duration of the ``with`` block. Each tool
    only touches the seams it uses; the rest are inert. ``service_methods``
    maps a WorkflowService method name to the AsyncMock it should return, and
    ``extra`` holds additional patch objects (entered after the defaults).
    """

    def __init__(
        self,
        *,
        service_methods: dict[str, Any] | None = None,
        parsed: Any = None,
        runner_output: str = "subagent output",
        runner_error: Exception | None = None,
    ) -> None:
        self.writer = MagicMock()
        self.service = MagicMock()
        for name, behavior in (service_methods or {}).items():
            setattr(self.service, name, behavior)
        self.runner = MagicMock()
        self.runner.execute = (
            AsyncMock(side_effect=runner_error)
            if runner_error is not None
            else AsyncMock(return_value=runner_output)
        )
        self.parse = MagicMock(return_value=parsed)
        self.log = MagicMock()
        self.extra: list[Any] = []

    def __enter__(self) -> "_ToolSeams":
        self._stack = ExitStack()
        for patcher in (
            patch(f"{MODULE}.get_stream_writer", return_value=self.writer),
            patch(f"{MODULE}.WorkflowService", self.service),
            patch(f"{MODULE}.WorkflowSubagentRunner", self.runner),
            patch(f"{MODULE}.parse_subagent_response", self.parse),
            patch(f"{MODULE}.log", self.log),
            *self.extra,
        ):
            self._stack.enter_context(patcher)
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self._stack.close()


def _assert_create_flow_logs(log_mock: MagicMock, mode: str) -> None:
    """Assert create_workflow's common log lines (set + Executing + parsed mode)."""
    log_mock.set.assert_called_once_with(tool={"name": "create_workflow", "action": "create"})
    log_mock.info.assert_any_call(f"{LogTag.TOOL} create_workflow: Executing")
    log_mock.info.assert_any_call(f"{LogTag.TOOL} create_workflow: parsed mode", mode=mode)


def _assert_create_exception_logs(log_mock: MagicMock, error_type: str) -> None:
    """Assert create_workflow's exception log line."""
    log_mock.set.assert_called_once_with(tool={"name": "create_workflow", "action": "create"})
    log_mock.error.assert_any_call(
        f"{LogTag.TOOL} create_workflow: exception",
        error_type=error_type,
        exc_info=True,
    )


def _assert_edit_flow_logs(log_mock: MagicMock, mode: str) -> None:
    """Assert edit_workflow's common log lines (set + parsed mode)."""
    log_mock.set.assert_called_once_with(tool={"name": "edit_workflow", "action": "edit"})
    log_mock.info.assert_any_call(f"{LogTag.TOOL} edit_workflow: parsed mode", mode=mode)


def _assert_edit_exception_logs(log_mock: MagicMock, error_type: str) -> None:
    """Assert edit_workflow's exception log line."""
    log_mock.set.assert_called_once_with(tool={"name": "edit_workflow", "action": "edit"})
    log_mock.error.assert_any_call(
        f"{LogTag.TOOL} edit_workflow: exception",
        error_type=error_type,
        exc_info=True,
    )


# ---------------------------------------------------------------------------
# Tests: create_workflow
# ---------------------------------------------------------------------------


class TestCreateWorkflow:
    """Tests for the create_workflow tool."""

    async def test_new_mode_draft_sent(self) -> None:
        """Finalized draft is streamed and draft_sent returned, with exact seam args."""
        from app.agents.tools.workflow_tool import create_workflow

        config = _make_config()
        draft = _make_draft()
        parsed = _make_parsed_result(mode="finalized", draft=draft)

        with (
            _ToolSeams(parsed=parsed) as seams,
            patch(f"{MODULE}.build_new_workflow_task", return_value="built task") as build_task,
            patch(f"{MODULE}.can_create_directly", return_value=False) as can_direct,
            patch(
                f"{MODULE}.create_workflow_directly",
                new_callable=AsyncMock,
                return_value={"success": True},
            ) as create_direct,
        ):
            result = await create_workflow.coroutine(  # type: ignore[attr-defined]
                config=config,
                user_request="  send me a summary every morning  ",
            )

        assert _envelope(result) == {
            "success": True,
            "data": {"status": "draft_sent"},
            "message": "Workflow draft sent to user for confirmation.",
        }
        _assert_create_flow_logs(seams.log, "finalized")
        seams.log.info.assert_any_call(
            f"{LogTag.TOOL} create_workflow: streamed draft", draft_title="Test Workflow"
        )
        build_task.assert_called_once_with("send me a summary every morning")
        seams.runner.execute.assert_awaited_once_with(
            task="built task",
            user_id=FAKE_USER_ID,
            thread_id="thread-123",
            user_name="Test User",
            user_timezone="+05:30",
            stream_writer=seams.writer,
            base_configurable=config["configurable"],
        )
        seams.parse.assert_called_once_with("subagent output")
        can_direct.assert_called_once_with(draft)
        create_direct.assert_not_awaited()
        draft.to_stream_payload.assert_called_once_with()
        seams.writer.assert_called_once_with({"workflow_draft": {"title": "Test Workflow"}})

    async def test_sparse_config_passes_defaults(self) -> None:
        """Missing thread_id/user_name/user_timezone fall back to their defaults."""
        from app.agents.tools.workflow_tool import create_workflow

        parsed = _make_parsed_result(mode="finalized", draft=_make_draft())

        with (
            _ToolSeams(parsed=parsed) as seams,
            patch(f"{MODULE}.build_new_workflow_task", return_value="built task"),
        ):
            result = await create_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config_sparse(),
                user_request="make me a workflow",
            )

        assert _envelope(result)["data"]["status"] == "draft_sent"
        _assert_create_flow_logs(seams.log, "finalized")
        seams.log.info.assert_any_call(
            f"{LogTag.TOOL} create_workflow: streamed draft", draft_title="Test Workflow"
        )
        seams.runner.execute.assert_awaited_once_with(
            task="built task",
            user_id=FAKE_USER_ID,
            thread_id="",
            user_name=None,
            user_timezone="UTC",
            stream_writer=seams.writer,
            base_configurable={"user_id": FAKE_USER_ID},
        )

    async def test_new_mode_clarifying(self) -> None:
        """Clarifying mode returns the question for the user."""
        from app.agents.tools.workflow_tool import create_workflow

        parsed = _make_parsed_result(mode="clarifying", message="What time should it run?")

        with _ToolSeams(parsed=parsed) as seams:
            result = await create_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                user_request="create a workflow",
            )

        assert _envelope(result) == {
            "success": True,
            "data": {"status": "clarifying", "question": "What time should it run?"},
            "message": "The workflow assistant needs clarification from the user: What time should it run?",
        }
        _assert_create_flow_logs(seams.log, "clarifying")
        seams.writer.assert_not_called()

    async def test_new_mode_clarifying_without_message(self) -> None:
        """Clarifying mode without a message falls back to the default question."""
        from app.agents.tools.workflow_tool import create_workflow

        parsed = _make_parsed_result(mode="clarifying", message=None)

        with _ToolSeams(parsed=parsed) as seams:
            result = await create_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                user_request="create a workflow",
            )

        assert _envelope(result) == {
            "success": True,
            "data": {
                "status": "clarifying",
                "question": "The workflow assistant needs more information.",
            },
            "message": (
                "The workflow assistant needs clarification from the user: "
                "The workflow assistant needs more information."
            ),
        }
        _assert_create_flow_logs(seams.log, "clarifying")
        seams.writer.assert_not_called()

    async def test_new_mode_parse_error(self) -> None:
        """Parse error from subagent is handled gracefully."""
        from app.agents.tools.workflow_tool import create_workflow

        parsed = _make_parsed_result(mode="parse_error", parse_error="Invalid JSON")

        with _ToolSeams(parsed=parsed) as seams:
            result = await create_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                user_request="create workflow",
            )

        assert _envelope(result) == {
            "success": False,
            "error": "parse_error",
            "message": (
                "Failed to process the workflow assistant's response: Invalid JSON. "
                "Please try again or rephrase your request."
            ),
        }
        _assert_create_flow_logs(seams.log, "parse_error")
        seams.log.warning.assert_any_call(
            f"{LogTag.TOOL} create_workflow: parse error", parse_error="Invalid JSON"
        )
        seams.writer.assert_not_called()

    async def test_new_mode_finalized_without_draft_completed(self) -> None:
        """Finalized mode without a draft falls through to completed."""
        from app.agents.tools.workflow_tool import create_workflow

        parsed = _make_parsed_result(mode="finalized", draft=None)

        with _ToolSeams(parsed=parsed) as seams:
            result = await create_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                user_request="create workflow",
            )

        assert _envelope(result) == {
            "success": True,
            "data": {"status": "completed"},
            "message": "Workflow creation completed.",
        }
        _assert_create_flow_logs(seams.log, "finalized")
        seams.writer.assert_not_called()

    async def test_unknown_mode_completed(self) -> None:
        """Any unhandled mode still returns a completed response."""
        from app.agents.tools.workflow_tool import create_workflow

        parsed = _make_parsed_result(mode="unexpected_mode")

        with _ToolSeams(parsed=parsed) as seams:
            result = await create_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                user_request="create workflow",
            )

        assert _envelope(result) == {
            "success": True,
            "data": {"status": "completed"},
            "message": "Workflow creation completed.",
        }
        _assert_create_flow_logs(seams.log, "unexpected_mode")
        seams.writer.assert_not_called()

    async def test_new_mode_empty_request(self) -> None:
        """Empty user_request returns missing_request error."""
        from app.agents.tools.workflow_tool import create_workflow

        with _ToolSeams() as seams:
            result = await create_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                user_request="",
            )

        assert _envelope(result) == EXPECTED_MISSING_REQUEST
        seams.log.set.assert_called_once_with(tool={"name": "create_workflow", "action": "create"})
        seams.runner.execute.assert_not_awaited()

    async def test_new_mode_whitespace_request(self) -> None:
        """Whitespace-only user_request is rejected like an empty one."""
        from app.agents.tools.workflow_tool import create_workflow

        with _ToolSeams() as seams:
            result = await create_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                user_request="   ",
            )

        assert _envelope(result) == EXPECTED_MISSING_REQUEST
        seams.log.set.assert_called_once_with(tool={"name": "create_workflow", "action": "create"})
        seams.runner.execute.assert_not_awaited()

    async def test_missing_user_id(self) -> None:
        """Missing user_id in config surfaces as a subagent_failed error."""
        from app.agents.tools.workflow_tool import create_workflow

        with _ToolSeams() as seams:
            result = await create_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config_no_user(),
                user_request="create workflow",
            )

        assert _envelope(result) == {
            "success": False,
            "error": "subagent_failed",
            "message": "User authentication required",
        }
        _assert_create_exception_logs(seams.log, "WorkflowConfigError")
        seams.runner.execute.assert_not_awaited()

    async def test_direct_creation_success(self) -> None:
        """Direct creation of simple workflows bypasses confirmation."""
        from app.agents.tools.workflow_tool import create_workflow

        draft = _make_draft(direct_create=True)
        parsed = _make_parsed_result(mode="finalized", draft=draft)
        direct_result = {"success": True, "data": {"id": "wf-new"}}

        with (
            _ToolSeams(parsed=parsed) as seams,
            patch(f"{MODULE}.can_create_directly", return_value=True) as can_direct,
            patch(
                f"{MODULE}.create_workflow_directly",
                new_callable=AsyncMock,
                return_value=direct_result,
            ) as create_direct,
        ):
            result = await create_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                user_request="run daily at 9am",
            )

        assert _envelope(result) == {"success": True, "data": {"id": "wf-new"}}
        _assert_create_flow_logs(seams.log, "finalized")
        seams.log.info.assert_any_call(
            f"{LogTag.TOOL} create_workflow: attempting direct creation",
            draft_title="Test Workflow",
        )
        can_direct.assert_called_once_with(draft)
        create_direct.assert_awaited_once_with(
            draft=draft,
            user_id=FAKE_USER_ID,
            writer=seams.writer,
            user_timezone="+05:30",
        )
        draft.to_stream_payload.assert_not_called()
        seams.writer.assert_not_called()

    async def test_direct_creation_fallback_to_draft(self) -> None:
        """When direct creation fails, falls back to streaming draft."""
        from app.agents.tools.workflow_tool import create_workflow

        draft = _make_draft(direct_create=True)
        parsed = _make_parsed_result(mode="finalized", draft=draft)

        with (
            _ToolSeams(parsed=parsed) as seams,
            patch(f"{MODULE}.can_create_directly", return_value=True),
            patch(
                f"{MODULE}.create_workflow_directly",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            result = await create_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                user_request="run daily",
            )

        assert _envelope(result) == {
            "success": True,
            "data": {"status": "draft_sent"},
            "message": "Workflow draft sent to user for confirmation.",
        }
        _assert_create_flow_logs(seams.log, "finalized")
        seams.log.info.assert_any_call(
            f"{LogTag.TOOL} create_workflow: attempting direct creation",
            draft_title="Test Workflow",
        )
        seams.log.info.assert_any_call(
            f"{LogTag.TOOL} create_workflow: Direct creation failed, falling back to draft"
        )
        seams.log.info.assert_any_call(
            f"{LogTag.TOOL} create_workflow: streamed draft", draft_title="Test Workflow"
        )
        draft.to_stream_payload.assert_called_once_with()
        seams.writer.assert_called_once_with({"workflow_draft": {"title": "Test Workflow"}})

    async def test_subagent_exception(self) -> None:
        """Subagent runner exception returns error."""
        from app.agents.tools.workflow_tool import create_workflow

        with _ToolSeams(runner_error=Exception("Runner crashed")) as seams:
            result = await create_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                user_request="make a workflow",
            )

        assert _envelope(result) == {
            "success": False,
            "error": "subagent_failed",
            "message": "Runner crashed",
        }
        _assert_create_exception_logs(seams.log, "Exception")
        seams.writer.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: get_workflow
# ---------------------------------------------------------------------------


class TestGetWorkflow:
    """Tests for the get_workflow tool."""

    async def test_happy_path(self) -> None:
        """Successfully retrieves a workflow with exact service args and payloads."""
        from app.agents.tools.workflow_tool import get_workflow

        workflow = _make_workflow_mock()

        with _ToolSeams(
            service_methods={"get_workflow": AsyncMock(return_value=workflow)}
        ) as seams:
            result = await get_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                workflow_id="wf-1",
            )

        expected_dump = workflow.model_dump()
        seams.service.get_workflow.assert_awaited_once_with("wf-1", FAKE_USER_ID)
        seams.log.set.assert_called_once_with(tool={"name": "get_workflow", "action": "get"})
        seams.writer.assert_called_once_with(
            {"workflow_data": {"action": "get", "workflow": expected_dump}}
        )
        assert _envelope(result) == {"success": True, "data": expected_dump}

    async def test_not_found(self) -> None:
        """Returns error when workflow not found."""
        from app.agents.tools.workflow_tool import get_workflow

        with _ToolSeams(service_methods={"get_workflow": AsyncMock(return_value=None)}) as seams:
            result = await get_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                workflow_id="wf-nonexistent",
            )

        assert _envelope(result) == {
            "success": False,
            "error": "not_found",
            "message": "Workflow wf-nonexistent not found",
        }
        seams.log.set.assert_called_once_with(tool={"name": "get_workflow", "action": "get"})
        seams.writer.assert_not_called()

    async def test_service_error(self) -> None:
        """Service exception returns fetch_failed error."""
        from app.agents.tools.workflow_tool import get_workflow

        with _ToolSeams(
            service_methods={"get_workflow": AsyncMock(side_effect=Exception("DB timeout"))}
        ) as seams:
            result = await get_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                workflow_id="wf-1",
            )

        assert _envelope(result) == {
            "success": False,
            "error": "fetch_failed",
            "message": "DB timeout",
        }
        seams.log.set.assert_called_once_with(tool={"name": "get_workflow", "action": "get"})
        seams.log.error.assert_any_call(
            f"{LogTag.TOOL} Error getting workflow",
            workflow_id="wf-1",
            error_type="Exception",
        )
        seams.writer.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: execute_workflow
# ---------------------------------------------------------------------------


class TestExecuteWorkflow:
    """Tests for the execute_workflow tool."""

    async def test_happy_path(self) -> None:
        """Successfully starts workflow execution with exact service args and payloads."""
        from app.agents.tools.workflow_tool import execute_workflow

        exec_result = MagicMock()
        exec_result.execution_id = "exec-1"
        exec_result.message = "Workflow started"

        with _ToolSeams(
            service_methods={"execute_workflow": AsyncMock(return_value=exec_result)}
        ) as seams:
            result = await execute_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                workflow_id="wf-1",
            )

        expected_data = {
            "workflow_id": "wf-1",
            "execution_id": "exec-1",
            "message": "Workflow started",
        }
        seams.service.execute_workflow.assert_awaited_once_with(
            "wf-1", WorkflowExecutionRequest(), FAKE_USER_ID
        )
        seams.log.set.assert_called_once_with(
            tool={"name": "execute_workflow", "action": "execute"}
        )
        seams.writer.assert_called_once_with(
            {"workflow_execution": {"action": "started", "execution": expected_data}}
        )
        assert _envelope(result) == {"success": True, "data": expected_data}

    async def test_execution_failure(self) -> None:
        """Execution failure returns error."""
        from app.agents.tools.workflow_tool import execute_workflow

        with _ToolSeams(
            service_methods={
                "execute_workflow": AsyncMock(side_effect=Exception("Workflow disabled"))
            }
        ) as seams:
            result = await execute_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                workflow_id="wf-1",
            )

        assert _envelope(result) == {
            "success": False,
            "error": "execution_failed",
            "message": "Workflow disabled",
        }
        seams.log.set.assert_called_once_with(
            tool={"name": "execute_workflow", "action": "execute"}
        )
        seams.log.error.assert_any_call(
            f"{LogTag.TOOL} Error executing workflow",
            workflow_id="wf-1",
            error_type="Exception",
        )
        seams.writer.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: pause_workflow
# ---------------------------------------------------------------------------


class TestPauseWorkflow:
    """Tests for the pause_workflow tool."""

    async def test_happy_path(self) -> None:
        """Pauses a workflow with exact service args and payloads."""
        from app.agents.tools.workflow_tool import pause_workflow

        workflow = _make_workflow_mock()

        with _ToolSeams(
            service_methods={"deactivate_workflow": AsyncMock(return_value=workflow)}
        ) as seams:
            result = await pause_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                workflow_id="wf-1",
            )

        expected_dump = workflow.model_dump()
        seams.service.deactivate_workflow.assert_awaited_once_with("wf-1", FAKE_USER_ID)
        seams.log.set.assert_called_once_with(tool={"name": "pause_workflow", "action": "pause"})
        seams.writer.assert_called_once_with(
            {"workflow_data": {"action": "paused", "workflow": expected_dump}}
        )
        assert _envelope(result) == {
            "success": True,
            "data": {"workflow_id": "wf-1", "title": "My Workflow", "activated": True},
        }

    async def test_not_found(self) -> None:
        """Returns error when workflow not found."""
        from app.agents.tools.workflow_tool import pause_workflow

        with _ToolSeams(
            service_methods={"deactivate_workflow": AsyncMock(return_value=None)}
        ) as seams:
            result = await pause_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                workflow_id="wf-missing",
            )

        assert _envelope(result) == {
            "success": False,
            "error": "not_found",
            "message": "Workflow wf-missing not found",
        }
        seams.log.set.assert_called_once_with(tool={"name": "pause_workflow", "action": "pause"})
        seams.writer.assert_not_called()

    async def test_service_error(self) -> None:
        """Service exception returns pause_failed error."""
        from app.agents.tools.workflow_tool import pause_workflow

        with _ToolSeams(
            service_methods={"deactivate_workflow": AsyncMock(side_effect=Exception("DB timeout"))}
        ) as seams:
            result = await pause_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                workflow_id="wf-1",
            )

        assert _envelope(result) == {
            "success": False,
            "error": "pause_failed",
            "message": "DB timeout",
        }
        seams.log.set.assert_called_once_with(tool={"name": "pause_workflow", "action": "pause"})
        seams.log.error.assert_any_call(
            f"{LogTag.TOOL} Error pausing workflow",
            workflow_id="wf-1",
            error_type="Exception",
        )
        seams.writer.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: resume_workflow
# ---------------------------------------------------------------------------


class TestResumeWorkflow:
    """Tests for the resume_workflow tool."""

    async def test_happy_path(self) -> None:
        """Resumes a workflow with exact service args and payloads."""
        from app.agents.tools.workflow_tool import resume_workflow

        workflow = _make_workflow_mock()

        with _ToolSeams(
            service_methods={"activate_workflow": AsyncMock(return_value=workflow)}
        ) as seams:
            result = await resume_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                workflow_id="wf-1",
            )

        expected_dump = workflow.model_dump()
        seams.service.activate_workflow.assert_awaited_once_with(
            "wf-1", FAKE_USER_ID, user_timezone="+05:30"
        )
        seams.log.set.assert_called_once_with(tool={"name": "resume_workflow", "action": "resume"})
        seams.writer.assert_called_once_with(
            {"workflow_data": {"action": "resumed", "workflow": expected_dump}}
        )
        assert _envelope(result) == {
            "success": True,
            "data": {"workflow_id": "wf-1", "title": "My Workflow", "activated": True},
        }

    async def test_not_found(self) -> None:
        """Returns error when workflow not found."""
        from app.agents.tools.workflow_tool import resume_workflow

        with _ToolSeams(
            service_methods={"activate_workflow": AsyncMock(return_value=None)}
        ) as seams:
            result = await resume_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                workflow_id="wf-missing",
            )

        assert _envelope(result) == {
            "success": False,
            "error": "not_found",
            "message": "Workflow wf-missing not found",
        }
        seams.log.set.assert_called_once_with(tool={"name": "resume_workflow", "action": "resume"})
        seams.writer.assert_not_called()

    async def test_service_error(self) -> None:
        """Service exception returns resume_failed error."""
        from app.agents.tools.workflow_tool import resume_workflow

        with _ToolSeams(
            service_methods={"activate_workflow": AsyncMock(side_effect=Exception("Not connected"))}
        ) as seams:
            result = await resume_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                workflow_id="wf-1",
            )

        assert _envelope(result) == {
            "success": False,
            "error": "resume_failed",
            "message": "Not connected",
        }
        seams.log.set.assert_called_once_with(tool={"name": "resume_workflow", "action": "resume"})
        seams.log.error.assert_any_call(
            f"{LogTag.TOOL} Error resuming workflow",
            workflow_id="wf-1",
            error_type="Exception",
        )
        seams.writer.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: edit_workflow
# ---------------------------------------------------------------------------


class TestEditWorkflow:
    """Tests for the edit_workflow tool."""

    async def test_empty_request(self) -> None:
        """Empty user_request returns missing_request error."""
        from app.agents.tools.workflow_tool import edit_workflow

        with _ToolSeams() as seams:
            result = await edit_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                workflow_id="wf-1",
                user_request="",
            )

        assert _envelope(result) == EXPECTED_EDIT_MISSING_REQUEST
        seams.log.set.assert_called_once_with(tool={"name": "edit_workflow", "action": "edit"})
        seams.runner.execute.assert_not_awaited()

    async def test_whitespace_request(self) -> None:
        """Whitespace-only user_request is rejected like an empty one."""
        from app.agents.tools.workflow_tool import edit_workflow

        with _ToolSeams() as seams:
            result = await edit_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                workflow_id="wf-1",
                user_request="   ",
            )

        assert _envelope(result) == EXPECTED_EDIT_MISSING_REQUEST
        seams.log.set.assert_called_once_with(tool={"name": "edit_workflow", "action": "edit"})
        seams.runner.execute.assert_not_awaited()

    async def test_workflow_not_found(self) -> None:
        """Returns not_found before delegating to the subagent."""
        from app.agents.tools.workflow_tool import edit_workflow

        with _ToolSeams(service_methods={"get_workflow": AsyncMock(return_value=None)}) as seams:
            result = await edit_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                workflow_id="wf-missing",
                user_request="change the schedule",
            )

        assert _envelope(result) == {
            "success": False,
            "error": "not_found",
            "message": "Workflow wf-missing not found",
        }
        seams.service.get_workflow.assert_awaited_once_with("wf-missing", FAKE_USER_ID)
        seams.log.set.assert_called_once_with(tool={"name": "edit_workflow", "action": "edit"})
        seams.runner.execute.assert_not_awaited()
        seams.writer.assert_not_called()

    async def test_finalized_applies_edit(self) -> None:
        """Finalized edit draft is applied with exact seam args."""
        from app.agents.tools.workflow_tool import edit_workflow

        workflow = _make_workflow_mock()
        draft = _make_draft(title="New Title")
        parsed = _make_parsed_result(mode="finalized", draft=draft)
        edit_result = {"success": True, "data": {"status": "updated"}}

        with (
            _ToolSeams(
                service_methods={"get_workflow": AsyncMock(return_value=workflow)},
                parsed=parsed,
            ) as seams,
            patch(f"{MODULE}.build_edit_workflow_task", return_value="edit task") as build_task,
            patch(
                f"{MODULE}.apply_workflow_edit",
                new_callable=AsyncMock,
                return_value=edit_result,
            ) as apply_edit,
        ):
            result = await edit_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                workflow_id="wf-1",
                user_request="  rename it to New Title  ",
            )

        assert _envelope(result) == {"success": True, "data": {"status": "updated"}}
        seams.service.get_workflow.assert_awaited_once_with("wf-1", FAKE_USER_ID)
        _assert_edit_flow_logs(seams.log, "finalized")
        build_task.assert_called_once_with(workflow, "rename it to New Title")
        seams.runner.execute.assert_awaited_once_with(
            task="edit task",
            user_id=FAKE_USER_ID,
            thread_id="thread-123",
            user_name="Test User",
            user_timezone="+05:30",
            stream_writer=seams.writer,
        )
        seams.parse.assert_called_once_with("subagent output")
        apply_edit.assert_awaited_once_with(
            draft=draft,
            workflow=workflow,
            user_id=FAKE_USER_ID,
            writer=seams.writer,
            user_timezone="+05:30",
        )

    async def test_sparse_config_passes_defaults(self) -> None:
        """Missing thread_id/user_name/user_timezone fall back to their defaults."""
        from app.agents.tools.workflow_tool import edit_workflow

        parsed = _make_parsed_result(mode="clarifying", message="Which part?")

        with (
            _ToolSeams(
                service_methods={"get_workflow": AsyncMock(return_value=_make_workflow_mock())},
                parsed=parsed,
            ) as seams,
            patch(f"{MODULE}.build_edit_workflow_task", return_value="built task"),
        ):
            result = await edit_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config_sparse(),
                workflow_id="wf-1",
                user_request="change it",
            )

        assert _envelope(result)["data"]["status"] == "clarifying"
        _assert_edit_flow_logs(seams.log, "clarifying")
        seams.runner.execute.assert_awaited_once_with(
            task="built task",
            user_id=FAKE_USER_ID,
            thread_id="",
            user_name=None,
            user_timezone="UTC",
            stream_writer=seams.writer,
        )

    async def test_clarifying(self) -> None:
        """Clarifying mode returns the question for the user."""
        from app.agents.tools.workflow_tool import edit_workflow

        parsed = _make_parsed_result(mode="clarifying", message="What exactly should change?")

        with _ToolSeams(
            service_methods={"get_workflow": AsyncMock(return_value=_make_workflow_mock())},
            parsed=parsed,
        ) as seams:
            result = await edit_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                workflow_id="wf-1",
                user_request="tweak it",
            )

        assert _envelope(result) == {
            "success": True,
            "data": {
                "status": "clarifying",
                "question": "What exactly should change?",
            },
            "message": (
                "The workflow assistant needs clarification from the user: "
                "What exactly should change?"
            ),
        }
        _assert_edit_flow_logs(seams.log, "clarifying")
        seams.writer.assert_not_called()

    async def test_clarifying_without_message(self) -> None:
        """Clarifying mode without a message falls back to the default question."""
        from app.agents.tools.workflow_tool import edit_workflow

        parsed = _make_parsed_result(mode="clarifying", message=None)

        with _ToolSeams(
            service_methods={"get_workflow": AsyncMock(return_value=_make_workflow_mock())},
            parsed=parsed,
        ) as seams:
            result = await edit_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                workflow_id="wf-1",
                user_request="tweak it",
            )

        assert _envelope(result) == {
            "success": True,
            "data": {
                "status": "clarifying",
                "question": "The workflow assistant needs more information.",
            },
            "message": (
                "The workflow assistant needs clarification from the user: "
                "The workflow assistant needs more information."
            ),
        }
        _assert_edit_flow_logs(seams.log, "clarifying")
        seams.writer.assert_not_called()

    async def test_parse_error(self) -> None:
        """Parse error from subagent is handled gracefully."""
        from app.agents.tools.workflow_tool import edit_workflow

        parsed = _make_parsed_result(mode="parse_error", parse_error="Invalid JSON")

        with _ToolSeams(
            service_methods={"get_workflow": AsyncMock(return_value=_make_workflow_mock())},
            parsed=parsed,
        ) as seams:
            result = await edit_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                workflow_id="wf-1",
                user_request="change it",
            )

        assert _envelope(result) == {
            "success": False,
            "error": "parse_error",
            "message": (
                "Failed to process the workflow assistant's response: Invalid JSON. "
                "Please try again or rephrase the change."
            ),
        }
        _assert_edit_flow_logs(seams.log, "parse_error")
        seams.log.warning.assert_any_call(
            f"{LogTag.TOOL} edit_workflow: parse error", parse_error="Invalid JSON"
        )
        seams.writer.assert_not_called()

    async def test_finalized_without_draft_completed(self) -> None:
        """Finalized mode without a draft falls through to completed."""
        from app.agents.tools.workflow_tool import edit_workflow

        parsed = _make_parsed_result(mode="finalized", draft=None)

        with _ToolSeams(
            service_methods={"get_workflow": AsyncMock(return_value=_make_workflow_mock())},
            parsed=parsed,
        ) as seams:
            result = await edit_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                workflow_id="wf-1",
                user_request="change it",
            )

        assert _envelope(result) == {
            "success": True,
            "data": {"status": "completed"},
            "message": "Workflow edit completed.",
        }
        _assert_edit_flow_logs(seams.log, "finalized")
        seams.writer.assert_not_called()

    async def test_subagent_exception(self) -> None:
        """Subagent runner exception returns error."""
        from app.agents.tools.workflow_tool import edit_workflow

        with _ToolSeams(
            service_methods={"get_workflow": AsyncMock(return_value=_make_workflow_mock())},
            runner_error=Exception("Runner crashed"),
        ) as seams:
            result = await edit_workflow.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                workflow_id="wf-1",
                user_request="change it",
            )

        assert _envelope(result) == {
            "success": False,
            "error": "edit_failed",
            "message": "Runner crashed",
        }
        _assert_edit_exception_logs(seams.log, "Exception")
        seams.writer.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: search_triggers (shared tool)
# ---------------------------------------------------------------------------


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
            mock_trigger_svc.search = AsyncMock(side_effect=Exception("ChromaDB unavailable"))

            result = await search_triggers.coroutine(  # type: ignore[attr-defined]
                config=_make_config(),
                query="test",
            )

        assert result["success"] is False
        assert result["error"] == "search_failed"


# ---------------------------------------------------------------------------
# Tests: list_workflows (shared tool)
# ---------------------------------------------------------------------------


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
            mock_service.list_workflows = AsyncMock(return_value=([workflow], 1))

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
            mock_service.list_workflows = AsyncMock(side_effect=Exception("Connection refused"))

            result = await list_workflows.coroutine(config=_make_config())  # type: ignore[attr-defined]

        assert result["success"] is False
        assert result["error"] == "fetch_failed"
