"""Unit tests for the MiddlewareExecutor."""

from unittest.mock import AsyncMock, MagicMock, patch

from langchain.agents.middleware import AgentMiddleware, SummarizationMiddleware
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, ToolMessage
from langchain_google_genai.chat_models import _parse_chat_history
import pytest

from app.agents.middleware.executor import MiddlewareExecutor, _has_override
from tests.factories import make_config, make_state, make_tool_call


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


class SampleAsyncAfterMiddleware(AgentMiddleware):
    """Test middleware that overrides aafter_model."""

    async def aafter_model(self, state, runtime):
        return {"async_after_key": "async_after_value"}


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
    pytestmark = pytest.mark.asyncio

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

        with (
            patch("app.agents.middleware.executor.to_agent_state") as mock_to_state,
            patch("app.agents.middleware.executor.BigtoolRuntime") as mock_runtime_cls,
        ):
            mock_runtime_cls.from_graph_context.return_value = MagicMock()
            mock_to_state.return_value = MagicMock()
            await executor.execute_before_model(mock_state, {})

        # NoopMiddleware has no before_model/abefore_model overrides
        # so the loop hits `continue` without calling mw.before_model
        assert not _has_override(noop, "before_model")
        assert not _has_override(noop, "abefore_model")


@pytest.mark.unit
class TestExecuteAfterModel:
    pytestmark = pytest.mark.asyncio

    async def test_returns_state_unchanged_when_no_middleware(self):
        executor = MiddlewareExecutor()
        state = MagicMock()

        result = await executor.execute_after_model(state, {})
        assert result is state

    async def test_sync_after_model_hook_merges_result_into_state(self):
        """execute_after_model must call after_model and merge its return dict
        into the state.  Without this test the entire active-middleware branch
        of execute_after_model had zero coverage, meaning a silent deletion of
        the update() call would never be caught."""
        mw = SampleAfterMiddleware()
        executor = MiddlewareExecutor([mw])
        state = make_state()
        config = make_config()

        with patch("app.agents.middleware.executor.BigtoolRuntime") as mock_rt_cls:
            mock_rt_cls.from_graph_context.return_value = MagicMock()
            result = await executor.execute_after_model(state, config)

        # SampleAfterMiddleware.after_model returns {"after_key": "after_value"}
        # which must have been merged into the returned State.
        assert result["after_key"] == "after_value"

    async def test_async_aafter_model_hook_merges_result_into_state(self):
        """execute_after_model must prefer aafter_model over after_model and
        still merge the async result.  A bug that awaited the wrong branch
        (or forgot to await) would produce a coroutine instead of a dict and
        the update() call would silently do nothing."""
        mw = SampleAsyncAfterMiddleware()
        executor = MiddlewareExecutor([mw])
        state = make_state()
        config = make_config()

        with patch("app.agents.middleware.executor.BigtoolRuntime") as mock_rt_cls:
            mock_rt_cls.from_graph_context.return_value = MagicMock()
            result = await executor.execute_after_model(state, config)

        assert result["async_after_key"] == "async_after_value"

    async def test_noop_middleware_skipped_returns_state_type(self):
        """execute_after_model with a NoopMiddleware should hit the `continue`
        branch and return a State, not the original object identity."""
        mw = NoopMiddleware()
        executor = MiddlewareExecutor([mw])
        state = make_state()
        config = make_config()

        with patch("app.agents.middleware.executor.BigtoolRuntime") as mock_rt_cls:
            mock_rt_cls.from_graph_context.return_value = MagicMock()
            result = await executor.execute_after_model(state, config)

        # The returned object is a freshly constructed State from dict(state)
        # so it is NOT the same object but carries the same keys.
        assert result["query"] == state["query"]


class MessagesAppendingMiddleware(AgentMiddleware):
    """Middleware that appends one message, the way LangChain hooks are meant to."""

    async def abefore_model(self, state, runtime):
        return {"messages": [HumanMessage(content="injected", id="injected-1")]}


def _summarizing_executor(trigger_after: int, keep: int) -> MiddlewareExecutor:
    """Executor wrapping the real ``SummarizationMiddleware``, tuned to fire immediately."""
    summarizer = GenericFakeChatModel(messages=iter([AIMessage(content="SUMMARY")] * 50))
    return MiddlewareExecutor(
        [
            SummarizationMiddleware(
                model=summarizer,
                trigger=("messages", trigger_after),
                keep=("messages", keep),
            )
        ]
    )


