"""
Integration Service for MCP Marketplace.

This service handles:
- Hybrid integration retrieval (platform + custom integrations)
- User integration management (add/remove/connect)
- Custom integration CRUD operations
- Tool loading based on user's connected integrations
"""

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any, Dict, List, Literal, Optional

from app.config.loggers import app_logger as logger
from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.db.mongodb.collections import (
    integrations_collection,
    user_integrations_collection,
    users_collection,
)
from app.decorators.caching import CacheInvalidator
from app.models.integration_models import (
    CreateCustomIntegrationRequest,
    Integration,
    IntegrationResponse,
    IntegrationTool,
    MarketplaceResponse,
    UpdateCustomIntegrationRequest,
    UserIntegration,
    UserIntegrationResponse,
    UserIntegrationsListResponse,
)
from app.models.oauth_models import MCPConfig
from app.services.integrations.integration_resolver import IntegrationResolver
from app.services.mcp.mcp_tools_store import get_mcp_tools_store
from bson import ObjectId


async def get_all_integrations(
    category: Optional[str] = None,
    include_custom_public: bool = True,
) -> MarketplaceResponse:
    """
    Get all available integrations for the marketplace.

    Combines (fetched in parallel):
    - Platform integrations from OAUTH_INTEGRATIONS (code)
    - Public custom integrations from MongoDB (if include_custom_public=True)
    - Global MCP tools for hydration

    Args:
        category: Optional category filter
        include_custom_public: Whether to include public custom integrations

    Returns:
        MarketplaceResponse with featured and all integrations
    """
    tools_store = get_mcp_tools_store()

    async def fetch_mcp_tools() -> dict[str, list[dict]]:
        return await tools_store.get_all_mcp_tools()

    async def fetch_custom_integrations() -> list[IntegrationResponse]:
        if not include_custom_public:
            return []

        custom_integrations = []
        query = {"source": "custom", "is_public": True}
        if category:
            query["category"] = category

        cursor = integrations_collection.find(query).sort("created_at", -1)
        async for doc in cursor:
            try:
                integration = Integration(**doc)
                custom_integrations.append(
                    IntegrationResponse.from_integration(integration)
                )
            except Exception as e:
                logger.warning(f"Failed to parse custom integration: {e}")

        return custom_integrations

    # Fetch MCP tools and custom integrations in parallel
    all_mcp_tools, custom_integrations = await asyncio.gather(
        fetch_mcp_tools(),
        fetch_custom_integrations(),
    )

    # Build platform integrations (synchronous, just iterating code config)
    platform_integrations = []
    for oauth_int in OAUTH_INTEGRATIONS:
        if not oauth_int.available:
            continue
        if category and oauth_int.category != category:
            continue

        response = IntegrationResponse.from_oauth_integration(oauth_int)

        # Hydrate tools from global store if available
        stored_tools = all_mcp_tools.get(oauth_int.id, [])
        if stored_tools:
            response.tools = [
                IntegrationTool(name=t["name"], description=t.get("description"))
                for t in stored_tools
            ]

        platform_integrations.append(response)

    # Combine and sort
    all_integrations = platform_integrations + custom_integrations

    # Separate featured
    featured = [i for i in all_integrations if i.is_featured]
    featured.sort(key=lambda x: (-x.display_priority, x.name))

    # Sort rest by priority then name
    all_integrations.sort(key=lambda x: (-x.display_priority, x.name))

    return MarketplaceResponse(
        featured=featured,
        integrations=all_integrations,
        total=len(all_integrations),
    )


async def get_integration_details(integration_id: str) -> Optional[IntegrationResponse]:
    """
    Get single integration details by ID.

    Uses IntegrationResolver for unified lookup and hydrates tools from global store.

    Args:
        integration_id: The integration ID to look up

    Returns:
        IntegrationResponse or None if not found
    """
    # Fetch tools from global store
    tools_store = get_mcp_tools_store()
    stored_tools = await tools_store.get_tools(integration_id)

    # Use IntegrationResolver for unified lookup
    resolved = await IntegrationResolver.resolve(integration_id)
    if not resolved:
        return None

    # Build response based on source
    if resolved.platform_integration:
        response = IntegrationResponse.from_oauth_integration(
            resolved.platform_integration
        )
    elif resolved.custom_doc:
        try:
            integration = Integration(**resolved.custom_doc)
            response = IntegrationResponse.from_integration(integration)
        except Exception as e:
            logger.error(f"Failed to parse integration {integration_id}: {e}")
            return None
    else:
        return None

    # Hydrate tools
    if stored_tools and not response.tools:
        response.tools = [
            IntegrationTool(name=t["name"], description=t.get("description"))
            for t in stored_tools
        ]

    # Populate creator info if created_by exists
    if response.created_by:
        try:
            # Try to parse as ObjectId, skip if it's a system value like "system_seed"
            try:
                creator_oid = ObjectId(response.created_by)
                creator_doc = await users_collection.find_one(
                    {"_id": creator_oid},
                    {"name": 1, "picture": 1},
                )
                if creator_doc:
                    response.creator = {
                        "name": creator_doc.get("name"),
                        "picture": creator_doc.get("picture"),
                    }
            except Exception:  # nosec B110 - invalid ObjectId is expected, skip gracefully
                # Invalid ObjectId (e.g., "system_seed"), skip creator lookup
                pass
        except Exception as e:
            logger.warning(f"Failed to fetch creator for {integration_id}: {e}")

    return response


