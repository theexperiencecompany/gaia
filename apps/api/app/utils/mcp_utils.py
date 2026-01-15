"""
MCP Utility Functions.

Contains helper functions for MCP client operations including
PKCE generation, tool wrapping, and schema handling.
"""

import base64
import hashlib
import secrets
from functools import wraps
from typing import Any, Union

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


def wrap_tool_with_null_filter(tool: BaseTool) -> BaseTool:
    """
    Wrap a LangChain tool to filter out None values before MCP invocation.

    MCP servers expect optional parameters to be OMITTED, not sent as null.
    However, Pydantic models populate all fields with their defaults (including None),
    which causes MCP validation errors like:
        "Expected string, received null"

    This wrapper intercepts the _arun call and filters out None values.
    It also handles errors from MCP servers gracefully.
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

            # Check if result contains an error message from MCP server
            if isinstance(result, str) and "Error" in result:
                logger.warning(f"MCP tool '{tool.name}' returned error: {result}")

            return result
        except Exception as e:
            error_msg = str(e)
            logger.error(f"MCP tool '{tool.name}' failed: {error_msg}")

            # Provide helpful error message for common MCP errors
            if "Cannot read properties of undefined" in error_msg:
                return f"The MCP server encountered an internal error while processing your request. This is typically a bug in the MCP server implementation. Error: {error_msg}"
            elif "timeout" in error_msg.lower():
                return f"The MCP server timed out. Please try again. Error: {error_msg}"
            elif "401" in error_msg or "unauthorized" in error_msg.lower():
                return f"Authentication required for this MCP tool. Please reconnect the integration. Error: {error_msg}"
            else:
                return f"MCP tool error: {error_msg}"

    tool._arun = filtered_arun  # type: ignore[method-assign]
    return tool


def wrap_tools_with_null_filter(tools: list[BaseTool]) -> list[BaseTool]:
    """Wrap all tools with null value filtering."""
    return [wrap_tool_with_null_filter(t) for t in tools]


def extract_type_from_field(field_info: dict) -> tuple[type, Any, bool]:
    """
    Extract Python type from JSON Schema field info.

    MCP tools use JSON Schema with nullable types via anyOf:
    {"anyOf": [{"type": "number"}, {"type": "null"}], "default": 50}

    Returns: (python_type, default_value, is_optional)
    """
    default_val = field_info.get("default")
    is_optional = False

    any_of = field_info.get("anyOf", [])
    if any_of:
        is_optional = True
        json_type = "string"
        for option in any_of:
            if isinstance(option, dict) and option.get("type") != "null":
                json_type = option.get("type", "string")
                break
    else:
        json_type = field_info.get("type", "string")
        if isinstance(json_type, list):
            is_optional = "null" in json_type
            json_type = next((t for t in json_type if t != "null"), "string")

    type_map = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    python_type = type_map.get(json_type, Any)

    if is_optional and default_val is None:
        python_type = Union[python_type, None]  # type: ignore[assignment]

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
        schema = args_schema.model_json_schema()
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
