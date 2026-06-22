"""Tools service for managing and retrieving tool information.

`get_available_tools` is the single source for the tools a user can use: core
(no-integration) tools plus the tools of integrations in their workspace. It is
leak-safe (only the user's own added integrations, never another user's MCP) and
self-describing — each tool carries server-computed `locked` (added but not
connected), so the client never re-derives lock state. Per-user results cache
under `tools:user:{user_id}:*`, which the integration mutators bust via
`USER_INTEGRATION_CACHE_PATTERNS`.
"""

from typing import Any

from app.agents.tools.core.registry import DESKTOP_TOOL_CATEGORY, get_tool_registry
from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.constants.cache import ONE_DAY_TTL
from app.constants.log_tags import LogTag
from app.decorators.caching import Cacheable
from app.models.tools_models import ToolInfo, ToolsCategoryResponse, ToolsListResponse
from app.schemas.integrations.responses import IntegrationTool
from app.services.integrations.user_integrations import get_user_integration_records
from app.services.mcp.mcp_tools_store import get_mcp_tools_store
from app.utils.request_coalescing import coalesce_request
from shared.py.wide_events import log

_INTEGRATION_NAME_MAP: dict[str, str] = {
    integration.id.lower(): integration.name for integration in OAUTH_INTEGRATIONS
}


def get_integration_name(integration_id: str) -> str | None:
    return _INTEGRATION_NAME_MAP.get(integration_id.lower())


async def get_available_tools(user_id: str | None = None) -> ToolsListResponse:
    """Core tools + the tools of the user's workspace integrations, each tagged
    with `locked`. Anonymous callers (warmup) get core tools only. Per-user
    results are cached; the anonymous build is coalesced."""
    log.set(service="tools_service", operation="get_available_tools", user_id=user_id)
    if user_id is None:
        return await coalesce_request("global_tools", _build_tools_response)
    return await _get_user_tools_catalog(user_id)


@Cacheable(key_pattern="tools:user:{user_id}:catalog", ttl=ONE_DAY_TTL, model=ToolsListResponse)
async def _get_user_tools_catalog(user_id: str) -> ToolsListResponse:
    return await _build_tools_response(user_id)


def filter_tools_response(
    response: ToolsListResponse,
    *,
    include_desktop: bool = False,
) -> ToolsListResponse:
    """Drop desktop-only tools unless the caller is the desktop client (mirrors
    the chat endpoint's X-Client-Type gating). Applied per-request, post-cache."""
    if include_desktop:
        return response
    tools = [t for t in response.tools if t.category != DESKTOP_TOOL_CATEGORY]
    if len(tools) == len(response.tools):
        return response
    return ToolsListResponse(
        tools=tools,
        total_count=len(tools),
        categories=sorted({t.category for t in tools}),
    )


