"""
Global MCP Tool Storage Service.

Stores MCP tool metadata globally (not per-user) for frontend visibility.
When a user first connects to an MCP integration, tools are stored globally
so other users can see available tools without connecting first.

Uses MongoDB `integrations` collection to store tool metadata within the
integration document as `tools` array.

Performance: Uses Redis cache to reduce MongoDB queries across all workers.
"""

from typing import Optional

from app.config.loggers import langchain_logger as logger
from app.db.mongodb.collections import integrations_collection
from app.db.redis import delete_cache, get_cache, set_cache

# Redis cache key and TTL for global MCP tools
MCP_TOOLS_CACHE_KEY = "mcp:tools:all"
MCP_TOOLS_CACHE_TTL = 86400  # 24 hours (invalidated on write)


class MCPToolsStore:
    """Global MCP tool metadata storage using MongoDB with Redis caching."""

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
            logger.warning(f"[{integration_id}] Empty tools list - skipping store")
            return

        try:
            formatted_tools = [
                {"name": t.get("name", ""), "description": t.get("description", "")}
                for t in tools
            ]

            logger.info(
                f"[{integration_id}] Storing {len(formatted_tools)} tools in integrations collection"
            )

            result = await integrations_collection.update_one(
                {"integration_id": integration_id},
                {"$set": {"tools": formatted_tools, "integration_id": integration_id}},
                upsert=True,
            )

            logger.info(
                f"[{integration_id}] Tools stored: "
                f"upserted={result.upserted_id is not None}, modified={result.modified_count}"
            )

            # Invalidate cache
            await delete_cache(MCP_TOOLS_CACHE_KEY)

        except Exception as e:
            logger.error(f"[{integration_id}] Error storing tools: {e}", exc_info=True)
            raise

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

        Uses Redis cache with 24-hour TTL (invalidated on tool storage).

        Returns:
            Dict mapping integration_id to list of tool dicts.
        """
        # Check Redis cache
        cached = await get_cache(MCP_TOOLS_CACHE_KEY)
        if cached:
            logger.debug("Returning cached MCP tools from Redis")
            return cached

        # Cache miss - fetch from MongoDB
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

            # Store in Redis cache
            await set_cache(MCP_TOOLS_CACHE_KEY, grouped, ttl=MCP_TOOLS_CACHE_TTL)
            logger.debug(f"Cached {len(grouped)} MCP tool integrations in Redis")

            return grouped
        except Exception as e:
            logger.error(f"Error getting all MCP tools: {e}")
            return {}


def get_mcp_tools_store() -> MCPToolsStore:
    """Get the global MCP tools store instance."""
    return MCPToolsStore()
