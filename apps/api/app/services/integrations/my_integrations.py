"""The current user's personalized integration catalog.

get_my_integrations is the single server-side merge of the platform catalog,
the user's custom integrations, and their connection status — the work the web
client used to do across three calls (/config + /status + /users/me/integrations).
It returns lightweight items (status + tool_count, no per-tool schemas); full
tools are fetched on demand via get_integration_tools.
"""

import asyncio
from typing import cast

from app.constants.cache import ONE_DAY_TTL
from app.decorators.caching import Cacheable
from app.models.integration_models import UserIntegrationsListResponse
from app.schemas.integrations.responses import (
    CommunityIntegrationCreator,
    IntegrationToolsResponse,
    MyIntegrationItem,
    MyIntegrationsResponse,
)
from app.services.integrations.integration_connection_service import build_integrations_config
from app.services.integrations.integration_resolver import IntegrationResolver
from app.services.integrations.integration_status import get_all_integrations_status
from app.services.integrations.user_integrations import (
    check_user_has_integration,
    get_user_integrations,
)
from app.services.tools.tools_service import get_integration_tool_list, get_tool_categories
from app.utils.errors import create_error
from shared.py.wide_events import log


async def get_my_integrations(user_id: str) -> MyIntegrationsResponse:
    """Return the cached integration catalog with current auth-MCP status."""
    status_map = await get_all_integrations_status(user_id)
    result = cast(
        MyIntegrationsResponse,
        await _get_cached_my_integrations(user_id, status_map),
    )
    stale_mcp_ids = {
        item.id
        for item in result.integrations
        if item.status == "connected"
        and item.managed_by == "mcp"
        and item.requires_auth
        and not status_map.get(item.id, False)
    }
    if not stale_mcp_ids:
        return result
    return result.model_copy(
        update={
            "integrations": [
                item.model_copy(update={"status": "created"}) if item.id in stale_mcp_ids else item
                for item in result.integrations
            ]
        }
    )


async def get_my_integrations_snapshot(user_id: str) -> MyIntegrationsResponse:
    """Return the cached catalog from Mongo without external status checks."""
    return cast(
        MyIntegrationsResponse,
        await _get_cached_my_integrations_snapshot(user_id),
    )


@Cacheable(
    key_pattern="tools:user:{user_id}:my_snapshot",
    ttl=ONE_DAY_TTL,
    model=MyIntegrationsResponse,
)
async def _get_cached_my_integrations_snapshot(user_id: str) -> MyIntegrationsResponse:
    added, category_counts = await asyncio.gather(
        get_user_integrations(user_id),
        get_tool_categories(),
    )
    status_map = {item.integration_id: item.status == "connected" for item in added.integrations}
    return _build_my_integrations_response(user_id, status_map, added, category_counts)


@Cacheable(
    key_pattern="tools:user:{user_id}:my",
    ttl=ONE_DAY_TTL,
    model=MyIntegrationsResponse,
)
async def _get_cached_my_integrations(
    user_id: str, status_map: dict[str, bool]
) -> MyIntegrationsResponse:
    """Build the cached catalog after the live MCP credential check."""
    log.set(component="my_integrations", operation="get_my_integrations", user={"id": user_id})
    added, category_counts = await asyncio.gather(
        get_user_integrations(user_id),
        get_tool_categories(),
    )
    return _build_my_integrations_response(user_id, status_map, added, category_counts)


def _build_my_integrations_response(
    user_id: str,
    status_map: dict[str, bool],
    added: UserIntegrationsListResponse,
    category_counts: dict[str, int],
) -> MyIntegrationsResponse:
    config = build_integrations_config()

    # Registry tool counts are keyed by (often upper-case) category; the user's
    # own tool lists give exact counts for custom/MCP integrations.
    counts = {name.lower(): count for name, count in category_counts.items()}
    added_by_id = {ui.integration_id.lower(): ui for ui in added.integrations}
    platform_ids = {item.id.lower() for item in config.integrations}

    items: list[MyIntegrationItem] = []

    for cfg in config.integrations:
        ui = added_by_id.get(cfg.id.lower())
        status = (
            ui.status
            if ui is not None
            else ("connected" if status_map.get(cfg.id) else "not_connected")
        )
        tool_count = (
            (len(ui.integration.tools) or counts.get(cfg.id.lower(), 0))
            if ui is not None
            else counts.get(cfg.id.lower(), 0)
        )
        items.append(
            MyIntegrationItem(
                id=cfg.id,
                name=cfg.name,
                description=cfg.description,
                category=cfg.category,
                source="platform",
                managed_by=cfg.managed_by,
                status=status,
                expired_at=ui.expired_at if ui is not None else None,
                requires_auth=cfg.requires_auth,
                auth_type=cfg.auth_type,
                is_featured=cfg.is_featured,
                display_priority=cfg.display_priority,
                available=cfg.available,
                slug=cfg.slug,
                tool_count=tool_count,
            )
        )

    for ui in added.integrations:
        if ui.integration_id.lower() in platform_ids:
            continue  # platform integrations are already emitted above
        integ = ui.integration
        items.append(
            MyIntegrationItem(
                id=ui.integration_id,
                name=integ.name,
                description=integ.description,
                category=integ.category,
                source="custom",
                managed_by=integ.managed_by,
                status=ui.status,
                expired_at=ui.expired_at,
                requires_auth=integ.requires_auth,
                auth_type=integ.auth_type,
                is_featured=integ.is_featured,
                display_priority=integ.display_priority,
                icon_url=integ.icon_url,
                slug=integ.slug,
                tool_count=len(integ.tools),
                is_public=integ.is_public,
                created_by=integ.created_by,
                published_at=integ.published_at,
                clone_count=integ.clone_count,
                creator=CommunityIntegrationCreator.model_validate(integ.creator)
                if integ.creator
                else None,
            )
        )

    log.set(result_count=len(items), outcome="success")
    return MyIntegrationsResponse(integrations=items, total=len(items))


async def get_integration_tools(integration_id: str, user_id: str) -> IntegrationToolsResponse:
    """Full tool list for one integration, on demand.

    Authorization: platform integrations are always readable; a custom integration
    is readable only when it is public, owned by the caller, or already in the
    caller's workspace — so one user can't read another's private MCP tools. Raises
    AppError(403) otherwise.
    """
    resolved = await IntegrationResolver.resolve(integration_id)
    if resolved is None:
        return IntegrationToolsResponse(integration_id=integration_id, tools=[], count=0)

    if resolved.source == "custom":
        doc = resolved.custom_doc or {}
        visible = (
            bool(doc.get("is_public"))
            or doc.get("created_by") == user_id
            or await check_user_has_integration(user_id, integration_id)
        )
        if not visible:
            raise create_error(
                message="Integration not accessible",
                why="This integration is private and not in your workspace",
                status_code=403,
            )

    tools = await get_integration_tool_list(integration_id)
    return IntegrationToolsResponse(integration_id=integration_id, tools=tools, count=len(tools))
