"""
MCP Utility Functions.

Contains helper functions for MCP client operations including
PKCE generation, tool wrapping, and schema handling.
"""

import base64
import hashlib
import inspect
import secrets
from functools import wraps
from typing import Any, Callable, Optional

from langchain_core.tools import BaseTool

from app.config.loggers import langchain_logger as logger


def generate_pkce_pair() -> tuple[str, str]:
    """
    Generate PKCE code_verifier and code_challenge (S256).

    Returns (code_verifier, code_challenge) tuple.
    """
    code_verifier = secrets.token_urlsafe(32)
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return code_verifier, code_challenge


_CONNECTION_ERROR_PATTERNS = (
    "timeout",
    "connection reset",
    "broken pipe",
    "unexpected eof",
    "eof error",
    "eoferror",
    "connection refused",
    "connection closed",
    "server disconnected",
    "connect call failed",
)


def wrap_tool_with_null_filter(
    tool: BaseTool,
    on_connection_error: Optional[Callable[[], None]] = None,
) -> BaseTool:
    """
    Wrap a LangChain tool to filter out None values before MCP invocation.

    MCP servers expect optional parameters to be OMITTED, not sent as null.
    However, Pydantic models populate all fields with their defaults (including None),
    which causes MCP validation errors like:
        "Expected string, received null"

    This wrapper intercepts the _arun call and filters out None values.

    Error handling:
    - Auth errors (401/unauthorized) are RE-RAISED so the orchestrator can handle
      token refresh. This is critical for proper OAuth flow.
    - Connection errors trigger on_connection_error callback to evict stale sessions.
    - Other errors are returned as user-friendly messages.
    """
    original_arun = tool._arun

    @wraps(original_arun)
    async def filtered_arun(**kwargs: Any) -> Any:
        filtered_kwargs = {k: v for k, v in kwargs.items() if v is not None}
        logger.debug(
            f"MCP tool '{tool.name}': original args={kwargs}, filtered={filtered_kwargs}"
        )
        try:
            result = await original_arun(**filtered_kwargs)
            return result
        except Exception as e:
            error_msg = str(e)
            logger.error(f"MCP tool '{tool.name}' failed: {error_msg}")

            # CRITICAL: Re-raise auth errors so orchestrator can handle token refresh.
            # Previously these were swallowed, preventing automatic token refresh.
            if "401" in error_msg or "unauthorized" in error_msg.lower():
                raise

            # On connection-type errors, evict the stale session so next call reconnects
            error_lower = error_msg.lower()
            if on_connection_error and any(
                pat in error_lower for pat in _CONNECTION_ERROR_PATTERNS
            ):
                if inspect.iscoroutinefunction(on_connection_error):
                    raise TypeError(
                        "on_connection_error must be a synchronous callable, not a coroutine function"
                    )
                logger.warning(
                    f"MCP tool '{tool.name}' hit connection error, evicting session"
                )
                on_connection_error()

            # Provide helpful error message for common MCP errors
            if "Cannot read properties of undefined" in error_msg:
                return f"The MCP server encountered an internal error while processing your request. This is typically a bug in the MCP server implementation. Error: {error_msg}"
            elif "timeout" in error_lower:
                return f"The MCP server timed out. Please try again. Error: {error_msg}"
            else:
                return f"MCP tool error: {error_msg}"

    tool._arun = filtered_arun  # type: ignore[method-assign]
    return tool


def wrap_tools_with_null_filter(
    tools: list[BaseTool],
    on_connection_error: Any = None,
) -> list[BaseTool]:
    """Wrap all tools with null value filtering."""
    return [
        wrap_tool_with_null_filter(t, on_connection_error=on_connection_error)
        for t in tools
    ]