def _long_history(turns: int) -> list:
    messages = []
    for i in range(turns):
        messages.append(HumanMessage(content=f"user turn {i}", id=f"h{i}"))
        messages.append(AIMessage(content=f"assistant turn {i}", id=f"a{i}"))
    return messages


@pytest.mark.unit
class TestExecuteBeforeModelStateUpdates:
    """A middleware hook returns a LangGraph *state update*, not replacement state.

    The executor runs those hooks inside a single bigtool node, so it — not the
    graph — has to resolve them through the channel reducers. Merging them with
    ``dict.update`` instead is what put a ``RemoveMessage(REMOVE_ALL_MESSAGES)``
    tombstone at position 0 of the list handed to the model, 500ing the executor
    endpoint in production.
    """

    pytestmark = pytest.mark.asyncio

    async def test_summarization_tombstone_never_reaches_model_input(self):
        executor = _summarizing_executor(trigger_after=6, keep=2)
        state = make_state(messages=_long_history(10), selected_tool_ids=[])

        with patch("app.agents.middleware.executor.BigtoolRuntime") as mock_rt_cls:
            mock_rt_cls.from_graph_context.return_value = MagicMock()
            result = await executor.execute_before_model(state, make_config())

        assert not any(isinstance(m, RemoveMessage) for m in result["messages"]), (
            "RemoveMessage tombstones are control-plane markers for the state "
            "reducer and must never survive into the model's message list"
        )

    async def test_summarized_messages_are_accepted_by_the_real_provider_serializer(self):
        """The production symptom, pinned to the real serializer that raised it.

        ``langchain_google_genai._parse_chat_history`` is the function that
        raised "Unexpected message with type RemoveMessage at the position 0"
        in the traceback behind the 500s. It runs before any network call, so
        the real one is used here rather than a stand-in.
        """
        executor = _summarizing_executor(trigger_after=6, keep=2)
        state = make_state(messages=_long_history(10), selected_tool_ids=[])

        with patch("app.agents.middleware.executor.BigtoolRuntime") as mock_rt_cls:
            mock_rt_cls.from_graph_context.return_value = MagicMock()
            result = await executor.execute_before_model(state, make_config())

        _parse_chat_history(result["messages"], convert_system_message_to_human=False)

    async def test_summarization_drops_the_summarized_history(self):
        """The tombstone must be *applied*, not merely dropped.

        Filtering the sentinel out without honouring it would leave the full
        pre-summarization history in front of the model — no crash, but
        summarization silently doing nothing, which is the harder bug to see.
        """
        executor = _summarizing_executor(trigger_after=6, keep=2)
        state = make_state(messages=_long_history(10), selected_tool_ids=[])

        with patch("app.agents.middleware.executor.BigtoolRuntime") as mock_rt_cls:
            mock_rt_cls.from_graph_context.return_value = MagicMock()
            result = await executor.execute_before_model(state, make_config())

        surviving_ids = {m.id for m in result["messages"]}
        assert "h0" not in surviving_ids and "a0" not in surviving_ids
        assert len(result["messages"]) < 20

    async def test_message_update_appends_instead_of_replacing_history(self):
        """A hook returning one message must not wipe the conversation.

        ``LLMAccountingMiddleware.abefore_model`` is documented to start
        returning ``{"messages": [AIMessage("Credit limit reached…")]}`` for
        credit gating; under ``dict.update`` that would hand the model a
        one-message conversation.
        """
        executor = MiddlewareExecutor([MessagesAppendingMiddleware()])
        state = make_state(messages=_long_history(2), selected_tool_ids=[])

        with patch("app.agents.middleware.executor.BigtoolRuntime") as mock_rt_cls:
            mock_rt_cls.from_graph_context.return_value = MagicMock()
            result = await executor.execute_before_model(state, make_config())

        assert [m.id for m in result["messages"]] == ["h0", "a0", "h1", "a1", "injected-1"]

    async def test_non_message_keys_are_still_last_write_wins(self):
        executor = MiddlewareExecutor([SampleAsyncBeforeMiddleware()])
        state = make_state(async_key="stale")

        with patch("app.agents.middleware.executor.BigtoolRuntime") as mock_rt_cls:
            mock_rt_cls.from_graph_context.return_value = MagicMock()
            result = await executor.execute_before_model(state, make_config())

        assert result["async_key"] == "async_value"


