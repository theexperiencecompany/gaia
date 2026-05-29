"""Unit tests for the MiddlewareExecutor.

BEHAVIOR SPEC
=============

UNIT: app/agents/middleware/executor.py :: _has_override
EXPECTED: Return True iff a concrete subclass (not the AgentMiddleware base, not
          object) defines `method_name` in its own __dict__. The base class
          defines every hook, so a naive hasattr() is wrong — only real overrides
          count.
MECHANISM: walk type(mw).__mro__, skip AgentMiddleware and object, return True on
           first cls with method_name in cls.__dict__; else False.
MUST-CATCH:
  - a subclass that overrides sync `before_model` -> True
  - a subclass that overrides async `abefore_model` -> True
  - a subclass that overrides nothing (NoopMiddleware) -> False for every hook
  - a name that exists nowhere -> False
  - overrides for wrap_model_call / wrap_tool_call (sync + async) detected
EQUIVALENT MUTANTS: none.

UNIT: MiddlewareExecutor.__init__
EXPECTED: store the given list; coerce None/empty to [].
MUST-CATCH: None -> [], explicit list preserved by identity-of-contents.

UNIT: MiddlewareExecutor._create_runtime / _create_tool_runtime
EXPECTED: return the runtime built by BigtoolRuntime/BigtoolToolRuntime
          .from_graph_context, forwarding config (+ store, +tool_name).
MECHANISM: return BigtoolRuntime.from_graph_context(config=config, store=store).
MUST-CATCH:
  - the returned object IS the runtime from from_graph_context (not None)
  - config and store are forwarded
  - _create_tool_runtime forwards the tool_name

UNIT: execute_before_model / execute_after_model
EXPECTED: with no middleware, return the SAME state object untouched. With
          middleware, run each hook in order (async hook preferred over sync),
          merge any returned dict into a working copy of the state, swallow
          per-middleware exceptions (logged, not raised), and return a freshly
          built State carrying the merged keys. NoopMiddleware is skipped via
          `continue`.
MECHANISM: if not middleware: return state. Else dict(state); per mw:
           if abefore_model override -> await; elif before_model -> call; else
           continue. if result is not None: current_state.update(result).
           except CancelledError: raise; except Exception: log.warning.
           return State(**current_state).
MUST-CATCH:
  - empty executor returns the *identical* input object (is state)
  - sync hook result merged into returned state
  - async hook result merged, and async hook PREFERRED when both exist
  - `if result is not None` guard: a None-returning hook does not crash/merge
  - a raising middleware is swallowed; later middleware still runs; state returned
  - CancelledError propagates (not swallowed)
  - Noop middleware skipped, returned object still carries original keys

UNIT: wrap_model_invocation
EXPECTED: build a request, thread it through every awrap_model_call /
          wrap_model_call middleware (first middleware outermost), the innermost
          handler prepends system_message then sends messages to invoke_fn, and
          the AIMessage in ModelResponse.result[0] is returned. A non-AIMessage
          result is coerced to AIMessage(content=str(...)). Empty result list ->
          ValueError caught -> fallback to direct invoke_fn(state messages).
          A middleware exception -> fallback to direct invoke.
MUST-CATCH:
  - invoke_fn called once, its AIMessage returned through the chain
  - middleware before/after ordering with TWO middleware (outermost = first)
  - sync wrap_model_call middleware is awaited correctly (coroutine handling)
  - system_message prepended before messages when present
  - non-AIMessage result coerced to AIMessage with its content
  - empty-result -> fallback path returns invoke_fn result
  - middleware raising -> fallback to direct invoke

UNIT: wrap_tool_invocation
EXPECTED: extract tool name (default "unknown"), build tool runtime with that
          name, thread the request through awrap_tool_call / wrap_tool_call
          middleware (first outermost), innermost handler calls invoke_fn with
          request.tool_call, return the ToolMessage. Middleware exception ->
          fallback to direct invoke_fn(tool_call).
MUST-CATCH:
  - invoke_fn called, ToolMessage returned through chain
  - tool runtime created with the tool_call's name (not a constant)
  - middleware before/after ordering with TWO middleware
  - sync wrap_tool_call middleware awaited correctly
  - middleware raising -> fallback to direct invoke

UNIT: has_wrap_model_call / has_wrap_tool_call
EXPECTED: True iff any middleware overrides the sync OR async wrap hook.
MUST-CATCH: sync-only override detected, async-only override detected, Noop ->
            False, empty -> False.

EQUIVALENT MUTANTS (allowed survivors, justified):
  - executor.py L287 `raise ValueError("Model middleware returned empty result
    list")` -> `raise ValueError("")`: behaviour-preserving. The empty-result
    guard raises inside the `try`, and the `except Exception` immediately catches
    it and falls back to direct invoke_fn regardless of the message text. The
    string is never read by any code path, so no non-log-snooping assertion can
    distinguish it. (kill rate 56/57 = 98.25%)
"""

