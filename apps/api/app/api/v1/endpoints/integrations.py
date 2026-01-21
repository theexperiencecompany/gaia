"""Integration API routes."""

import asyncio
from datetime import datetime, timezone
from typing import Optional

from app.api.v1.dependencies.oauth_dependencies import get_current_user, get_user_id
from app.config.loggers import auth_logger as logger
from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.db.chroma.public_integrations_store import (
    index_public_integration,
    remove_public_integration,
    search_public_integrations,
)
from app.db.mongodb.collections import (
    integrations_collection,
    user_integrations_collection,
)
from app.db.redis import delete_cache_by_pattern, get_cache, set_cache
from app.helpers.mcp_helpers import get_api_base_url
from app.models.integration_models import (
    CreateCustomIntegrationRequest as CreateCustomIntegrationRequestModel,
)
from app.models.integration_models import (
    UpdateCustomIntegrationRequest as UpdateCustomIntegrationRequestModel,
)
from app.models.integration_models import (
    UserIntegrationsListResponse as UserIntegrationsListResponseModel,
)
from app.schemas.integrations.requests import (
    AddUserIntegrationRequest,
    ConnectIntegrationRequest,
    CreateCustomIntegrationRequest,
    UpdateCustomIntegrationRequest,
)
from app.schemas.integrations.responses import (
    AddIntegrationResponse,
    AddUserIntegrationResponse,
    CommunityIntegrationCreator,
    CommunityListResponse,
    ConnectIntegrationResponse,
    CreateCustomIntegrationResponse,
    CustomIntegrationConnectionResult,
    IntegrationResponse,
    IntegrationsConfigResponse,
    IntegrationsStatusResponse,
    IntegrationStatusItem,
    IntegrationSuccessResponse,
    IntegrationTool,
    MarketplaceResponse,
    MCPConfigDetail,
    PublicIntegrationDetailResponse,
    PublishIntegrationResponse,
    SearchIntegrationItem,
    SearchIntegrationsResponse,
    UnpublishIntegrationResponse,
    UserIntegrationsListResponse,
)
from app.services.integrations.category_inference_service import (
    infer_integration_category,
)
from app.services.integrations.integration_connection_service import (
    build_integrations_config,
    connect_composio_integration,
    connect_mcp_integration,
    connect_self_integration,
    disconnect_integration,
)
from app.services.integrations.integration_resolver import IntegrationResolver
from app.services.integrations.integration_service import (
    add_user_integration,
    build_creator_lookup_stages,
    create_custom_integration,
    delete_custom_integration,
    format_community_integrations,
    get_all_integrations,
    get_integration_details,
    get_user_integrations,
    remove_user_integration,
    update_custom_integration,
)
from app.services.integrations.publish_validator import (
    PublishIntegrationValidator,
)
from app.services.mcp.mcp_client import get_mcp_client
from app.services.oauth.oauth_service import get_all_integrations_status
from app.utils.favicon_utils import fetch_favicon_from_url
from fastapi import APIRouter, Depends, HTTPException
from mcp_use.client.exceptions import OAuthAuthenticationError

router = APIRouter()


@router.get("/config", response_model=IntegrationsConfigResponse)
async def get_integrations_config() -> IntegrationsConfigResponse:
    return build_integrations_config()


@router.get("/status", response_model=IntegrationsStatusResponse)
async def get_integrations_status(
    user_id: str = Depends(get_user_id),
) -> IntegrationsStatusResponse:
    try:
        status_map = await get_all_integrations_status(user_id)
        return IntegrationsStatusResponse(
            integrations=[
                IntegrationStatusItem(integration_id=iid, connected=connected)
                for iid, connected in status_map.items()
            ]
        )
    except Exception as e:
        logger.error(f"Error checking integration status: {e}")
        return IntegrationsStatusResponse(
            integrations=[
                IntegrationStatusItem(integration_id=i.id, connected=False)
                for i in OAUTH_INTEGRATIONS
                if i.managed_by != "internal"
            ]
        )