@pytest.mark.unit
class TestExecuteAfterModelStateUpdates:
    """``execute_after_model`` merges hook returns the same way and needs the same fix."""

    pytestmark = pytest.mark.asyncio

    async def test_message_update_appends_instead_of_replacing_history(self):
        class AppendingAfterMiddleware(AgentMiddleware):
            async def aafter_model(self, state, runtime):
                return {"messages": [AIMessage(content="appended", id="appended-1")]}

        executor = MiddlewareExecutor([AppendingAfterMiddleware()])
        state = make_state(messages=_long_history(2), selected_tool_ids=[])

        with patch("app.agents.middleware.executor.BigtoolRuntime") as mock_rt_cls:
            mock_rt_cls.from_graph_context.return_value = MagicMock()
            result = await executor.execute_after_model(state, make_config())

        assert [m.id for m in result["messages"]] == ["h0", "a0", "h1", "a1", "appended-1"]


@pytest.mark.unit
class TestWrapModelInvocation:
    pytestmark = pytest.mark.asyncio

    async def test_calls_invoke_fn_and_returns_ai_message(self):
        """wrap_model_invocation must call the provided invoke_fn exactly once
        and return the AIMessage it produces.  Zero coverage here meant that a
        bug swapping invoke_fn for some other callable would go undetected."""
        executor = MiddlewareExecutor([SampleWrapModelMiddleware()])
        state = make_state()
        config = make_config()

        expected = AIMessage(content="hello from model")
        invoke_fn = AsyncMock(return_value=expected)
        fake_model = MagicMock()

        with (
            patch("app.agents.middleware.executor.BigtoolRuntime") as mock_rt_cls,
            patch("app.agents.middleware.executor.create_model_request") as mock_create_req,
        ):
            mock_rt_cls.from_graph_context.return_value = MagicMock()
            # ModelRequest stub: needs .system_message and .messages
            mock_req = MagicMock()
            mock_req.system_message = None
            mock_req.messages = [MagicMock()]
            mock_create_req.return_value = mock_req

            result = await executor.wrap_model_invocation(
                model=fake_model,
                state=state,
                config=config,
                store=None,
                tools=[],
                invoke_fn=invoke_fn,
            )

        assert isinstance(result, AIMessage)
        assert result.content == "hello from model"
        invoke_fn.assert_awaited_once()

    async def test_middleware_wraps_handler_chain(self):
        """wrap_model_invocation must thread the request through each
        middleware's awrap_model_call.  If the closure-capture bug (loop
        variable reuse) were introduced, all middleware would wrap with the
        same (last) handler and the chain would break."""
        call_log: list[str] = []

        class LoggingWrapMiddleware(AgentMiddleware):
            async def awrap_model_call(self, request, handler):
                call_log.append("before")
                response = await handler(request)
                call_log.append("after")
                return response

        executor = MiddlewareExecutor([LoggingWrapMiddleware()])
        state = make_state()
        config = make_config()

        sentinel = AIMessage(content="sentinel")
        invoke_fn = AsyncMock(return_value=sentinel)
        fake_model = MagicMock()

        with (
            patch("app.agents.middleware.executor.BigtoolRuntime") as mock_rt_cls,
            patch("app.agents.middleware.executor.create_model_request") as mock_create_req,
        ):
            mock_rt_cls.from_graph_context.return_value = MagicMock()
            mock_req = MagicMock()
            mock_req.system_message = None
            mock_req.messages = []
            mock_create_req.return_value = mock_req

            result = await executor.wrap_model_invocation(
                model=fake_model,
                state=state,
                config=config,
                store=None,
                tools=[],
                invoke_fn=invoke_fn,
            )

        assert result.content == "sentinel"
        assert call_log == ["before", "after"]

    async def test_empty_result_list_falls_back_to_direct_invoke(self):
        """If middleware returns a ModelResponse with an empty result list,
        wrap_model_invocation must fall back to calling invoke_fn directly
        rather than raising to the caller."""

        class EmptyResponseMiddleware(AgentMiddleware):
            async def awrap_model_call(self, request, handler):
                from langchain.agents.middleware.types import ModelResponse

                return ModelResponse(result=[])

        executor = MiddlewareExecutor([EmptyResponseMiddleware()])
        state = make_state()
        config = make_config()

        fallback_msg = AIMessage(content="fallback")
        invoke_fn = AsyncMock(return_value=fallback_msg)
        fake_model = MagicMock()

        with (
            patch("app.agents.middleware.executor.BigtoolRuntime") as mock_rt_cls,
            patch("app.agents.middleware.executor.create_model_request") as mock_create_req,
        ):
            mock_rt_cls.from_graph_context.return_value = MagicMock()
            mock_req = MagicMock()
            mock_req.system_message = None
            mock_req.messages = []
            mock_create_req.return_value = mock_req

            result = await executor.wrap_model_invocation(
                model=fake_model,
                state=state,
                config=config,
                store=None,
                tools=[],
                invoke_fn=invoke_fn,
            )

        assert isinstance(result, AIMessage)
        invoke_fn.assert_awaited()