from unittest.mock import AsyncMock, MagicMock, patch

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
import pytest

from app.agents.middleware.executor import MiddlewareExecutor, _has_override
from tests.factories import make_config, make_state, make_tool_call

RT_PATH = "app.agents.middleware.executor.BigtoolRuntime"
TOOL_RT_PATH = "app.agents.middleware.executor.BigtoolToolRuntime"
MODEL_REQ_PATH = "app.agents.middleware.executor.create_model_request"
TOOL_REQ_PATH = "app.agents.middleware.executor.create_tool_call_request"


class SampleBeforeMiddleware(AgentMiddleware):
    """Overrides sync before_model."""

    def before_model(self, state, runtime):
        return {"injected_key": "before_value"}


class SampleAsyncBeforeMiddleware(AgentMiddleware):
    """Overrides async abefore_model."""

    async def abefore_model(self, state, runtime):
        return {"async_key": "async_value"}


class SampleAfterMiddleware(AgentMiddleware):
    """Overrides sync after_model."""

    def after_model(self, state, runtime):
        return {"after_key": "after_value"}


class SampleAsyncAfterMiddleware(AgentMiddleware):
    """Overrides async aafter_model."""

    async def aafter_model(self, state, runtime):
        return {"async_after_key": "async_after_value"}


class NoopMiddleware(AgentMiddleware):
    """Overrides nothing."""


class SampleWrapModelMiddleware(AgentMiddleware):
    """Overrides async awrap_model_call (pass-through)."""

    async def awrap_model_call(self, request, handler):
        return await handler(request)


class SampleSyncWrapModelMiddleware(AgentMiddleware):
    """Overrides sync wrap_model_call. Returns a coroutine that the executor must
    detect-and-await, and stamps the result so the wrap branch is observable."""

    def wrap_model_call(self, request, handler):
        async def _run():
            response = await handler(request)
            response.result[0].content += "+sync"
            return response

        return _run()


class SampleWrapToolMiddleware(AgentMiddleware):
    """Overrides async awrap_tool_call (pass-through)."""

    async def awrap_tool_call(self, request, handler):
        return await handler(request)


class SampleSyncWrapToolMiddleware(AgentMiddleware):
    """Overrides sync wrap_tool_call. Returns a coroutine the executor must
    detect-and-await, and stamps the result so the wrap branch is observable."""

    def wrap_tool_call(self, request, handler):
        async def _run():
            response = await handler(request)
            response.content += "+sync"
            return response

        return _run()


def _model_req(system_message=None, messages=None) -> MagicMock:
    req = MagicMock()
    req.system_message = system_message
    req.messages = [] if messages is None else messages
    return req


@pytest.mark.unit
class TestHasOverride:
    def test_detects_overridden_sync_method(self):
        assert _has_override(SampleBeforeMiddleware(), "before_model") is True

    def test_detects_async_override(self):
        assert _has_override(SampleAsyncBeforeMiddleware(), "abefore_model") is True

    def test_returns_false_for_unoverridden_base_methods(self):
        mw = NoopMiddleware()
        assert _has_override(mw, "before_model") is False
        assert _has_override(mw, "abefore_model") is False
        assert _has_override(mw, "after_model") is False
        assert _has_override(mw, "wrap_model_call") is False

    def test_returns_false_for_nonexistent_method(self):
        assert _has_override(SampleBeforeMiddleware(), "totally_fake_method") is False

    def test_detects_wrap_model_call(self):
        assert _has_override(SampleWrapModelMiddleware(), "awrap_model_call") is True

    def test_detects_wrap_tool_call(self):
        assert _has_override(SampleWrapToolMiddleware(), "awrap_tool_call") is True

    def test_does_not_treat_base_class_definition_as_override(self):
        """A subclass that overrides before_model must NOT report the base-defined
        abefore_model as an override — the base is explicitly skipped in the MRO."""
        assert _has_override(SampleBeforeMiddleware(), "abefore_model") is False


