"""dispatch_tool — validation stands in for constrained decoding; analytics
attribute the REAL tool. These are the proxy's two load-bearing behaviors."""

import asyncio
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
            patch(
                f"{MODULE}.resolve_tool",
                new=AsyncMock(return_value=ResolvedTool(tool.name, tool, is_integration=True)),
            ),
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
            patch(
                f"{MODULE}.resolve_tool",
                new=AsyncMock(return_value=ResolvedTool(tool.name, tool, is_integration=True)),
            ),
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
            patch(
                f"{MODULE}.resolve_tool",
                new=AsyncMock(return_value=ResolvedTool(tool.name, tool, is_integration=True)),
            ),
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
            patch(
                f"{MODULE}.resolve_tool",
                new=AsyncMock(return_value=ResolvedTool(tool.name, tool, is_integration=True)),
            ),
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
class TestObservedShapeRecording:
    async def test_a_successful_integration_dispatch_records_the_output_shape(self) -> None:
        tool = _tool()
        with (
            patch(
                f"{MODULE}.resolve_tool",
                new=AsyncMock(return_value=ResolvedTool(tool.name, tool, is_integration=True)),
            ),
            patch(f"{MODULE}.capture_event"),
            patch(f"{MODULE}.record_observed_shape") as record,
            patch(f"{MODULE}.spawn_logged_task") as spawn,
        ):
            await dispatch_tool(
                user_id="u1",
                tool_name="GMAIL_SEND_EMAIL",
                data={"recipient": "a@b.c", "subject": "hi"},
                config=CONFIG,
            )
        record.assert_called_once_with("GMAIL_SEND_EMAIL", {"status": "sent"}, scope="global")
        spawn.assert_called_once()

    async def test_internal_tools_and_failures_record_nothing(self) -> None:
        tool = _tool(name="create_todo")
        with (
            patch(
                f"{MODULE}.resolve_tool",
                new=AsyncMock(return_value=ResolvedTool("create_todo", tool, is_integration=False)),
            ),
            patch(f"{MODULE}.capture_event"),
            patch(f"{MODULE}.spawn_logged_task") as spawn,
        ):
            await dispatch_tool(
                user_id="u1",
                tool_name="create_todo",
                data={"recipient": "x", "subject": "y"},
                config=CONFIG,
            )
            await dispatch_tool(  # invalid args: never invoked, never recorded
                user_id="u1", tool_name="create_todo", data={}, config=CONFIG
            )
        spawn.assert_not_called()


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


@pytest.mark.unit
class TestSubagentToolSpace:
    """A subagent's tool space must bound the proxy, not just its bindings.

    `execute` is in every subagent's tool set, and dispatch resolves names
    globally — so without a scope the proxy ran any registered tool by name,
    and the in-band refusal retrieve_tools returns ("They belong to the main
    executor, not this subagent") was advice the model could simply route
    around.
    """

    async def test_a_registered_tool_outside_the_space_is_refused(self) -> None:
        tool = _tool(name="SLACK_SEND_MESSAGE")
        with (
            patch(
                f"{MODULE}.resolve_tool",
                new=AsyncMock(
                    return_value=ResolvedTool(
                        tool.name, tool, is_integration=True, in_registry=True
                    )
                ),
            ),
            patch(f"{MODULE}.capture_event") as capture,
        ):
            result = await dispatch_tool(
                user_id="u1",
                tool_name="SLACK_SEND_MESSAGE",
                data={"recipient": "a@b.c", "subject": "hi"},
                config=CONFIG,
                scoped_tool_names={"GMAIL_SEND_EMAIL", "read"},
            )
        assert result.ok is False
        assert result.error is not None
        assert result.error.kind is DispatchErrorKind.OUT_OF_SCOPE
        tool.ainvoke.assert_not_awaited()
        capture.assert_called_once_with(
            "u1",
            AnalyticsEvents.EXECUTE_TOOL_FAILED,
            {"tool_name": "SLACK_SEND_MESSAGE", "reason": "out_of_scope"},
        )

    async def test_a_tool_inside_the_space_still_runs(self) -> None:
        tool = _tool()
        with (
            patch(
                f"{MODULE}.resolve_tool",
                new=AsyncMock(
                    return_value=ResolvedTool(
                        tool.name, tool, is_integration=True, in_registry=True
                    )
                ),
            ),
            patch(f"{MODULE}.capture_event"),
            patch(f"{MODULE}.spawn_logged_task"),
        ):
            result = await dispatch_tool(
                user_id="u1",
                tool_name="GMAIL_SEND_EMAIL",
                data={"recipient": "a@b.c", "subject": "hi"},
                config=CONFIG,
                scoped_tool_names={"GMAIL_SEND_EMAIL"},
            )
        assert result.ok is True

    async def test_a_tool_outside_the_registry_is_not_scope_checked(self) -> None:
        """MCP tools and unmaterialized catalog slugs belong to no tool space —
        no space can list them, so scoping them out would refuse every one.
        This is exactly what retrieve_tools already allows through."""
        tool = _tool(name="notion_mcp_search")
        with (
            patch(
                f"{MODULE}.resolve_tool",
                new=AsyncMock(return_value=ResolvedTool(tool.name, tool, is_integration=True)),
            ),
            patch(f"{MODULE}.capture_event"),
            patch(f"{MODULE}.spawn_logged_task"),
        ):
            result = await dispatch_tool(
                user_id="u1",
                tool_name="notion_mcp_search",
                data={"recipient": "a@b.c", "subject": "hi"},
                config=CONFIG,
                scoped_tool_names={"GMAIL_SEND_EMAIL"},
            )
        assert result.ok is True

    async def test_the_executor_is_unscoped(self) -> None:
        tool = _tool(name="SLACK_SEND_MESSAGE")
        with (
            patch(
                f"{MODULE}.resolve_tool",
                new=AsyncMock(
                    return_value=ResolvedTool(
                        tool.name, tool, is_integration=True, in_registry=True
                    )
                ),
            ),
            patch(f"{MODULE}.capture_event"),
            patch(f"{MODULE}.spawn_logged_task"),
        ):
            result = await dispatch_tool(
                user_id="u1",
                tool_name="SLACK_SEND_MESSAGE",
                data={"recipient": "a@b.c", "subject": "hi"},
                config=CONFIG,
            )
        assert result.ok is True


