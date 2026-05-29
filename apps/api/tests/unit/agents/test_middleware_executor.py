"""Behavior spec + unit tests for the MiddlewareExecutor.

UNIT: app/agents/middleware/executor.py :: _has_override
EXPECTED: Return True only when a *concrete* subclass of AgentMiddleware (not the
          base, not object) defines `method_name` in its own __dict__; otherwise
          return the literal bool False.
MECHANISM: walk type(mw).__mro__, skip AgentMiddleware and object, return True on
           first class whose __dict__ contains method_name; else `return False`.
MUST-CATCH:
  - a base AgentMiddleware (only NotImplementedError stubs) reports False for every hook
  - a subclass that overrides a sync hook reports True for that hook and False for its async twin
  - a subclass that overrides an async hook reports True for it and False for the sync twin
  - the return value is the bool False (not None) when nothing overrides  [return_none mutant]
  - an unknown method name reports False even on a concrete subclass

UNIT: app/agents/middleware/executor.py :: MiddlewareExecutor.__init__
EXPECTED: store the given middleware list; default to [] for None / omitted.
MECHANISM: self.middleware = middleware or [].
MUST-CATCH: None -> [], omitted -> [], a real list is stored verbatim.

UNIT: app/agents/middleware/executor.py :: MiddlewareExecutor.execute_before_model
EXPECTED: with no middleware return the state unchanged; otherwise run each
          middleware's before/abefore hook in list order, merging every returned
          dict into a fresh State; swallow non-cancel exceptions; re-raise CancelledError.
MECHANISM: if not self.middleware: return state; build runtime; current_state=dict(state);
           per mw -> async hook preferred over sync, skip if neither overrides, update on non-None;
           except CancelledError: raise; except Exception: log.warning; return State(**current_state).
MUST-CATCH:
  - empty middleware returns the SAME object (no rebuild) -> identity preserved
  - sync before_model result dict is merged into returned state
  - async abefore_model result dict is merged into returned state
  - async hook wins when both abefore_model and before_model are overridden
  - a no-op middleware (neither hook overridden) leaves state untouched and is skipped
  - a middleware returning None leaves state untouched
  - middleware run in order: earlier merges visible, later merges win on key clash
  - a middleware raising a normal Exception is swallowed; later middleware still run
  - a middleware raising CancelledError propagates out
  - the original input state is not mutated (a fresh State is returned)

UNIT: app/agents/middleware/executor.py :: MiddlewareExecutor.execute_after_model
EXPECTED / MECHANISM / MUST-CATCH: identical contract to execute_before_model but
          for after/aafter hooks (covered with the parametrized hook-name fixture).

UNIT: app/agents/middleware/executor.py :: MiddlewareExecutor.wrap_model_invocation
EXPECTED: build a real BigtoolRuntime + ModelRequest, wrap the model call with each
          wrap_model_call middleware (first = outermost), invoke innermost handler
          which prepends system_message then sends messages to invoke_fn; coerce the
          first result into an AIMessage; on empty result or any non-cancel error fall
          back to invoke_fn(state["messages"]); re-raise CancelledError.
MECHANISM: runtime=_create_runtime(config,store); request=create_model_request(...);
           final_handler prepends req.system_message then extends req.messages, calls
           invoke_fn, wraps in ModelResponse(result=[response]); chain built in reversed
           order, async hook preferred; execute -> if not result.result raise ValueError
           -> return result[0] if AIMessage else AIMessage(str(content)); except Cancelled
           raise; except Exception -> invoke_fn(state.get("messages", [])).
MUST-CATCH:
  - no middleware: invoke_fn receives system_message + messages, response returned verbatim
  - the innermost handler returns a ModelResponse (not None -> no spurious fallback double-invoke)
  - the runtime handed to middleware is a real BigtoolRuntime carrying the passed config
  - async wrap_model_call can transform the response and that transform is returned
  - sync wrap_model_call is detected and its (awaited) transform is returned
  - middleware ordering: first middleware is outermost (sees the inner result)
  - empty ModelResponse(result=[]) triggers fallback to invoke_fn (distinct payload)
  - a non-AIMessage result[0] is converted to AIMessage via str(content)
  - a chain that raises falls back to invoke_fn called with state["messages"]
  - fallback reads the "messages" key specifically (not a different/empty key)
  - CancelledError from the chain propagates

UNIT: app/agents/middleware/executor.py :: MiddlewareExecutor.wrap_tool_invocation
EXPECTED: build a real BigtoolToolRuntime (carrying tool name from tool_call["name"],
          defaulting to "unknown") + ToolCallRequest, wrap the tool call with each
          wrap_tool_call middleware, innermost handler calls invoke_fn(req.tool_call);
          on any non-cancel error fall back to invoke_fn(tool_call); re-raise CancelledError.
MECHANISM: tool_name=tool_call.get("name","unknown"); runtime=_create_tool_runtime(...,tool_name);
           request=create_tool_call_request(...); chain reversed, async preferred; execute;
           except Cancelled raise; except Exception -> invoke_fn(tool_call).
MUST-CATCH:
  - no middleware: invoke_fn receives req.tool_call, ToolMessage returned verbatim
  - the runtime carries tool_name == tool_call["name"] (not a constant, not "")
  - the runtime tool_name defaults to "unknown" when tool_call has no "name" key
  - async wrap_tool_call transform is returned
  - sync wrap_tool_call is detected and its (awaited) transform is returned
  - a chain that raises falls back to invoke_fn(tool_call) (distinct payload)
  - CancelledError from the chain propagates

UNIT: app/agents/middleware/executor.py :: MiddlewareExecutor.has_wrap_model_call / has_wrap_tool_call
EXPECTED: True iff ANY middleware overrides the sync OR async variant; False otherwise.
MUST-CATCH: sync-only True, async-only True, no-op False, empty list False.

EQUIVALENT MUTANTS (allowed survivors, justified — empirically only `const_str str -> ''`
mutants survive; every compare/boolop/binop/const_int/return_none mutant is killed):
  - docstring `str -> ''` mutants (the module/class/function docstrings, e.g. _has_override
    docstring, _create_runtime/_create_tool_runtime/final_handler docstrings, has_wrap_*
    docstrings): docstrings are not executed; blanking them cannot change behavior.
  - log-message `str -> ''` mutants in log.warning/log.error f-strings
    ("Middleware {...}.before_model failed", ".after_model failed",
     "...wrap_model_call chain failed", "...wrap_tool_call chain failed for {tool_name}"):
    the emitted string is observational only; control flow (swallow/fallback) is unchanged.
    Tests assert the *behavior* (state preserved / fallback taken), never the text.
  - the ValueError message `str -> ''` ("Model middleware returned empty result list"):
    the except clause catches ValueError regardless of its message, so the resulting
    behavior (fallback to invoke_fn) is identical. Tests assert the fallback, not the message.
"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import (
    ModelRequest,
    ModelResponse,
    ToolCallRequest,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
import pytest

from app.agents.middleware.executor import (
    MiddlewareExecutor,
    _has_override,
)
from app.agents.middleware.runtime_adapter import (
    BigtoolRuntime,
    BigtoolToolRuntime,
)
from app.override.langgraph_bigtool.utils import State

# ---------------------------------------------------------------------------
# Helpers — real State / real RunnableConfig; only invoke_fn (the LLM/tool I/O
# boundary) is mocked. The runtime adapters and request builders are exercised
# for real so we can assert the runtime/request they produce.
# ---------------------------------------------------------------------------


def _make_state(**overrides: Any) -> State:
    defaults: dict[str, Any] = {
        "messages": [HumanMessage(content="hello")],
        "selected_tool_ids": [],
        "todos": [],
    }
    defaults.update(overrides)
    return State(**defaults)


def _make_config(**overrides: Any) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "configurable": {"user_id": "user_123", "thread_id": "thread_abc"},
    }
    cfg.update(overrides)
    return cfg


class _NoOp(AgentMiddleware):
    """No overrides — base hooks raise NotImplementedError; executor must skip it."""


# ---------------------------------------------------------------------------
# _has_override
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHasOverride:
    def test_base_middleware_overrides_nothing(self) -> None:
        mw = _NoOp()
        assert _has_override(mw, "before_model") is False
        assert _has_override(mw, "abefore_model") is False
        assert _has_override(mw, "after_model") is False
        assert _has_override(mw, "wrap_model_call") is False
        assert _has_override(mw, "awrap_tool_call") is False

    def test_returns_literal_false_not_none(self) -> None:
        # Kills the `return False -> return None` mutant: a None return would still
        # be falsy but is NOT the bool False the contract promises.
        result = _has_override(_NoOp(), "before_model")
        assert result is False

    def test_sync_override_detected_async_twin_not(self) -> None:
        class _Sync(AgentMiddleware):
            def before_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
                return None

        mw = _Sync()
        assert _has_override(mw, "before_model") is True
        assert _has_override(mw, "abefore_model") is False

    def test_async_override_detected_sync_twin_not(self) -> None:
        class _Async(AgentMiddleware):
            async def abefore_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
                return None

        mw = _Async()
        assert _has_override(mw, "abefore_model") is True
        assert _has_override(mw, "before_model") is False

    def test_unknown_method_on_concrete_subclass_is_false(self) -> None:
        class _Sync(AgentMiddleware):
            def before_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
                return None

        assert _has_override(_Sync(), "method_that_does_not_exist") is False


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInit:
    def test_omitted_defaults_to_empty_list(self) -> None:
        assert MiddlewareExecutor().middleware == []

    def test_none_defaults_to_empty_list(self) -> None:
        assert MiddlewareExecutor(None).middleware == []

    def test_provided_list_is_stored(self) -> None:
        mw = _NoOp()
        executor = MiddlewareExecutor([mw])
        assert executor.middleware == [mw]


# ---------------------------------------------------------------------------
# execute_before_model / execute_after_model — same contract, parametrized by
# the hook method names so each branch is covered once per phase.
# ---------------------------------------------------------------------------

_PHASES = [
    ("execute_before_model", "before_model", "abefore_model"),
    ("execute_after_model", "after_model", "aafter_model"),
]


def _mw_returning(hook: str, *, is_async: bool, payload: dict[str, Any]) -> AgentMiddleware:
    """Build a middleware whose given hook returns `payload`."""
    if is_async:

        async def _ahook(self: Any, state: Any, runtime: Any) -> dict[str, Any]:
            return payload

        return type("_Mw", (AgentMiddleware,), {hook: _ahook})()

    def _hook(self: Any, state: Any, runtime: Any) -> dict[str, Any]:
        return payload

    return type("_Mw", (AgentMiddleware,), {hook: _hook})()


def _mw_raising(hook: str, exc: BaseException) -> AgentMiddleware:
    def _hook(self: Any, state: Any, runtime: Any) -> dict[str, Any]:
        raise exc

    return type("_Mw", (AgentMiddleware,), {hook: _hook})()


def _mw_returning_none(hook: str) -> AgentMiddleware:
    def _hook(self: Any, state: Any, runtime: Any) -> None:
        return None

    return type("_Mw", (AgentMiddleware,), {hook: _hook})()


@pytest.mark.unit
class TestExecuteModelHooks:
    @pytest.mark.parametrize("method,sync_hook,async_hook", _PHASES)
    async def test_no_middleware_returns_same_state_object(
        self, method: str, sync_hook: str, async_hook: str
    ) -> None:
        executor = MiddlewareExecutor([])
        state = _make_state()
        result = await getattr(executor, method)(state, _make_config())
        # No middleware -> early return of the *same* object, not a rebuilt State.
        assert result is state

    @pytest.mark.parametrize("method,sync_hook,async_hook", _PHASES)
    async def test_sync_hook_result_merged(
        self, method: str, sync_hook: str, async_hook: str
    ) -> None:
        mw = _mw_returning(sync_hook, is_async=False, payload={"k": "sync_value"})
        executor = MiddlewareExecutor([mw])
        result = await getattr(executor, method)(_make_state(), _make_config())
        assert result.get("k") == "sync_value"

    @pytest.mark.parametrize("method,sync_hook,async_hook", _PHASES)
    async def test_async_hook_result_merged(
        self, method: str, sync_hook: str, async_hook: str
    ) -> None:
        mw = _mw_returning(async_hook, is_async=True, payload={"k": "async_value"})
        executor = MiddlewareExecutor([mw])
        result = await getattr(executor, method)(_make_state(), _make_config())
        assert result.get("k") == "async_value"

    @pytest.mark.parametrize("method,sync_hook,async_hook", _PHASES)
    async def test_async_hook_wins_when_both_overridden(
        self, method: str, sync_hook: str, async_hook: str
    ) -> None:
        # Async branch is checked first; if it runs, the sync branch must not.
        async def _ahook(self: Any, state: Any, runtime: Any) -> dict[str, Any]:
            return {"winner": "async"}

        def _shook(self: Any, state: Any, runtime: Any) -> dict[str, Any]:
            return {"winner": "sync"}

        mw = type("_Both", (AgentMiddleware,), {async_hook: _ahook, sync_hook: _shook})()
        executor = MiddlewareExecutor([mw])
        result = await getattr(executor, method)(_make_state(), _make_config())
        assert result.get("winner") == "async"

    @pytest.mark.parametrize("method,sync_hook,async_hook", _PHASES)
    async def test_noop_middleware_skipped(
        self, method: str, sync_hook: str, async_hook: str
    ) -> None:
        executor = MiddlewareExecutor([_NoOp()])
        state = _make_state()
        result = await getattr(executor, method)(state, _make_config())
        # Skipped (neither hook overridden) -> no key added, messages preserved.
        assert result["messages"] == state["messages"]
        assert "winner" not in dict(result)

    @pytest.mark.parametrize("method,sync_hook,async_hook", _PHASES)
    async def test_none_result_leaves_state_unchanged(
        self, method: str, sync_hook: str, async_hook: str
    ) -> None:
        mw = _mw_returning_none(sync_hook)
        executor = MiddlewareExecutor([mw])
        state = _make_state(existing="kept")
        result = await getattr(executor, method)(state, _make_config())
        assert result.get("existing") == "kept"

    @pytest.mark.parametrize("method,sync_hook,async_hook", _PHASES)
    async def test_middleware_run_in_order_later_wins(
        self, method: str, sync_hook: str, async_hook: str
    ) -> None:
        first = _mw_returning(sync_hook, is_async=False, payload={"shared": "first", "a": 1})
        second = _mw_returning(sync_hook, is_async=False, payload={"shared": "second", "b": 2})
        executor = MiddlewareExecutor([first, second])
        result = await getattr(executor, method)(_make_state(), _make_config())
        assert result.get("a") == 1
        assert result.get("b") == 2
        # Order matters: the later middleware's value for the shared key wins.
        assert result.get("shared") == "second"

    @pytest.mark.parametrize("method,sync_hook,async_hook", _PHASES)
    async def test_exception_swallowed_and_later_middleware_still_runs(
        self, method: str, sync_hook: str, async_hook: str
    ) -> None:
        boom = _mw_raising(sync_hook, ValueError("boom"))
        good = _mw_returning(sync_hook, is_async=False, payload={"ran": "after_boom"})
        executor = MiddlewareExecutor([boom, good])
        state = _make_state()
        result = await getattr(executor, method)(state, _make_config())
        # Failure swallowed (no raise) AND the next middleware still executed.
        assert result.get("ran") == "after_boom"

    @pytest.mark.parametrize("method,sync_hook,async_hook", _PHASES)
    async def test_cancelled_error_propagates(
        self, method: str, sync_hook: str, async_hook: str
    ) -> None:
        mw = _mw_raising(sync_hook, asyncio.CancelledError())
        executor = MiddlewareExecutor([mw])
        with pytest.raises(asyncio.CancelledError):
            await getattr(executor, method)(_make_state(), _make_config())

    @pytest.mark.parametrize("method,sync_hook,async_hook", _PHASES)
    async def test_input_state_not_mutated(
        self, method: str, sync_hook: str, async_hook: str
    ) -> None:
        mw = _mw_returning(sync_hook, is_async=False, payload={"injected": "x"})
        executor = MiddlewareExecutor([mw])
        state = _make_state()
        result = await getattr(executor, method)(state, _make_config())
        # Result carries the injected key; the original input state does not.
        assert result.get("injected") == "x"
        assert "injected" not in dict(state)


# ---------------------------------------------------------------------------
# wrap_model_invocation
# ---------------------------------------------------------------------------


# invoke_fn whose payload depends on its argument so we can tell apart:
#   - the wrapped/chain path (passes [system?, *messages])
#   - the fallback path (passes state["messages"])
def _content_reporting_invoke_fn() -> AsyncMock:
    async def _fn(messages: list) -> AIMessage:
        contents = ",".join(getattr(m, "content", str(m)) for m in messages)
        return AIMessage(content=f"invoked:{contents}")

    return AsyncMock(side_effect=_fn)


@pytest.mark.unit
class TestWrapModelInvocation:
    async def test_no_middleware_prepends_system_and_returns_model_response(self) -> None:
        model = MagicMock(spec=BaseChatModel)
        invoke_fn = _content_reporting_invoke_fn()
        state = _make_state(messages=[SystemMessage(content="sys"), HumanMessage(content="hi")])
        executor = MiddlewareExecutor([])
        result = await executor.wrap_model_invocation(
            model, state, _make_config(), None, [], invoke_fn
        )
        # final_handler must send system_message first, then the messages.
        assert result.content == "invoked:sys,hi"

    async def test_no_middleware_returns_response_without_falling_back(self) -> None:
        # The innermost handler must wrap the model response in ModelResponse(result=[...])
        # and return it. If it returns None, the chain raises (None.result) and falls back
        # to a SECOND invoke_fn call. A per-call counter makes that double-invoke visible.
        call_contents: list[str] = []

        async def _fn(messages: list) -> AIMessage:
            content = f"call_{len(call_contents)}"
            call_contents.append(content)
            return AIMessage(content=content)

        model = MagicMock(spec=BaseChatModel)
        invoke_fn = AsyncMock(side_effect=_fn)
        executor = MiddlewareExecutor([])
        result = await executor.wrap_model_invocation(
            model, _make_state(), _make_config(), None, [], invoke_fn
        )
        # Exactly one invocation occurred (the result of the first), proving the handler
        # returned a usable ModelResponse instead of None+fallback.
        assert result.content == "call_0"
        assert invoke_fn.call_count == 1

    async def test_runtime_is_real_bigtool_runtime_with_config(self) -> None:
        captured: dict[str, Any] = {}

        class _Capture(AgentMiddleware):
            async def awrap_model_call(self, request: ModelRequest, handler: Any) -> ModelResponse:
                captured["runtime"] = request.runtime
                captured["system"] = request.system_message
                return await handler(request)

        model = MagicMock(spec=BaseChatModel)
        invoke_fn = AsyncMock(return_value=AIMessage(content="ok"))
        cfg = _make_config()
        state = _make_state(messages=[SystemMessage(content="S"), HumanMessage(content="hi")])
        executor = MiddlewareExecutor([_Capture()])
        result = await executor.wrap_model_invocation(model, state, cfg, None, [], invoke_fn)
        assert result.content == "ok"
        assert isinstance(captured["runtime"], BigtoolRuntime)
        assert captured["runtime"].config is cfg
        # create_model_request extracted the SystemMessage off the message list.
        assert captured["system"].content == "S"

    async def test_async_wrap_transforms_response(self) -> None:
        class _Transform(AgentMiddleware):
            async def awrap_model_call(self, request: ModelRequest, handler: Any) -> ModelResponse:
                await handler(request)
                return ModelResponse(result=[AIMessage(content="ASYNC_WRAPPED")])

        model = MagicMock(spec=BaseChatModel)
        # invoke_fn returns a DIFFERENT payload, so a broken chain (fallback) is detectable.
        invoke_fn = AsyncMock(return_value=AIMessage(content="raw_model"))
        executor = MiddlewareExecutor([_Transform()])
        result = await executor.wrap_model_invocation(
            model, _make_state(), _make_config(), None, [], invoke_fn
        )
        assert result.content == "ASYNC_WRAPPED"

    async def test_sync_wrap_transforms_response(self) -> None:
        class _SyncTransform(AgentMiddleware):
            def wrap_model_call(self, request: ModelRequest, handler: Any) -> Any:
                async def _run() -> ModelResponse:
                    await handler(request)
                    return ModelResponse(result=[AIMessage(content="SYNC_WRAPPED")])

                return _run()

        model = MagicMock(spec=BaseChatModel)
        invoke_fn = AsyncMock(return_value=AIMessage(content="raw_model"))
        executor = MiddlewareExecutor([_SyncTransform()])
        result = await executor.wrap_model_invocation(
            model, _make_state(), _make_config(), None, [], invoke_fn
        )
        # If sync detection / sync-wrapper return were broken, content would be the
        # fallback "raw_model"; the working sync path yields the transform.
        assert result.content == "SYNC_WRAPPED"

    async def test_first_middleware_is_outermost(self) -> None:
        order: list[str] = []

        class _Outer(AgentMiddleware):
            async def awrap_model_call(self, request: ModelRequest, handler: Any) -> ModelResponse:
                order.append("outer_enter")
                resp = await handler(request)
                order.append("outer_exit")
                return resp

        class _Inner(AgentMiddleware):
            async def awrap_model_call(self, request: ModelRequest, handler: Any) -> ModelResponse:
                order.append("inner_enter")
                resp = await handler(request)
                order.append("inner_exit")
                return resp

        model = MagicMock(spec=BaseChatModel)
        invoke_fn = AsyncMock(return_value=AIMessage(content="x"))
        executor = MiddlewareExecutor([_Outer(), _Inner()])
        await executor.wrap_model_invocation(
            model, _make_state(), _make_config(), None, [], invoke_fn
        )
        # First middleware in the list wraps the second: outer enters first, exits last.
        assert order == ["outer_enter", "inner_enter", "inner_exit", "outer_exit"]

    async def test_empty_result_falls_back_to_invoke_fn(self) -> None:
        class _Empty(AgentMiddleware):
            async def awrap_model_call(self, request: ModelRequest, handler: Any) -> ModelResponse:
                return ModelResponse(result=[])

        model = MagicMock(spec=BaseChatModel)
        invoke_fn = AsyncMock(return_value=AIMessage(content="FALLBACK"))
        executor = MiddlewareExecutor([_Empty()])
        result = await executor.wrap_model_invocation(
            model, _make_state(), _make_config(), None, [], invoke_fn
        )
        assert result.content == "FALLBACK"

    async def test_non_ai_message_result_coerced_via_str(self) -> None:
        class _NonAI(AgentMiddleware):
            async def awrap_model_call(self, request: ModelRequest, handler: Any) -> ModelResponse:
                fake = MagicMock()
                fake.content = "plain text"
                return ModelResponse(result=[fake])

        model = MagicMock(spec=BaseChatModel)
        invoke_fn = AsyncMock(return_value=AIMessage(content="unused"))
        executor = MiddlewareExecutor([_NonAI()])
        result = await executor.wrap_model_invocation(
            model, _make_state(), _make_config(), None, [], invoke_fn
        )
        assert isinstance(result, AIMessage)
        assert result.content == "plain text"

    async def test_chain_failure_falls_back_with_state_messages(self) -> None:
        class _Boom(AgentMiddleware):
            async def awrap_model_call(self, request: ModelRequest, handler: Any) -> ModelResponse:
                raise RuntimeError("chain failed")

        model = MagicMock(spec=BaseChatModel)
        invoke_fn = _content_reporting_invoke_fn()
        # Distinct messages on state so we can prove the fallback reads state["messages"].
        state = _make_state(messages=[HumanMessage(content="state_msg")])
        executor = MiddlewareExecutor([_Boom()])
        result = await executor.wrap_model_invocation(
            model, state, _make_config(), None, [], invoke_fn
        )
        # Fallback invokes invoke_fn(state.get("messages", [])) — the "messages" key
        # specifically (kills the `"messages" -> ''` const_str mutant, which would
        # default to []).
        assert result.content == "invoked:state_msg"

    async def test_cancelled_error_propagates(self) -> None:
        class _Cancel(AgentMiddleware):
            async def awrap_model_call(self, request: ModelRequest, handler: Any) -> ModelResponse:
                raise asyncio.CancelledError()

        model = MagicMock(spec=BaseChatModel)
        invoke_fn = AsyncMock(return_value=AIMessage(content="never"))
        executor = MiddlewareExecutor([_Cancel()])
        with pytest.raises(asyncio.CancelledError):
            await executor.wrap_model_invocation(
                model, _make_state(), _make_config(), None, [], invoke_fn
            )


# ---------------------------------------------------------------------------
# wrap_tool_invocation
# ---------------------------------------------------------------------------


def _tool_call(name: str = "search", call_id: str = "call_1") -> dict[str, Any]:
    return {"name": name, "args": {"q": "x"}, "id": call_id}


@pytest.mark.unit
class TestWrapToolInvocation:
    async def test_no_middleware_invokes_tool_with_request_tool_call(self) -> None:
        captured: dict[str, Any] = {}

        async def _fn(tc: Any) -> ToolMessage:
            captured["tc"] = tc
            return ToolMessage(content="tool_ok", tool_call_id=tc["id"])

        invoke_fn = AsyncMock(side_effect=_fn)
        tc = _tool_call()
        executor = MiddlewareExecutor([])
        result = await executor.wrap_tool_invocation(
            tc, None, _make_state(), _make_config(), None, invoke_fn
        )
        assert result.content == "tool_ok"
        # innermost handler passes req.tool_call (built by create_tool_call_request).
        assert captured["tc"]["name"] == "search"
        assert captured["tc"]["id"] == "call_1"

    async def test_runtime_carries_tool_name_from_tool_call(self) -> None:
        captured: dict[str, Any] = {}

        class _Capture(AgentMiddleware):
            async def awrap_tool_call(self, request: ToolCallRequest, handler: Any) -> ToolMessage:
                captured["runtime"] = request.runtime
                return await handler(request)

        invoke_fn = AsyncMock(return_value=ToolMessage(content="x", tool_call_id="call_1"))
        tc = _tool_call(name="weather_tool")
        executor = MiddlewareExecutor([_Capture()])
        await executor.wrap_tool_invocation(
            tc, None, _make_state(), _make_config(), None, invoke_fn
        )
        assert isinstance(captured["runtime"], BigtoolToolRuntime)
        # tool_name comes from tool_call["name"], not a constant or "".
        assert captured["runtime"].tool_name == "weather_tool"

    async def test_runtime_tool_name_defaults_to_unknown_when_missing(self) -> None:
        captured: dict[str, Any] = {}

        class _Capture(AgentMiddleware):
            async def awrap_tool_call(self, request: ToolCallRequest, handler: Any) -> ToolMessage:
                captured["runtime"] = request.runtime
                return await handler(request)

        # tool_call with NO "name" key -> the .get default "unknown" must be used.
        tc: dict[str, Any] = {"args": {}, "id": "call_x"}
        invoke_fn = AsyncMock(return_value=ToolMessage(content="x", tool_call_id="call_x"))
        executor = MiddlewareExecutor([_Capture()])
        await executor.wrap_tool_invocation(
            tc, None, _make_state(), _make_config(), None, invoke_fn
        )
        assert captured["runtime"].tool_name == "unknown"

    async def test_async_wrap_transforms_result(self) -> None:
        class _Transform(AgentMiddleware):
            async def awrap_tool_call(self, request: ToolCallRequest, handler: Any) -> ToolMessage:
                await handler(request)
                return ToolMessage(content="ASYNC_TOOL", tool_call_id="call_1")

        invoke_fn = AsyncMock(return_value=ToolMessage(content="raw", tool_call_id="call_1"))
        executor = MiddlewareExecutor([_Transform()])
        result = await executor.wrap_tool_invocation(
            _tool_call(), None, _make_state(), _make_config(), None, invoke_fn
        )
        assert result.content == "ASYNC_TOOL"

    async def test_sync_wrap_transforms_result(self) -> None:
        class _SyncTransform(AgentMiddleware):
            def wrap_tool_call(self, request: ToolCallRequest, handler: Any) -> Any:
                async def _run() -> ToolMessage:
                    await handler(request)
                    return ToolMessage(content="SYNC_TOOL", tool_call_id="call_1")

                return _run()

        invoke_fn = AsyncMock(return_value=ToolMessage(content="raw", tool_call_id="call_1"))
        executor = MiddlewareExecutor([_SyncTransform()])
        result = await executor.wrap_tool_invocation(
            _tool_call(), None, _make_state(), _make_config(), None, invoke_fn
        )
        # Broken sync detection/return would yield the fallback "raw".
        assert result.content == "SYNC_TOOL"

    async def test_chain_failure_falls_back_to_invoke_fn(self) -> None:
        class _Boom(AgentMiddleware):
            async def awrap_tool_call(self, request: ToolCallRequest, handler: Any) -> ToolMessage:
                raise RuntimeError("tool chain failed")

        invoke_fn = AsyncMock(return_value=ToolMessage(content="FALLBACK", tool_call_id="call_1"))
        executor = MiddlewareExecutor([_Boom()])
        result = await executor.wrap_tool_invocation(
            _tool_call(), None, _make_state(), _make_config(), None, invoke_fn
        )
        assert result.content == "FALLBACK"

    async def test_cancelled_error_propagates(self) -> None:
        class _Cancel(AgentMiddleware):
            async def awrap_tool_call(self, request: ToolCallRequest, handler: Any) -> ToolMessage:
                raise asyncio.CancelledError()

        invoke_fn = AsyncMock(return_value=ToolMessage(content="never", tool_call_id="call_1"))
        executor = MiddlewareExecutor([_Cancel()])
        with pytest.raises(asyncio.CancelledError):
            await executor.wrap_tool_invocation(
                _tool_call(), None, _make_state(), _make_config(), None, invoke_fn
            )


# ---------------------------------------------------------------------------
# has_wrap_model_call / has_wrap_tool_call
# ---------------------------------------------------------------------------


class _AsyncWrapModel(AgentMiddleware):
    async def awrap_model_call(self, request: ModelRequest, handler: Any) -> ModelResponse:
        return await handler(request)


class _SyncWrapModel(AgentMiddleware):
    def wrap_model_call(self, request: ModelRequest, handler: Any) -> Any:
        return handler(request)


class _AsyncWrapTool(AgentMiddleware):
    async def awrap_tool_call(self, request: ToolCallRequest, handler: Any) -> ToolMessage:
        return await handler(request)


class _SyncWrapTool(AgentMiddleware):
    def wrap_tool_call(self, request: ToolCallRequest, handler: Any) -> Any:
        return handler(request)


@pytest.mark.unit
class TestHasWrapMethods:
    def test_has_wrap_model_call_async(self) -> None:
        assert MiddlewareExecutor([_AsyncWrapModel()]).has_wrap_model_call() is True

    def test_has_wrap_model_call_sync(self) -> None:
        assert MiddlewareExecutor([_SyncWrapModel()]).has_wrap_model_call() is True

    def test_has_wrap_model_call_false_for_noop(self) -> None:
        assert MiddlewareExecutor([_NoOp()]).has_wrap_model_call() is False

    def test_has_wrap_tool_call_async(self) -> None:
        assert MiddlewareExecutor([_AsyncWrapTool()]).has_wrap_tool_call() is True

    def test_has_wrap_tool_call_sync(self) -> None:
        assert MiddlewareExecutor([_SyncWrapTool()]).has_wrap_tool_call() is True

    def test_has_wrap_tool_call_false_for_noop(self) -> None:
        assert MiddlewareExecutor([_NoOp()]).has_wrap_tool_call() is False

    def test_empty_middleware_has_neither(self) -> None:
        executor = MiddlewareExecutor([])
        assert executor.has_wrap_model_call() is False
        assert executor.has_wrap_tool_call() is False