@pytest.mark.unit
class TestMiddlewareExecutorInit:
    def test_empty_middleware_defaults_to_empty_list(self):
        assert MiddlewareExecutor().middleware == []

    def test_none_middleware_coerced_to_empty_list(self):
        assert MiddlewareExecutor(None).middleware == []

    def test_stores_provided_middleware(self):
        mw = SampleBeforeMiddleware()
        executor = MiddlewareExecutor([mw])
        assert executor.middleware == [mw]


@pytest.mark.unit
class TestCreateRuntime:
    def test_create_runtime_returns_runtime_and_forwards_config_store(self):
        """_create_runtime must RETURN the runtime from from_graph_context and
        forward config + store. A `return None` mutation must be caught."""
        executor = MiddlewareExecutor()
        config = make_config()
        store = MagicMock()
        runtime_obj = MagicMock()

        with patch(RT_PATH) as mock_cls:
            mock_cls.from_graph_context.return_value = runtime_obj
            result = executor._create_runtime(config, store)

        assert result is runtime_obj
        mock_cls.from_graph_context.assert_called_once_with(config=config, store=store)

    def test_create_tool_runtime_returns_runtime_and_forwards_tool_name(self):
        """_create_tool_runtime must RETURN the tool runtime and forward
        config + store + tool_name."""
        executor = MiddlewareExecutor()
        config = make_config()
        store = MagicMock()
        runtime_obj = MagicMock()

        with patch(TOOL_RT_PATH) as mock_cls:
            mock_cls.from_graph_context.return_value = runtime_obj
            result = executor._create_tool_runtime(config, store, tool_name="my_tool")

        assert result is runtime_obj
        mock_cls.from_graph_context.assert_called_once_with(
            config=config, store=store, tool_name="my_tool"
        )


@pytest.mark.unit
class TestHasWrapChecks:
    def test_has_wrap_model_call_true_for_async_override(self):
        assert MiddlewareExecutor([SampleWrapModelMiddleware()]).has_wrap_model_call() is True

    def test_has_wrap_model_call_true_for_sync_override(self):
        """The sync `wrap_model_call` name must also be detected (separate branch
        from the async name)."""
        assert MiddlewareExecutor([SampleSyncWrapModelMiddleware()]).has_wrap_model_call() is True

    def test_has_wrap_model_call_false_for_noop(self):
        assert MiddlewareExecutor([NoopMiddleware()]).has_wrap_model_call() is False

    def test_has_wrap_model_call_false_when_empty(self):
        assert MiddlewareExecutor().has_wrap_model_call() is False

    def test_has_wrap_tool_call_true_for_async_override(self):
        assert MiddlewareExecutor([SampleWrapToolMiddleware()]).has_wrap_tool_call() is True

    def test_has_wrap_tool_call_true_for_sync_override(self):
        assert MiddlewareExecutor([SampleSyncWrapToolMiddleware()]).has_wrap_tool_call() is True

    def test_has_wrap_tool_call_false_for_noop(self):
        assert MiddlewareExecutor([NoopMiddleware()]).has_wrap_tool_call() is False


