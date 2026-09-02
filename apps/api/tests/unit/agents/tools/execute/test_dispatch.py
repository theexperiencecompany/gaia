"""dispatch_tool — validation stands in for constrained decoding; analytics
attribute the REAL tool. These are the proxy's two load-bearing behaviors."""

from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import BaseModel, Field
import pytest

from app.agents.tools.execute.dispatch import DispatchErrorKind, dispatch_tool
from app.agents.tools.execute.resolver import ResolvedTool
from app.services.analytics_service import AnalyticsEvents

MODULE = "app.agents.tools.execute.dispatch"
CONFIG = {"configurable": {"user_id": "u1"}}


class _SendEmailArgs(BaseModel):
    recipient: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    max_results: int = 25


def _tool(name: str = "GMAIL_SEND_EMAIL", schema: object = _SendEmailArgs) -> MagicMock:
    tool = MagicMock()
    tool.name = name
    tool.args_schema = schema
    tool.ainvoke = AsyncMock(return_value={"status": "sent"})
    return tool


@pytest.mark.unit
class TestDispatchTool:
    async def test_unknown_tool_is_structured_and_never_invokes(self) -> None:
        with (
            patch(f"{MODULE}.resolve_tool", new=AsyncMock(return_value=None)),
            patch(f"{MODULE}.capture_event") as capture,
        ):
            result = await dispatch_tool(
                user_id="u1", tool_name="NOPE_TOOL", data={}, config=CONFIG
            )
        assert result.ok is False
        assert result.error is not None
        assert result.error.kind is DispatchErrorKind.UNKNOWN_TOOL
        # Failure is its own event, attributed to the user, with the reason.
        capture.assert_called_once_with(
            "u1",
            AnalyticsEvents.EXECUTE_TOOL_FAILED,
            {"tool_name": "NOPE_TOOL", "reason": "unknown_tool"},
        )

    async def test_invalid_args_fail_loud_with_pydantic_detail_and_never_invoke(self) -> None:
        tool = _tool()
        with (
            patch(f"{MODULE}.resolve_tool", new=AsyncMock(return_value=ResolvedTool(tool.name, tool, is_integration=True))),
            patch(f"{MODULE}.capture_event") as capture,
        ):
            result = await dispatch_tool(
                user_id="u1",
                tool_name="GMAIL_SEND_EMAIL",
                data={"recipient": "a@b.c"},  # subject missing
                config=CONFIG,
            )
        assert result.ok is False
        assert result.error is not None
        assert result.error.kind is DispatchErrorKind.INVALID_ARGS
        assert "subject" in result.error.detail
        tool.ainvoke.assert_not_awaited()
        # The retry-ratio numerator: every validation failure is captured.
        capture.assert_called_once_with(
            "u1",
            AnalyticsEvents.EXECUTE_TOOL_FAILED,
            {"tool_name": "GMAIL_SEND_EMAIL", "reason": "invalid_args"},
        )

    async def test_valid_args_invoke_with_coerced_supplied_fields_only(self) -> None:
        tool = _tool()
        with (
            patch(f"{MODULE}.resolve_tool", new=AsyncMock(return_value=ResolvedTool(tool.name, tool, is_integration=True))),
            patch(f"{MODULE}.capture_event") as capture,
        ):
            result = await dispatch_tool(
                user_id="u1",
                tool_name="GMAIL_SEND_EMAIL",
                data={"recipient": "a@b.c", "subject": "hi"},
                config=CONFIG,
            )
        assert result.ok is True
        assert result.output == {"status": "sent"}
        # exclude_unset: the tool keeps ownership of its own defaults.
        tool.ainvoke.assert_awaited_once_with(
            {"recipient": "a@b.c", "subject": "hi"}, config=CONFIG
        )
        capture.assert_called_once_with(
            "u1",
            AnalyticsEvents.TOOL_USED,
            {"tool_name": "GMAIL_SEND_EMAIL", "via": "execute"},
        )

    async def test_dict_schema_tool_invokes_with_raw_data(self) -> None:
        tool = _tool(name="MCP_DICT_TOOL", schema={"type": "object"})
        with (
            patch(f"{MODULE}.resolve_tool", new=AsyncMock(return_value=ResolvedTool(tool.name, tool, is_integration=True))),
            patch(f"{MODULE}.capture_event"),
        ):
            result = await dispatch_tool(
                user_id="u1", tool_name="MCP_DICT_TOOL", data={"q": 1}, config=CONFIG
            )
        assert result.ok is True
        tool.ainvoke.assert_awaited_once_with({"q": 1}, config=CONFIG)

    async def test_personless_run_skips_analytics_but_still_executes(self) -> None:
        tool = _tool()
        with (
            patch(f"{MODULE}.resolve_tool", new=AsyncMock(return_value=ResolvedTool(tool.name, tool, is_integration=True))),
            patch(f"{MODULE}.capture_event") as capture,
        ):
            result = await dispatch_tool(
                user_id=None,
                tool_name="GMAIL_SEND_EMAIL",
                data={"recipient": "a@b.c", "subject": "hi"},
                config=CONFIG,
            )
        assert result.ok is True
        capture.assert_not_called()


@pytest.mark.unit
class TestIntegrationOnlySurface:
    async def test_internal_tool_is_refused_and_never_invoked(self) -> None:
        tool = _tool(name="create_todo")
        with (
            patch(
                f"{MODULE}.resolve_tool",
                new=AsyncMock(return_value=ResolvedTool("create_todo", tool, is_integration=False)),
            ),
            patch(f"{MODULE}.capture_event"),
        ):
            result = await dispatch_tool(
                user_id="u1",
                tool_name="create_todo",
                data={"recipient": "x", "subject": "y"},
                config=CONFIG,
                integration_only=True,
            )
        assert result.ok is False
        assert result.error is not None
        assert result.error.kind is DispatchErrorKind.INTERNAL_TOOL
        tool.ainvoke.assert_not_awaited()

    async def test_internal_tool_still_runs_on_the_graph_surface(self) -> None:
        tool = _tool(name="create_todo")
        with (
            patch(
                f"{MODULE}.resolve_tool",
                new=AsyncMock(return_value=ResolvedTool("create_todo", tool, is_integration=False)),
            ),
            patch(f"{MODULE}.capture_event"),
        ):
            result = await dispatch_tool(
                user_id="u1",
                tool_name="create_todo",
                data={"recipient": "x", "subject": "y"},
                config=CONFIG,
            )
        assert result.ok is True
