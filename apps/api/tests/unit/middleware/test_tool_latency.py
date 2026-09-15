"""Unit tests for per-tool-call latency spans (Task 7)."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import ToolMessage
from langgraph.errors import GraphBubbleUp
from prometheus_client import REGISTRY
import pytest

from app.agents.middleware.executor import MiddlewareExecutor, _tool_metric_name


def _count(tool_name: str, status: str) -> float:
    return (
        REGISTRY.get_sample_value(
            "tool_call_seconds_count", {"tool_name": tool_name, "status": status}
        )
        or 0.0
    )


def _sum(tool_name: str, status: str) -> float:
    return (
        REGISTRY.get_sample_value(
            "tool_call_seconds_sum", {"tool_name": tool_name, "status": status}
        )
        or 0.0
    )


class _RegularTool:
    """A non-MCP tool: no ``tool_connector``, so it keeps its own name."""


class _McpTool:
    tool_connector = object()


def test_metric_name_keeps_a_regular_tools_own_name() -> None:
    # ``or`` instead of ``and`` would collapse EVERY non-None tool to "mcp".
    assert _tool_metric_name("web_search", _RegularTool()) == "web_search"


def test_metric_name_collapses_an_mcp_tool() -> None:
    assert _tool_metric_name("user_defined_thing", _McpTool()) == "mcp"


def test_metric_name_falls_back_to_unknown_without_a_name() -> None:
    assert _tool_metric_name("", None) == "unknown"


async def _invoke(
    executor: MiddlewareExecutor,
    tool_call: dict[str, Any],
    tool: Any,
    invoke_fn: Any,
) -> Any:
    state = {"messages": []}
    config: dict[str, Any] = {"configurable": {"user_id": "user-1"}}
    with (
        patch("app.agents.middleware.executor.create_tool_call_request"),
        patch(
            "app.agents.middleware.executor.BigtoolToolRuntime.from_graph_context",
            return_value=MagicMock(),
        ),
        patch("app.agents.middleware.executor.capture_event"),
    ):
        return await executor.wrap_tool_invocation(tool_call, tool, state, config, None, invoke_fn)


async def test_successful_call_observes_tool_span() -> None:
    before = _count("lat-tool-ok", "success")
    invoke_fn = AsyncMock(return_value=ToolMessage(content="ok", tool_call_id="c1"))
    result = await _invoke(
        MiddlewareExecutor([]), {"name": "lat-tool-ok", "args": {}, "id": "c1"}, None, invoke_fn
    )
    assert result.content == "ok"
    assert _count("lat-tool-ok", "success") == before + 1


async def test_failing_call_observes_error_span() -> None:
    before = _count("lat-tool-bad", "error")
    invoke_fn = AsyncMock(side_effect=RuntimeError("tool exploded"))
    with pytest.raises(RuntimeError, match="tool exploded"):
        await _invoke(
            MiddlewareExecutor([]),
            {"name": "lat-tool-bad", "args": {}, "id": "c1"},
            None,
            invoke_fn,
        )
    assert _count("lat-tool-bad", "error") == before + 1


async def test_mcp_tool_collapses_to_mcp_label() -> None:
    """User-defined MCP server tool names are unbounded cardinality — the
    collector sees ``mcp`` while the wide event keeps the real name."""
    before = _count("mcp", "success")
    mcp_tool = MagicMock()
    mcp_tool.tool_connector = MagicMock()
    invoke_fn = AsyncMock(return_value=ToolMessage(content="ok", tool_call_id="c1"))
    await _invoke(
        MiddlewareExecutor([]),
        {"name": "lat-user-defined-tool", "args": {}, "id": "c1"},
        mcp_tool,
        invoke_fn,
    )
    assert _count("mcp", "success") == before + 1
    assert _count("lat-user-defined-tool", "success") == 0.0


async def test_successful_call_records_exact_seconds() -> None:
    # Pinned clock: the recorded sample must be the elapsed subtraction in
    # SECONDS. A sign error (end + start) would record 20.25 here.
    labels = {"tool_name": "lat-tool-exact", "status": "success"}
    before = _sum("lat-tool-exact", "success")
    invoke_fn = AsyncMock(return_value=ToolMessage(content="ok", tool_call_id="c1"))
    with patch("app.agents.middleware.executor.time.perf_counter", side_effect=[10.0, 10.25]):
        await _invoke(
            MiddlewareExecutor([]),
            {"name": "lat-tool-exact", "args": {}, "id": "c1"},
            None,
            invoke_fn,
        )
    assert REGISTRY.get_sample_value("tool_call_seconds_sum", labels) == before + 0.25


async def test_failing_call_records_exact_seconds() -> None:
    labels = {"tool_name": "lat-tool-exact-bad", "status": "error"}
    before = _sum("lat-tool-exact-bad", "error")
    invoke_fn = AsyncMock(side_effect=RuntimeError("tool exploded"))
    with (
        patch("app.agents.middleware.executor.time.perf_counter", side_effect=[5.0, 5.5]),
        pytest.raises(RuntimeError, match="tool exploded"),
    ):
        await _invoke(
            MiddlewareExecutor([]),
            {"name": "lat-tool-exact-bad", "args": {}, "id": "c1"},
            None,
            invoke_fn,
        )
    assert REGISTRY.get_sample_value("tool_call_seconds_sum", labels) == before + 0.5
    # The tool already ran once: the fallback must re-raise, not run it again.
    invoke_fn.assert_awaited_once()


async def test_hil_pause_is_neither_success_nor_error() -> None:
    """A gate interrupt is control flow, not a result: it propagates and
    leaves nospan — the pause is measured as HIL wait, not tool time."""
    from langchain.agents.middleware import AgentMiddleware
    from langchain.agents.middleware.types import ToolCallRequest

    class _Gate(AgentMiddleware):  # type: ignore[type-arg] -- test double uses the unparameterized middleware base
        async def awrap_tool_call(self, request: ToolCallRequest, handler: Any) -> Any:
            raise GraphBubbleUp("paused")

    for status in ("success", "error"):
        before = _count("lat-tool-gated", status)
        with pytest.raises(GraphBubbleUp):
            await _invoke(
                MiddlewareExecutor([_Gate()]),
                {"name": "lat-tool-gated", "args": {}, "id": "c1"},
                None,
                AsyncMock(),
            )
        assert _count("lat-tool-gated", status) == before


async def test_middleware_chain_routes_through_each_wrapper() -> None:
    """The chain is built by wrapping each middleware around the inner handler:
    a wrapper wired to None (or a None seed) must route through the middleware,
    not silently fall back to a direct tool call."""
    from langchain.agents.middleware import AgentMiddleware
    from langchain.agents.middleware.types import ToolCallRequest

    seen: list[str] = []

    class _Recorder(AgentMiddleware):  # type: ignore[type-arg] -- test double uses the unparameterized middleware base
        async def awrap_tool_call(self, request: ToolCallRequest, handler: Any) -> Any:
            seen.append("async")
            return await handler(request)

    class _SyncRecorder(AgentMiddleware):  # type: ignore[type-arg] -- test double uses the unparameterized middleware base
        def wrap_tool_call(self, request: ToolCallRequest, handler: Any) -> Any:
            seen.append("sync")

            # A sync hook may hand back a coroutine for the bridge to await —
            # transform inside it so the result provably flowed through here.
            async def _transform() -> Any:
                result = await handler(request)
                return ToolMessage(content=f"{result.content}[sync]", tool_call_id="c1")

            return _transform()

    invoke_fn = AsyncMock(return_value=ToolMessage(content="ok", tool_call_id="c1"))
    result = await _invoke(
        MiddlewareExecutor([_Recorder(), _SyncRecorder()]),
        {"name": "lat-tool-chained", "args": {}, "id": "c1"},
        None,
        invoke_fn,
    )
    # The transform proves the result flowed through both wrappers: the
    # direct-invocation fallback returns the raw tool result untouched.
    assert result.content == "ok[sync]"
    assert seen == ["async", "sync"]
    invoke_fn.assert_awaited_once()


async def test_pre_tool_failure_falls_back_with_the_original_call() -> None:
    """A middleware that breaks before the tool runs is retried directly — and
    the retry must carry the original tool_call, not a nulled one."""
    from langchain.agents.middleware import AgentMiddleware
    from langchain.agents.middleware.types import ToolCallRequest

    class _PreToolBreak(AgentMiddleware):  # type: ignore[type-arg] -- test double uses the unparameterized middleware base
        async def awrap_tool_call(self, request: ToolCallRequest, handler: Any) -> Any:
            raise RuntimeError("pre-tool middleware broke")

    tool_call = {"name": "lat-tool-fallback", "args": {"q": 1}, "id": "c9"}
    invoke_fn = AsyncMock(return_value=ToolMessage(content="recovered", tool_call_id="c9"))
    result = await _invoke(MiddlewareExecutor([_PreToolBreak()]), tool_call, None, invoke_fn)

    assert result.content == "recovered"
    invoke_fn.assert_awaited_once_with(tool_call)


async def test_pre_tool_break_then_direct_invoke_failure_records_exact_error_seconds() -> None:
    """Pre-tool middleware breaks AND the direct-invoke retry also fails: the
    error span is the elapsed subtraction in seconds (a sign error records 14.5)."""
    from langchain.agents.middleware import AgentMiddleware
    from langchain.agents.middleware.types import ToolCallRequest

    class _PreToolBreak(AgentMiddleware):  # type: ignore[type-arg] -- test double uses the unparameterized middleware base
        async def awrap_tool_call(self, request: ToolCallRequest, handler: Any) -> Any:
            raise RuntimeError("pre-tool middleware broke")

    labels = {"tool_name": "lat-tool-double-fail", "status": "error"}
    before = _sum("lat-tool-double-fail", "error")
    invoke_fn = AsyncMock(side_effect=RuntimeError("tool exploded"))
    with (
        patch("app.agents.middleware.executor.time.perf_counter", side_effect=[7.0, 7.5]),
        pytest.raises(RuntimeError, match="tool exploded"),
    ):
        await _invoke(
            MiddlewareExecutor([_PreToolBreak()]),
            {"name": "lat-tool-double-fail", "args": {}, "id": "c1"},
            None,
            invoke_fn,
        )
    assert REGISTRY.get_sample_value("tool_call_seconds_sum", labels) == before + 0.5
    invoke_fn.assert_awaited_once()


async def test_post_tool_middleware_failure_still_records_success() -> None:
    """A middleware that breaks AFTER the tool ran and succeeded is a successful
    tool call: the status label reflects the tool's outcome, not the
    middleware's. Recording it as an error inflated the tool error rate while the
    tool's success went uncounted."""
    from langchain.agents.middleware import AgentMiddleware
    from langchain.agents.middleware.types import ToolCallRequest

    class _PostToolBreak(AgentMiddleware):  # type: ignore[type-arg] -- test double uses the unparameterized middleware base
        async def awrap_tool_call(self, request: ToolCallRequest, handler: Any) -> Any:
            await handler(request)  # the tool runs and succeeds here
            raise RuntimeError("post-tool middleware broke")

    ok_before = _count("lat-tool-post", "success")
    err_before = _count("lat-tool-post", "error")
    invoke_fn = AsyncMock(return_value=ToolMessage(content="shipped", tool_call_id="c1"))
    result = await _invoke(
        MiddlewareExecutor([_PostToolBreak()]),
        {"name": "lat-tool-post", "args": {}, "id": "c1"},
        None,
        invoke_fn,
    )

    # The raw tool result is shipped (re-invoking would double its side effects).
    assert result.content == "shipped"
    assert _count("lat-tool-post", "success") == ok_before + 1
    assert _count("lat-tool-post", "error") == err_before
    invoke_fn.assert_awaited_once()