@router.delete("/{integration_id}", response_model=IntegrationSuccessResponse)
async def disconnect_integration_endpoint(
    integration_id: str,
    user_id: str = Depends(get_user_id),
) -> IntegrationSuccessResponse:
    try:
        return await disconnect_integration(user_id, integration_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error disconnecting {integration_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to disconnect integration")


@router.post("/connect/{integration_id}", response_model=ConnectIntegrationResponse)
async def connect_integration_endpoint(
    integration_id: str,
    request: ConnectIntegrationRequest,
    user: dict = Depends(get_current_user),
) -> ConnectIntegrationResponse:
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")

    resolved = await IntegrationResolver.resolve(integration_id)
    if not resolved:
        raise HTTPException(
            status_code=404, detail=f"Integration {integration_id} not found"
        )

    if resolved.source == "platform" and resolved.platform_integration:
        if not resolved.platform_integration.available:
            return ConnectIntegrationResponse(
                status="error",
                integration_id=integration_id,
                error=f"Integration {integration_id} is not available yet",
            )

    try:
        if resolved.managed_by == "mcp":
            return await connect_mcp_integration(
                user_id=str(user_id),
                integration_id=integration_id,
                requires_auth=resolved.requires_auth,
                redirect_path=request.redirect_path,
                server_url=resolved.mcp_config.server_url
                if resolved.mcp_config
                else None,
                is_platform=resolved.source == "platform",
            )
        elif resolved.managed_by == "composio":
            provider = (
                resolved.platform_integration.provider
                if resolved.platform_integration
                else None
            )
            if not provider:
                raise HTTPException(status_code=400, detail="Provider not configured")
            return await connect_composio_integration(
                user_id=str(user_id),
                integration_id=integration_id,
                provider=provider,
                redirect_path=request.redirect_path,
            )
        elif resolved.managed_by == "self":
            provider = (
                resolved.platform_integration.provider
                if resolved.platform_integration
                else None
            )
            if not provider:
                raise HTTPException(status_code=400, detail="Provider not configured")
            return await connect_self_integration(
                user_id=str(user_id),
                user_email=user.get("email", ""),
                integration_id=integration_id,
                provider=provider,
                redirect_path=request.redirect_path,
            )
        else:
            return ConnectIntegrationResponse(
                status="error",
                integration_id=integration_id,
                error=f"Unsupported integration type: {resolved.managed_by}",
            )
    except Exception as e:
        logger.error(f"Failed to connect {integration_id}: {e}")
        return ConnectIntegrationResponse(
            status="error",
            integration_id=integration_id,
            error=str(e),
        )


@router.get("/marketplace", response_model=MarketplaceResponse)
async def list_marketplace_integrations(category: Optional[str] = None):
    try:
        return await get_all_integrations(category=category)
    except Exception as e:
        logger.error(f"Error fetching marketplace: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch integrations")


@router.get("/marketplace/{integration_id}", response_model=IntegrationResponse)
async def get_marketplace_integration(integration_id: str):
    integration = await get_integration_details(integration_id)
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    return integration


@router.get("/community", response_model=CommunityListResponse)
async def list_community_integrations(
    sort: str = "popular",  # popular | recent | name
    category: str = "all",
    limit: int = 20,
    offset: int = 0,
    search: Optional[str] = None,
) -> CommunityListResponse:
    """
    List public integrations for the community marketplace.

    Args:
        sort: Sorting method - "popular" (clone_count), "recent" (published_at), "name"
        category: Category filter or "all"
        limit: Max results (default 20, max 100)
        offset: Pagination offset
        search: Optional search query (triggers semantic search via ChromaDB)

    This is an UNAUTHENTICATED endpoint for browsing the marketplace.
    Results are cached for 5 minutes (except search queries).
    """
    CACHE_TTL = 300  # 5 minutes

    try:
        # Clamp limit to max 100
        limit = min(limit, 100)

        # If search query provided, try ChromaDB semantic search first, fallback to MongoDB
        # Search queries are NOT cached (dynamic content)
        if search and search.strip():
            search_query = search.strip()

            # Try semantic search via ChromaDB first
            search_results = await search_public_integrations(
                query=search_query,
                limit=limit,
                category=category if category != "all" else None,
            )

            # Fetch full integration docs from MongoDB for additional data
            integration_ids = [
                r.get("integration_id")
                for r in search_results
                if r.get("integration_id")
            ]

            if integration_ids:
                # ChromaDB returned results - use aggregation to join creator info
                pipeline: list = [
                    {
                        "$match": {
                            "integration_id": {"$in": integration_ids},
                            "is_public": True,
                        }
                    },
                    *build_creator_lookup_stages(),
                ]
                cursor = integrations_collection.aggregate(pipeline)
                docs = await cursor.to_list(length=limit)

                # Create a map for ordering by search relevance
                docs_map = {doc["integration_id"]: doc for doc in docs}
                ordered_docs = [
                    docs_map[iid] for iid in integration_ids if iid in docs_map
                ]

                integrations = format_community_integrations(ordered_docs)

                return CommunityListResponse(
                    integrations=integrations,
                    total=len(integrations),
                    has_more=False,  # Semantic search doesn't support pagination
                )

            # ChromaDB returned no results - fallback to MongoDB text search
            logger.info(
                f"ChromaDB returned no results for '{search_query}', falling back to MongoDB"
            )

            # Build MongoDB query with regex search on name and description
            mongo_query: dict = {"is_public": True}
            search_regex = {"$regex": search_query, "$options": "i"}
            mongo_query["$or"] = [
                {"name": search_regex},
                {"description": search_regex},
                {"tools.name": search_regex},
                {"tools.description": search_regex},
            ]

            if category and category != "all":
                mongo_query["category"] = category

            # Get total count for search
            total = await integrations_collection.count_documents(mongo_query)

            # Use aggregation to join creator info
            mongo_pipeline: list = [
                {"$match": mongo_query},
                {"$sort": {"clone_count": -1, "published_at": -1}},
                {"$skip": offset},
                {"$limit": limit},
                *build_creator_lookup_stages(),
            ]
            cursor = integrations_collection.aggregate(mongo_pipeline)
            docs = await cursor.to_list(length=limit)

            integrations = format_community_integrations(docs)

            return CommunityListResponse(
                integrations=integrations,
                total=total,
                has_more=(offset + len(docs)) < total,
            )

        # MongoDB query path (without search) - CHECK CACHE FIRST
        cache_key = f"marketplace:community:{sort}:{category}:{limit}:{offset}"
        cached = await get_cache(cache_key)
        if cached:
            return CommunityListResponse(**cached)

        query: dict = {
            "is_public": True,
            "published_at": {"$ne": None},  # Only show published integrations
        }

        # Apply category filter
        if category and category != "all":
            query["category"] = category

        # Determine sort order for aggregation
        if sort == "popular":
            sort_dict = {"clone_count": -1, "published_at": -1}
        elif sort == "recent":
            sort_dict = {"published_at": -1}
        elif sort == "name":
            sort_dict = {"name": 1}
        else:
            sort_dict = {"clone_count": -1, "published_at": -1}

        # Get total count
        total = await integrations_collection.count_documents(query)

        # Use aggregation pipeline to join creator info from users collection
        sort_pipeline: list = [
            {"$match": query},
            {"$sort": sort_dict},
            {"$skip": offset},
            {"$limit": limit},
            *build_creator_lookup_stages(),
        ]

        cursor = integrations_collection.aggregate(sort_pipeline)
        docs = await cursor.to_list(length=limit)

        integrations = format_community_integrations(docs)

        response = CommunityListResponse(
            integrations=integrations,
            total=total,
            has_more=(offset + len(docs)) < total,
        )

        # Cache the response for 5 minutes
        await set_cache(cache_key, response.model_dump(), ttl=CACHE_TTL)

        return response

    except Exception as e:
        logger.error(f"Error fetching community integrations: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to fetch community integrations"
        )


@router.get("/users/me/integrations", response_model=UserIntegrationsListResponse)
async def list_user_integrations(
    user_id: str = Depends(get_user_id),
) -> UserIntegrationsListResponseModel:
    try:
        return await get_user_integrations(user_id)
    except Exception as e:
        logger.error(f"Error fetching user integrations: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch user integrations")


@router.post("/users/me/integrations", response_model=AddUserIntegrationResponse)
async def add_integration_to_workspace(
    request: AddUserIntegrationRequest,
    user_id: str = Depends(get_user_id),
) -> AddUserIntegrationResponse:
    try:
        user_integration = await add_user_integration(user_id, request.integration_id)
        return AddUserIntegrationResponse(
            message="Integration added to workspace",
            integration_id=user_integration.integration_id,
            connection_status=user_integration.status,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error adding integration: {e}")
        raise HTTPException(status_code=500, detail="Failed to add integration")


@router.delete(
    "/users/me/integrations/{integration_id}", response_model=IntegrationSuccessResponse
)
async def remove_integration_from_workspace(
    integration_id: str,
    user_id: str = Depends(get_user_id),
) -> IntegrationSuccessResponse:
    try:
        removed = await remove_user_integration(user_id, integration_id)
        if not removed:
            raise HTTPException(
                status_code=404, detail="Integration not found in workspace"
            )
        return IntegrationSuccessResponse(
            message="Integration removed from workspace",
            integration_id=integration_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error removing integration: {e}")
        raise HTTPException(status_code=500, detail="Failed to remove integration")


@router.post("/custom", response_model=CreateCustomIntegrationResponse)
async def create_custom_mcp_integration(
    request: CreateCustomIntegrationRequest,
    user_id: str = Depends(get_user_id),
) -> CreateCustomIntegrationResponse:
    """Create a custom MCP integration."""
    try:
        # Note: With UUID-based integration_ids, duplicate name check is no longer needed
        # Each integration gets a unique UUID regardless of name

        mcp_client = await get_mcp_client(user_id=user_id)

        # Parallel: Favicon fetch + MCP probe
        favicon_result, probe_result = await asyncio.gather(
            fetch_favicon_from_url(request.server_url),
            mcp_client.probe_connection(request.server_url),
            return_exceptions=True,
        )

        # Log individual results for debugging
        if isinstance(favicon_result, Exception):
            logger.debug(f"Favicon fetch failed: {favicon_result}")
        if isinstance(probe_result, Exception):
            logger.debug(f"Probe failed: {probe_result}")

        icon_url = None
        if favicon_result and not isinstance(favicon_result, Exception):
            icon_url = favicon_result

        integration = await create_custom_integration(
            user_id,
            CreateCustomIntegrationRequestModel(
                name=request.name,
                description=request.description,
                category=request.category,
                server_url=request.server_url,
                requires_auth=request.requires_auth,
                auth_type=request.auth_type,
                is_public=request.is_public,
            ),
            icon_url,
        )

        # Helper to build OAuth URL and return appropriate connection result
        async def build_oauth_result() -> CustomIntegrationConnectionResult:
            """Try to build OAuth URL, return result with status and url or error."""
            try:
                auth_url = await mcp_client.build_oauth_auth_url(
                    integration_id=integration.integration_id,
                    redirect_uri=f"{get_api_base_url()}/api/v1/mcp/oauth/callback",
                    redirect_path="/integrations",
                )
                return CustomIntegrationConnectionResult(
                    status="requires_oauth", oauth_url=auth_url
                )
            except Exception as oauth_err:
                logger.error(f"OAuth discovery failed: {oauth_err}")
                return CustomIntegrationConnectionResult(
                    status="failed",
                    error=f"OAuth required but discovery failed: {oauth_err}",
                )

        connection_result: CustomIntegrationConnectionResult = (
            CustomIntegrationConnectionResult(status="created")
        )

        # Handle probe result
        if isinstance(probe_result, Exception):
            connection_result = CustomIntegrationConnectionResult(
                status="failed", error=str(probe_result)
            )
        elif probe_result.get("error"):
            connection_result = CustomIntegrationConnectionResult(
                status="failed", error=probe_result["error"]
            )
        elif probe_result.get("requires_auth"):
            # Probe detected OAuth requirement - update the stored integration
            # This ensures mcp_config.requires_auth is correct when connecting later
            await mcp_client.update_integration_auth_status(
                integration.integration_id,
                requires_auth=True,
                auth_type=probe_result.get("auth_type", "oauth"),
            )
            logger.info(
                f"[{integration.integration_id}] Probe detected OAuth, "
                f"updated integration requires_auth=True"
            )
            connection_result = await build_oauth_result()
        else:
            # Probe says no auth required - try to connect
            try:
                tools = await mcp_client.connect(integration.integration_id)
                tools_count = len(tools) if tools else 0
                connection_result = CustomIntegrationConnectionResult(
                    status="connected", tools_count=tools_count
                )
            except OAuthAuthenticationError:
                await mcp_client.update_integration_auth_status(
                    integration.integration_id,
                    requires_auth=True,
                    auth_type="oauth",
                )
                logger.info(
                    f"[{integration.integration_id}] mcp-use detected OAuth at runtime, "
                    "updated integration requires_auth=True"
                )
                connection_result = await build_oauth_result()
            except Exception as conn_err:
                logger.warning(f"Connect failed: {conn_err}")
                connection_result = CustomIntegrationConnectionResult(
                    status="failed", error=str(conn_err)
                )

        return CreateCustomIntegrationResponse(
            message="Custom integration created",
            integration_id=integration.integration_id,
            name=integration.name,
            connection=connection_result,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating custom integration: {e}")
        raise HTTPException(status_code=500, detail="Failed to create integration")


@router.patch("/custom/{integration_id}", response_model=IntegrationSuccessResponse)
async def update_custom_mcp_integration(
    integration_id: str,
    request: UpdateCustomIntegrationRequest,
    user_id: str = Depends(get_user_id),
) -> IntegrationSuccessResponse:
    try:
        updated = await update_custom_integration(
            user_id,
            integration_id,
            UpdateCustomIntegrationRequestModel(
                name=request.name,
                description=request.description,
                server_url=request.server_url,
                requires_auth=request.requires_auth,
                auth_type=request.auth_type,
                is_public=request.is_public,
            ),
        )
        if not updated:
            raise HTTPException(
                status_code=404, detail="Integration not found or you are not the owner"
            )
        return IntegrationSuccessResponse(
            message="Integration updated",
            integration_id=updated.integration_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating integration {integration_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to update integration")


@router.delete("/custom/{integration_id}", response_model=IntegrationSuccessResponse)
async def delete_custom_mcp_integration(
    integration_id: str,
    user_id: str = Depends(get_user_id),
) -> IntegrationSuccessResponse:
    try:
        deleted = await delete_custom_integration(user_id, integration_id)
        if not deleted:
            raise HTTPException(
                status_code=404, detail="Integration not found or you are not the owner"
            )
        return IntegrationSuccessResponse(
            message="Integration deleted",
            integration_id=integration_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting integration {integration_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete integration")


@router.get("/public/{integration_id}", response_model=PublicIntegrationDetailResponse)
async def get_public_integration(
    integration_id: str,
) -> PublicIntegrationDetailResponse:
    """
    Get public integration details by integration_id.
    No authentication required - used for public pages (SEO/sharing).
    """
    try:
        # Use aggregation to join creator data from users collection
        pipeline = [
            {"$match": {"integration_id": integration_id, "is_public": True}},
            {
                "$lookup": {
                    "from": "users",
                    "let": {
                        "creator_id": {
                            "$convert": {
                                "input": "$created_by",
                                "to": "objectId",
                                "onError": None,
                                "onNull": None,
                            }
                        }
                    },
                    "pipeline": [
                        {"$match": {"$expr": {"$eq": ["$_id", "$$creator_id"]}}},
                        {"$project": {"name": 1, "picture": 1}},
                    ],
                    "as": "creator_info",
                }
            },
            {
                "$addFields": {
                    "creator": {
                        "$cond": {
                            "if": {"$gt": [{"$size": "$creator_info"}, 0]},
                            "then": {"$arrayElemAt": ["$creator_info", 0]},
                            "else": None,
                        }
                    }
                }
            },
            {"$project": {"creator_info": 0}},
        ]

        cursor = integrations_collection.aggregate(pipeline)
        docs = await cursor.to_list(length=1)

        if not docs:
            raise HTTPException(status_code=404, detail="Integration not found")

        doc = docs[0]

        # Extract MCP config details as nested object
        mcp_config_doc = doc.get("mcp_config", {})
        mcp_config = None
        if mcp_config_doc:
            mcp_config = MCPConfigDetail(
                server_url=mcp_config_doc.get("server_url"),
                requires_auth=mcp_config_doc.get("requires_auth", False),
                auth_type=mcp_config_doc.get("auth_type"),
            )

        # Build creator as nested object from aggregated data
        creator = None
        creator_data = doc.get("creator")
        if creator_data:
            creator = CommunityIntegrationCreator(
                name=creator_data.get("name"),
                picture=creator_data.get("picture"),
            )

        tools = doc.get("tools", [])

        return PublicIntegrationDetailResponse(
            integration_id=doc["integration_id"],
            name=doc["name"],
            description=doc.get("description", ""),
            category=doc.get("category", "custom"),
            icon_url=doc.get("icon_url"),
            creator=creator,
            mcp_config=mcp_config,
            tools=[
                IntegrationTool(
                    name=t.get("name", ""), description=t.get("description")
                )
                for t in tools
            ],
            clone_count=doc.get("clone_count", 0),
            tool_count=len(tools),
            published_at=doc.get("published_at"),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching public integration {integration_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch integration")


@router.post("/public/{integration_id}/add", response_model=AddIntegrationResponse)
async def add_public_integration(
    integration_id: str,
    request: ConnectIntegrationRequest,
    user_id: str = Depends(get_user_id),
) -> AddIntegrationResponse:
    """
    Add a public integration to user's workspace and trigger connection.

    This does NOT duplicate the integration - it just creates a user_integrations
    entry pointing to the original public integration, then triggers the OAuth
    flow if needed.

    Args:
        integration_id: The public integration's ID
        request: Contains redirect_path for OAuth callback

    Returns:
        AddIntegrationResponse with status "connected", "redirect", or "error"
    """

    try:
        # 1. Get public integration
        original_doc = await integrations_collection.find_one(
            {"integration_id": integration_id, "is_public": True}
        )
        if not original_doc:
            raise HTTPException(status_code=404, detail="Integration not found")

        integration_name = original_doc["name"]

        # 2. Check if user already has this integration
        existing = await user_integrations_collection.find_one(
            {"user_id": user_id, "integration_id": integration_id}
        )
        if existing:
            # Already added - check status
            if existing.get("status") == "connected":
                return AddIntegrationResponse(
                    integration_id=integration_id,
                    name=integration_name,
                    status="connected",
                    message="Integration already connected",
                )
            # Not connected yet - try connecting again
            logger.info(f"User {user_id} re-attempting connection to {integration_id}")
        else:
            # 3. Add to user_integrations (pointing to ORIGINAL, not a copy)
            try:
                await add_user_integration(
                    user_id=user_id,
                    integration_id=integration_id,
                    initial_status="created",
                )
            except ValueError:
                # Already added (race condition) - continue to connection
                pass

            # 4. Increment clone_count on original
            await integrations_collection.update_one(
                {"integration_id": integration_id},
                {"$inc": {"clone_count": 1}},
            )

            logger.info(f"User {user_id} added integration {integration_id}")

        # 5. Trigger connection flow immediately
        mcp_config = original_doc.get("mcp_config", {})
        server_url = mcp_config.get("server_url")
        requires_auth = mcp_config.get("requires_auth", False)

        connect_result = await connect_mcp_integration(
            user_id=user_id,
            integration_id=integration_id,
            requires_auth=requires_auth,
            redirect_path=request.redirect_path,
            server_url=server_url,
            is_platform=False,
        )

        # 6. Return result (may include redirect_url for OAuth)
        return AddIntegrationResponse(
            integration_id=integration_id,
            name=integration_name,
            status=connect_result.status,
            redirect_url=connect_result.redirect_url,
            tools_count=connect_result.tools_count,
            message=connect_result.message or "Integration added successfully",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding integration {integration_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to add integration")


@router.get("/search", response_model=SearchIntegrationsResponse)
async def search_integrations(q: str) -> SearchIntegrationsResponse:
    """
    Search public integrations using semantic search.
    No authentication required.
    """

    try:
        if not q or not q.strip():
            return SearchIntegrationsResponse(integrations=[], query=q)

        # Use ChromaDB semantic search
        results = await search_public_integrations(
            query=q.strip(),
            limit=20,
        )

        # If ChromaDB returns empty, return early
        if not results:
            return SearchIntegrationsResponse(integrations=[], query=q)

        # Fetch full docs from MongoDB for additional fields (icon_url, etc.)
        integration_ids = [
            r.get("integration_id") for r in results if r.get("integration_id")
        ]

        if integration_ids:
            cursor = integrations_collection.find(
                {"integration_id": {"$in": integration_ids}, "is_public": True}
            )
            docs = await cursor.to_list(length=20)
            docs_map = {doc["integration_id"]: doc for doc in docs}
        else:
            docs_map = {}

        # Format results with relevance scores
        formatted = []
        for r in results:
            iid = r.get("integration_id")
            doc = docs_map.get(iid, {}) if iid else {}

            formatted.append(
                SearchIntegrationItem(
                    integration_id=iid or r.get("id", "unknown"),
                    name=r.get("name", doc.get("name", "")),
                    description=r.get("description", doc.get("description", "")),
                    category=r.get("category", doc.get("category", "custom")),
                    relevance_score=r.get("relevance_score", 0.0),
                    clone_count=r.get("clone_count", doc.get("clone_count", 0)),
                    tool_count=r.get("tool_count", len(doc.get("tools", []))),
                    icon_url=doc.get("icon_url"),
                )
            )

        return SearchIntegrationsResponse(integrations=formatted, query=q)

    except Exception as e:
        logger.error(f"Error searching integrations: {e}")
        raise HTTPException(status_code=500, detail="Failed to search integrations")


@router.post(
    "/custom/{integration_id}/publish", response_model=PublishIntegrationResponse
)
async def publish_integration(
    integration_id: str,
    user_id: str = Depends(get_user_id),
) -> PublishIntegrationResponse:
    """Publish a custom integration to the community marketplace."""
    try:
        # Fetch the integration
        integration = await integrations_collection.find_one(
            {"integration_id": integration_id}
        )
        if not integration:
            raise HTTPException(status_code=404, detail="Integration not found")

        # Verify user owns this integration
        if integration.get("created_by") != user_id:
            raise HTTPException(
                status_code=403, detail="You can only publish integrations you created"
            )

        # Verify it's a custom integration
        if integration.get("source") != "custom":
            raise HTTPException(
                status_code=400, detail="Only custom integrations can be published"
            )

        # Verify user has this integration connected
        user_integration = await user_integrations_collection.find_one(
            {"user_id": user_id, "integration_id": integration_id}
        )
        if not user_integration or user_integration.get("status") != "connected":
            raise HTTPException(
                status_code=400,
                detail="Integration must be connected before publishing",
            )

        # Verify integration has tools (is connected)
        tools = integration.get("tools", [])
        if not tools:
            raise HTTPException(
                status_code=400,
                detail="Integration must be connected with tools before publishing",
            )

        validation_errors = PublishIntegrationValidator.validate_for_publish(
            name=integration.get("name", ""),
            description=integration.get("description"),
            tools=tools,
        )
        if validation_errors:
            raise HTTPException(
                status_code=400,
                detail="; ".join(validation_errors),
            )

        # Infer category using LLM
        category = await infer_integration_category(
            name=integration.get("name", ""),
            description=integration.get("description", ""),
            tools=tools,
            server_url=integration.get("mcp_config", {}).get("server_url", ""),
        )

        # Note: creator_name and creator_picture are no longer stored
        # Creator info is now fetched from users collection at runtime via aggregation

        # Atomic update with condition to prevent race condition
        # Only update if is_public is not already True
        now = datetime.now(timezone.utc)
        update_result = await integrations_collection.update_one(
            {
                "integration_id": integration_id,
                "created_by": user_id,
                "source": "custom",
                "is_public": {"$ne": True},  # Only update if not already public
            },
            {
                "$set": {
                    "is_public": True,
                    "published_at": now,
                    "category": category,
                    "clone_count": integration.get("clone_count", 0),
                }
            },
        )

        if update_result.modified_count == 0:
            # Either not found or already published - check which
            existing = await integrations_collection.find_one(
                {"integration_id": integration_id, "created_by": user_id}
            )
            if existing and existing.get("is_public"):
                raise HTTPException(
                    status_code=400, detail="Integration is already published"
                )
            raise HTTPException(status_code=404, detail="Integration not found")

        # Index in ChromaDB for semantic search
        await index_public_integration(
            integration_id=integration_id,
            name=integration.get("name", ""),
            description=integration.get("description", ""),
            category=category,
            created_by=user_id,
            clone_count=integration.get("clone_count", 0),
            published_at=now.isoformat(),
            tool_count=len(tools),
            tools=tools,
        )

        # Invalidate marketplace cache so new integration appears
        await delete_cache_by_pattern("marketplace:community:*")

        public_url = f"/marketplace/{integration_id}"
        logger.info(f"Published integration {integration_id}")

        return PublishIntegrationResponse(
            message="Integration published successfully",
            integration_id=integration_id,
            public_url=public_url,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error publishing integration {integration_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to publish integration")


@router.post(
    "/custom/{integration_id}/unpublish", response_model=UnpublishIntegrationResponse
)
async def unpublish_integration(
    integration_id: str,
    user_id: str = Depends(get_user_id),
) -> UnpublishIntegrationResponse:
    """Unpublish a custom integration from the community marketplace."""
    try:
        # Fetch the integration
        integration = await integrations_collection.find_one(
            {"integration_id": integration_id}
        )
        if not integration:
            raise HTTPException(status_code=404, detail="Integration not found")

        # Verify user owns this integration
        if integration.get("created_by") != user_id:
            raise HTTPException(
                status_code=403,
                detail="You can only unpublish integrations you created",
            )

        # Check if it's actually published
        if not integration.get("is_public"):
            raise HTTPException(
                status_code=400, detail="Integration is not currently published"
            )

        # Update the integration to unpublish
        update_result = await integrations_collection.update_one(
            {"integration_id": integration_id},
            {
                "$set": {"is_public": False},
                "$unset": {"published_at": ""},
            },
        )

        if update_result.modified_count == 0:
            raise HTTPException(status_code=500, detail="Failed to update integration")

        # Remove from ChromaDB index
        await remove_public_integration(integration_id)

        # Invalidate marketplace cache so integration is removed
        await delete_cache_by_pattern("marketplace:community:*")

        logger.info(f"Unpublished integration {integration_id}")

        return UnpublishIntegrationResponse(
            message="Integration unpublished successfully",
            integration_id=integration_id,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error unpublishing integration {integration_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to unpublish integration")
