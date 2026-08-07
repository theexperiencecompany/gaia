"""Resilient LangChain adapter that skips tools with invalid schemas.

This adapter wraps the standard SanitizingLangChainAdapter and adds
resilience by catching schema conversion errors on a per-tool basis,
allowing valid tools to work even if some tools have malformed schemas.

It also memoizes mcp_use's jsonschema_to_pydantic at module import time —
a fresh cold connect for a server with 339 tools used to spend ~2.5s rebuilding
Pydantic classes that are deterministic functions of the schema content. The
cache lives per worker, so the first cold connect still pays the cost; every
subsequent cold connect (post worker restart, post LRU eviction) skips it.
"""

from functools import lru_cache
import json
from typing import Any, cast

from langchain_core.tools import BaseTool
import mcp_use.agents.adapters.langchain_adapter as _mcp_use_lc_adapter
from mcp_use.client.client import MCPClient
from mcp_use.client.connectors.base import BaseConnector
from pydantic import BaseModel

from app.constants.log_tags import LogTag
from app.services.mcp.langchain_adapter import SanitizingLangChainAdapter
from app.utils.schema_fixes import patch_tool_schema
from mcp.types import Tool
from shared.py.wide_events import log

_ORIGINAL_JSONSCHEMA_TO_PYDANTIC = _mcp_use_lc_adapter.jsonschema_to_pydantic


@lru_cache(maxsize=10000)
def _cached_jsonschema_to_pydantic_by_key(schema_key: str) -> type[BaseModel]:
    # mcp_use's jsonschema_to_pydantic is untyped (returns Any); it always
    # builds a pydantic model class from a JSON schema.
    return cast(type[BaseModel], _ORIGINAL_JSONSCHEMA_TO_PYDANTIC(json.loads(schema_key)))


def _memoized_jsonschema_to_pydantic(schema: dict[str, Any]) -> type[BaseModel]:
    """Drop-in replacement for mcp_use's jsonschema_to_pydantic with an LRU cache.

    Falls through to the original when the schema isn't JSON-serializable
    (rare, but possible if a server smuggles non-JSON types into inputSchema).
    Do NOT pass `default=str` to json.dumps — it would silently coerce
    non-serializable values into their string form, building a lossy cache
    key and risking two different schemas mapping to the same Pydantic model.
    """
    try:
        key = json.dumps(schema, sort_keys=True)
    except (TypeError, ValueError):
        return cast(type[BaseModel], _ORIGINAL_JSONSCHEMA_TO_PYDANTIC(schema))
    return _cached_jsonschema_to_pydantic_by_key(key)


_mcp_use_lc_adapter.jsonschema_to_pydantic = _memoized_jsonschema_to_pydantic


