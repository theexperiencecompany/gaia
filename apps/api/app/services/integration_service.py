"""
Integration Service for MCP Marketplace.

This service handles:
- Hybrid integration retrieval (platform + custom integrations)
- User integration management (add/remove/connect)
- Custom integration CRUD operations
- Tool loading based on user's connected integrations
"""

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.config.loggers import app_logger as logger
from app.config.oauth_config import OAUTH_INTEGRATIONS, get_integration_by_id
from app.db.mongodb.collections import (
    integrations_collection,
    user_integrations_collection,
)
from app.models.integration_models import (
    CreateCustomIntegrationRequest,
    Integration,
    IntegrationResponse,
    IntegrationTool,
    MarketplaceResponse,
    MCPConfigDoc,
    UpdateCustomIntegrationRequest,
    UserIntegration,
    UserIntegrationResponse,
    UserIntegrationsListResponse,
)
from app.services.mcp.mcp_token_store import MCPTokenStore
from app.services.mcp.mcp_tools_store import get_mcp_tools_store


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

    Checks platform integrations first, then custom integrations in MongoDB.
    Hydrates tools from global store.

    Args:
        integration_id: The integration ID to look up

    Returns:
        IntegrationResponse or None if not found
    """
    # Fetch tools from global store
    tools_store = get_mcp_tools_store()
    stored_tools = await tools_store.get_tools(integration_id)

    # Step 1: Check platform integrations
    oauth_int = get_integration_by_id(integration_id)
    if oauth_int:
        response = IntegrationResponse.from_oauth_integration(oauth_int)
        # Hydrate tools
        if stored_tools:
            response.tools = [
                IntegrationTool(name=t["name"], description=t.get("description"))
                for t in stored_tools
            ]
        return response

    # Step 2: Check MongoDB for custom integrations
    doc = await integrations_collection.find_one({"integration_id": integration_id})
    if doc:
        try:
            integration = Integration(**doc)
            response = IntegrationResponse.from_integration(integration)
            # Hydrate tools if not already in doc
            if not response.tools and stored_tools:
                response.tools = [
                    IntegrationTool(name=t["name"], description=t.get("description"))
                    for t in stored_tools
                ]
            return response
        except Exception as e:
            logger.error(f"Failed to parse integration {integration_id}: {e}")

    return None


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
) -> UserIntegration:
    """
    Add an integration to user's workspace.

    Creates a user_integration record with status='created'.
    If the integration doesn't require auth, status is set to 'connected'.

    Args:
        user_id: The user's ID
        integration_id: ID of integration to add

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

    # Determine initial status - if no auth required, connect immediately
    status = "connected" if not integration.requires_auth else "created"
    connected_at = datetime.utcnow() if status == "connected" else None

    user_integration = UserIntegration(
        user_id=user_id,
        integration_id=integration_id,
        status=status,
        created_at=datetime.utcnow(),
        connected_at=connected_at,
    )

    await user_integrations_collection.insert_one(user_integration.model_dump())

    logger.info(
        f"User {user_id} added integration {integration_id} with status {status}"
    )

    return user_integration


