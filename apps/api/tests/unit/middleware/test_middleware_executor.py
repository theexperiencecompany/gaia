"""Unit tests for the MiddlewareExecutor."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from langchain.agents.middleware import AgentMiddleware

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


@pytest.mark.unit
class TestExecuteAfterModel:
    async def test_returns_state_unchanged_when_no_middleware(self):
        executor = MiddlewareExecutor()
        state = MagicMock()

        result = await executor.execute_after_model(state, {})
        assert result is state