class ResilientLangChainAdapter(SanitizingLangChainAdapter):
    """LangChain adapter that gracefully handles tools with invalid schemas.

    Unlike the standard adapter which fails completely if any tool has an
    invalid schema, this adapter:
    1. Attempts to normalize schemas (fix common issues)
    2. Tries to convert each tool individually
    3. Skips tools that fail conversion
    4. Returns all successfully converted tools

    This allows integrations to work even if some tools are broken.
    """

    async def create_tools(self, client: MCPClient) -> list[BaseTool]:
        """Create LangChain tools, skipping any with invalid schemas.

        Args:
            client: BaseMCPClient instance with active session

        Returns:
            List of successfully converted LangChain tools
        """
        # Get connectors from active sessions
        sessions = client.get_all_active_sessions()
        if not sessions:
            log.warning(f"{LogTag.MCP} No active sessions found in client")
            return []

        # Get first session (we typically only have one per integration)
        session = list(sessions.values())[0]
        connector = session.connector
        integration_id = list(sessions.keys())[0]

        # Get tools from MCP server
        try:
            mcp_tools = await connector.list_tools()
            log.info(
                f"{LogTag.MCP} MCP server returned tools",
                integration_id=integration_id,
                mcp_tools_count=len(mcp_tools),
            )
        except Exception as e:
            log.error(
                f"{LogTag.MCP} Failed to list tools",
                integration_id=integration_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            raise

        if not mcp_tools:
            log.warning(
                f"{LogTag.MCP} No tools returned from MCP server", integration_id=integration_id
            )
            return []

        # Normalize schemas before conversion
        normalized_tools: list[Tool] = []
        for tool in mcp_tools:
            try:
                normalized_tool = patch_tool_schema(tool)
                normalized_tools.append(normalized_tool)
            except Exception as e:
                log.warning(
                    f"{LogTag.MCP} Could not normalize schema for",
                    integration_id=integration_id,
                    name=tool.name,
                    error=str(e),
                    error_type=type(e).__name__,
                )
                # Still try to use the original tool
                normalized_tools.append(tool)

        # Try to convert each tool individually
        successfully_converted: list[BaseTool] = []
        failed_tools: list[tuple[str, str]] = []

        for tool in normalized_tools:
            try:
                # Create a temporary connector with just this one tool
                # This way if conversion fails, it only affects this tool
                langchain_tool = await self._convert_single_tool(tool, connector)

                # Attach _meta.ui info if present on the raw MCP tool.
                # Support both modern nested metadata and legacy flat key.
                raw_meta = getattr(tool, "meta", None)
                if not isinstance(raw_meta, dict):
                    raw_meta = getattr(tool, "_meta", None)

                if isinstance(raw_meta, dict):
                    ui_meta = raw_meta.get("ui")
                    if not isinstance(ui_meta, dict):
                        ui_meta = {}

                    resource_uri = ui_meta.get("resourceUri") or raw_meta.get("ui/resourceUri")
                    if isinstance(resource_uri, str) and resource_uri:
                        if langchain_tool.metadata is None:
                            langchain_tool.metadata = {}
                        langchain_tool.metadata["mcp_ui"] = {
                            "resource_uri": resource_uri,
                            "csp": ui_meta.get("csp"),
                            "permissions": ui_meta.get("permissions", []),
                        }
                        log.debug(
                            f"{LogTag.MCP} Attached mcp_ui metadata to tool",
                            integration_id=integration_id,
                            name=tool.name,
                        )

                successfully_converted.append(langchain_tool)
                log.debug(
                    f"{LogTag.MCP} Converted tool", integration_id=integration_id, name=tool.name
                )
            except Exception as e:
                failed_tools.append((tool.name, str(e)))
                log.warning(
                    f"{LogTag.MCP} Failed to convert tool",
                    integration_id=integration_id,
                    tool_name=tool.name,
                    error_type=type(e).__name__,
                )
                # Continue with other tools

        # Log summary
        if successfully_converted:
            log.info(
                f"{LogTag.MCP} Successfully converted / tools",
                integration_id=integration_id,
                successfully_converted_count=len(successfully_converted),
                mcp_tools_count=len(mcp_tools),
            )

        if failed_tools:
            log.warning(
                f"{LogTag.MCP} [{integration_id}] Skipped {len(failed_tools)} tools with invalid schemas:\n"
                + "\n".join(f"  - {name}: {error}" for name, error in failed_tools)
            )

        if not successfully_converted:
            # All tools failed - this is a problem
            error_summary = "\n".join(f"  - {name}: {error}" for name, error in failed_tools[:5])
            raise ValueError(
                f"Failed to convert any tools from {integration_id}. "
                f"All {len(mcp_tools)} tools have invalid schemas:\n{error_summary}"
            )

        return successfully_converted

    async def _convert_single_tool(self, mcp_tool: Tool, connector: BaseConnector) -> BaseTool:
        """Convert a single MCP tool to LangChain format.

        Args:
            mcp_tool: MCP tool to convert
            connector: MCP connector instance

        Returns:
            Converted LangChain tool

        Raises:
            Exception: If conversion fails
        """
        # Use the parent class's conversion logic
        # This calls jsonschema_to_pydantic internally
        converted = self._convert_tool(mcp_tool, connector)
        return converted
