"""Integration API routes."""

from datetime import datetime, timezone
from typing import Optional

from app.api.v1.dependencies.oauth_dependencies import get_current_user, get_user_id
from app.config.loggers import auth_logger as logger
from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.db.chroma.public_integrations_store import (
    index_public_integration,
    remove_public_integration,
)
from app.db.mongodb.collections import integrations_collection, users_collection
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
    AddUserIntegrationResponse,
    CloneIntegrationResponse,
    CommunityIntegrationCreator,
    CommunityIntegrationItem,
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
from app.utils.string_utils import generate_unique_slug
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
    create_custom_integration,
    delete_custom_integration,
    get_all_integrations,
    get_integration_details,
    get_user_integrations,
    remove_user_integration,
    update_custom_integration,
)
from app.services.mcp.mcp_client import get_mcp_client
from app.services.oauth.oauth_service import get_all_integrations_status
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
    """
    from app.db.chroma.public_integrations_store import search_public_integrations

    try:
        # Clamp limit to max 100
        limit = min(limit, 100)

        # If search query provided, use ChromaDB semantic search
        if search and search.strip():
            # Use semantic search via ChromaDB
            search_results = await search_public_integrations(
                query=search.strip(),
                limit=limit,
                category=category if category != "all" else None,
            )

            # Fetch full integration docs from MongoDB for additional data
            integration_ids = [
                r.get("integration_id")
                for r in search_results
                if r.get("integration_id")
            ]

            if not integration_ids:
                return CommunityListResponse(integrations=[], total=0, has_more=False)

            # Fetch full documents from MongoDB
            cursor = integrations_collection.find(
                {"integration_id": {"$in": integration_ids}, "is_public": True}
            )
            docs = await cursor.to_list(length=limit)

            # Create a map for ordering by search relevance
            docs_map = {doc["integration_id"]: doc for doc in docs}
            ordered_docs = [docs_map[iid] for iid in integration_ids if iid in docs_map]

            integrations = _format_community_integrations(ordered_docs)

            return CommunityListResponse(
                integrations=integrations,
                total=len(integrations),
                has_more=False,  # Semantic search doesn't support pagination
            )

        # MongoDB query path (without search)
        query = {"is_public": True}

        # Apply category filter
        if category and category != "all":
            query["category"] = category

        # Determine sort order
        if sort == "popular":
            sort_field = [("clone_count", -1), ("published_at", -1)]
        elif sort == "recent":
            sort_field = [("published_at", -1)]
        elif sort == "name":
            sort_field = [("name", 1)]
        else:
            sort_field = [("clone_count", -1), ("published_at", -1)]

        # Get total count
        total = await integrations_collection.count_documents(query)

        # Fetch with pagination
        cursor = (
            integrations_collection.find(query)
            .sort(sort_field)
            .skip(offset)
            .limit(limit)
        )
        docs = await cursor.to_list(length=limit)

        integrations = _format_community_integrations(docs)

        return CommunityListResponse(
            integrations=integrations,
            total=total,
            has_more=(offset + len(docs)) < total,
        )

    except Exception as e:
        logger.error(f"Error fetching community integrations: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to fetch community integrations"
        )


def _format_community_integrations(docs: list) -> list[CommunityIntegrationItem]:
    """Format MongoDB documents into CommunityIntegrationItem responses."""
    result = []
    for doc in docs:
        tools = doc.get("tools", [])
        tool_items = [
            IntegrationTool(
                name=t.get("name", ""),
                description=t.get("description"),
            )
            for t in tools[:10]  # Limit to first 10 tools
        ]

        creator = None
        if doc.get("creator_name") or doc.get("creator_picture"):
            creator = CommunityIntegrationCreator(
                name=doc.get("creator_name"),
                picture=doc.get("creator_picture"),
            )

        result.append(
            CommunityIntegrationItem(
                integration_id=doc["integration_id"],
                name=doc["name"],
                description=doc.get("description", ""),
                category=doc.get("category", "custom"),
                icon_url=doc.get("icon_url"),
                slug=doc.get("slug"),
                clone_count=doc.get("clone_count", 0),
                tool_count=len(tools),
                tools=tool_items,
                published_at=doc.get("published_at"),
                creator=creator,
            )
        )
    return result


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
    import asyncio
    import time

    from app.db.mongodb.collections import integrations_collection
    from app.utils.favicon_utils import fetch_favicon_from_url

    try:
        t_start = time.perf_counter()

        # EARLY VALIDATION: Check for duplicate name BEFORE slow network ops
        # This prevents users from waiting 50+ seconds only to get a duplicate error
        potential_id = f"custom_{request.name.lower().replace(' ', '_')}_{user_id}"
        existing = await integrations_collection.find_one(
            {"integration_id": potential_id}
        )
        if existing:
            raise ValueError(
                f"You already have an integration named '{request.name}'. "
                "Please choose a different name."
            )

        t0 = time.perf_counter()
        mcp_client = await get_mcp_client(user_id=user_id)
        logger.info(
            f"[TIMING] get_mcp_client: {(time.perf_counter() - t0) * 1000:.0f}ms"
        )

        # Parallel: Favicon fetch + MCP probe
        t1 = time.perf_counter()
        favicon_result, probe_result = await asyncio.gather(
            fetch_favicon_from_url(request.server_url),
            mcp_client.probe_connection(request.server_url),
            return_exceptions=True,
        )
        logger.info(
            f"[TIMING] parallel fetch (favicon + probe): {(time.perf_counter() - t1) * 1000:.0f}ms"
        )

        # Log individual results for debugging
        if isinstance(favicon_result, Exception):
            logger.debug(f"[TIMING] favicon fetch failed: {favicon_result}")
        if isinstance(probe_result, Exception):
            logger.debug(f"[TIMING] probe failed: {probe_result}")

        icon_url = None
        if favicon_result and not isinstance(favicon_result, Exception):
            icon_url = favicon_result

        t2 = time.perf_counter()
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
        logger.info(
            f"[TIMING] create_custom_integration: {(time.perf_counter() - t2) * 1000:.0f}ms"
        )
        logger.info(
            f"[TIMING] total before connect: {(time.perf_counter() - t_start) * 1000:.0f}ms"
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
                # mcp-use detected OAuth requirement at runtime (probe missed it)
                # Update the stored integration so future connects know auth is required
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
