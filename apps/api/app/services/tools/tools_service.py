"""Tools service for managing and retrieving tool information.

get_available_tools is the single source for the tools a user can use: core
(no-integration) tools plus the tools of integrations in their workspace. It is
leak-safe (only the user's own added integrations, never another user's MCP) and
self-describing — each tool carries server-computed locked (added but not
connected), so the client never re-derives lock state. Per-user results cache
under tools:user:{user_id}:*, which the integration mutators bust via
USER_INTEGRATION_CACHE_PATTERNS.
"""

from app.agents.tools.core.registry import (
    DESKTOP_TOOL_CATEGORY,
    get_tool_registry,
    integration_destructive_tools,
)
from app.config.oauth_config import all_integrations
from app.constants.cache import ONE_DAY_TTL
from app.constants.log_tags import LogTag
from app.decorators.caching import Cacheable
from app.models.tools_models import ToolInfo, ToolsCategoryResponse, ToolsListResponse
from app.schemas.integrations.responses import IntegrationToolApproval
from app.services.hil.tool_key import MCPToolIdentity, hil_tool_key
from app.services.integrations.user_integrations import (
    UserIntegrationRecord,
    get_user_integration_records,
)
from app.services.mcp.mcp_tools_service import get_all_mcp_tools, get_integration_tools
from app.utils.request_coalescing import coalesce_request
from shared.py.wide_events import log


def get_integration_name(integration_id: str) -> str | None:
    lowered = integration_id.lower()
    return next((i.name for i in all_integrations() if i.id.lower() == lowered), None)


async def get_available_tools(user_id: str | None = None) -> ToolsListResponse:
    """Return core tools plus the user's workspace integration tools, each tagged with locked.

    Anonymous callers (warmup) get core tools only. Per-user results are cached;
    the anonymous build is coalesced.
    """
    log.set(component="tools_service", operation="get_available_tools", user_id=user_id)
    if user_id is None:
        return await coalesce_request("global_tools", _build_tools_response)
    catalog: ToolsListResponse = await _get_user_tools_catalog(user_id)
    return catalog


@Cacheable(key_pattern="tools:user:{user_id}:catalog", ttl=ONE_DAY_TTL, model=ToolsListResponse)
async def _get_user_tools_catalog(user_id: str) -> ToolsListResponse:
    return await _build_tools_response(user_id)


def filter_tools_response(
    response: ToolsListResponse,
    *,
    include_desktop: bool = False,
) -> ToolsListResponse:
    """Drop desktop-only tools unless the caller is the desktop client.

    Mirrors the chat endpoint's X-Client-Type gating. Applied per-request, post-cache.
    """
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


async def _workspace_integration_ids(user_id: str | None) -> tuple[set[str], set[str]]:
    """Return the lowercased (added, connected) integration ids of the user's workspace.

    added scopes which integration tools appear at all; connected decides locked vs unlocked.
    """
    added: set[str] = set()
    connected: set[str] = set()
    if not user_id:
        return added, connected
    records: list[UserIntegrationRecord] = await get_user_integration_records(user_id)
    for record in records:
        iid = record.get("integration_id")
        if not iid:
            continue
        added.add(str(iid).lower())
        if record.get("status") == "connected":
            connected.add(str(iid).lower())
    return added, connected


async def _build_tools_response(user_id: str | None = None) -> ToolsListResponse:
    tool_infos: list[ToolInfo] = []
    seen_tool_names: set[str] = set()
    # Registry category ids can be upper/mixed case, records lowercase, so
    # membership tests go through `.lower()`.
    added, connected = await _workspace_integration_ids(user_id)
    tool_infos.extend(await _registry_tool_infos(added, connected, seen_tool_names))
    tool_infos.extend(await _mcp_tool_infos(user_id, added, connected, seen_tool_names))
    categories = {t.category for t in tool_infos}

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


async def _registry_tool_infos(
    added: set[str], connected: set[str], seen_tool_names: set[str]
) -> list[ToolInfo]:
    """Return the registry's tools: core always, integration-backed only when in the workspace."""
    tool_infos: list[ToolInfo] = []
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
                log.debug(f"{LogTag.TOOL} Skipping duplicate tool from registry", name=tool.name)
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
    return tool_infos


async def _mcp_tool_infos(
    user_id: str | None, added: set[str], connected: set[str], seen_tool_names: set[str]
) -> list[ToolInfo]:
    """Return the MCP tools (platform + custom) of integrations in the user's workspace."""
    tool_infos: list[ToolInfo] = []
    # MCP tools live only in the global store. Scoping to the workspace here is
    # also the leak guard: an entry the user hasn't added — a platform MCP they
    # never connected, or another user's custom MCP — is skipped.
    try:
        global_mcp_tools = await get_all_mcp_tools()
    except Exception as e:
        log.warning(
            f"{LogTag.TOOL} Failed to fetch MCP tools",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )
        global_mcp_tools = {}

    for integration_id, data in global_mcp_tools.items():
        iid = integration_id.lower()
        if iid not in added:
            continue
        display_name = (
            data.name
            or get_integration_name(integration_id)
            or integration_id.replace("_", " ").title()
        )
        icon_url = data.icon_url
        locked = iid not in connected
        for stored_tool in data.tools:
            tool_name = stored_tool.name
            if not tool_name:
                log.warning(
                    f"{LogTag.TOOL} Skipping tool with missing 'name' from custom MCP",
                    integration_id=integration_id,
                    user_id=user_id,
                )
                continue
            if tool_name in seen_tool_names:
                log.debug(
                    f"{LogTag.TOOL} Skipping duplicate tool from custom MCP",
                    integration_id=integration_id,
                    tool_name=tool_name,
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
    return tool_infos


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


async def get_integration_tool_list(integration_id: str) -> list[IntegrationToolApproval]:
    """Return one integration's tools from the registry catalog, else the MCP store.

    destructive is the curated HIL default (False for MCP tools). approval_key is
    the key the gate reads the user's override under; stored MCP names are the
    server's own names, which that key is built from.
    """
    destructive = integration_destructive_tools(integration_id) or set()
    tool_registry = await get_tool_registry()
    for name, category_obj in tool_registry.get_all_category_objects().items():
        if category_obj.internal or name.lower() != integration_id.lower():
            continue
        return [
            IntegrationToolApproval(
                name=tool.name,
                description=tool.tool.description,
                # The registry stamped this from the same curated set at add time
                # and is the single source of truth — it also carries LLM
                # classifications written back via mark_tool_destructive.
                destructive=bool(tool.destructive),
                approval_key=hil_tool_key(tool.name, None),
            )
            for tool in category_obj.tools
        ]

    stored = await get_integration_tools(integration_id)
    return [
        IntegrationToolApproval(
            name=tool.name,
            description=tool.description,
            destructive=tool.name in destructive,
            approval_key=hil_tool_key(
                tool.name, MCPToolIdentity(integration_id=integration_id, server_name=tool.name)
            ),
        )
        for tool in stored
        if tool.name
    ]
