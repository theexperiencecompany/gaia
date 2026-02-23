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
from typing import Any, Callable, Literal, Optional, Union

from langchain_core.tools import BaseTool
from pydantic import BaseModel

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

    any_of = field_info.get("anyOf", [])
    if any_of:
        is_optional = True
        json_type = "string"
        for option in any_of:
            if isinstance(option, dict) and option.get("type") != "null":
                json_type = option.get("type", "string")
                # Also check for enum in anyOf option
                if option.get("enum"):
                    python_type = Literal[tuple(option["enum"])]  # type: ignore[valid-type]
                    return python_type, default_val, is_optional
                break
    else:
        json_type = field_info.get("type", "string")
        if isinstance(json_type, list):
            is_optional = "null" in json_type
            json_type = next((t for t in json_type if t != "null"), "string")

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
        logger.debug(f"Tool {tool.name} has no args_schema")
        return None

    try:
        args_schema = tool.args_schema
        if not isinstance(args_schema, type) or not issubclass(args_schema, BaseModel):
            logger.debug(f"Tool {tool.name} args_schema is not a BaseModel")
            return None
        schema = args_schema.model_json_schema()  # type: ignore[attr-defined]
        result = {
            "properties": schema.get("properties", {}),
            "required": schema.get("required", []),
        }
        logger.debug(
            f"Serialized schema for {tool.name}: {len(result.get('properties', {}))} properties"
        )
        return result
    except Exception as e:
        logger.warning(f"Failed to serialize schema for {tool.name}: {e}")
        return None