async def get_user_integrations(user_id: str) -> UserIntegrationsListResponse:
    """
    Get all integrations a user has added to their workspace.

    Args:
        user_id: The user's ID

    Returns:
        UserIntegrationsListResponse with hydrated integration details
    """
    user_integrations = []

    cursor = user_integrations_collection.find({"user_id": user_id}).sort(
        "created_at", -1
    )

    async for doc in cursor:
        try:
            user_int = UserIntegration(**doc)

            # Hydrate integration details
            integration = await get_integration_details(user_int.integration_id)
            if integration:
                user_integrations.append(
                    UserIntegrationResponse(
                        integration_id=user_int.integration_id,
                        status=user_int.status,
                        created_at=user_int.created_at,
                        connected_at=user_int.connected_at,
                        integration=integration,
                    )
                )
        except Exception as e:
            logger.warning(f"Failed to parse user integration: {e}")

    return UserIntegrationsListResponse(
        integrations=user_integrations,
        total=len(user_integrations),
    )


async def get_user_connected_integrations(user_id: str) -> List[Dict[str, Any]]:
    """
    Get only the integrations that user has connected (status='connected').

    This is used by the tool registry to load tools for the agent.

    Args:
        user_id: The user's ID

    Returns:
        List of user integration documents with status='connected'
    """
    results = []
    cursor = user_integrations_collection.find(
        {
            "user_id": user_id,
            "status": "connected",
        }
    )

    async for doc in cursor:
        results.append(doc)

    return results


async def add_user_integration(
    user_id: str,
    integration_id: str,
    initial_status: Optional[Literal["created", "connected"]] = None,
) -> UserIntegration:
    """
    Add an integration to user's workspace.

    Creates a user_integration record with status='created'.
    If the integration doesn't require auth, status is set to 'connected'.

    Args:
        user_id: The user's ID
        integration_id: ID of integration to add
        initial_status: Optional override for initial status (e.g., 'created' for custom MCPs)

    Returns:
        The created UserIntegration

    Raises:
        ValueError: If integration not found or already added
    """
    # Check if integration exists
    integration = await get_integration_details(integration_id)
    if not integration:
        raise ValueError(f"Integration '{integration_id}' not found")

    # Check if already added
    existing = await user_integrations_collection.find_one(
        {
            "user_id": user_id,
            "integration_id": integration_id,
        }
    )
    if existing:
        raise ValueError(f"Integration '{integration_id}' already added to workspace")

    # Determine initial status:
    # - If initial_status is provided, use it (for custom MCPs that need probe first)
    # - No auth required: connect immediately
    # - Auth required: set to created (needs OAuth to complete)
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

    logger.info(
        f"User {user_id} added integration {integration_id} with status {status}"
    )

    return user_integration


@CacheInvalidator(key_patterns=["tools:user:{user_id}"])
async def remove_user_integration(user_id: str, integration_id: str) -> bool:
    """
    Remove an integration from user's workspace.

    Invalidates the user's tools cache since available tools have changed.

    Args:
        user_id: The user's ID
        integration_id: ID of integration to remove

    Returns:
        True if removed, False if not found
    """
    result = await user_integrations_collection.delete_one(
        {
            "user_id": user_id,
            "integration_id": integration_id,
        }
    )

    if result.deleted_count > 0:
        logger.info(f"User {user_id} removed integration {integration_id}")
        # Note: ChromaDB subagent cleanup for custom integrations is handled
        # in delete_custom_integration() which is called separately
        return True

    return False


async def check_user_has_integration(user_id: str, integration_id: str) -> bool:
    """
    Check if a user has added a specific integration.

    Args:
        user_id: The user's ID
        integration_id: ID of integration to check

    Returns:
        True if user has the integration, False otherwise
    """
    doc = await user_integrations_collection.find_one(
        {
            "user_id": user_id,
            "integration_id": integration_id,
        }
    )
    return doc is not None


