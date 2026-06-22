"""User integration management functions."""

import asyncio
from datetime import UTC, datetime
from typing import Any, Literal

from bson import ObjectId

from app.agents.tools.core.registry import get_tool_registry
from app.config.oauth_config import get_integration_by_id
from app.constants.cache import ONE_DAY_TTL, USER_INTEGRATION_CACHE_PATTERNS
from app.constants.log_tags import LogTag
from app.db.mongodb.collections import (
    integrations_collection,
    user_integrations_collection,
    users_collection,
)
from app.db.redis import delete_cache
from app.db.utils import serialize_document
from app.decorators.caching import Cacheable, CacheInvalidator
from app.models.integration_models import (
    IntegrationResponse,
    IntegrationTool,
    UserIntegration,
    UserIntegrationResponse,
    UserIntegrationsListResponse,
)
from app.services.integrations.marketplace import (
    assemble_integration_response,
    get_integration_details,
)
from shared.py.wide_events import log


def _build_integration_response(
    integration_id: str, doc: dict | None, creators: dict[str, dict]
) -> IntegrationResponse | None:
    """Build an IntegrationResponse from prefetched data — no per-item DB queries.

    The batch-prefetched counterpart to get_integration_details: platform metadata
    from the in-memory catalog, custom metadata + stored MCP tools from ``doc``,
    creator from the prefetched ``creators`` map. Shares the assembly step with
    get_integration_details via assemble_integration_response.
    """
    created_by = doc.get("created_by") if doc else None
    creator_doc = creators.get(created_by) if created_by else None
    return assemble_integration_response(
        get_integration_by_id(integration_id),
        doc,
        doc.get("tools") if doc else None,
        creator_doc,
    )


async def get_user_integrations(user_id: str) -> UserIntegrationsListResponse:
    """Get all integrations a user has added to their workspace."""
    docs = (
        await user_integrations_collection.find({"user_id": user_id})
        .sort("created_at", -1)
        .to_list(None)
    )

    parsed: list[UserIntegration] = []
    for doc in docs:
        try:
            parsed.append(UserIntegration(**doc))
        except Exception as e:
            log.warning(f"{LogTag.INTEGRATION} Failed to parse user integration: {e}")

    ids = [ui.integration_id for ui in parsed]

    # One query for every integration's stored doc (custom metadata + stored MCP
    # tools). Platform metadata comes from the in-memory catalog, so there are no
    # per-integration DB round trips.
    int_docs: dict[str, dict] = {}
    if ids:
        async for doc in integrations_collection.find({"integration_id": {"$in": ids}}):
            int_docs[doc["integration_id"]] = doc

    # One query for all creators referenced by the user's custom integrations.
    creator_oids = [
        ObjectId(doc["created_by"])
        for doc in int_docs.values()
        if doc.get("created_by") and ObjectId.is_valid(doc["created_by"])
    ]
    creators: dict[str, dict] = {}
    if creator_oids:
        async for creator in users_collection.find(
            {"_id": {"$in": creator_oids}}, {"name": 1, "picture": 1}
        ):
            creators[str(creator["_id"])] = creator

    user_integrations: list[UserIntegrationResponse] = []
    for ui in parsed:
        integration = _build_integration_response(
            ui.integration_id, int_docs.get(ui.integration_id), creators
        )
        if not integration:
            continue
        user_integrations.append(
            UserIntegrationResponse(
                integration_id=ui.integration_id,
                status=ui.status,
                created_at=ui.created_at,
                connected_at=ui.connected_at,
                integration=integration,
            )
        )

    return UserIntegrationsListResponse(
        integrations=user_integrations,
        total=len(user_integrations),
    )


@Cacheable(key_pattern="tools:user:{user_id}:integrations", ttl=ONE_DAY_TTL)
async def get_user_integration_records(user_id: str) -> list[dict[str, Any]]:
    """Return the raw records for all of a user's integrations.

    Includes both ``created`` (added, not yet authenticated) and ``connected``
    states — callers that only want usable integrations filter on
    ``status == "connected"`` (see ``get_connected_integration_ids``).
    """
    results = []
    cursor = user_integrations_collection.find({"user_id": user_id})

    async for doc in cursor:
        results.append(serialize_document(doc))

    return results


async def get_connected_integration_ids(user_id: str) -> set[str]:
    """Return the integration ids the user has actually *connected*.

    Single source of the ``status == "connected"`` filter shared by the
    workspace materializers (chat path, registration, integration sync, bulk
    sync) so they can never disagree on what "connected" means.
    """
    docs = await get_user_integration_records(user_id)
    return {
        str(d["integration_id"])
        for d in docs
        if d.get("status") == "connected" and d.get("integration_id")
    }


@Cacheable(key_pattern="tools:user:{user_id}:connected_named", ttl=ONE_DAY_TTL)
async def get_connected_integrations_named(user_id: str) -> list[dict[str, str]]:
    """Connected integration ids paired with their display name (platform + custom).

    Platform names resolve from the in-memory OAuth config; custom MCP names (whose
    ids are UUIDs and are absent from that config) come from a single batched
    catalog query rather than degrading to a bare id. Used to render the
    agent-facing connected-integrations manifest. Cached and invalidated on the
    same ``tools:user:{user_id}:*`` family as the other per-user integration
    caches, so connect/disconnect is reflected immediately.
    """
    connected = sorted(await get_connected_integration_ids(user_id))
    if not connected:
        return []

    names: dict[str, str] = {}
    unresolved: list[str] = []
    for iid in connected:
        integration = get_integration_by_id(iid)
        if integration:
            names[iid] = integration.name
        else:
            unresolved.append(iid)

    if unresolved:
        async for doc in integrations_collection.find(
            {"integration_id": {"$in": unresolved}}, {"integration_id": 1, "name": 1}
        ):
            if name := doc.get("name"):
                names[str(doc["integration_id"])] = name

    return [{"id": iid, "name": names.get(iid, iid)} for iid in connected]


