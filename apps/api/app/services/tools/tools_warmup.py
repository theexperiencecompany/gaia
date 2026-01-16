"""
Tools cache warmup service.

Pre-loads provider tools and warms the global cache at startup,
eliminating cold-start latency for the /tools endpoint.
"""

from app.config.loggers import app_logger as logger
from app.db.redis import set_cache

# Global tools cache key - shared across all users
GLOBAL_TOOLS_CACHE_KEY = "tools:global"
GLOBAL_TOOLS_CACHE_TTL = 21600  # 6 hours


async def warmup_tools_cache() -> None:
    """
    Pre-load tools and warm the global cache at startup.

    This function:
    1. Loads provider tools into registry (Composio integrations)
    2. Builds and caches the global tools response

    Called from lifespan to ensure tools are ready before serving requests.
    """
    from app.agents.tools.core.registry import get_tool_registry
    from app.services.tools.tools_service import get_available_tools

    logger.info("Warming up tools cache...")

    try:
        # 1. Load provider tools into registry (Composio integrations)
        tool_registry = await get_tool_registry()
        await tool_registry.load_all_provider_tools()
        logger.info("Provider tools loaded into registry")

        # 2. Build and cache global tools response
        # Pass None for user_id to get only global tools (no user-specific overlays)
        global_tools = await get_available_tools(user_id=None)

        # Cache the serialized response for fast retrieval
        await set_cache(
            GLOBAL_TOOLS_CACHE_KEY,
            global_tools.model_dump(),
            ttl=GLOBAL_TOOLS_CACHE_TTL,
        )

        logger.info(
            f"Tools cache warmed with {global_tools.total_count} tools "
            f"across {len(global_tools.categories)} categories"
        )

    except Exception as e:
        # Don't fail startup if warmup fails - tools will be loaded on first request
        logger.warning(f"Tools cache warmup failed (non-fatal): {e}")
