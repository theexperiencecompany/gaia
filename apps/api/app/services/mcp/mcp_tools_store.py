"""
Global MCP Tool Storage Service.

Stores MCP tool metadata globally (not per-user) for frontend visibility.
When a user first connects to an MCP integration, tools are stored globally
so other users can see available tools without connecting first.
"""

from typing import Optional

from sqlalchemy import select, delete

from app.config.loggers import langchain_logger as logger
from app.db.postgresql import get_db_session
from app.models.oauth_models import MCPIntegrationTool


class MCPToolsStore:
    """Global MCP tool metadata storage."""

    async def store_tools(self, integration_id: str, tools: list[dict]) -> None:
        """Store tools for an MCP integration (global, not per-user).

        Tools are stored when first user connects. Subsequent users
        will see these tools in the frontend without connecting.

        Args:
            integration_id: MCP integration ID (e.g., "linear")
            tools: List of dicts with 'name' and 'description' keys
        """
        if not tools:
            return

        async with get_db_session() as session:
            # Delete existing tools for this integration (fresh insert)
            await session.execute(
                delete(MCPIntegrationTool).where(
                    MCPIntegrationTool.integration_id == integration_id
                )
            )

            # Insert new tools
            for tool in tools:
                tool_record = MCPIntegrationTool(
                    integration_id=integration_id,
                    tool_name=tool.get("name", ""),
                    tool_description=tool.get("description"),
                )
                session.add(tool_record)

            await session.commit()
            logger.info(
                f"Stored {len(tools)} global tools for MCP integration {integration_id}"
            )

    async def get_tools(self, integration_id: str) -> Optional[list[dict]]:
        """Get stored tools for an MCP integration.

        Returns:
            List of tool dicts with 'name' and 'description', or None if not found.
        """
        try:
            async with get_db_session() as session:
                result = await session.execute(
                    select(MCPIntegrationTool).where(
                        MCPIntegrationTool.integration_id == integration_id
                    )
                )
                tools = result.scalars().all()

                if not tools:
                    return None

                return [
                    {"name": t.tool_name, "description": t.tool_description}
                    for t in tools
                ]
        except Exception as e:
            logger.error(f"Error getting tools for {integration_id}: {e}")
            return None

    async def get_all_mcp_tools(self) -> dict[str, list[dict]]:
        """Get all stored MCP tools keyed by integration_id.

        Returns:
            Dict mapping integration_id to list of tool dicts.
        """
        try:
            async with get_db_session() as session:
                result = await session.execute(select(MCPIntegrationTool))
                tools = result.scalars().all()

                grouped: dict[str, list[dict]] = {}
                for tool in tools:
                    if tool.integration_id not in grouped:
                        grouped[tool.integration_id] = []
                    grouped[tool.integration_id].append(
                        {"name": tool.tool_name, "description": tool.tool_description}
                    )

                return grouped
        except Exception as e:
            logger.error(f"Error getting all MCP tools: {e}")
            return {}


def get_mcp_tools_store() -> MCPToolsStore:
    """Get the global MCP tools store instance."""
    return MCPToolsStore()