@pytest.mark.unit
class TestExecuteBeforeModel:
    pytestmark = pytest.mark.asyncio

    async def test_returns_same_state_object_when_no_middleware(self):
        executor = MiddlewareExecutor()
        state = make_state()

        result = await executor.execute_before_model(state, make_config())

        assert result is state

    async def test_sync_before_model_result_merged_into_state(self):
        """The sync before_model branch must run and its dict be merged in."""
        executor = MiddlewareExecutor([SampleBeforeMiddleware()])

        with patch(RT_PATH) as mock_rt:
            mock_rt.from_graph_context.return_value = MagicMock()
            result = await executor.execute_before_model(make_state(), make_config())

        assert result["injected_key"] == "before_value"

    async def test_async_abefore_model_preferred_and_merged(self):
        """When a middleware overrides BOTH async and sync, the async hook must be
        chosen, and its result merged into the returned state."""

        class BothBeforeMiddleware(AgentMiddleware):
            async def abefore_model(self, state, runtime):
                return {"chosen": "async"}

            def before_model(self, state, runtime):
                return {"chosen": "sync"}

        executor = MiddlewareExecutor([BothBeforeMiddleware()])

        with patch(RT_PATH) as mock_rt:
            mock_rt.from_graph_context.return_value = MagicMock()
            result = await executor.execute_before_model(make_state(), make_config())

        assert result["chosen"] == "async"

    async def test_none_returning_hook_does_not_merge(self):
        """A hook returning None must NOT crash and must leave state keys intact —
        guards the `if result is not None` branch."""

        class NoneReturningMiddleware(AgentMiddleware):
            def before_model(self, state, runtime):
                return None

        state = make_state(query="keep me")
        executor = MiddlewareExecutor([NoneReturningMiddleware()])

        with patch(RT_PATH) as mock_rt:
            mock_rt.from_graph_context.return_value = MagicMock()
            result = await executor.execute_before_model(state, make_config())

        assert result["query"] == "keep me"

    async def test_raising_middleware_is_swallowed_and_later_runs(self):
        """A raising middleware must be swallowed (logged), and a later middleware
        must still run and merge its result."""

        class ExplodingMiddleware(AgentMiddleware):
            def before_model(self, state, runtime):
                raise RuntimeError("boom")

        executor = MiddlewareExecutor([ExplodingMiddleware(), SampleBeforeMiddleware()])

        with patch(RT_PATH) as mock_rt:
            mock_rt.from_graph_context.return_value = MagicMock()
            result = await executor.execute_before_model(make_state(), make_config())

        assert result["injected_key"] == "before_value"

    async def test_cancelled_error_propagates(self):
        """asyncio.CancelledError must NOT be swallowed — it re-raises."""
        import asyncio

        class CancelMiddleware(AgentMiddleware):
            async def abefore_model(self, state, runtime):
                raise asyncio.CancelledError()

        executor = MiddlewareExecutor([CancelMiddleware()])

        with patch(RT_PATH) as mock_rt:
            mock_rt.from_graph_context.return_value = MagicMock()
            with pytest.raises(asyncio.CancelledError):
                await executor.execute_before_model(make_state(), make_config())

    async def test_noop_middleware_skipped_preserves_keys(self):
        """A Noop middleware hits `continue`; the returned State still carries the
        original keys (and is a freshly built object, not the input)."""
        state = make_state(query="preserved")
        executor = MiddlewareExecutor([NoopMiddleware()])

        with patch(RT_PATH) as mock_rt:
            mock_rt.from_graph_context.return_value = MagicMock()
            result = await executor.execute_before_model(state, make_config())

        assert result["query"] == "preserved"


@pytest.mark.unit
class TestExecuteAfterModel:
    pytestmark = pytest.mark.asyncio

    async def test_returns_same_state_object_when_no_middleware(self):
        executor = MiddlewareExecutor()
        state = make_state()

        result = await executor.execute_after_model(state, make_config())

        assert result is state

    async def test_sync_after_model_result_merged_into_state(self):
        executor = MiddlewareExecutor([SampleAfterMiddleware()])

        with patch(RT_PATH) as mock_rt:
            mock_rt.from_graph_context.return_value = MagicMock()
            result = await executor.execute_after_model(make_state(), make_config())

        assert result["after_key"] == "after_value"

    async def test_async_aafter_model_preferred_and_merged(self):
        class BothAfterMiddleware(AgentMiddleware):
            async def aafter_model(self, state, runtime):
                return {"chosen": "async"}

            def after_model(self, state, runtime):
                return {"chosen": "sync"}

        executor = MiddlewareExecutor([BothAfterMiddleware()])

        with patch(RT_PATH) as mock_rt:
            mock_rt.from_graph_context.return_value = MagicMock()
            result = await executor.execute_after_model(make_state(), make_config())

        assert result["chosen"] == "async"

    async def test_noop_middleware_skipped_preserves_keys(self):
        state = make_state(query="preserved")
        executor = MiddlewareExecutor([NoopMiddleware()])

        with patch(RT_PATH) as mock_rt:
            mock_rt.from_graph_context.return_value = MagicMock()
            result = await executor.execute_after_model(state, make_config())

        assert result["query"] == "preserved"


