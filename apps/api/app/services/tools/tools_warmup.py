"""Tools registry warmup.

Indexes the provider-tool catalog at startup so the first `/tools` and
`retrieve_tools` calls don't pay the Composio-catalog cold start. Per-user
`/tools` responses cache on demand under `tools:user:{user_id}:*`, so there is
no global response to pre-warm.
"""

from app.agents.tools.core.registry import get_tool_registry
from app.constants.log_tags import LogTag
from shared.py.wide_events import log


async def warmup_tools_cache() -> None:
    """Index provider-tool metadata (name + description) into the registry.

    Does NOT materialize the ~1.6k catalog tools into StructuredTools — that eager
    wrapping was the dominant source of resident memory. Executable tools are built
    lazily per provider when a subagent is first created. Non-fatal: on failure the
    catalog is indexed on first use instead.
    """
    log.set(service="tools_warmup", operation="warmup_tools_cache")
    log.info(f"{LogTag.TOOL} Warming up tools cache...")
    try:
        tool_registry = await get_tool_registry()
        await tool_registry.populate_provider_catalog()
        log.info(
            f"{LogTag.TOOL} Provider catalog metadata indexed (tools materialized lazily on use)"
        )
    except Exception as e:
        log.warning(f"{LogTag.TOOL} Tools catalog warmup failed (non-fatal): {e}")
