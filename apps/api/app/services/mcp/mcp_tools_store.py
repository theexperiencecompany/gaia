"""
Global MCP Tool Storage Service.

Stores MCP tool metadata globally (not per-user) for frontend visibility.
When a user first connects to an MCP integration, tools are stored globally
so other users can see available tools without connecting first.

Uses MongoDB `integrations` collection to store tool metadata within the
integration document as `tools` array.

Performance: Uses in-memory TTL cache to reduce MongoDB queries.
"""

import time
from typing import Optional

from app.config.loggers import langchain_logger as logger
from app.db.mongodb.collections import integrations_collection


# Simple in-memory TTL cache for global MCP tools
_global_tools_cache: dict[str, list[dict]] | None = None
_cache_timestamp: float = 0
_CACHE_TTL_SECONDS: int = 300  # 5 minutes


class MCPToolsStore:
    """Global MCP tool metadata storage using MongoDB with in-memory caching."""

    async def store_tools(self, integration_id: str, tools: list[dict]) -> None:
        """Store tools for an MCP integration (global, not per-user).

        Tools are stored when first user connects. Subsequent users
        will see these tools in the frontend without connecting.

        Updates the `tools` array in the integration document.

        Args:
            integration_id: MCP integration ID (e.g., "linear")
            tools: List of dicts with 'name' and 'description' keys
        """
        if not tools:
            return

        try:
            # Format tools for storage
            formatted_tools = [
                {"name": t.get("name", ""), "description": t.get("description", "")}
                for t in tools
            ]

            # Update the integration document with tools
            result = await integrations_collection.update_one(
                {"integration_id": integration_id},
                {
                    "$set": {"tools": formatted_tools},
                    "$setOnInsert": {
                        "integration_id": integration_id,
                        "source": "platform",
                    },
                },
                upsert=True,
            )

            if result.modified_count > 0 or result.upserted_id:
                # Invalidate cache on tool storage
                global _global_tools_cache, _cache_timestamp
                _global_tools_cache = None
                _cache_timestamp = 0
                logger.info(
                    f"Stored {len(tools)} global tools for MCP integration {integration_id}"
                )
        except Exception as e:
            logger.error(f"Error storing tools for {integration_id}: {e}")

    async def get_tools(self, integration_id: str) -> Optional[list[dict]]:
        """Get stored tools for an MCP integration.

        Returns:
            List of tool dicts with 'name' and 'description', or None if not found.
        """
        try:
            doc = await integrations_collection.find_one(
                {"integration_id": integration_id},
                {"tools": 1},
            )

            if not doc or "tools" not in doc:
                return None

            return doc["tools"]
        except Exception as e:
            logger.error(f"Error getting tools for {integration_id}: {e}")
            return None

    async def get_all_mcp_tools(self) -> dict[str, list[dict]]:
        """Get all stored MCP tools keyed by integration_id.

        Uses in-memory cache with 5-minute TTL to reduce MongoDB queries.

        Returns:
            Dict mapping integration_id to list of tool dicts.
        """
        global _global_tools_cache, _cache_timestamp

        # Check if cache is valid
        current_time = time.time()
        if (
            _global_tools_cache is not None
            and (current_time - _cache_timestamp) < _CACHE_TTL_SECONDS
        ):
            logger.debug("Returning cached MCP tools")
            return _global_tools_cache

        # Cache miss or expired - fetch from MongoDB
        try:
            cursor = integrations_collection.find(
                {"tools": {"$exists": True, "$ne": []}},
                {"integration_id": 1, "tools": 1},
            )

            grouped: dict[str, list[dict]] = {}
            async for doc in cursor:
                integration_id = doc.get("integration_id")
                tools = doc.get("tools", [])
                if integration_id and tools:
                    grouped[integration_id] = tools

            # Update cache
            _global_tools_cache = grouped
            _cache_timestamp = current_time
            logger.debug(f"Cached {len(grouped)} MCP tool integrations")

            return grouped
        except Exception as e:
            logger.error(f"Error getting all MCP tools: {e}")
            return {}


def get_mcp_tools_store() -> MCPToolsStore:
    """Get the global MCP tools store instance."""
    return MCPToolsStore()