@pytest.mark.unit
class TestWrapModelInvocation:
    pytestmark = pytest.mark.asyncio

    async def test_invokes_model_and_returns_ai_message(self):
        executor = MiddlewareExecutor([SampleWrapModelMiddleware()])
        expected = AIMessage(content="hello from model")
        invoke_fn = AsyncMock(return_value=expected)

        with (
            patch(RT_PATH) as mock_rt,
            patch(MODEL_REQ_PATH, return_value=_model_req()),
        ):
            mock_rt.from_graph_context.return_value = MagicMock()
            result = await executor.wrap_model_invocation(
                model=MagicMock(),
                state=make_state(),
                config=make_config(),
                store=None,
                tools=[],
                invoke_fn=invoke_fn,
            )

        assert isinstance(result, AIMessage)
        assert result.content == "hello from model"
        invoke_fn.assert_awaited_once()

    async def test_system_message_prepended_before_messages(self):
        """The innermost handler must prepend system_message, then messages, in
        that order, before calling invoke_fn."""
        executor = MiddlewareExecutor([])
        sys_msg = SystemMessage(content="SYS")
        human = HumanMessage(content="hi")
        invoke_fn = AsyncMock(return_value=AIMessage(content="ok"))

        with (
            patch(RT_PATH) as mock_rt,
            patch(
                MODEL_REQ_PATH, return_value=_model_req(system_message=sys_msg, messages=[human])
            ),
        ):
            mock_rt.from_graph_context.return_value = MagicMock()
            await executor.wrap_model_invocation(
                model=MagicMock(),
                state=make_state(),
                config=make_config(),
                store=None,
                tools=[],
                invoke_fn=invoke_fn,
            )

        sent = invoke_fn.await_args.args[0]
        assert sent == [sys_msg, human]

    async def test_two_middleware_wrap_in_first_outermost_order(self):
        """Two middleware must nest correctly: the first listed is outermost.
        Order is mw1.before, mw2.before, handler, mw2.after, mw1.after."""
        call_log: list[str] = []

        def _logger(tag: str):
            class _Mw(AgentMiddleware):
                async def awrap_model_call(self, request, handler):
                    call_log.append(f"{tag}:before")
                    resp = await handler(request)
                    call_log.append(f"{tag}:after")
                    return resp

            return _Mw()

        executor = MiddlewareExecutor([_logger("A"), _logger("B")])
        invoke_fn = AsyncMock(return_value=AIMessage(content="x"))

        with (
            patch(RT_PATH) as mock_rt,
            patch(MODEL_REQ_PATH, return_value=_model_req()),
        ):
            mock_rt.from_graph_context.return_value = MagicMock()
            await executor.wrap_model_invocation(
                model=MagicMock(),
                state=make_state(),
                config=make_config(),
                store=None,
                tools=[],
                invoke_fn=invoke_fn,
            )

        assert call_log == ["A:before", "B:before", "B:after", "A:after"]

    async def test_sync_wrap_model_call_middleware_awaited(self):
        """A sync wrap_model_call returning a coroutine must be awaited so the
        chain still produces the model's AIMessage."""
        executor = MiddlewareExecutor([SampleSyncWrapModelMiddleware()])
        invoke_fn = AsyncMock(return_value=AIMessage(content="model"))

        with (
            patch(RT_PATH) as mock_rt,
            patch(MODEL_REQ_PATH, return_value=_model_req()),
        ):
            mock_rt.from_graph_context.return_value = MagicMock()
            result = await executor.wrap_model_invocation(
                model=MagicMock(),
                state=make_state(),
                config=make_config(),
                store=None,
                tools=[],
                invoke_fn=invoke_fn,
            )

        # The sync wrap branch must have run AND been awaited: it appends "+sync".
        assert result.content == "model+sync"
        invoke_fn.assert_awaited_once()

    async def test_non_ai_message_result_coerced_to_ai_message(self):
        """If middleware returns a ModelResponse whose result[0] is not an
        AIMessage, it is coerced to AIMessage(content=str(.content))."""

        class CoerceMiddleware(AgentMiddleware):
            async def awrap_model_call(self, request, handler):
                fake = HumanMessage(content="raw-content")
                return ModelResponse(result=[fake])

        executor = MiddlewareExecutor([CoerceMiddleware()])
        invoke_fn = AsyncMock(return_value=AIMessage(content="unused"))

        with (
            patch(RT_PATH) as mock_rt,
            patch(MODEL_REQ_PATH, return_value=_model_req()),
        ):
            mock_rt.from_graph_context.return_value = MagicMock()
            result = await executor.wrap_model_invocation(
                model=MagicMock(),
                state=make_state(),
                config=make_config(),
                store=None,
                tools=[],
                invoke_fn=invoke_fn,
            )

        assert isinstance(result, AIMessage)
        assert result.content == "raw-content"

    async def test_empty_result_falls_back_to_direct_invoke(self):
        """An empty ModelResponse.result raises ValueError internally, which the
        except block catches and falls back to direct invoke_fn(state messages)."""

        class EmptyResponseMiddleware(AgentMiddleware):
            async def awrap_model_call(self, request, handler):
                return ModelResponse(result=[])

        fallback = AIMessage(content="fallback")
        invoke_fn = AsyncMock(return_value=fallback)
        executor = MiddlewareExecutor([EmptyResponseMiddleware()])

        with (
            patch(RT_PATH) as mock_rt,
            patch(MODEL_REQ_PATH, return_value=_model_req()),
        ):
            mock_rt.from_graph_context.return_value = MagicMock()
            result = await executor.wrap_model_invocation(
                model=MagicMock(),
                state=make_state(),
                config=make_config(),
                store=None,
                tools=[],
                invoke_fn=invoke_fn,
            )

        assert result is fallback

    async def test_middleware_exception_falls_back_to_direct_invoke(self):
        """A middleware raising mid-chain must be caught and direct invoke used."""

        class ExplodingMiddleware(AgentMiddleware):
            async def awrap_model_call(self, request, handler):
                raise RuntimeError("model middleware exploded")

        fallback = AIMessage(content="direct-model")
        invoke_fn = AsyncMock(return_value=fallback)
        executor = MiddlewareExecutor([ExplodingMiddleware()])

        with (
            patch(RT_PATH) as mock_rt,
            patch(MODEL_REQ_PATH, return_value=_model_req()),
        ):
            mock_rt.from_graph_context.return_value = MagicMock()
            result = await executor.wrap_model_invocation(
                model=MagicMock(),
                state=make_state(),
                config=make_config(),
                store=None,
                tools=[],
                invoke_fn=invoke_fn,
            )

        assert result is fallback