async def test_pre_tool_failure_records_success_when_the_direct_invoke_succeeds() -> None:
    """A pre-tool middleware breaks, the tool never ran, the direct fallback runs
    it and it succeeds — that is a successful tool call, not an error."""
    from langchain.agents.middleware import AgentMiddleware
    from langchain.agents.middleware.types import ToolCallRequest

    class _PreToolBreak(AgentMiddleware):  # type: ignore[type-arg] -- test double uses the unparameterized middleware base
        async def awrap_tool_call(self, request: ToolCallRequest, handler: Any) -> Any:
            raise RuntimeError("pre-tool middleware broke")

    ok_before = _count("lat-tool-pre-ok", "success")
    err_before = _count("lat-tool-pre-ok", "error")
    invoke_fn = AsyncMock(return_value=ToolMessage(content="recovered", tool_call_id="c1"))
    await _invoke(
        MiddlewareExecutor([_PreToolBreak()]),
        {"name": "lat-tool-pre-ok", "args": {}, "id": "c1"},
        None,
        invoke_fn,
    )

    assert _count("lat-tool-pre-ok", "success") == ok_before + 1
    assert _count("lat-tool-pre-ok", "error") == err_before


async def test_pre_tool_failure_records_error_when_the_direct_invoke_also_fails() -> None:
    """The tool genuinely never produced a result — a real error span, and the
    failure propagates."""
    from langchain.agents.middleware import AgentMiddleware
    from langchain.agents.middleware.types import ToolCallRequest

    class _PreToolBreak(AgentMiddleware):  # type: ignore[type-arg] -- test double uses the unparameterized middleware base
        async def awrap_tool_call(self, request: ToolCallRequest, handler: Any) -> Any:
            raise RuntimeError("pre-tool middleware broke")

    ok_before = _count("lat-tool-pre-bad", "success")
    err_before = _count("lat-tool-pre-bad", "error")
    invoke_fn = AsyncMock(side_effect=RuntimeError("tool also exploded"))
    with pytest.raises(RuntimeError, match="tool also exploded"):
        await _invoke(
            MiddlewareExecutor([_PreToolBreak()]),
            {"name": "lat-tool-pre-bad", "args": {}, "id": "c1"},
            None,
            invoke_fn,
        )

    assert _count("lat-tool-pre-bad", "error") == err_before + 1
    assert _count("lat-tool-pre-bad", "success") == ok_before