@pytest.mark.unit
class TestWrapToolInvocation:
    pytestmark = pytest.mark.asyncio

    async def test_calls_invoke_fn_with_tool_call_dict(self):
        """wrap_tool_invocation must call the provided invoke_fn and return the
        ToolMessage it produces.  Zero coverage here meant that a regression
        switching tool_call to request.tool_call would be invisible."""
        executor = MiddlewareExecutor([SampleWrapToolMiddleware()])
        state = make_state()
        config = make_config()
        tool_call = make_tool_call("my_tool", {"param": "value"})

        expected = ToolMessage(content="tool result", tool_call_id=tool_call["id"])
        invoke_fn = AsyncMock(return_value=expected)
        fake_tool = MagicMock()

        with (
            patch("app.agents.middleware.executor.BigtoolToolRuntime") as mock_rt_cls,
            patch("app.agents.middleware.executor.create_tool_call_request") as mock_create_req,
        ):
            mock_rt_cls.from_graph_context.return_value = MagicMock()
            mock_req = MagicMock()
            mock_req.tool_call = tool_call
            mock_create_req.return_value = mock_req

            result = await executor.wrap_tool_invocation(
                tool_call=tool_call,
                tool=fake_tool,
                state=state,
                config=config,
                store=None,
                invoke_fn=invoke_fn,
            )

        assert isinstance(result, ToolMessage)
        assert result.content == "tool result"
        invoke_fn.assert_awaited_once()

    async def test_middleware_wraps_tool_handler_chain(self):
        """wrap_tool_invocation must thread through awrap_tool_call middleware.
        If the wrapping chain is skipped entirely the middleware's before/after
        logic would silently not run."""
        call_log: list[str] = []

        class LoggingToolWrapMiddleware(AgentMiddleware):
            async def awrap_tool_call(self, request, handler):
                call_log.append("before_tool")
                response = await handler(request)
                call_log.append("after_tool")
                return response

        executor = MiddlewareExecutor([LoggingToolWrapMiddleware()])
        state = make_state()
        config = make_config()
        tool_call = make_tool_call("search", {"q": "test"})

        sentinel = ToolMessage(content="ok", tool_call_id=tool_call["id"])
        invoke_fn = AsyncMock(return_value=sentinel)
        fake_tool = MagicMock()

        with (
            patch("app.agents.middleware.executor.BigtoolToolRuntime") as mock_rt_cls,
            patch("app.agents.middleware.executor.create_tool_call_request") as mock_create_req,
        ):
            mock_rt_cls.from_graph_context.return_value = MagicMock()
            mock_req = MagicMock()
            mock_req.tool_call = tool_call
            mock_create_req.return_value = mock_req

            result = await executor.wrap_tool_invocation(
                tool_call=tool_call,
                tool=fake_tool,
                state=state,
                config=config,
                store=None,
                invoke_fn=invoke_fn,
            )

        assert result.content == "ok"
        assert call_log == ["before_tool", "after_tool"]

    async def test_exception_in_wrap_falls_back_to_direct_invoke(self):
        """wrap_tool_invocation must catch middleware exceptions and fall back
        to direct invoke_fn rather than propagating to the caller.  Without
        coverage of this path a removal of the except block would pass silently."""

        class ExplodingToolMiddleware(AgentMiddleware):
            async def awrap_tool_call(self, request, handler):
                raise RuntimeError("middleware exploded")

        executor = MiddlewareExecutor([ExplodingToolMiddleware()])
        state = make_state()
        config = make_config()
        tool_call = make_tool_call("exploding_tool")

        fallback = ToolMessage(content="direct result", tool_call_id=tool_call["id"])
        invoke_fn = AsyncMock(return_value=fallback)
        fake_tool = MagicMock()

        with (
            patch("app.agents.middleware.executor.BigtoolToolRuntime") as mock_rt_cls,
            patch("app.agents.middleware.executor.create_tool_call_request") as mock_create_req,
        ):
            mock_rt_cls.from_graph_context.return_value = MagicMock()
            mock_req = MagicMock()
            mock_req.tool_call = tool_call
            mock_create_req.return_value = mock_req

            result = await executor.wrap_tool_invocation(
                tool_call=tool_call,
                tool=fake_tool,
                state=state,
                config=config,
                store=None,
                invoke_fn=invoke_fn,
            )

        assert result.content == "direct result"
        invoke_fn.assert_awaited()