@pytest.mark.unit
class TestWrapToolInvocation:
    pytestmark = pytest.mark.asyncio

    async def test_invokes_tool_and_returns_tool_message(self):
        executor = MiddlewareExecutor([SampleWrapToolMiddleware()])
        tool_call = make_tool_call("my_tool", {"param": "value"})
        expected = ToolMessage(content="tool result", tool_call_id=tool_call["id"])
        invoke_fn = AsyncMock(return_value=expected)
        mock_req = MagicMock()
        mock_req.tool_call = tool_call

        with (
            patch(TOOL_RT_PATH) as mock_rt,
            patch(TOOL_REQ_PATH, return_value=mock_req),
        ):
            mock_rt.from_graph_context.return_value = MagicMock()
            result = await executor.wrap_tool_invocation(
                tool_call=tool_call,
                tool=MagicMock(),
                state=make_state(),
                config=make_config(),
                store=None,
                invoke_fn=invoke_fn,
            )

        assert isinstance(result, ToolMessage)
        assert result.content == "tool result"
        invoke_fn.assert_awaited_once()

    async def test_tool_runtime_created_with_tool_call_name(self):
        """The tool runtime must be built with the tool_call's own name (not a
        constant), so middleware/logging can identify the tool."""
        executor = MiddlewareExecutor([SampleWrapToolMiddleware()])
        tool_call = make_tool_call("search_web", {"q": "x"})
        invoke_fn = AsyncMock(return_value=ToolMessage(content="r", tool_call_id=tool_call["id"]))
        mock_req = MagicMock()
        mock_req.tool_call = tool_call

        with (
            patch(TOOL_RT_PATH) as mock_rt,
            patch(TOOL_REQ_PATH, return_value=mock_req),
        ):
            mock_rt.from_graph_context.return_value = MagicMock()
            await executor.wrap_tool_invocation(
                tool_call=tool_call,
                tool=MagicMock(),
                state=make_state(),
                config=make_config(),
                store=None,
                invoke_fn=invoke_fn,
            )

        assert mock_rt.from_graph_context.call_args.kwargs["tool_name"] == "search_web"

    async def test_missing_name_defaults_to_unknown(self):
        """A tool_call without a name falls back to the literal 'unknown'."""
        executor = MiddlewareExecutor([])
        tool_call = {"args": {}, "id": "call_x"}
        invoke_fn = AsyncMock(return_value=ToolMessage(content="r", tool_call_id="call_x"))
        mock_req = MagicMock()
        mock_req.tool_call = tool_call

        with (
            patch(TOOL_RT_PATH) as mock_rt,
            patch(TOOL_REQ_PATH, return_value=mock_req),
        ):
            mock_rt.from_graph_context.return_value = MagicMock()
            await executor.wrap_tool_invocation(
                tool_call=tool_call,
                tool=None,
                state=make_state(),
                config=make_config(),
                store=None,
                invoke_fn=invoke_fn,
            )

        assert mock_rt.from_graph_context.call_args.kwargs["tool_name"] == "unknown"

    async def test_two_middleware_wrap_in_first_outermost_order(self):
        call_log: list[str] = []

        def _logger(tag: str):
            class _Mw(AgentMiddleware):
                async def awrap_tool_call(self, request, handler):
                    call_log.append(f"{tag}:before")
                    resp = await handler(request)
                    call_log.append(f"{tag}:after")
                    return resp

            return _Mw()

        executor = MiddlewareExecutor([_logger("A"), _logger("B")])
        tool_call = make_tool_call("t", {})
        invoke_fn = AsyncMock(return_value=ToolMessage(content="ok", tool_call_id=tool_call["id"]))
        mock_req = MagicMock()
        mock_req.tool_call = tool_call

        with (
            patch(TOOL_RT_PATH) as mock_rt,
            patch(TOOL_REQ_PATH, return_value=mock_req),
        ):
            mock_rt.from_graph_context.return_value = MagicMock()
            await executor.wrap_tool_invocation(
                tool_call=tool_call,
                tool=MagicMock(),
                state=make_state(),
                config=make_config(),
                store=None,
                invoke_fn=invoke_fn,
            )

        assert call_log == ["A:before", "B:before", "B:after", "A:after"]

    async def test_sync_wrap_tool_call_middleware_awaited(self):
        """A sync wrap_tool_call returning a coroutine must be awaited."""
        executor = MiddlewareExecutor([SampleSyncWrapToolMiddleware()])
        tool_call = make_tool_call("t", {})
        invoke_fn = AsyncMock(
            return_value=ToolMessage(content="tool", tool_call_id=tool_call["id"])
        )
        mock_req = MagicMock()
        mock_req.tool_call = tool_call

        with (
            patch(TOOL_RT_PATH) as mock_rt,
            patch(TOOL_REQ_PATH, return_value=mock_req),
        ):
            mock_rt.from_graph_context.return_value = MagicMock()
            result = await executor.wrap_tool_invocation(
                tool_call=tool_call,
                tool=MagicMock(),
                state=make_state(),
                config=make_config(),
                store=None,
                invoke_fn=invoke_fn,
            )

        # The sync wrap branch must have run AND been awaited: it appends "+sync".
        assert result.content == "tool+sync"
        invoke_fn.assert_awaited_once()

    async def test_middleware_exception_falls_back_to_direct_invoke(self):
        class ExplodingToolMiddleware(AgentMiddleware):
            async def awrap_tool_call(self, request, handler):
                raise RuntimeError("tool middleware exploded")

        executor = MiddlewareExecutor([ExplodingToolMiddleware()])
        tool_call = make_tool_call("exploding_tool")
        fallback = ToolMessage(content="direct result", tool_call_id=tool_call["id"])
        invoke_fn = AsyncMock(return_value=fallback)
        mock_req = MagicMock()
        mock_req.tool_call = tool_call

        with (
            patch(TOOL_RT_PATH) as mock_rt,
            patch(TOOL_REQ_PATH, return_value=mock_req),
        ):
            mock_rt.from_graph_context.return_value = MagicMock()
            result = await executor.wrap_tool_invocation(
                tool_call=tool_call,
                tool=MagicMock(),
                state=make_state(),
                config=make_config(),
                store=None,
                invoke_fn=invoke_fn,
            )

        assert result is fallback
        invoke_fn.assert_awaited_with(tool_call)