async def remove_user_integration(user_id: str, integration_id: str) -> bool:
    """
    Remove an integration from user's workspace.

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
        return True

    return False


async def update_user_integration_status(
    user_id: str,
    integration_id: str,
    status: str,
) -> bool:
    """
    Update or create user integration status (upsert).

    Called after successful OAuth or MCP connection to set status='connected'.
    Creates the record if it doesn't exist.

    Args:
        user_id: The user's ID
        integration_id: ID of integration
        status: New status ('created' or 'connected')

    Returns:
        True if updated or created
    """
    update_data = {
        "status": status,
        "user_id": user_id,
        "integration_id": integration_id,
    }
    if status == "connected":
        update_data["connected_at"] = datetime.utcnow()

    result = await user_integrations_collection.update_one(
        {"user_id": user_id, "integration_id": integration_id},
        {
            "$set": update_data,
            "$setOnInsert": {"created_at": datetime.utcnow()},
        },
        upsert=True,
    )

    if result.modified_count > 0 or result.upserted_id:
        logger.info(
            f"Updated user {user_id} integration {integration_id} status to {status}"
        )
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
) -> Integration:
    """
    Create a custom MCP integration.

    Args:
        user_id: The user creating the integration
        request: Integration creation request

    Returns:
        The created Integration

    Raises:
        ValueError: If integration with same ID already exists
    """
    # Generate integration_id from name
    integration_id = f"custom_{request.name.lower().replace(' ', '_')}_{user_id[:8]}"

    # Check if ID already exists
    existing = await integrations_collection.find_one(
        {"integration_id": integration_id}
    )
    if existing:
        raise ValueError(f"Integration with ID '{integration_id}' already exists")

    integration = Integration(
        integration_id=integration_id,
        name=request.name,
        description=request.description,
        category=request.category,
        managed_by="mcp",
        source="custom",
        is_public=request.is_public,
        created_by=user_id,
        mcp_config=MCPConfigDoc(
            server_url=request.server_url,
            requires_auth=request.requires_auth,
            auth_type=request.auth_type,
        ),
        created_at=datetime.utcnow(),
    )

    await integrations_collection.insert_one(integration.model_dump())

    # Auto-add to user's workspace
    await add_user_integration(user_id, integration_id)

    logger.info(f"User {user_id} created custom integration {integration_id}")

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
    update_data = {}
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

    update_data["updated_at"] = datetime.utcnow()

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
    Delete a custom integration.

    Only the creator can delete their custom integration.
    Also removes all user_integrations referencing this integration.

    Args:
        user_id: The user making the deletion
        integration_id: ID of integration to delete

    Returns:
        True if deleted, False if not found/not authorized
    """
    result = await integrations_collection.delete_one(
        {
            "integration_id": integration_id,
            "source": "custom",
            "created_by": user_id,
        }
    )

    if result.deleted_count > 0:
        # Remove all user_integration references
        await user_integrations_collection.delete_many(
            {"integration_id": integration_id}
        )
        logger.info(f"User {user_id} deleted custom integration {integration_id}")
        return True

    return False


async def get_user_available_tool_namespaces(user_id: str) -> set[str]:
    """
    Get the set of integration namespaces (tool spaces) that user has connected.

    Queries ALL integration sources in parallel for unified namespace discovery:
    - user_integrations (MongoDB) - marketplace preferences for unauthenticated MCPs
    - mcp_credentials (PostgreSQL) - actual MCP tokens for authenticated MCPs
    - oauth_service (cached) - Composio and self-managed integrations
    - internal integrations - always available (e.g., todos)

    This ensures all users (including legacy users) can discover tools from their
    connected integrations.

    Args:
        user_id: The user's ID

    Returns:
        Set of integration IDs that user has connected
    """
    from app.services.oauth_service import get_all_integrations_status

    namespaces = set()

    # Add core namespaces that are always available
    namespaces.update({"general", "subagents"})

    # Internal integrations (like todos) are core platform features - always available
    # They're NOT integrations that need connecting via UI
    internal_integrations = [
        integration.id
        for integration in OAUTH_INTEGRATIONS
        if integration.managed_by == "internal" and integration.available
    ]
    namespaces.update(internal_integrations)

    async def fetch_mongodb_integrations() -> list[str]:
        try:
            connected = await get_user_connected_integrations(user_id)
            return [doc["integration_id"] for doc in connected]
        except Exception as e:
            logger.warning(f"Failed to get user_integrations from MongoDB: {e}")
            return []

    async def fetch_postgres_integrations() -> list[str]:
        try:
            token_store = MCPTokenStore(user_id)
            return await token_store.get_connected_integrations()
        except Exception as e:
            logger.warning(f"Failed to get mcp_credentials from PostgreSQL: {e}")
            return []

    async def fetch_oauth_integrations() -> list[str]:
        """Get all connected integrations (Composio, self-managed, MCP) from unified status."""
        try:
            all_statuses = await get_all_integrations_status(user_id)
            return [
                integration_id
                for integration_id, connected in all_statuses.items()
                if connected
            ]
        except Exception as e:
            logger.warning(f"Failed to get oauth integration status: {e}")
            return []

    # Fetch from all sources in parallel
    (
        mongo_integrations,
        postgres_integrations,
        oauth_integrations,
    ) = await asyncio.gather(
        fetch_mongodb_integrations(),
        fetch_postgres_integrations(),
        fetch_oauth_integrations(),
    )

    namespaces.update(mongo_integrations)
    namespaces.update(postgres_integrations)
    namespaces.update(oauth_integrations)

    return namespaces
