"""Unit tests for the MiddlewareExecutor."""

import asyncio
import pytest
from unittest.mock import MagicMock, patch

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse, ToolCallRequest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.messages.tool import ToolCall

from app.agents.middleware.executor import MiddlewareExecutor, _has_override


class SampleBeforeMiddleware(AgentMiddleware):
    """Test middleware that overrides before_model."""

    def before_model(self, state, runtime):
        return {"injected_key": "before_value"}


class SampleAsyncBeforeMiddleware(AgentMiddleware):
    """Test middleware that overrides abefore_model."""

    async def abefore_model(self, state, runtime):
        return {"async_key": "async_value"}


class SampleAfterMiddleware(AgentMiddleware):
    """Test middleware that overrides after_model."""

    def after_model(self, state, runtime):
        return {"after_key": "after_value"}


class SampleAsyncAfterMiddleware(AgentMiddleware):
    """Test middleware that overrides aafter_model."""

    async def aafter_model(self, state, runtime):
        return {"async_after_key": "async_after_value"}


class RaisingBeforeMiddleware(AgentMiddleware):
    """Test middleware whose before_model raises asyncio.CancelledError."""

    def before_model(self, state, runtime):
        raise asyncio.CancelledError("task was cancelled")


class NoopMiddleware(AgentMiddleware):
    """Middleware that does not override any methods."""

    pass


class SampleWrapModelMiddleware(AgentMiddleware):
    """Test middleware that overrides awrap_model_call."""

    async def awrap_model_call(self, request, handler):
        return await handler(request)


class SampleWrapToolMiddleware(AgentMiddleware):
    """Test middleware that overrides awrap_tool_call."""

    async def awrap_tool_call(self, request, handler):
        return await handler(request)


class RecordingWrapModelMiddleware(AgentMiddleware):
    """Middleware that records the call order and delegates to the handler."""

    def __init__(self, call_log: list, label: str) -> None:
        self._call_log = call_log
        self._label = label

    async def awrap_model_call(self, request, handler):
        self._call_log.append(f"{self._label}:before")
        result = await handler(request)
        self._call_log.append(f"{self._label}:after")
        return result


class TransformingWrapModelMiddleware(AgentMiddleware):
    """Middleware that replaces the model response with a fixed AIMessage."""

    TRANSFORMED_CONTENT = "transformed by middleware"

    async def awrap_model_call(self, request, handler):
        await handler(request)
        return ModelResponse(result=[AIMessage(content=self.TRANSFORMED_CONTENT)])


class RecordingWrapToolMiddleware(AgentMiddleware):
    """Middleware that captures the ToolCallRequest passed to it."""

    def __init__(self) -> None:
        self.captured_request: ToolCallRequest | None = None

    async def awrap_tool_call(self, request, handler):
        self.captured_request = request
        return await handler(request)


@pytest.mark.unit
class TestHasOverride:
    def test_detects_overridden_method(self):
        mw = SampleBeforeMiddleware()
        assert _has_override(mw, "before_model") is True

    def test_detects_async_override(self):
        mw = SampleAsyncBeforeMiddleware()
        assert _has_override(mw, "abefore_model") is True

    def test_returns_false_for_base_methods(self):
        mw = NoopMiddleware()
        assert _has_override(mw, "before_model") is False
        assert _has_override(mw, "abefore_model") is False
        assert _has_override(mw, "after_model") is False
        assert _has_override(mw, "wrap_model_call") is False

    def test_returns_false_for_nonexistent_method(self):
        mw = SampleBeforeMiddleware()
        assert _has_override(mw, "totally_fake_method") is False

    def test_detects_wrap_model_call(self):
        mw = SampleWrapModelMiddleware()
        assert _has_override(mw, "awrap_model_call") is True

    def test_detects_wrap_tool_call(self):
        mw = SampleWrapToolMiddleware()
        assert _has_override(mw, "awrap_tool_call") is True


@pytest.mark.unit
class TestMiddlewareExecutorInit:
    def test_empty_middleware_list(self):
        executor = MiddlewareExecutor()
        assert executor.middleware == []

    def test_none_middleware_list(self):
        executor = MiddlewareExecutor(None)
        assert executor.middleware == []

    def test_stores_middleware(self):
        mw = [SampleBeforeMiddleware()]
        executor = MiddlewareExecutor(mw)
        assert len(executor.middleware) == 1


