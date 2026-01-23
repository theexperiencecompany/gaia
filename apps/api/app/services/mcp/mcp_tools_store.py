"""Global MCP tool storage. Redis-cached MongoDB storage for frontend tool visibility."""

import asyncio
from typing import Optional

from app.config.loggers import langchain_logger as logger
from app.constants.cache import MCP_TOOLS_CACHE_KEY, MCP_TOOLS_CACHE_TTL
from app.db.mongodb.collections import integrations_collection
from app.db.redis import delete_cache, get_cache, set_cache


class MCPToolsStore:
    """Global MCP tool metadata storage with Redis caching."""

    async def store_tools(self, integration_id: str, tools: list[dict]) -> None:
        """Store tools for an MCP integration globally."""
        if not tools:
            return

        formatted_tools = [
            {
                "name": t.get("name", "").strip(),
                "description": t.get("description", "").strip(),
            }
            for t in tools
            if t.get("name", "").strip()
        ]

        if not formatted_tools:
            return

        try:
            await integrations_collection.update_one(
                {"integration_id": integration_id},
                {"$set": {"tools": formatted_tools, "integration_id": integration_id}},
                upsert=True,
            )
            await delete_cache(MCP_TOOLS_CACHE_KEY)
            asyncio.create_task(self._refresh_cache())
        except Exception as e:
            logger.error(f"[{integration_id}] Error storing tools: {e}")
            raise

    async def get_tools(self, integration_id: str) -> Optional[list[dict]]:
        """Get stored tools for an integration."""
        try:
            doc = await integrations_collection.find_one(
                {"integration_id": integration_id},
                {"tools": 1},
            )
            return doc.get("tools") if doc else None
        except Exception as e:
            logger.error(f"Error getting tools for {integration_id}: {e}")
            return None

    async def get_all_mcp_tools(self) -> dict[str, dict]:
        """Get all MCP tools with metadata. Redis-cached 24h."""
        cached = await get_cache(MCP_TOOLS_CACHE_KEY)
        if cached:
            return cached

        try:
            cursor = integrations_collection.find(
                {"tools": {"$exists": True, "$ne": []}},
                {"integration_id": 1, "tools": 1, "name": 1, "icon_url": 1},
            )

            grouped: dict[str, dict] = {}
            async for doc in cursor:
                integration_id = doc.get("integration_id")
                tools = doc.get("tools", [])
                if integration_id and tools:
                    grouped[integration_id] = {
                        "tools": tools,
                        "name": doc.get("name"),
                        "icon_url": doc.get("icon_url"),
                    }

            await set_cache(MCP_TOOLS_CACHE_KEY, grouped, ttl=MCP_TOOLS_CACHE_TTL)
            return grouped
        except Exception as e:
            logger.error(f"Error getting all MCP tools: {e}")
            return {}

    async def _refresh_cache(self) -> None:
        """Pre-warm cache after write."""
        try:
            cursor = integrations_collection.find(
                {"tools": {"$exists": True, "$ne": []}},
                {"integration_id": 1, "tools": 1, "name": 1, "icon_url": 1},
            )

            grouped: dict[str, dict] = {}
            async for doc in cursor:
                integration_id = doc.get("integration_id")
                tools = doc.get("tools", [])
                if integration_id and tools:
                    grouped[integration_id] = {
                        "tools": tools,
                        "name": doc.get("name"),
                        "icon_url": doc.get("icon_url"),
                    }

            await set_cache(MCP_TOOLS_CACHE_KEY, grouped, ttl=MCP_TOOLS_CACHE_TTL)
        except Exception as e:
            logger.warning(f"Failed to refresh MCP tools cache: {e}")


def get_mcp_tools_store() -> MCPToolsStore:
    """Get the global MCP tools store instance."""
    return MCPToolsStore()