async def create_custom_integration(
    user_id: str,
    request: CreateCustomIntegrationRequest,
    icon_url: str | None = None,
) -> Integration:
    """
    Create a custom MCP integration.

    Args:
        user_id: The user creating the integration
        request: Integration creation request
        icon_url: Pre-fetched favicon URL (optional, for parallel fetching)

    Returns:
        The created Integration

    Raises:
        ValueError: If integration with same ID already exists
    """
    # Generate short UUID for integration_id (12 hex chars)
    integration_id = str(uuid.uuid4())

    # Clean up orphaned user_integration if exists (from failed previous creation)
    orphaned = await user_integrations_collection.find_one(
        {"integration_id": integration_id, "user_id": user_id}
    )
    if orphaned:
        logger.warning(f"Cleaning up orphaned user_integration for {integration_id}")
        await user_integrations_collection.delete_one(
            {"integration_id": integration_id, "user_id": user_id}
        )

    integration = Integration(
        integration_id=str(integration_id),
        name=request.name,
        description=request.description or "",
        category=request.category,
        managed_by="mcp",
        source="custom",
        is_public=request.is_public,
        created_by=user_id,
        icon_url=icon_url,
        display_priority=0,
        is_featured=False,
        mcp_config=MCPConfig(
            server_url=request.server_url,
            requires_auth=request.requires_auth,
            auth_type=request.auth_type,
        ),
        created_at=datetime.now(UTC),
        published_at=None,
        clone_count=0,
    )

    await integrations_collection.insert_one(integration.model_dump())

    # Auto-add to user's workspace with status='created'
    # The probe/connect flow in the endpoint will update to 'connected' after success
    try:
        await add_user_integration(
            user_id, str(integration_id), initial_status="created"
        )
    except Exception as e:
        # Rollback: remove the orphaned integration if user_integration creation fails
        logger.error(f"Failed to add user_integration, rolling back integration: {e}")
        await integrations_collection.delete_one({"integration_id": integration_id})
        raise

    return integration


async def update_custom_integration(
    user_id: str,
    integration_id: str,
    request: UpdateCustomIntegrationRequest,
) -> Optional[Integration]:
    """
    Update a custom integration.

    Only the creator can update their custom integration.

    Args:
        user_id: The user making the update
        integration_id: ID of integration to update
        request: Update request with partial fields

    Returns:
        Updated Integration or None if not found/not authorized
    """
    # Find and verify ownership
    doc = await integrations_collection.find_one(
        {
            "integration_id": integration_id,
            "source": "custom",
            "created_by": user_id,
        }
    )

    if not doc:
        return None

    # Build update
    update_data: Dict[str, Any] = {}
    if request.name is not None:
        update_data["name"] = request.name
    if request.description is not None:
        update_data["description"] = request.description
    if request.is_public is not None:
        update_data["is_public"] = request.is_public

    # Update MCP config if any server settings changed
    if any([request.server_url, request.requires_auth, request.auth_type]):
        current_config = doc.get("mcp_config", {})
        if request.server_url is not None:
            current_config["server_url"] = request.server_url
        if request.requires_auth is not None:
            current_config["requires_auth"] = request.requires_auth
        if request.auth_type is not None:
            current_config["auth_type"] = request.auth_type
        update_data["mcp_config"] = current_config

    update_data["updated_at"] = datetime.now(UTC)

    await integrations_collection.update_one(
        {"integration_id": integration_id},
        {"$set": update_data},
    )

    # Fetch updated doc
    updated_doc = await integrations_collection.find_one(
        {"integration_id": integration_id}
    )
    if updated_doc:
        return Integration(**updated_doc)

    return None