@pytest.mark.unit
class TestHasWrapChecks:
    def test_has_wrap_model_call_true(self):
        executor = MiddlewareExecutor([SampleWrapModelMiddleware()])
        assert executor.has_wrap_model_call() is True

    def test_has_wrap_model_call_false(self):
        executor = MiddlewareExecutor([NoopMiddleware()])
        assert executor.has_wrap_model_call() is False

    def test_has_wrap_model_call_empty(self):
        executor = MiddlewareExecutor()
        assert executor.has_wrap_model_call() is False

    def test_has_wrap_tool_call_true(self):
        executor = MiddlewareExecutor([SampleWrapToolMiddleware()])
        assert executor.has_wrap_tool_call() is True

    def test_has_wrap_tool_call_false(self):
        executor = MiddlewareExecutor([NoopMiddleware()])
        assert executor.has_wrap_tool_call() is False


@pytest.mark.unit
class TestExecuteBeforeModel:
    async def test_returns_state_unchanged_when_no_middleware(self):
        executor = MiddlewareExecutor()
        state = MagicMock()

        result = await executor.execute_before_model(state, {})
        assert result is state

    async def test_skips_noop_middleware_hooks(self):
        noop = NoopMiddleware()
        executor = MiddlewareExecutor([noop])

        mock_state = MagicMock()
        mock_state.__iter__ = MagicMock(return_value=iter([]))
        mock_state.keys = MagicMock(return_value=[])

        with patch(
            "app.agents.middleware.executor.to_agent_state"
        ) as mock_to_state, patch(
            "app.agents.middleware.executor.BigtoolRuntime"
        ) as mock_runtime_cls:
            mock_runtime_cls.from_graph_context.return_value = MagicMock()
            mock_to_state.return_value = MagicMock()
            await executor.execute_before_model(mock_state, {})

        # NoopMiddleware has no before_model/abefore_model overrides
        # so the loop hits `continue` without calling mw.before_model
        assert not _has_override(noop, "before_model")
        assert not _has_override(noop, "abefore_model")

    async def test_execute_before_model_applies_state_updates(self):
        """Middleware that returns a dict must have its updates merged into state."""
        mw = SampleBeforeMiddleware()
        executor = MiddlewareExecutor([mw])

        # Use a plain dict so dict(state) inside execute_before_model works correctly.
        fake_state = {"messages": [], "selected_tool_ids": [], "todos": []}

        captured_state_kwargs: dict = {}

        def fake_state_constructor(**kwargs):
            captured_state_kwargs.update(kwargs)
            return MagicMock()

        with patch(
            "app.agents.middleware.executor.to_agent_state"
        ) as mock_to_state, patch(
            "app.agents.middleware.executor.BigtoolRuntime"
        ) as mock_runtime_cls, patch(
            "app.agents.middleware.executor.State",
            side_effect=fake_state_constructor,
        ):
            mock_runtime_cls.from_graph_context.return_value = MagicMock()
            mock_to_state.return_value = MagicMock()
            await executor.execute_before_model(fake_state, {})

        # SampleBeforeMiddleware.before_model returns {"injected_key": "before_value"}
        # That dict must have been merged into the state passed to State(...)
        assert captured_state_kwargs.get("injected_key") == "before_value"

    async def test_execute_before_model_runs_async_middleware(self):
        """abefore_model must be awaited and its updates applied."""
        mw = SampleAsyncBeforeMiddleware()
        executor = MiddlewareExecutor([mw])

        fake_state = {"messages": [], "selected_tool_ids": [], "todos": []}

        captured_state_kwargs: dict = {}

        def fake_state_constructor(**kwargs):
            captured_state_kwargs.update(kwargs)
            return MagicMock()

        with patch(
            "app.agents.middleware.executor.to_agent_state"
        ) as mock_to_state, patch(
            "app.agents.middleware.executor.BigtoolRuntime"
        ) as mock_runtime_cls, patch(
            "app.agents.middleware.executor.State",
            side_effect=fake_state_constructor,
        ):
            mock_runtime_cls.from_graph_context.return_value = MagicMock()
            mock_to_state.return_value = MagicMock()
            await executor.execute_before_model(fake_state, {})

        # SampleAsyncBeforeMiddleware.abefore_model returns {"async_key": "async_value"}
        assert captured_state_kwargs.get("async_key") == "async_value"

    async def test_execute_before_model_runs_sync_middleware(self):
        """Sync before_model (not async) must also be called and applied."""
        mw = SampleBeforeMiddleware()
        executor = MiddlewareExecutor([mw])

        fake_state = {"messages": [], "selected_tool_ids": [], "todos": []}

        captured_state_kwargs: dict = {}

        def fake_state_constructor(**kwargs):
            captured_state_kwargs.update(kwargs)
            return MagicMock()

        with patch(
            "app.agents.middleware.executor.to_agent_state"
        ) as mock_to_state, patch(
            "app.agents.middleware.executor.BigtoolRuntime"
        ) as mock_runtime_cls, patch(
            "app.agents.middleware.executor.State",
            side_effect=fake_state_constructor,
        ):
            mock_runtime_cls.from_graph_context.return_value = MagicMock()
            mock_to_state.return_value = MagicMock()
            await executor.execute_before_model(fake_state, {})

        # before_model (sync) returned {"injected_key": "before_value"}
        assert "injected_key" in captured_state_kwargs
        assert captured_state_kwargs["injected_key"] == "before_value"

    async def test_execute_before_model_exception_propagates(self):
        """asyncio.CancelledError from middleware must propagate, not be swallowed."""
        mw = RaisingBeforeMiddleware()
        executor = MiddlewareExecutor([mw])

        fake_state = {"messages": [], "selected_tool_ids": [], "todos": []}

        with patch(
            "app.agents.middleware.executor.to_agent_state"
        ) as mock_to_state, patch(
            "app.agents.middleware.executor.BigtoolRuntime"
        ) as mock_runtime_cls:
            mock_runtime_cls.from_graph_context.return_value = MagicMock()
            mock_to_state.return_value = MagicMock()
            with pytest.raises(asyncio.CancelledError):
                await executor.execute_before_model(fake_state, {})