async def _build_tools_response(user_id: str | None = None) -> ToolsListResponse:
    tool_infos: list[ToolInfo] = []
    categories: set[str] = set()
    seen_tool_names: set[str] = set()

    # The user's workspace: every integration they've added. `added` scopes which
    # integration tools appear at all; `connected` decides locked vs unlocked.
    # Registry category ids can be upper/mixed case (Composio toolkits) while
    # records are lowercase, so all membership tests go through `.lower()`.
    added: set[str] = set()
    connected: set[str] = set()
    if user_id:
        for record in await get_user_integration_records(user_id):
            iid = record.get("integration_id")
            if not iid:
                continue
            added.add(str(iid).lower())
            if record.get("status") == "connected":
                connected.add(str(iid).lower())

    tool_registry = await get_tool_registry()
    _categories = tool_registry.get_all_category_objects(ignore_categories=["delegation"])

    for category, category_obj in _categories.items():
        if category_obj.internal:
            continue
        requires_integration = category_obj.require_integration
        cat_id = category.lower()
        # Integration-backed tools only surface for integrations in the workspace;
        # core tools (no integration) are always available.
        if requires_integration and cat_id not in added:
            continue
        locked = requires_integration and cat_id not in connected
        for tool in category_obj.tools:
            if tool.name in seen_tool_names:
                log.debug(f"{LogTag.TOOL} Skipping duplicate tool from registry: {tool.name}")
                continue
            seen_tool_names.add(tool.name)
            tool_infos.append(
                ToolInfo(
                    name=tool.name,
                    category=category,
                    display_name=get_integration_name(category)
                    or category.replace("_", " ").title(),
                    icon_url=None,
                    requires_integration=requires_integration,
                    locked=locked,
                )
            )
            categories.add(category)

    # MCP tools (platform + custom) live only in the global store. Scoping to the
    # workspace here is also the leak guard: an entry the user hasn't added — a
    # platform MCP they never connected, or another user's custom MCP — is skipped.
    mcp_store = get_mcp_tools_store()
    try:
        global_mcp_tools: dict[str, dict[str, Any]] = await mcp_store.get_all_mcp_tools()
    except Exception as e:
        log.warning(f"{LogTag.TOOL} Failed to fetch MCP tools: {e}")
        global_mcp_tools = {}

    for integration_id, data in global_mcp_tools.items():
        iid = integration_id.lower()
        if iid not in added:
            continue
        display_name = (
            data.get("name")
            or get_integration_name(integration_id)
            or integration_id.replace("_", " ").title()
        )
        icon_url = data.get("icon_url")
        locked = iid not in connected
        for tool_dict in data.get("tools", []):
            tool_name = tool_dict.get("name")
            if not tool_name:
                log.warning(
                    f"{LogTag.TOOL} Skipping tool with missing 'name' from custom MCP {integration_id}"
                )
                continue
            if tool_name in seen_tool_names:
                log.debug(
                    f"{LogTag.TOOL} Skipping duplicate tool from custom MCP {integration_id}: {tool_name}"
                )
                continue
            seen_tool_names.add(tool_name)
            tool_infos.append(
                ToolInfo(
                    name=tool_name,
                    category=integration_id,
                    display_name=display_name,
                    icon_url=icon_url,
                    requires_integration=True,
                    locked=locked,
                )
            )
            categories.add(integration_id)

    log.set(
        tools={
            "total_count": len(tool_infos),
            "locked_count": sum(1 for t in tool_infos if t.locked),
            "category_count": len(categories),
        }
    )
    return ToolsListResponse(
        tools=tool_infos,
        total_count=len(tool_infos),
        categories=sorted(categories),
    )


async def get_tools_by_category(category: str) -> ToolsCategoryResponse:
    tool_registry = await get_tool_registry()
    category_obj = tool_registry.get_category(category)

    if not category_obj or category_obj.internal:
        return ToolsCategoryResponse(category=category, tools=[], count=0)

    tool_infos = []
    for tool in category_obj.tools:
        tool_info = ToolInfo(
            name=tool.name,
            category=category,
            display_name=get_integration_name(category) or category.replace("_", " ").title(),
        )
        tool_infos.append(tool_info)

    return ToolsCategoryResponse(category=category, tools=tool_infos, count=len(tool_infos))


async def get_tool_categories() -> dict[str, int]:
    category_counts: dict[str, int] = {}
    tool_registry = await get_tool_registry()
    all_categories = tool_registry.get_all_category_objects()

    for category_name, category_obj in all_categories.items():
        if category_obj.internal:
            continue
        category_counts[category_name] = len(category_obj.tools)

    return category_counts


async def get_integration_tool_list(integration_id: str) -> list[IntegrationTool]:
    """Full tool list for one integration from its source of truth: the registry
    catalog for Composio/platform toolkits, the MCP store for MCP/custom servers.

    Registry category ids may be upper/mixed case, so the match is case-insensitive.
    """
    tool_registry = await get_tool_registry()
    for name, category_obj in tool_registry.get_all_category_objects().items():
        if category_obj.internal or name.lower() != integration_id.lower():
            continue
        return [
            IntegrationTool(name=tool.name, description=tool.description)
            for tool in category_obj.tools
        ]

    stored = await get_mcp_tools_store().get_tools(integration_id)
    return [
        IntegrationTool(name=tool["name"], description=tool.get("description"))
        for tool in stored
        if tool.get("name")
    ]
