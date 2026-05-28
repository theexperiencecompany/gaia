"""
MCP Utility Functions.

Contains helper functions for MCP client operations including
PKCE generation, tool wrapping, and schema handling.
"""

import base64
from collections.abc import Awaitable, Callable, Iterable
from functools import wraps
import hashlib
import inspect
import secrets
from typing import Any, Literal, Union

from langchain_core.tools import BaseTool
from pydantic import BaseModel

from shared.py.wide_events import log


def canonical_tool_name_map(names: Iterable[str]) -> dict[str, str]:
    """Map underscore-canonical → original tool name.

    MCP tools keep their original (often hyphenated) names because the
    upstream server expects them, but LLMs commonly echo them with
    underscores. Use the returned map to recover the canonical name when an
    LLM call misses the strict bound-set membership check.
    """
    return {n.replace("-", "_"): n for n in names}


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
    2. On a connection-loss error, evict the stale session via `on_connection_error`
       and — if `reconnect_and_retry` is provided — silently rebuild the connector
       and retry the call once. The user sees latency, not an error.
    3. Re-raise auth errors (401/unauthorized) so the OAuth refresh layer can handle them.

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

            # Re-raise auth errors so the orchestrator can handle token refresh.
            if "401" in error_msg or "unauthorized" in error_lower:
                raise

            is_connection_error = any(pat in error_lower for pat in _CONNECTION_ERROR_PATTERNS)

            if is_connection_error and on_connection_error:
                if inspect.iscoroutinefunction(on_connection_error):
                    raise TypeError(
                        "on_connection_error must be a synchronous callable, not a coroutine function"
                    )
                log.warning(f"MCP tool '{tool.name}' hit connection error, evicting session")
                on_connection_error()

            if is_connection_error and reconnect_and_retry:
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
                    return f"MCP tool error after reconnect: {retry_err}"

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


def extract_type_from_field(field_info: dict) -> tuple[Any, Any, bool]:
    """
    Extract Python type from JSON Schema field info.

    MCP tools use JSON Schema with nullable types via anyOf:
    {"anyOf": [{"type": "number"}, {"type": "null"}], "default": 50}

    Also handles enums by returning Literal types:
    {"type": "string", "enum": ["low", "medium", "high"]}
    -> Literal["low", "medium", "high"]

    Returns: (python_type, default_value, is_optional)
    """
    default_val = field_info.get("default")
    is_optional = False
    python_type: Any = str  # Default type, will be reassigned

    # Check for enum first - this takes priority over type
    enum_values = field_info.get("enum")
    if enum_values and isinstance(enum_values, list) and len(enum_values) > 0:
        # Create a Literal type from enum values
        # Literal requires a tuple of values
        python_type = Literal[tuple(enum_values)]  # type: ignore[valid-type]
        return python_type, default_val, is_optional

    json_type: str = "string"
    any_of = field_info.get("anyOf", [])
    if any_of:
        is_optional = True
        for option in any_of:
            if isinstance(option, dict) and option.get("type") != "null":
                json_type = option.get("type", "string")
                # Also check for enum in anyOf option
                if option.get("enum"):
                    python_type = Literal[tuple(option["enum"])]  # type: ignore[valid-type]
                    return python_type, default_val, is_optional
                break
    else:
        type_value = field_info.get("type", "string")
        if isinstance(type_value, list):
            is_optional = "null" in type_value
            json_type = next((t for t in type_value if t != "null"), "string")
        else:
            json_type = type_value

    type_map: dict[str, type] = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    python_type = type_map.get(json_type, Any)

    if is_optional and default_val is None:
        python_type = Union[python_type, None]

    return python_type, default_val, is_optional


def serialize_args_schema(tool: BaseTool) -> dict | None:
    """Serialize tool's args schema to JSON-compatible dict."""
    if not hasattr(tool, "args_schema") or not tool.args_schema:
        log.debug(f"Tool {tool.name} has no args_schema")
        return None

    try:
        args_schema = tool.args_schema
        if not isinstance(args_schema, type) or not issubclass(args_schema, BaseModel):
            log.debug(f"Tool {tool.name} args_schema is not a BaseModel")
            return None
        schema = args_schema.model_json_schema()  # type: ignore[attr-defined]
        result = {
            "properties": schema.get("properties", {}),
            "required": schema.get("required", []),
        }
        log.debug(
            f"Serialized schema for {tool.name}: {len(result.get('properties', {}))} properties"
        )
        return result
    except Exception as e:
        log.warning(f"Failed to serialize schema for {tool.name}: {e}")
        return None