@pytest.mark.unit
class TestExecuteAfterModel:
    async def test_returns_state_unchanged_when_no_middleware(self):
        executor = MiddlewareExecutor()
        state = MagicMock()

        result = await executor.execute_after_model(state, {})
        assert result is state

    async def test_execute_after_model_receives_model_output(self):
        """after_model hook must receive a state that reflects the AI response."""
        mw = SampleAfterMiddleware()
        executor = MiddlewareExecutor([mw])

        ai_response = AIMessage(content="The answer is 42.")
        # Use a plain dict so that dict(state) inside execute_after_model
        # faithfully reproduces the mapping including the messages key.
        fake_state = {
            "messages": [ai_response],
            "selected_tool_ids": [],
            "todos": [],
        }

        captured_agent_state_calls: list = []

        def fake_to_agent_state(state_dict):
            captured_agent_state_calls.append(state_dict)
            return MagicMock()

        captured_state_kwargs: dict = {}

        def fake_state_constructor(**kwargs):
            captured_state_kwargs.update(kwargs)
            return MagicMock()

        with patch(
            "app.agents.middleware.executor.to_agent_state",
            side_effect=fake_to_agent_state,
        ), patch(
            "app.agents.middleware.executor.BigtoolRuntime"
        ) as mock_runtime_cls, patch(
            "app.agents.middleware.executor.State",
            side_effect=fake_state_constructor,
        ):
            mock_runtime_cls.from_graph_context.return_value = MagicMock()
            await executor.execute_after_model(fake_state, {})

        # to_agent_state was called with the current_state dict; the messages
        # key must include the AI response, proving the model output reached
        # the after-model hook.
        assert len(captured_agent_state_calls) >= 1
        passed_dict = captured_agent_state_calls[0]
        assert passed_dict.get("messages") == [ai_response]
        # SampleAfterMiddleware returns {"after_key": "after_value"}
        assert captured_state_kwargs.get("after_key") == "after_value"