@pytest.mark.unit
class TestDispatchOutcomeReporting:
    async def test_an_infrastructure_failure_is_never_stamped_ok(self) -> None:
        """`execute.outcome` is the migration's health metric. Stamping it
        before the invoke reported every failed dispatch as a success."""
        tool = _tool()
        tool.ainvoke = AsyncMock(side_effect=ConnectionError("provider down"))
        stamped: dict[str, object] = {}
        with (
            patch(
                f"{MODULE}.resolve_tool",
                new=AsyncMock(return_value=ResolvedTool(tool.name, tool, is_integration=True)),
            ),
            patch(f"{MODULE}.capture_event"),
            patch(f"{MODULE}.log") as log,
        ):
            log.set_ns.side_effect = lambda _ns, **kw: stamped.update(kw)
            with pytest.raises(ConnectionError):
                await dispatch_tool(
                    user_id="u1",
                    tool_name="GMAIL_SEND_EMAIL",
                    data={"recipient": "a@b.c", "subject": "hi"},
                    config=CONFIG,
                )
        # The tool is named (an infra failure must say which one), the outcome is not.
        assert stamped == {"tool": "GMAIL_SEND_EMAIL"}

    async def test_a_hung_tool_is_bounded_and_reported_as_unknown_effect(self) -> None:
        """The sandbox route had no bound of its own, so its client gave up
        first and the script's retry re-applied a mutation still in flight."""
        tool = _tool()

        async def _never_returns(*_args: object, **_kwargs: object) -> None:
            # Long enough that only the bound can end it, short enough that
            # losing the bound fails this test in seconds rather than hanging
            # until the suite-wide timeout.
            await asyncio.sleep(5)

        tool.ainvoke = AsyncMock(side_effect=_never_returns)
        with (
            patch(
                f"{MODULE}.resolve_tool",
                new=AsyncMock(return_value=ResolvedTool(tool.name, tool, is_integration=True)),
            ),
            patch(f"{MODULE}.capture_event") as capture,
            patch(f"{MODULE}.TOOL_EXECUTION_TIMEOUT_SECONDS", 0.01),
        ):
            result = await dispatch_tool(
                user_id="u1",
                tool_name="GMAIL_SEND_EMAIL",
                data={"recipient": "a@b.c", "subject": "hi"},
                config=CONFIG,
            )
        assert result.ok is False
        assert result.error is not None
        assert result.error.kind is DispatchErrorKind.TIMEOUT
        # The model must not read this as "it did not happen".
        assert "may or may not have completed" in result.error.hint
        capture.assert_called_once_with(
            "u1",
            AnalyticsEvents.EXECUTE_TOOL_FAILED,
            {"tool_name": "GMAIL_SEND_EMAIL", "reason": "timeout"},
        )

    async def test_an_exempt_tool_is_not_bounded(self) -> None:
        """Long-running orchestration tools manage their own lifecycles — the
        in-graph node exempts them, and a proxied call must not be tighter."""
        tool = _tool(name="deep_research", schema=None)
        with (
            patch(
                f"{MODULE}.resolve_tool",
                new=AsyncMock(
                    return_value=ResolvedTool("deep_research", tool, is_integration=False)
                ),
            ),
            patch(f"{MODULE}.capture_event"),
            patch(f"{MODULE}.TOOL_EXECUTION_TIMEOUT_SECONDS", 0.01),
        ):
            result = await dispatch_tool(
                user_id="u1", tool_name="deep_research", data={}, config=CONFIG
            )
        assert result.ok is True