async def delete_custom_integration(user_id: str, integration_id: str) -> bool:
    """
    Delete or remove a custom integration based on ownership.

    - If user is the creator: Full delete (integration doc + all user_integrations + cleanup)
    - If user is NOT the creator but has the integration: Remove only their user_integrations entry

    This handles both "own" integrations and "forked" integrations from the marketplace.

    Args:
        user_id: The user making the deletion
        integration_id: ID of integration to delete/remove

    Returns:
        True if deleted/removed, False if not found
    """
    # Check if integration exists and if user is the creator
    doc = await integrations_collection.find_one(
        {"integration_id": integration_id, "source": "custom"}
    )

    if not doc:
        # Integration doesn't exist - check if user has a user_integrations entry anyway
        # (cleanup for orphaned records)
        user_int = await user_integrations_collection.find_one(
            {"user_id": user_id, "integration_id": integration_id}
        )
        if user_int:
            await user_integrations_collection.delete_one(
                {"user_id": user_id, "integration_id": integration_id}
            )
            logger.info(
                f"User {user_id} removed orphaned user_integration for {integration_id}"
            )
            return True
        return False

    is_creator = doc.get("created_by") == user_id

    if is_creator:
        # Full delete: user is the creator
        # If the integration was public, remove from ChromaDB public integrations index
        if doc.get("is_public"):
            try:
                from app.db.chroma.public_integrations_store import (
                    remove_public_integration,
                )

                await remove_public_integration(integration_id)
            except Exception as e:
                logger.warning(f"Failed to remove from public integrations: {e}")

        # Delete the integration document
        result = await integrations_collection.delete_one(
            {
                "integration_id": integration_id,
                "source": "custom",
                "created_by": user_id,
            }
        )

        if result.deleted_count > 0:
            # Clean up ALL user_integrations for this integration (all users who added it)
            await user_integrations_collection.delete_many(
                {"integration_id": integration_id}
            )

            # Clean up MCP credentials from PostgreSQL
            try:
                from app.db.postgresql import get_db_session
                from app.models.oauth_models import MCPCredential
                from sqlalchemy import delete

                async with get_db_session() as session:
                    await session.execute(
                        delete(MCPCredential).where(
                            MCPCredential.integration_id == integration_id
                        )
                    )
                    await session.commit()
                    logger.debug(f"Deleted MCP credentials for {integration_id}")
            except Exception as e:
                logger.warning(f"Failed to delete MCP credentials: {e}")

            # Invalidate global MCP tools cache
            try:
                from app.db.redis import delete_cache

                await delete_cache("mcp:tools:all")
            except Exception as e:
                logger.warning(f"Failed to invalidate tools cache: {e}")

            # Remove subagent entry from ChromaDB
            try:
                from app.core.lazy_loader import providers

                store = await providers.aget("chroma_tools_store")
                if store:
                    await store.adelete(namespace=("subagents",), key=integration_id)
                    logger.info(
                        f"Deleted subagent entry for {integration_id} from ChromaDB"
                    )
            except Exception as e:
                logger.warning(f"Failed to delete subagent from ChromaDB: {e}")

            logger.info(f"User {user_id} deleted custom integration {integration_id}")
            return True

        return False
    else:
        # User is NOT the creator - just remove their user_integrations entry
        result = await user_integrations_collection.delete_one(
            {"user_id": user_id, "integration_id": integration_id}
        )

        if result.deleted_count > 0:
            # Also clean up this user's MCP credentials for this integration
            try:
                from app.db.postgresql import get_db_session
                from app.models.oauth_models import MCPCredential
                from sqlalchemy import delete

                async with get_db_session() as session:
                    await session.execute(
                        delete(MCPCredential).where(
                            MCPCredential.integration_id == integration_id,
                            MCPCredential.user_id == user_id,
                        )
                    )
                    await session.commit()
                    logger.debug(
                        f"Deleted MCP credentials for user {user_id} integration {integration_id}"
                    )
            except Exception as e:
                logger.warning(f"Failed to delete user MCP credentials: {e}")

            logger.info(
                f"User {user_id} removed forked integration {integration_id} from workspace"
            )
            return True

        return False


async def get_user_available_tool_namespaces(user_id: str) -> set[str]:
    """
    Get the set of integration namespaces (tool spaces) that user has connected.

    Uses the cached get_all_integrations_status() for unified namespace discovery.
    This returns connected integrations from:
    - user_integrations (MongoDB) - for unauthenticated MCPs
    - mcp_credentials (PostgreSQL) - for authenticated MCPs
    - Composio API - for Composio-managed integrations
    - oauth_tokens (PostgreSQL) - for self-managed integrations

    Args:
        user_id: The user's ID

    Returns:
        Set of integration IDs that user has connected
    """
    namespaces = set()

    # Add core namespaces that are always available
    namespaces.update({"general", "subagents"})

    # Internal integrations (like todos) are core platform features - always available
    internal_integrations = [
        integration.id
        for integration in OAUTH_INTEGRATIONS
        if integration.managed_by == "internal" and integration.available
    ]
    namespaces.update(internal_integrations)

    # Use cached unified status check for all connected integrations
    try:
        # Lazy import to avoid circular dependency with oauth_service
        from app.services.oauth.oauth_service import get_all_integrations_status

        all_statuses = await get_all_integrations_status(user_id)
        connected = [
            integration_id
            for integration_id, is_connected in all_statuses.items()
            if is_connected
        ]
        namespaces.update(connected)
    except Exception as e:
        logger.warning(f"Failed to get integration status: {e}")

    # Also include custom integrations from MongoDB (not in OAUTH_INTEGRATIONS)
    try:
        custom_connected = await get_user_connected_integrations(user_id)
        for doc in custom_connected:
            integration_id = doc.get("integration_id", "")
            # Add custom integrations (they start with 'custom_')
            if integration_id.startswith("custom_"):
                namespaces.add(integration_id)
    except Exception as e:
        logger.warning(f"Failed to get custom integrations from MongoDB: {e}")

    return namespaces