@pytest.mark.unit
class TestWrapModelInvocation:
    def _make_model_request(self) -> ModelRequest:
        return ModelRequest(
            model=MagicMock(),
            messages=[HumanMessage(content="hello")],
            system_message=None,
            tool_choice=None,
            tools=[],
            response_format=None,
            state=MagicMock(),
            runtime=MagicMock(),
            model_settings={},
        )

    async def test_wrap_model_invocation_chains_handlers(self):
        """Each middleware must wrap the next; the call log proves the chain order."""
        call_log: list[str] = []
        mw_first = RecordingWrapModelMiddleware(call_log, "first")
        mw_second = RecordingWrapModelMiddleware(call_log, "second")
        executor = MiddlewareExecutor([mw_first, mw_second])

        fake_request = self._make_model_request()
        final_ai_msg = AIMessage(content="model reply")

        async def fake_invoke(messages):
            call_log.append("invoke")
            return final_ai_msg

        with patch(
            "app.agents.middleware.executor.BigtoolRuntime"
        ) as mock_runtime_cls, patch(
            "app.agents.middleware.executor.create_model_request",
            return_value=fake_request,
        ):
            mock_runtime_cls.from_graph_context.return_value = MagicMock()
            result = await executor.wrap_model_invocation(
                model=MagicMock(),
                state=MagicMock(),
                config={},
                store=None,
                tools=[],
                invoke_fn=fake_invoke,
            )

        # With two wrapping middlewares the expected order is:
        # first:before -> second:before -> invoke -> second:after -> first:after
        assert call_log == [
            "first:before",
            "second:before",
            "invoke",
            "second:after",
            "first:after",
        ]
        assert isinstance(result, AIMessage)
        assert result.content == "model reply"

    async def test_wrap_model_invocation_transforms_response(self):
        """Middleware can replace the model response with its own AIMessage."""
        mw = TransformingWrapModelMiddleware()
        executor = MiddlewareExecutor([mw])

        fake_request = self._make_model_request()
        original_ai_msg = AIMessage(content="original model reply")

        async def fake_invoke(messages):
            return original_ai_msg

        with patch(
            "app.agents.middleware.executor.BigtoolRuntime"
        ) as mock_runtime_cls, patch(
            "app.agents.middleware.executor.create_model_request",
            return_value=fake_request,
        ):
            mock_runtime_cls.from_graph_context.return_value = MagicMock()
            result = await executor.wrap_model_invocation(
                model=MagicMock(),
                state=MagicMock(),
                config={},
                store=None,
                tools=[],
                invoke_fn=fake_invoke,
            )

        assert isinstance(result, AIMessage)
        assert result.content == TransformingWrapModelMiddleware.TRANSFORMED_CONTENT


@pytest.mark.unit
class TestWrapToolInvocation:
    def _make_tool_call_request(self, tool_call: dict) -> ToolCallRequest:
        tc: ToolCall = {
            "name": tool_call.get("name", ""),
            "args": tool_call.get("args", {}),
            "id": tool_call.get("id"),
        }
        return ToolCallRequest(
            tool_call=tc,
            tool=None,
            state=MagicMock(),
            runtime=MagicMock(),
        )

    async def test_wrap_tool_invocation_called_with_tool_args(self):
        """The ToolCallRequest received by middleware must contain the original args."""
        tool_call_dict = {
            "name": "search_web",
            "args": {"query": "latest news", "max_results": 5},
            "id": "call_abc123",
        }
        mw = RecordingWrapToolMiddleware()
        executor = MiddlewareExecutor([mw])

        fake_request = self._make_tool_call_request(tool_call_dict)
        expected_tool_msg = ToolMessage(
            content="search results",
            tool_call_id="call_abc123",
        )

        async def fake_invoke(tc):
            return expected_tool_msg

        with patch(
            "app.agents.middleware.executor.BigtoolToolRuntime"
        ) as mock_tool_runtime_cls, patch(
            "app.agents.middleware.executor.create_tool_call_request",
            return_value=fake_request,
        ):
            mock_tool_runtime_cls.from_graph_context.return_value = MagicMock()
            result = await executor.wrap_tool_invocation(
                tool_call=tool_call_dict,
                tool=None,
                state=MagicMock(),
                config={},
                store=None,
                invoke_fn=fake_invoke,
            )

        # The middleware captured the request; its tool_call must carry the args
        assert mw.captured_request is not None
        assert mw.captured_request.tool_call["name"] == "search_web"
        assert mw.captured_request.tool_call["args"] == {
            "query": "latest news",
            "max_results": 5,
        }
        assert mw.captured_request.tool_call["id"] == "call_abc123"
        assert result is expected_tool_msg
