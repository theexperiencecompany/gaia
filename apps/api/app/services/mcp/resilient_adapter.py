"""Resilient LangChain adapter that skips tools with invalid schemas.

This adapter wraps the standard SanitizingLangChainAdapter and adds
resilience by catching schema conversion errors on a per-tool basis,
allowing valid tools to work even if some tools have malformed schemas.
"""

from typing import Any

from langchain_core.tools import BaseTool

from app.config.loggers import langchain_logger as logger
from app.services.mcp.langchain_adapter import SanitizingLangChainAdapter
from app.utils.schema_fixes import patch_tool_schema


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

    async def create_tools(self, client) -> list[BaseTool]:
        """Create LangChain tools, skipping any with invalid schemas.

        Args:
            client: BaseMCPClient instance with active session

        Returns:
            List of successfully converted LangChain tools
        """
        # Get connectors from active sessions
        sessions = client.get_all_active_sessions()
        if not sessions:
            logger.warning("No active sessions found in client")
            return []

        # Get first session (we typically only have one per integration)
        session = list(sessions.values())[0]
        connector = session.connector
        integration_id = list(sessions.keys())[0]

        # Get tools from MCP server
        try:
            mcp_tools = await connector.list_tools()
            logger.info(
                f"[{integration_id}] MCP server returned {len(mcp_tools)} tools"
            )
        except Exception as e:
            logger.error(f"[{integration_id}] Failed to list tools: {e}")
            raise

        if not mcp_tools:
            logger.warning(f"[{integration_id}] No tools returned from MCP server")
            return []

        # Normalize schemas before conversion
        normalized_tools = []
        for tool in mcp_tools:
            try:
                normalized_tool = patch_tool_schema(tool)
                normalized_tools.append(normalized_tool)
            except Exception as e:
                logger.warning(
                    f"[{integration_id}] Could not normalize schema for {tool.name}: {e}"
                )
                # Still try to use the original tool
                normalized_tools.append(tool)

        # Try to convert each tool individually
        successfully_converted = []
        failed_tools = []

        for tool in normalized_tools:
            try:
                # Create a temporary connector with just this one tool
                # This way if conversion fails, it only affects this tool
                langchain_tool = await self._convert_single_tool(tool, connector)
                successfully_converted.append(langchain_tool)
                logger.debug(f"[{integration_id}] ✓ Converted tool: {tool.name}")
            except Exception as e:
                failed_tools.append((tool.name, str(e)))
                logger.warning(
                    f"[{integration_id}] ✗ Failed to convert tool '{tool.name}': "
                    f"{type(e).__name__}: {e}"
                )
                # Continue with other tools

        # Log summary
        if successfully_converted:
            logger.info(
                f"[{integration_id}] Successfully converted {len(successfully_converted)}/{len(mcp_tools)} tools"
            )

        if failed_tools:
            logger.warning(
                f"[{integration_id}] Skipped {len(failed_tools)} tools with invalid schemas:\n"
                + "\n".join(f"  - {name}: {error}" for name, error in failed_tools)
            )

        if not successfully_converted:
            # All tools failed - this is a problem
            error_summary = "\n".join(
                f"  - {name}: {error}" for name, error in failed_tools[:5]
            )
            raise ValueError(
                f"Failed to convert any tools from {integration_id}. "
                f"All {len(mcp_tools)} tools have invalid schemas:\n{error_summary}"
            )

        return successfully_converted

    async def _convert_single_tool(self, mcp_tool: Any, connector: Any) -> BaseTool:
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
