"""Unit tests for the MiddlewareExecutor.

Tests execution of before_model, after_model, wrap_model_call,
and wrap_tool_call middleware hooks.
"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import (
    ModelRequest,
    ModelResponse,
    ToolCallRequest,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from app.agents.middleware.executor import (
    MiddlewareExecutor,
    _has_override,
)
from app.override.langgraph_bigtool.utils import State


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(**overrides: Any) -> State:
    defaults: dict[str, Any] = {
        "messages": [HumanMessage(content="hello")],
        "selected_tool_ids": [],
        "todos": [],
    }
    defaults.update(overrides)
    return State(**defaults)


def _make_config(**overrides: Any) -> RunnableConfig:
    cfg: dict[str, Any] = {
        "configurable": {
            "user_id": "user_123",
            "thread_id": "thread_abc",
        },
    }
    cfg.update(overrides)
    return cfg  # type: ignore[return-value]


class _NoOpMiddleware(AgentMiddleware):
    """Middleware with no overrides — all methods raise NotImplementedError."""

    pass


class _BeforeModelMiddleware(AgentMiddleware):
    """Middleware that overrides before_model."""

    def before_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        return {"custom_key": "from_before_model"}


class _AsyncBeforeModelMiddleware(AgentMiddleware):
    """Middleware that overrides abefore_model."""

    async def abefore_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        return {"async_key": "from_async_before_model"}


class _AfterModelMiddleware(AgentMiddleware):
    """Middleware that overrides after_model."""

    def after_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        return {"after_key": "from_after_model"}


class _AsyncAfterModelMiddleware(AgentMiddleware):
    """Middleware that overrides aafter_model."""

    async def aafter_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        return {"async_after": "value"}


class _WrapModelMiddleware(AgentMiddleware):
    """Middleware that overrides awrap_model_call."""

    async def awrap_model_call(
        self, request: ModelRequest, handler: Any
    ) -> ModelResponse:
        # Pass through to next handler
        return await handler(request)


class _SyncWrapModelMiddleware(AgentMiddleware):
    """Middleware that overrides wrap_model_call (sync version returns coroutine)."""

    def wrap_model_call(self, request: ModelRequest, handler: Any) -> Any:
        # Return a coroutine so the executor can detect and await it
        return handler(request)


class _WrapToolMiddleware(AgentMiddleware):
    """Middleware that overrides awrap_tool_call."""

    async def awrap_tool_call(
        self, request: ToolCallRequest, handler: Any
    ) -> ToolMessage:
        return await handler(request)


class _SyncWrapToolMiddleware(AgentMiddleware):
    """Middleware that overrides wrap_tool_call (sync version returns coroutine)."""

    def wrap_tool_call(self, request: ToolCallRequest, handler: Any) -> Any:
        return handler(request)


class _FailingBeforeModelMiddleware(AgentMiddleware):
    """Middleware whose before_model raises an exception."""

    def before_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        raise ValueError("before_model exploded")


class _FailingAfterModelMiddleware(AgentMiddleware):
    """Middleware whose after_model raises an exception."""

    def after_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        raise ValueError("after_model exploded")


class _ReturnsNoneBeforeModel(AgentMiddleware):
    """Middleware that returns None from before_model (no state changes)."""

    def before_model(self, state: Any, runtime: Any) -> None:
        return None


# ---------------------------------------------------------------------------
# _has_override
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHasOverride:
    def test_no_override_on_base(self) -> None:
        mw = _NoOpMiddleware()
        assert not _has_override(mw, "before_model")
        assert not _has_override(mw, "abefore_model")
        assert not _has_override(mw, "wrap_model_call")
        assert not _has_override(mw, "awrap_tool_call")

    def test_sync_before_model_override(self) -> None:
        mw = _BeforeModelMiddleware()
        assert _has_override(mw, "before_model")
        assert not _has_override(mw, "abefore_model")

    def test_async_before_model_override(self) -> None:
        mw = _AsyncBeforeModelMiddleware()
        assert _has_override(mw, "abefore_model")
        assert not _has_override(mw, "before_model")

    def test_after_model_override(self) -> None:
        mw = _AfterModelMiddleware()
        assert _has_override(mw, "after_model")

    def test_async_after_model_override(self) -> None:
        mw = _AsyncAfterModelMiddleware()
        assert _has_override(mw, "aafter_model")

    def test_wrap_model_call_override(self) -> None:
        mw = _WrapModelMiddleware()
        assert _has_override(mw, "awrap_model_call")

    def test_wrap_tool_call_override(self) -> None:
        mw = _WrapToolMiddleware()
        assert _has_override(mw, "awrap_tool_call")

    def test_nonexistent_method(self) -> None:
        mw = _BeforeModelMiddleware()
        assert not _has_override(mw, "nonexistent_method")


# ---------------------------------------------------------------------------
# MiddlewareExecutor init
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMiddlewareExecutorInit:
    def test_no_middleware(self) -> None:
        executor = MiddlewareExecutor()
        assert executor.middleware == []

    def test_with_middleware(self) -> None:
        mw_list = [_NoOpMiddleware(), _BeforeModelMiddleware()]
        executor = MiddlewareExecutor(mw_list)
        assert len(executor.middleware) == 2

    def test_none_middleware(self) -> None:
        executor = MiddlewareExecutor(None)
        assert executor.middleware == []


# ---------------------------------------------------------------------------
# execute_before_model
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExecuteBeforeModel:
    @patch(
        "app.agents.middleware.executor.BigtoolRuntime.from_graph_context",
        return_value=MagicMock(),
    )
    async def test_no_middleware_returns_state(self, mock_rt: MagicMock) -> None:
        executor = MiddlewareExecutor([])
        state = _make_state()
        result = await executor.execute_before_model(state, _make_config())
        # Should return same state since no middleware
        assert result["messages"] == state["messages"]

    @patch(
        "app.agents.middleware.executor.BigtoolRuntime.from_graph_context",
        return_value=MagicMock(),
    )
    async def test_sync_before_model(self, mock_rt: MagicMock) -> None:
        mw = _BeforeModelMiddleware()
        executor = MiddlewareExecutor([mw])
        state = _make_state()
        result = await executor.execute_before_model(state, _make_config())
        assert result.get("custom_key") == "from_before_model"

    @patch(
        "app.agents.middleware.executor.BigtoolRuntime.from_graph_context",
        return_value=MagicMock(),
    )
    async def test_async_before_model(self, mock_rt: MagicMock) -> None:
        mw = _AsyncBeforeModelMiddleware()
        executor = MiddlewareExecutor([mw])
        state = _make_state()
        result = await executor.execute_before_model(state, _make_config())
        assert result.get("async_key") == "from_async_before_model"

    @patch(
        "app.agents.middleware.executor.BigtoolRuntime.from_graph_context",
        return_value=MagicMock(),
    )
    async def test_failing_middleware_logs_warning(self, mock_rt: MagicMock) -> None:
        mw = _FailingBeforeModelMiddleware()
        executor = MiddlewareExecutor([mw])
        state = _make_state()
        # Should not raise, should continue
        result = await executor.execute_before_model(state, _make_config())
        assert result["messages"] == state["messages"]

    @patch(
        "app.agents.middleware.executor.BigtoolRuntime.from_graph_context",
        return_value=MagicMock(),
    )
    async def test_none_returning_middleware_no_state_change(
        self, mock_rt: MagicMock
    ) -> None:
        mw = _ReturnsNoneBeforeModel()
        executor = MiddlewareExecutor([mw])
        state = _make_state()
        result = await executor.execute_before_model(state, _make_config())
        assert result["messages"] == state["messages"]

    @patch(
        "app.agents.middleware.executor.BigtoolRuntime.from_graph_context",
        return_value=MagicMock(),
    )
    async def test_noop_middleware_skipped(self, mock_rt: MagicMock) -> None:
        mw = _NoOpMiddleware()
        executor = MiddlewareExecutor([mw])
        state = _make_state()
        result = await executor.execute_before_model(state, _make_config())
        assert result["messages"] == state["messages"]

    @patch(
        "app.agents.middleware.executor.BigtoolRuntime.from_graph_context",
        return_value=MagicMock(),
    )
    async def test_multiple_middleware_executed_in_order(
        self, mock_rt: MagicMock
    ) -> None:
        mw1 = _BeforeModelMiddleware()
        mw2 = _AsyncBeforeModelMiddleware()
        executor = MiddlewareExecutor([mw1, mw2])
        state = _make_state()
        result = await executor.execute_before_model(state, _make_config())
        assert result.get("custom_key") == "from_before_model"
        assert result.get("async_key") == "from_async_before_model"


# ---------------------------------------------------------------------------
# execute_after_model
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExecuteAfterModel:
    @patch(
        "app.agents.middleware.executor.BigtoolRuntime.from_graph_context",
        return_value=MagicMock(),
    )
    async def test_no_middleware_returns_state(self, mock_rt: MagicMock) -> None:
        executor = MiddlewareExecutor([])
        state = _make_state()
        result = await executor.execute_after_model(state, _make_config())
        assert result["messages"] == state["messages"]

    @patch(
        "app.agents.middleware.executor.BigtoolRuntime.from_graph_context",
        return_value=MagicMock(),
    )
    async def test_sync_after_model(self, mock_rt: MagicMock) -> None:
        mw = _AfterModelMiddleware()
        executor = MiddlewareExecutor([mw])
        state = _make_state()
        result = await executor.execute_after_model(state, _make_config())
        assert result.get("after_key") == "from_after_model"

    @patch(
        "app.agents.middleware.executor.BigtoolRuntime.from_graph_context",
        return_value=MagicMock(),
    )
    async def test_async_after_model(self, mock_rt: MagicMock) -> None:
        mw = _AsyncAfterModelMiddleware()
        executor = MiddlewareExecutor([mw])
        state = _make_state()
        result = await executor.execute_after_model(state, _make_config())
        assert result.get("async_after") == "value"

    @patch(
        "app.agents.middleware.executor.BigtoolRuntime.from_graph_context",
        return_value=MagicMock(),
    )
    async def test_failing_after_model_logs_warning(self, mock_rt: MagicMock) -> None:
        mw = _FailingAfterModelMiddleware()
        executor = MiddlewareExecutor([mw])
        state = _make_state()
        result = await executor.execute_after_model(state, _make_config())
        assert result["messages"] == state["messages"]


# ---------------------------------------------------------------------------
# wrap_model_invocation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWrapModelInvocation:
    @patch(
        "app.agents.middleware.executor.create_model_request",
    )
    @patch(
        "app.agents.middleware.executor.BigtoolRuntime.from_graph_context",
        return_value=MagicMock(),
    )
    async def test_no_middleware_calls_invoke_fn(
        self, mock_rt: MagicMock, mock_create_req: MagicMock
    ) -> None:
        mock_model = MagicMock(spec=BaseChatModel)
        expected_msg = AIMessage(content="response")
        invoke_fn = AsyncMock(return_value=expected_msg)

        mock_request = MagicMock(spec=ModelRequest)
        mock_request.system_message = None
        mock_request.messages = [HumanMessage(content="hello")]
        mock_create_req.return_value = mock_request

        executor = MiddlewareExecutor([])
        state = _make_state()
        result = await executor.wrap_model_invocation(
            mock_model, state, _make_config(), None, [], invoke_fn
        )
        assert result.content == "response"

    @patch(
        "app.agents.middleware.executor.create_model_request",
    )
    @patch(
        "app.agents.middleware.executor.BigtoolRuntime.from_graph_context",
        return_value=MagicMock(),
    )
    async def test_async_wrap_model_call(
        self, mock_rt: MagicMock, mock_create_req: MagicMock
    ) -> None:
        mock_model = MagicMock(spec=BaseChatModel)
        expected_msg = AIMessage(content="wrapped response")
        invoke_fn = AsyncMock(return_value=expected_msg)

        mock_request = MagicMock(spec=ModelRequest)
        mock_request.system_message = None
        mock_request.messages = [HumanMessage(content="hello")]
        mock_create_req.return_value = mock_request

        mw = _WrapModelMiddleware()
        executor = MiddlewareExecutor([mw])
        state = _make_state()
        result = await executor.wrap_model_invocation(
            mock_model, state, _make_config(), None, [], invoke_fn
        )
        assert result.content == "wrapped response"

    @patch(
        "app.agents.middleware.executor.create_model_request",
    )
    @patch(
        "app.agents.middleware.executor.BigtoolRuntime.from_graph_context",
        return_value=MagicMock(),
    )
    async def test_sync_wrap_model_call(
        self, mock_rt: MagicMock, mock_create_req: MagicMock
    ) -> None:
        mock_model = MagicMock(spec=BaseChatModel)
        expected_msg = AIMessage(content="sync wrapped")
        invoke_fn = AsyncMock(return_value=expected_msg)

        mock_request = MagicMock(spec=ModelRequest)
        mock_request.system_message = None
        mock_request.messages = [HumanMessage(content="hello")]
        mock_create_req.return_value = mock_request

        mw = _SyncWrapModelMiddleware()
        executor = MiddlewareExecutor([mw])
        state = _make_state()
        result = await executor.wrap_model_invocation(
            mock_model, state, _make_config(), None, [], invoke_fn
        )
        assert result.content == "sync wrapped"

    @patch(
        "app.agents.middleware.executor.create_model_request",
    )
    @patch(
        "app.agents.middleware.executor.BigtoolRuntime.from_graph_context",
        return_value=MagicMock(),
    )
    async def test_chain_failure_falls_back(
        self, mock_rt: MagicMock, mock_create_req: MagicMock
    ) -> None:
        """When the middleware chain raises, executor falls back to direct invocation."""
        mock_model = MagicMock(spec=BaseChatModel)
        expected_msg = AIMessage(content="fallback response")
        invoke_fn = AsyncMock(return_value=expected_msg)

        mock_request = MagicMock(spec=ModelRequest)
        mock_request.system_message = None
        mock_request.messages = [HumanMessage(content="hello")]
        mock_create_req.return_value = mock_request

        # Middleware that always fails
        class _FailingWrapModel(AgentMiddleware):
            async def awrap_model_call(
                self, request: ModelRequest, handler: Any
            ) -> ModelResponse:
                raise RuntimeError("middleware failed")

        executor = MiddlewareExecutor([_FailingWrapModel()])
        state = _make_state()
        result = await executor.wrap_model_invocation(
            mock_model, state, _make_config(), None, [], invoke_fn
        )
        assert result.content == "fallback response"

    @patch(
        "app.agents.middleware.executor.create_model_request",
    )
    @patch(
        "app.agents.middleware.executor.BigtoolRuntime.from_graph_context",
        return_value=MagicMock(),
    )
    async def test_empty_result_falls_back(
        self, mock_rt: MagicMock, mock_create_req: MagicMock
    ) -> None:
        """When model response result list is empty, falls back to direct invocation."""
        mock_model = MagicMock(spec=BaseChatModel)
        expected_msg = AIMessage(content="fallback")
        invoke_fn = AsyncMock(return_value=expected_msg)

        mock_request = MagicMock(spec=ModelRequest)
        mock_request.system_message = None
        mock_request.messages = [HumanMessage(content="hello")]
        mock_create_req.return_value = mock_request

        class _EmptyResultWrap(AgentMiddleware):
            async def awrap_model_call(
                self, request: ModelRequest, handler: Any
            ) -> ModelResponse:
                return ModelResponse(result=[])

        executor = MiddlewareExecutor([_EmptyResultWrap()])
        state = _make_state()
        result = await executor.wrap_model_invocation(
            mock_model, state, _make_config(), None, [], invoke_fn
        )
        assert result.content == "fallback"

    @patch(
        "app.agents.middleware.executor.create_model_request",
    )
    @patch(
        "app.agents.middleware.executor.BigtoolRuntime.from_graph_context",
        return_value=MagicMock(),
    )
    async def test_non_ai_message_result_converted(
        self, mock_rt: MagicMock, mock_create_req: MagicMock
    ) -> None:
        """When result[0] is not AIMessage, it should be converted via str()."""
        mock_model = MagicMock(spec=BaseChatModel)
        invoke_fn = AsyncMock()

        mock_request = MagicMock(spec=ModelRequest)
        mock_request.system_message = None
        mock_request.messages = [HumanMessage(content="hello")]
        mock_create_req.return_value = mock_request

        class _NonAIMessageWrap(AgentMiddleware):
            async def awrap_model_call(
                self, request: ModelRequest, handler: Any
            ) -> ModelResponse:
                fake_msg = MagicMock()
                fake_msg.content = "non-ai content"
                return ModelResponse(result=[fake_msg])

        executor = MiddlewareExecutor([_NonAIMessageWrap()])
        state = _make_state()
        result = await executor.wrap_model_invocation(
            mock_model, state, _make_config(), None, [], invoke_fn
        )
        assert isinstance(result, AIMessage)
        assert "non-ai content" in result.content

    @patch(
        "app.agents.middleware.executor.create_model_request",
    )
    @patch(
        "app.agents.middleware.executor.BigtoolRuntime.from_graph_context",
        return_value=MagicMock(),
    )
    async def test_cancelled_error_propagates(
        self, mock_rt: MagicMock, mock_create_req: MagicMock
    ) -> None:
        mock_model = MagicMock(spec=BaseChatModel)
        invoke_fn = AsyncMock()

        mock_request = MagicMock(spec=ModelRequest)
        mock_request.system_message = None
        mock_request.messages = []
        mock_create_req.return_value = mock_request

        class _CancellingWrap(AgentMiddleware):
            async def awrap_model_call(
                self, request: ModelRequest, handler: Any
            ) -> ModelResponse:
                raise asyncio.CancelledError()

        executor = MiddlewareExecutor([_CancellingWrap()])
        state = _make_state()
        with pytest.raises(asyncio.CancelledError):
            await executor.wrap_model_invocation(
                mock_model, state, _make_config(), None, [], invoke_fn
            )


# ---------------------------------------------------------------------------
# wrap_tool_invocation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWrapToolInvocation:
    @patch(
        "app.agents.middleware.executor.create_tool_call_request",
    )
    @patch(
        "app.agents.middleware.executor.BigtoolToolRuntime.from_graph_context",
        return_value=MagicMock(),
    )
    async def test_no_middleware_calls_invoke_fn(
        self, mock_rt: MagicMock, mock_create_req: MagicMock
    ) -> None:
        tool_call = {"name": "test_tool", "args": {}, "id": "call_1"}
        expected = ToolMessage(content="result", tool_call_id="call_1")
        invoke_fn = AsyncMock(return_value=expected)

        mock_request = MagicMock(spec=ToolCallRequest)
        mock_request.tool_call = tool_call
        mock_create_req.return_value = mock_request

        executor = MiddlewareExecutor([])
        state = _make_state()
        result = await executor.wrap_tool_invocation(
            tool_call, None, state, _make_config(), None, invoke_fn
        )
        assert result.content == "result"

    @patch(
        "app.agents.middleware.executor.create_tool_call_request",
    )
    @patch(
        "app.agents.middleware.executor.BigtoolToolRuntime.from_graph_context",
        return_value=MagicMock(),
    )
    async def test_async_wrap_tool_call(
        self, mock_rt: MagicMock, mock_create_req: MagicMock
    ) -> None:
        tool_call = {"name": "test_tool", "args": {}, "id": "call_1"}
        expected = ToolMessage(content="tool result", tool_call_id="call_1")
        invoke_fn = AsyncMock(return_value=expected)

        mock_request = MagicMock(spec=ToolCallRequest)
        mock_request.tool_call = tool_call
        mock_create_req.return_value = mock_request

        mw = _WrapToolMiddleware()
        executor = MiddlewareExecutor([mw])
        state = _make_state()
        result = await executor.wrap_tool_invocation(
            tool_call, None, state, _make_config(), None, invoke_fn
        )
        assert result.content == "tool result"

    @patch(
        "app.agents.middleware.executor.create_tool_call_request",
    )
    @patch(
        "app.agents.middleware.executor.BigtoolToolRuntime.from_graph_context",
        return_value=MagicMock(),
    )
    async def test_sync_wrap_tool_call(
        self, mock_rt: MagicMock, mock_create_req: MagicMock
    ) -> None:
        tool_call = {"name": "test_tool", "args": {}, "id": "call_1"}
        expected = ToolMessage(content="sync tool result", tool_call_id="call_1")
        invoke_fn = AsyncMock(return_value=expected)

        mock_request = MagicMock(spec=ToolCallRequest)
        mock_request.tool_call = tool_call
        mock_create_req.return_value = mock_request

        mw = _SyncWrapToolMiddleware()
        executor = MiddlewareExecutor([mw])
        state = _make_state()
        result = await executor.wrap_tool_invocation(
            tool_call, None, state, _make_config(), None, invoke_fn
        )
        assert result.content == "sync tool result"

    @patch(
        "app.agents.middleware.executor.create_tool_call_request",
    )
    @patch(
        "app.agents.middleware.executor.BigtoolToolRuntime.from_graph_context",
        return_value=MagicMock(),
    )
    async def test_tool_chain_failure_falls_back(
        self, mock_rt: MagicMock, mock_create_req: MagicMock
    ) -> None:
        tool_call = {"name": "test_tool", "args": {}, "id": "call_1"}
        expected = ToolMessage(content="fallback", tool_call_id="call_1")
        invoke_fn = AsyncMock(return_value=expected)

        mock_request = MagicMock(spec=ToolCallRequest)
        mock_request.tool_call = tool_call
        mock_create_req.return_value = mock_request

        class _FailingWrapTool(AgentMiddleware):
            async def awrap_tool_call(
                self, request: ToolCallRequest, handler: Any
            ) -> ToolMessage:
                raise RuntimeError("tool middleware failed")

        executor = MiddlewareExecutor([_FailingWrapTool()])
        state = _make_state()
        result = await executor.wrap_tool_invocation(
            tool_call, None, state, _make_config(), None, invoke_fn
        )
        assert result.content == "fallback"

    @patch(
        "app.agents.middleware.executor.create_tool_call_request",
    )
    @patch(
        "app.agents.middleware.executor.BigtoolToolRuntime.from_graph_context",
        return_value=MagicMock(),
    )
    async def test_tool_cancelled_error_propagates(
        self, mock_rt: MagicMock, mock_create_req: MagicMock
    ) -> None:
        tool_call = {"name": "test_tool", "args": {}, "id": "call_1"}
        invoke_fn = AsyncMock()

        mock_request = MagicMock(spec=ToolCallRequest)
        mock_request.tool_call = tool_call
        mock_create_req.return_value = mock_request

        class _CancellingWrapTool(AgentMiddleware):
            async def awrap_tool_call(
                self, request: ToolCallRequest, handler: Any
            ) -> ToolMessage:
                raise asyncio.CancelledError()

        executor = MiddlewareExecutor([_CancellingWrapTool()])
        state = _make_state()
        with pytest.raises(asyncio.CancelledError):
            await executor.wrap_tool_invocation(
                tool_call, None, state, _make_config(), None, invoke_fn
            )


# ---------------------------------------------------------------------------
# has_wrap_model_call / has_wrap_tool_call
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHasWrapMethods:
    def test_has_wrap_model_call_true(self) -> None:
        executor = MiddlewareExecutor([_WrapModelMiddleware()])
        assert executor.has_wrap_model_call() is True

    def test_has_wrap_model_call_false(self) -> None:
        executor = MiddlewareExecutor([_NoOpMiddleware()])
        assert executor.has_wrap_model_call() is False

    def test_has_wrap_model_call_sync(self) -> None:
        executor = MiddlewareExecutor([_SyncWrapModelMiddleware()])
        assert executor.has_wrap_model_call() is True

    def test_has_wrap_tool_call_true(self) -> None:
        executor = MiddlewareExecutor([_WrapToolMiddleware()])
        assert executor.has_wrap_tool_call() is True

    def test_has_wrap_tool_call_false(self) -> None:
        executor = MiddlewareExecutor([_NoOpMiddleware()])
        assert executor.has_wrap_tool_call() is False

    def test_has_wrap_tool_call_sync(self) -> None:
        executor = MiddlewareExecutor([_SyncWrapToolMiddleware()])
        assert executor.has_wrap_tool_call() is True

    def test_empty_middleware(self) -> None:
        executor = MiddlewareExecutor([])
        assert executor.has_wrap_model_call() is False
        assert executor.has_wrap_tool_call() is False


# ---------------------------------------------------------------------------
# before_model CancelledError propagates
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCancelledErrorPropagation:
    @patch(
        "app.agents.middleware.executor.BigtoolRuntime.from_graph_context",
        return_value=MagicMock(),
    )
    async def test_before_model_cancelled_error(self, mock_rt: MagicMock) -> None:
        class _CancellingBefore(AgentMiddleware):
            def before_model(self, state: Any, runtime: Any) -> None:
                raise asyncio.CancelledError()

        executor = MiddlewareExecutor([_CancellingBefore()])
        state = _make_state()
        with pytest.raises(asyncio.CancelledError):
            await executor.execute_before_model(state, _make_config())

    @patch(
        "app.agents.middleware.executor.BigtoolRuntime.from_graph_context",
        return_value=MagicMock(),
    )
    async def test_after_model_cancelled_error(self, mock_rt: MagicMock) -> None:
        class _CancellingAfter(AgentMiddleware):
            def after_model(self, state: Any, runtime: Any) -> None:
                raise asyncio.CancelledError()

        executor = MiddlewareExecutor([_CancellingAfter()])
        state = _make_state()
        with pytest.raises(asyncio.CancelledError):
            await executor.execute_after_model(state, _make_config())
