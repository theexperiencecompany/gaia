"""
MCP Utility Functions.

Contains helper functions for MCP client operations including
PKCE generation, tool wrapping, and schema handling.
"""

from collections.abc import Awaitable, Callable, Iterable
from functools import wraps
import inspect
import re

from langchain_core.tools import BaseTool

from app.constants.log_tags import LogTag
from app.constants.mcp import MCP_TOOL_NAME_MAX_CHARS, MCP_UNNAMED_SOURCE_PREFIX
from shared.py.wide_events import log


def canonical_tool_name_map(names: Iterable[str]) -> dict[str, str]:
    """Map underscore-canonical → original tool name.

    MCP tools keep their original (often hyphenated) names because the
    upstream server expects them, but LLMs commonly echo them with
    underscores. Use the returned map to recover the canonical name when an
    LLM call misses the strict bound-set membership check.
    """
    return {n.replace("-", "_"): n for n in names}


def source_prefixed_tool_name(source_name: str, tool_name: str) -> str:
    """Name a tool after its source, e.g. ("Dodo Payments", "execute") -> "dodo_payments_execute"."""
    prefix = re.sub(r"[^a-z0-9]+", "_", source_name.lower()).strip("_")
    prefix = prefix[: MCP_TOOL_NAME_MAX_CHARS - len(tool_name) - 1].rstrip("_")
    return f"{prefix or MCP_UNNAMED_SOURCE_PREFIX}_{tool_name}"


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
    reconnect_and_retry: Callable[[str, dict[str, object]], Awaitable[object]] | None = None,
) -> BaseTool:
    """Wrap a LangChain MCP tool with null-arg filtering and transparent reconnect.

    Filters None-valued args (MCP servers reject null for optional fields).
    On connection-loss or 401, evicts the stale session and, if
    reconnect_and_retry is given, rebuilds the connector and retries once —
    a 401 surviving the refresh is re-raised.
    """
    # mcp_use's adapter sets handle_tool_error=True by default, swallowing
    # exceptions as a formatted string; flip it off so _arun re-raises and
    # the reconnect path can run.
    if hasattr(tool, "handle_tool_error"):
        tool.handle_tool_error = False

    original_arun = tool._arun

    @wraps(original_arun)
    async def filtered_arun(**kwargs: object) -> object:
        filtered_kwargs = {k: v for k, v in kwargs.items() if v is not None}
        log.set(operation="mcp_tool_call", tool_name=tool.name)
        log.debug(
            f"{LogTag.MCP} MCP tool call args filtered",
            name=tool.name,
            kwargs=kwargs,
            filtered_kwargs=filtered_kwargs,
        )
        try:
            return await original_arun(**filtered_kwargs)
        except Exception as e:
            error_msg = str(e)
            error_lower = error_msg.lower()
            log.error(
                f"{LogTag.MCP} MCP tool failed",
                name=tool.name,
                error_msg=error_msg,
                error=str(e),
                error_type=type(e).__name__,
            )

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
                        ) from None
                    log.warning(
                        f"{LogTag.MCP} MCP tool session error, evicting session",
                        name=tool.name,
                        error=str(e),
                        error_type=type(e).__name__,
                    )
                    on_connection_error()

                if reconnect_and_retry:
                    try:
                        log.warning(
                            f"{LogTag.MCP} MCP tool attempting transparent reconnect-and-retry",
                            name=tool.name,
                            error=str(e),
                            error_type=type(e).__name__,
                        )
                        return await reconnect_and_retry(tool.name, filtered_kwargs)
                    except Exception as retry_err:
                        log.error(
                            f"{LogTag.MCP} MCP tool reconnect-retry failed",
                            tool_name=tool.name,
                            error_type=type(retry_err).__name__,
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
            # Matched by type, not substring — "timeout" inside a tool error
            # message would otherwise get rebranded as an MCP server timeout.
            if isinstance(e, TimeoutError) or "timeouterror" in type(e).__name__.lower():
                return f"The MCP server timed out. Please try again. Error: {error_msg}"
            return f"MCP tool error: {error_msg}"

    tool._arun = filtered_arun  # type: ignore[method-assign]  # swapping BaseTool._arun with a filtered wrapper is the deliberate dispatch mechanism
    # Stash original for the reconnect path to bypass this wrapper on retry.
    tool._original_arun = original_arun
    return tool


def wrap_tools_with_null_filter(
    tools: list[BaseTool],
    on_connection_error: Callable[[], None] | None = None,
    reconnect_and_retry: Callable[[str, dict[str, object]], Awaitable[object]] | None = None,
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