async def invalidate_user_integration_caches(user_id: str) -> None:
    """Bust every cache derived from this user's integration set.

    The imperative twin of the ``@CacheInvalidator(USER_INTEGRATION_CACHE_PATTERNS)``
    on the canonical mutators, for paths that change a user's integrations without
    going through them (e.g. direct ``user_integrations_collection`` writes). Uses
    the SAME pattern list so no caller can bust a partial set and let one cache
    (e.g. OAUTH_STATUS) drift out of sync with the others.
    """
    # gather (not a sequential loop) so one failing delete doesn't skip the
    # rest — every pattern is attempted. Mirrors the @CacheInvalidator decorator
    # exactly, and still propagates the error (fail loud, never a partial silent
    # success).
    await asyncio.gather(
        *(
            delete_cache(pattern.format(user_id=user_id))
            for pattern in USER_INTEGRATION_CACHE_PATTERNS
        )
    )


@CacheInvalidator(key_patterns=USER_INTEGRATION_CACHE_PATTERNS)
async def add_user_integration(
    user_id: str,
    integration_id: str,
    initial_status: Literal["created", "connected"] | None = None,
) -> UserIntegration:
    """Add an integration to user's workspace."""
    log.set(integration={"provider": integration_id, "action": "add_user_integration"})
    integration = await get_integration_details(integration_id)
    if not integration:
        raise ValueError(f"Integration '{integration_id}' not found")

    existing = await user_integrations_collection.find_one(
        {
            "user_id": user_id,
            "integration_id": integration_id,
        }
    )
    if existing:
        raise ValueError(f"Integration '{integration_id}' already added to workspace")

    status: Literal["created", "connected"]
    if initial_status:
        status = initial_status
    else:
        status = "connected" if not integration.requires_auth else "created"
    connected_at = datetime.now(UTC) if status == "connected" else None

    user_integration = UserIntegration(
        user_id=user_id,
        integration_id=integration_id,
        status=status,
        created_at=datetime.now(UTC),
        connected_at=connected_at,
    )

    await user_integrations_collection.insert_one(user_integration.model_dump())
    log.info(
        f"{LogTag.INTEGRATION} User {user_id} added integration {integration_id} with status {status}"
    )

    return user_integration


@CacheInvalidator(key_patterns=USER_INTEGRATION_CACHE_PATTERNS)
async def remove_user_integration(user_id: str, integration_id: str) -> bool:
    """Remove an integration from user's workspace."""
    log.set(integration={"provider": integration_id, "action": "remove_user_integration"})
    result = await user_integrations_collection.delete_one(
        {
            "user_id": user_id,
            "integration_id": integration_id,
        }
    )

    if result.deleted_count > 0:
        log.info(f"{LogTag.INTEGRATION} User {user_id} removed integration {integration_id}")
        return True

    return False


async def check_user_has_integration(user_id: str, integration_id: str) -> bool:
    """Check if a user has added a specific integration."""
    doc = await user_integrations_collection.find_one(
        {
            "user_id": user_id,
            "integration_id": integration_id,
        }
    )
    return doc is not None


@Cacheable(key_pattern="tools:user:{user_id}:integration_capabilities", ttl=ONE_DAY_TTL)
async def get_user_integration_capabilities(user_id: str) -> dict[str, Any]:
    """
    Get capabilities (tools) for user's connected integrations + core tools.

    This is optimized for follow-up action generation to avoid passing
    all tools to the LLM. Instead, only tools from user's connected
    integrations plus core built-in tools are included.

    Returns:
        Dict with:
        - integration_names: List of connected integration names
        - tool_names: List of available tool names (core + integrations)
        - capabilities: Dict mapping integration_id -> list of tool info
    """

    # Get core tools that are always available (categories that don't require integration)
    tool_registry = await get_tool_registry()
    core_categories = tool_registry.get_core_categories()

    tool_names_set = set()

    # Add core tool names
    for category in core_categories:
        for tool in category.tools:
            tool_names_set.add(tool.name)

    # Only the user's *connected* (authenticated) integrations. These tool names
    # feed user-clickable follow-up suggestions, so a merely-added but
    # not-yet-connected integration must not surface — its suggested action would
    # fail at execution time.
    connected_ids = await get_connected_integration_ids(user_id)

    integration_names = []
    capabilities = {}

    for integration_id in connected_ids:
        # Get integration details with tools
        integration = await get_integration_details(integration_id)
        if not integration:
            continue

        integration_names.append(integration.name)

        # Extract tool names and descriptions
        tools_info = []
        integration_tool: IntegrationTool
        for integration_tool in integration.tools:
            tool_names_set.add(integration_tool.name)
            tools_info.append(
                {
                    "name": integration_tool.name,
                    "description": integration_tool.description or "",
                }
            )

        if tools_info:
            capabilities[integration_id] = {
                "name": integration.name,
                "tools": tools_info,
            }

    return {
        "integration_names": integration_names,
        "tool_names": list(tool_names_set),
        "capabilities": capabilities,
    }
