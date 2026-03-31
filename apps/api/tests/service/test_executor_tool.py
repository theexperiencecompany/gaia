"""Service tests for executor_tool.call_executor.

Tests call the real call_executor production function with mocked boundaries
(prepare_executor_execution, execute_subagent_stream, get_stream_writer, and
MCP tool loading). No reimplementation of production logic.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.runnables import RunnableConfig

from app.agents.tools.executor_tool import call_executor, tools
from app.api.v1.middleware.tiered_rate_limiter import RateLimitExceededException
from app.decorators.rate_limiting import LangChainRateLimitException


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(
    user_id: str = "user-123", stream_id: str = "stream-abc"
) -> RunnableConfig:
    return RunnableConfig(
        configurable={
            "user_id": user_id,
            "thread_id": "thread-1",
            "stream_id": stream_id,
            "user_time": "2026-03-31T12:00:00",
        }
    )


def _base_patches(
    prepare_return: tuple,
    execute_return: str = "task done",
) -> list:
    """Return context managers that mock all I/O boundaries in call_executor."""
    return [
        patch(
            "app.agents.tools.executor_tool.prepare_executor_execution",
            new_callable=AsyncMock,
            return_value=prepare_return,
        ),
        patch(
            "app.agents.tools.executor_tool.execute_subagent_stream",
            new_callable=AsyncMock,
            return_value=execute_return,
        ),
        patch(
            "app.agents.tools.executor_tool.get_stream_writer",
            return_value=lambda _: None,
        ),
        patch(
            "app.agents.tools.executor_tool.get_tool_registry",
            new_callable=AsyncMock,
            return_value=MagicMock(load_user_mcp_tools=AsyncMock(return_value={})),
        ),
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.service
class TestCallExecutorTool:
    """Service tests for the call_executor LangGraph tool."""

    # --- module-level contract ------------------------------------------

    def test_tool_is_importable_and_named(self) -> None:
        """call_executor must be importable and carry the expected tool name."""
        # call_executor is a LangGraph StructuredTool, not a plain function.
        # Verify it has the expected name and is invokable.
        assert call_executor.name == "call_executor"
        assert hasattr(call_executor, "ainvoke")

    def test_tools_list_contains_call_executor(self) -> None:
        """The module-level tools list must expose call_executor."""
        assert call_executor in tools
        assert len(tools) == 1

    # --- happy path --------------------------------------------------------

    async def test_successful_delegation_returns_execute_result(self) -> None:
        """When prepare succeeds, call_executor returns execute_subagent_stream result."""
        fake_ctx = MagicMock()
        patches = _base_patches(
            prepare_return=(fake_ctx, None), execute_return="Created todo successfully"
        )

        with patches[0], patches[1], patches[2], patches[3]:
            result = await call_executor.ainvoke(
                {"task": "Create a todo: buy milk", "config": _make_config()}
            )

        assert result == "Created todo successfully"

    # --- prepare_executor_execution failure --------------------------------

    async def test_prepare_returns_none_ctx_yields_error_string(self) -> None:
        """When prepare returns (None, error_msg), call_executor returns 'Error: <msg>' string."""
        patches = _base_patches(prepare_return=(None, "Executor agent not available"))

        with patches[0], patches[1], patches[2], patches[3]:
            result = await call_executor.ainvoke(
                {"task": "do something", "config": _make_config()}
            )

        assert isinstance(result, str)
        assert result.startswith("Error:")
        assert "Executor agent not available" in result

    async def test_prepare_returns_none_ctx_no_error_message(self) -> None:
        """When prepare returns (None, None), call_executor returns a fallback error string."""
        patches = _base_patches(prepare_return=(None, None))

        with patches[0], patches[1], patches[2], patches[3]:
            result = await call_executor.ainvoke(
                {"task": "do something", "config": _make_config()}
            )

        assert isinstance(result, str)
        assert "Error" in result

    async def test_prepare_returns_error_string(self) -> None:
        """When prepare returns (None, error), result must NOT be empty or a crash."""
        patches = _base_patches(prepare_return=(None, "DB unreachable"))

        with patches[0], patches[1], patches[2], patches[3]:
            result = await call_executor.ainvoke(
                {"task": "fetch emails", "config": _make_config()}
            )

        assert isinstance(result, str)
        assert len(result) > 0

    # --- cancellation ------------------------------------------------------

    async def test_cancelled_error_propagates(self) -> None:
        """asyncio.CancelledError must be re-raised, not swallowed."""
        with (
            patch(
                "app.agents.tools.executor_tool.prepare_executor_execution",
                new_callable=AsyncMock,
                side_effect=asyncio.CancelledError(),
            ),
            patch(
                "app.agents.tools.executor_tool.get_tool_registry",
                new_callable=AsyncMock,
                return_value=MagicMock(load_user_mcp_tools=AsyncMock(return_value={})),
            ),
        ):
            with pytest.raises(asyncio.CancelledError):
                await call_executor.ainvoke(
                    {"task": "cancel me", "config": _make_config()}
                )

    # --- rate limiting -----------------------------------------------------

    async def test_langchain_rate_limit_returns_user_message(self) -> None:
        """LangChainRateLimitException must produce a rate-limit message, not a crash."""
        exc = LangChainRateLimitException(feature="gpt-4o")

        with (
            patch(
                "app.agents.tools.executor_tool.prepare_executor_execution",
                new_callable=AsyncMock,
                side_effect=exc,
            ),
            patch(
                "app.agents.tools.executor_tool.get_tool_registry",
                new_callable=AsyncMock,
                return_value=MagicMock(load_user_mcp_tools=AsyncMock(return_value={})),
            ),
        ):
            result = await call_executor.ainvoke(
                {"task": "send email", "config": _make_config()}
            )

        assert isinstance(result, str)
        assert "Rate limit" in result or "rate limit" in result.lower()
        assert "gpt-4o" in result

    async def test_tiered_rate_limit_returns_user_message(self) -> None:
        """RateLimitExceededException must produce a rate-limit message, not a crash."""
        exc = RateLimitExceededException(feature="email_send")

        with (
            patch(
                "app.agents.tools.executor_tool.prepare_executor_execution",
                new_callable=AsyncMock,
                side_effect=exc,
            ),
            patch(
                "app.agents.tools.executor_tool.get_tool_registry",
                new_callable=AsyncMock,
                return_value=MagicMock(load_user_mcp_tools=AsyncMock(return_value={})),
            ),
        ):
            result = await call_executor.ainvoke(
                {"task": "send email", "config": _make_config()}
            )

        assert isinstance(result, str)
        assert "Rate limit" in result or "rate limit" in result.lower()
        assert "email_send" in result

    async def test_tiered_rate_limit_without_plan_returns_message(self) -> None:
        """RateLimitExceededException without a plan_required still returns graceful message."""
        exc = RateLimitExceededException(feature="web_search")

        with (
            patch(
                "app.agents.tools.executor_tool.prepare_executor_execution",
                new_callable=AsyncMock,
                side_effect=exc,
            ),
            patch(
                "app.agents.tools.executor_tool.get_tool_registry",
                new_callable=AsyncMock,
                return_value=MagicMock(load_user_mcp_tools=AsyncMock(return_value={})),
            ),
        ):
            result = await call_executor.ainvoke(
                {"task": "search web", "config": _make_config()}
            )

        assert isinstance(result, str)
        assert "Rate limit" in result or "rate limit" in result.lower()

    # --- generic exception -------------------------------------------------

    async def test_generic_exception_returns_error_string(self) -> None:
        """Unexpected exceptions must be caught and returned as a readable string."""
        with (
            patch(
                "app.agents.tools.executor_tool.prepare_executor_execution",
                new_callable=AsyncMock,
                side_effect=RuntimeError("internal failure"),
            ),
            patch(
                "app.agents.tools.executor_tool.get_tool_registry",
                new_callable=AsyncMock,
                return_value=MagicMock(load_user_mcp_tools=AsyncMock(return_value={})),
            ),
        ):
            result = await call_executor.ainvoke(
                {"task": "crash me", "config": _make_config()}
            )

        assert isinstance(result, str)
        assert "Error executing task" in result
        assert "internal failure" in result

    # --- MCP tool loading failure ------------------------------------------

    async def test_mcp_load_failure_is_non_fatal(self) -> None:
        """A failure to load MCP tools must not abort the executor call."""
        fake_ctx = MagicMock()
        tool_registry_mock = MagicMock()
        tool_registry_mock.load_user_mcp_tools = AsyncMock(
            side_effect=Exception("MCP registry unavailable")
        )

        with (
            patch(
                "app.agents.tools.executor_tool.prepare_executor_execution",
                new_callable=AsyncMock,
                return_value=(fake_ctx, None),
            ),
            patch(
                "app.agents.tools.executor_tool.execute_subagent_stream",
                new_callable=AsyncMock,
                return_value="task completed despite MCP failure",
            ),
            patch(
                "app.agents.tools.executor_tool.get_stream_writer",
                return_value=lambda _: None,
            ),
            patch(
                "app.agents.tools.executor_tool.get_tool_registry",
                new_callable=AsyncMock,
                return_value=tool_registry_mock,
            ),
        ):
            result = await call_executor.ainvoke(
                {"task": "list todos", "config": _make_config()}
            )

        assert result == "task completed despite MCP failure"

    # --- config without user_id --------------------------------------------

    async def test_no_user_id_skips_mcp_loading(self) -> None:
        """When user_id is absent from config, MCP tools are not loaded."""
        config_without_user = RunnableConfig(configurable={"thread_id": "t1"})
        fake_ctx = MagicMock()
        registry_mock = MagicMock(load_user_mcp_tools=AsyncMock(return_value={}))

        with (
            patch(
                "app.agents.tools.executor_tool.prepare_executor_execution",
                new_callable=AsyncMock,
                return_value=(fake_ctx, None),
            ),
            patch(
                "app.agents.tools.executor_tool.execute_subagent_stream",
                new_callable=AsyncMock,
                return_value="ok",
            ),
            patch(
                "app.agents.tools.executor_tool.get_stream_writer",
                return_value=lambda _: None,
            ),
            patch(
                "app.agents.tools.executor_tool.get_tool_registry",
                new_callable=AsyncMock,
                return_value=registry_mock,
            ),
        ):
            result = await call_executor.ainvoke(
                {"task": "some task", "config": config_without_user}
            )

        assert result == "ok"
        registry_mock.load_user_mcp_tools.assert_not_called()
