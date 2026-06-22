"""
MCP Utility Functions.

Contains helper functions for MCP client operations including
PKCE generation, tool wrapping, and schema handling.
"""

from collections.abc import Awaitable, Callable, Iterable
from functools import wraps
import inspect
from typing import Any

from langchain_core.tools import BaseTool

from shared.py.wide_events import log


def canonical_tool_name_map(names: Iterable[str]) -> dict[str, str]:
    """Map underscore-canonical → original tool name.

    MCP tools keep their original (often hyphenated) names because the
    upstream server expects them, but LLMs commonly echo them with
    underscores. Use the returned map to recover the canonical name when an
    LLM call misses the strict bound-set membership check.
    """
    return {n.replace("-", "_"): n for n in names}


_CONNECTION_ERROR_PATTERNS = (
    "timeout",
    "connection reset",
    "connection reset by peer",
    "broken pipe",
    "unexpected eof",
    "eof error",
    "eoferror",
    "connection refused",
    "connection closed",
    "server disconnected",
    "connect call failed",
    "network unreachable",
    "no route to host",
    "not connected",
    "session closed",
    "session expired",
    "ssl",
    "certificate",
)


def wrap_tool_with_null_filter(
    tool: BaseTool,
    on_connection_error: Callable[[], None] | None = None,
    reconnect_and_retry: Callable[[str, dict], Awaitable[Any]] | None = None,
) -> BaseTool:
    """Wrap a LangChain MCP tool with null-arg filtering and transparent reconnect.

    Three behaviors:
    1. Filter `None`-valued args before calling the underlying tool (MCP servers
       reject `null` for optional fields; they want them omitted).
    2. On a connection-loss OR 401/unauthorized error (both mean a dead/expired
       session), evict the stale session via `on_connection_error` and — if
       `reconnect_and_retry` is provided — rebuild the connector (refreshing the
       token) and retry once. A 401 that survives the refresh is re-raised so the
       user can re-authenticate.

    The underlying tool's `_arun` is stashed on the wrapped tool as `_original_arun`
    so the reconnect path can bypass this wrapper when invoking the fresh tool
    (otherwise a second failure would recurse).
    """
    # mcp_use's McpToLangChainAdapter sets handle_tool_error=True by default,
    # which swallows exceptions and returns a formatted error string. That
    # hides connection-loss errors from our wrapper — we'd never see the
    # exception, just a result string we couldn't react to. Flip it off so
    # the inner _arun re-raises and we can run the reconnect path.
    if hasattr(tool, "handle_tool_error"):
        tool.handle_tool_error = False

    original_arun = tool._arun

    @wraps(original_arun)
    async def filtered_arun(**kwargs: Any) -> Any:
        filtered_kwargs = {k: v for k, v in kwargs.items() if v is not None}
        log.set(operation="mcp_tool_call", tool_name=tool.name)
        log.debug(f"MCP tool '{tool.name}': original args={kwargs}, filtered={filtered_kwargs}")
        try:
            return await original_arun(**filtered_kwargs)
        except Exception as e:
            error_msg = str(e)
            error_lower = error_msg.lower()
            log.error(f"MCP tool '{tool.name}' failed: {error_msg}")

            is_auth_error = "401" in error_msg or "unauthorized" in error_lower
            is_connection_error = any(pat in error_lower for pat in _CONNECTION_ERROR_PATTERNS)

            # A dropped session surfaces as a connection error OR a 401 (the vendored
            # client reconnects in place with a now-expired token). Both heal the same
            # way: evict + reconnect, which refreshes the token. Try once.
            if is_auth_error or is_connection_error:
                if on_connection_error:
                    if inspect.iscoroutinefunction(on_connection_error):
                        raise TypeError(
                            "on_connection_error must be a synchronous callable, not a coroutine function"
                        )
                    log.warning(f"MCP tool '{tool.name}' session error, evicting session")
                    on_connection_error()

                if reconnect_and_retry:
                    try:
                        log.warning(
                            f"MCP tool '{tool.name}' attempting transparent reconnect-and-retry"
                        )
                        return await reconnect_and_retry(tool.name, filtered_kwargs)
                    except Exception as retry_err:
                        log.error(
                            f"MCP tool '{tool.name}' reconnect-retry failed: "
                            f"{type(retry_err).__name__}: {retry_err}"
                        )
                        # A 401 that survives a fresh token = server rejecting a valid
                        # token; surface it so the user can re-authenticate.
                        if "401" in str(retry_err) or "unauthorized" in str(retry_err).lower():
                            raise
                        return f"MCP tool error after reconnect: {retry_err}"

                if is_auth_error:
                    raise

            if "Cannot read properties of undefined" in error_msg:
                return (
                    f"The MCP server encountered an internal error while processing your "
                    f"request. This is typically a bug in the MCP server implementation. "
                    f"Error: {error_msg}"
                )
            # Match real network/asyncio timeout exceptions (e.g. TimeoutError,
            # ReadTimeout, asyncio.TimeoutError) by type rather than a string
            # substring — "timeout" inside a tool error message would otherwise
            # get rebranded as an MCP server timeout.
            if isinstance(e, TimeoutError) or "timeouterror" in type(e).__name__.lower():
                return f"The MCP server timed out. Please try again. Error: {error_msg}"
            return f"MCP tool error: {error_msg}"

    tool._arun = filtered_arun  # type: ignore[method-assign]
    # Stash original for the reconnect path to bypass this wrapper on retry.
    tool._original_arun = original_arun  # type: ignore[attr-defined]
    return tool


def wrap_tools_with_null_filter(
    tools: list[BaseTool],
    on_connection_error: Any = None,
    reconnect_and_retry: Callable[[str, dict], Awaitable[Any]] | None = None,
) -> list[BaseTool]:
    """Wrap all tools with null filtering + optional transparent reconnect."""
    return [
        wrap_tool_with_null_filter(
            t,
            on_connection_error=on_connection_error,
            reconnect_and_retry=reconnect_and_retry,
        )
        for t in tools
    ]
