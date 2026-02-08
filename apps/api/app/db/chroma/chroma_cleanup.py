"""ChromaDB cleanup utilities for integration lifecycle management."""

from app.config.loggers import app_logger as logger
from app.constants.cache import SUBAGENT_CACHE_PREFIX
from app.core.lazy_loader import providers
from app.db.chroma.chroma_tools_store import delete_tools_by_namespace
from app.db.redis import delete_cache
from app.helpers.namespace_utils import derive_integration_namespace


async def cleanup_integration_chroma_data(
    integration_id: str,
    server_url: str,
) -> dict[str, bool]:
    """Clean up all ChromaDB data for an integration.

    Removes:
    1. Subagent discovery entry from ("subagents",) namespace
    2. All indexed tools under the integration's namespace
    3. Redis caches (namespace hash + subagent cache)

    Args:
        integration_id: The integration's unique ID
        server_url: The MCP server URL (used for namespace derivation)

    Returns:
        Dict with cleanup status for each component:
        - "subagent": Whether subagent entry was deleted
        - "tools": Whether tools were deleted
        - "cache": Whether cache was invalidated
    """
    results = {"subagent": False, "tools": False, "cache": False}

    namespace = derive_integration_namespace(integration_id, server_url, is_custom=True)

    # 1. Delete subagent discovery entry
    try:
        store = await providers.aget("chroma_tools_store")
        if store:
            await store.adelete(namespace=("subagents",), key=integration_id)
            results["subagent"] = True
            logger.debug(f"Deleted subagent entry for {integration_id}")
    except Exception as e:
        logger.warning(f"Failed to delete subagent entry for {integration_id}: {e}")

    # 2. Delete indexed tools
    try:
        deleted_count = await delete_tools_by_namespace(namespace)
        results["tools"] = True
        logger.info(f"Deleted {deleted_count} tools for namespace '{namespace}'")
    except Exception as e:
        logger.warning(f"Failed to delete tools for namespace '{namespace}': {e}")

    # 3. Invalidate caches
    try:
        await delete_cache(f"chroma:indexed:{namespace}")
        await delete_cache(f"{SUBAGENT_CACHE_PREFIX}:{integration_id}")
        results["cache"] = True
    except Exception as e:
        logger.warning(f"Failed to invalidate cache for namespace '{namespace}': {e}")

    return results
