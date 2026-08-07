"""Global MCP tool metadata: Redis-cached roll-up over the integrations repository.

The repository owns the Mongo access (typed); this service adds the aggregate cache
(``MCP_TOOLS_CACHE_KEY``) and the dict-shaped views its callers consume. Writes bust
the roll-up cache so a freshly stored tool set is reflected on the next read.
"""

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any, cast

from app.constants.cache import MCP_TOOLS_CACHE_KEY, MCP_TOOLS_CACHE_TTL
from app.constants.log_tags import LogTag
from app.db.redis import delete_cache, get_cache, set_cache
from app.db.repositories.integrations import integration_repository
from app.models.integration_models import IntegrationTool
from shared.py.wide_events import log

# One raw tool entry as the callers build it — ``{"name": ..., "description": ...}``
# assembled from LangChain/Composio tool objects. It stays a mapping rather than a
# model because ``_format_tools`` is the validation boundary (Type Safety item 8):
# it drops nameless entries and returns real ``IntegrationTool`` models.
RawToolMetadata = Mapping[str, Any]

# Background refresh tasks are held here so they are not garbage-collected mid-flight.
_background_tasks: set[asyncio.Task[None]] = set()


def _format_tools(tools: Sequence[RawToolMetadata]) -> list[IntegrationTool]:
    """Normalize raw tool dicts: strip whitespace, drop entries without a name."""
    formatted: list[IntegrationTool] = []
    for tool in tools:
        name = tool.get("name", "").strip()
        if name:
            formatted.append(
                IntegrationTool(name=name, description=(tool.get("description") or "").strip())
            )
    return formatted


async def _refresh_cache() -> None:
    """Pre-warm the roll-up cache after a write (re-queries since the key was busted)."""
    try:
        await get_all_mcp_tools()
    except Exception as e:
        log.warning(f"{LogTag.MCP} Failed to refresh MCP tools cache: {e}")


def _schedule_refresh() -> None:
    task = asyncio.create_task(_refresh_cache())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def store_mcp_tools(integration_id: str, tools: Sequence[RawToolMetadata]) -> None:
    """Store tools for one MCP integration globally, then refresh the roll-up cache."""
    formatted = _format_tools(tools)
    if not formatted:
        return
    try:
        await integration_repository.store_tools(integration_id, formatted)
        await delete_cache(MCP_TOOLS_CACHE_KEY)
        _schedule_refresh()
    except Exception as e:
        log.error(f"{LogTag.MCP} [{integration_id}] Error storing tools: {e}")
        raise


async def store_mcp_tools_batch(items: Sequence[tuple[str, Sequence[RawToolMetadata]]]) -> None:
    """Store tools for several integrations in one pass, then refresh the roll-up cache."""
    formatted_items = [
        (integration_id, formatted)
        for integration_id, tools in items
        if (formatted := _format_tools(tools))
    ]
    if not formatted_items:
        return
    try:
        await integration_repository.store_tools_batch(formatted_items)
        await delete_cache(MCP_TOOLS_CACHE_KEY)
        _schedule_refresh()
    except Exception as e:
        log.error(f"{LogTag.MCP} Error storing tools batch: {e}")
        raise


async def get_integration_tools(integration_id: str) -> list[dict[str, Any]]:
    """Stored tools for an integration as plain dicts (frontend/display consumers)."""
    try:
        tools = await integration_repository.get_tools(integration_id)
        return [t.model_dump() for t in tools]
    except Exception as e:
        log.error(f"{LogTag.MCP} Error getting tools for {integration_id}: {e}")
        return []


async def get_all_mcp_tools() -> dict[str, dict[str, Any]]:
    """All MCP tools with metadata, keyed by integration_id. Redis-cached 24h."""
    cached = await get_cache(MCP_TOOLS_CACHE_KEY)
    if cached:
        # get_cache is typed Any; this key is only ever written below as
        # the `grouped` roll-up.
        return cast(dict[str, dict[str, Any]], cached)

    try:
        grouped: dict[str, dict[str, Any]] = {
            record.integration_id: {
                "tools": [t.model_dump() for t in record.tools],
                "name": record.name,
                "icon_url": record.icon_url,
            }
            for record in await integration_repository.all_with_tools()
            if record.integration_id and record.tools
        }
        await set_cache(MCP_TOOLS_CACHE_KEY, grouped, ttl=MCP_TOOLS_CACHE_TTL)
        return grouped
    except Exception as e:
        log.error(f"{LogTag.MCP} Error getting all MCP tools: {e}")
        return {}
