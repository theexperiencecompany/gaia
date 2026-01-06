from functools import lru_cache
from typing import Optional
from urllib.parse import urlencode

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.config.loggers import auth_logger as logger
from app.config.oauth_config import (
    OAUTH_INTEGRATIONS,
    get_integration_by_id,
    get_integration_scopes,
)
from app.config.settings import settings
from app.config.token_repository import token_repository
from app.constants.keys import OAUTH_STATUS_KEY
from app.db.redis import delete_cache
from app.helpers.mcp_helpers import get_api_base_url, invalidate_mcp_status_cache
from app.models.integration_models import (
    AddUserIntegrationRequest,
    ConnectIntegrationRequest,
    ConnectIntegrationResponse,
    CreateCustomIntegrationRequest,
    IntegrationResponse,
    MarketplaceResponse,
    UpdateCustomIntegrationRequest,
    UserIntegrationsListResponse,
)
from app.models.oauth_models import IntegrationConfigResponse
from app.services.composio.composio_service import (
    COMPOSIO_SOCIAL_CONFIGS,
    get_composio_service,
)
from app.services.integration_service import (
    add_user_integration,
    create_custom_integration,
    delete_custom_integration,
    get_all_integrations,
    get_integration_details,
    get_user_integrations,
    remove_user_integration,
    update_custom_integration,
    update_user_integration_status,
)
from app.services.mcp.mcp_client import get_mcp_client
from app.services.mcp.mcp_tools_store import get_mcp_tools_store
from app.services.oauth_service import get_all_integrations_status
from app.services.oauth_state_service import create_oauth_state
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse

router = APIRouter()


@lru_cache(maxsize=1)
def _build_integrations_config():
    """
    Build and cache the integrations configuration response.
    This function is cached using lru_cache for performance.

    Note: Internal integrations (managed_by="internal") like todos, reminders,
    and goals are core platform features that don't require user connection.
    They are filtered out from the frontend integrations UI.
    """
    integration_configs = []
    for integration in OAUTH_INTEGRATIONS:
        # Skip internal integrations - they're core platform features, not user-connectable
        if integration.managed_by == "internal":
            continue

        # Determine loginEndpoint based on managed_by
        if not integration.available:
            login_endpoint = None
        elif integration.managed_by == "mcp":
            login_endpoint = f"mcp/connect/{integration.id}"
        else:
            login_endpoint = f"integrations/login/{integration.id}"

        # Determine authType for MCP integrations (for frontend display)
        auth_type = None
        if integration.mcp_config:
            auth_type = "oauth" if integration.mcp_config.requires_auth else "none"

        config = IntegrationConfigResponse(
            id=integration.id,
            name=integration.name,
            description=integration.description,
            category=integration.category,
            provider=integration.provider,
            available=integration.available,
            loginEndpoint=login_endpoint,
            isSpecial=integration.is_special,
            displayPriority=integration.display_priority,
            includedIntegrations=integration.included_integrations,
            isFeatured=integration.is_featured,
            managedBy=integration.managed_by,
            authType=auth_type,
        )
        integration_configs.append(config.model_dump())

    return {"integrations": integration_configs}


@router.get("/config")
async def get_integrations_config():
    """
    Get the configuration for all integrations.
    This endpoint is public and returns integration metadata.
    Uses lru_cache for improved performance.
    """
    cached_config = _build_integrations_config()
    return JSONResponse(content=cached_config)


@router.get("/status")
async def get_integrations_status(
    user: dict = Depends(get_current_user),
):
    """
    Get the integration status for the current user based on OAuth scopes.
    """
    try:
        user_id = user.get("user_id")

        if not user_id:
            logger.warning("User ID not found in user object")
            return JSONResponse(
                content={"integrations": [], "debug": {"error": "User ID not found"}},
                status_code=400,
            )

        # Use unified status checker for all integrations
        status_map = await get_all_integrations_status(str(user_id))

        # Build integration statuses
        integration_statuses = [
            {
                "integrationId": integration_id,
                "connected": status_map.get(integration_id, False),
            }
            for integration_id in status_map.keys()
        ]

        return JSONResponse(
            content={
                "integrations": integration_statuses,
            }
        )

    except Exception as e:
        logger.error(f"Error checking integration status: {e}")
        # Return all disconnected on error
        return JSONResponse(
            content={
                "integrations": [
                    {"integrationId": i.id, "connected": False}
                    for i in OAUTH_INTEGRATIONS
                ]
            }
        )


@router.delete("/{integration_id}")
async def disconnect_integration(
    integration_id: str,
    user: dict = Depends(get_current_user),
):
    """
    Disconnect a connected integration for the current user.
    Supports platform integrations (Composio, self, MCP) and custom integrations.
    """
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")

    # Try platform integration first
    integration = get_integration_by_id(integration_id)

    # If not found in platform list, check MongoDB for custom integrations
    if not integration:
        integration_details = await get_integration_details(integration_id)
        if not integration_details or integration_details.source != "custom":
            raise HTTPException(
                status_code=404, detail=f"Integration {integration_id} not found"
            )

        # Handle custom MCP integration disconnect
        try:
            mcp_client = get_mcp_client(user_id=str(user_id))
            await mcp_client.disconnect(integration_id)
            # Remove from user_integrations
            await remove_user_integration(str(user_id), integration_id)
            # If user is the creator, also delete the integration itself
            if integration_details.created_by == str(user_id):
                await delete_custom_integration(str(user_id), integration_id)

            return JSONResponse(
                content={
                    "status": "success",
                    "message": f"Successfully disconnected {integration_details.name}",
                    "integrationId": integration_id,
                }
            )
        except Exception as e:
            logger.error(
                f"Error disconnecting custom integration {integration_id} for user {user_id}: {e}"
            )
            raise HTTPException(
                status_code=500, detail="Failed to disconnect integration"
            )

    # Handle platform integrations
    if integration.managed_by == "composio":
        composio_service = get_composio_service()
        try:
            await composio_service.delete_connected_account(
                user_id=str(user_id), provider=integration.provider
            )
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:
            logger.error(
                f"Error disconnecting integration {integration_id} for user {user_id}: {e}"
            )
            raise HTTPException(
                status_code=500, detail="Failed to disconnect integration"
            )

    elif integration.managed_by == "self":
        # Handle internal disconnection by revoking the token
        try:
            # For internal integrations, the provider in config matches the provider in token repo
            success = await token_repository.revoke_token(
                user_id=str(user_id), provider=integration.provider
            )
            if not success:
                # If token not found, consider it already disconnected
                logger.warning(
                    f"Attempted to disconnect {integration_id} but no token found for user {user_id}"
                )
        except Exception as e:
            logger.error(
                f"Error disconnecting internal integration {integration_id} for user {user_id}: {e}"
            )
            raise HTTPException(
                status_code=500, detail="Failed to disconnect integration"
            )

    elif integration.managed_by == "mcp":
        # Handle MCP integration disconnection (both auth and unauth)
        try:
            mcp_client = get_mcp_client(user_id=str(user_id))
            await mcp_client.disconnect(integration_id)
            # Also remove from user_integrations for unauthenticated MCPs
            if integration.mcp_config and not integration.mcp_config.requires_auth:
                await remove_user_integration(str(user_id), integration_id)
        except Exception as e:
            logger.error(
                f"Error disconnecting MCP integration {integration_id} for user {user_id}: {e}"
            )
            raise HTTPException(
                status_code=500, detail="Failed to disconnect MCP integration"
            )

    else:
        raise HTTPException(
            status_code=400,
            detail=f"Integration {integration_id} disconnect not supported.",
        )

    try:
        cache_key = f"{OAUTH_STATUS_KEY}:{user_id}"
        await delete_cache(cache_key)
        logger.info(f"OAuth status cache invalidated for user {user_id}")
    except Exception as e:
        logger.warning(f"Failed to invalidate OAuth status cache: {e}")

    # Update user_integrations status in MongoDB
    try:
        await update_user_integration_status(str(user_id), integration_id, "created")
        logger.info(
            f"Updated user_integrations status to 'created' for {integration_id}"
        )
    except Exception as e:
        logger.warning(f"Failed to update user_integrations status: {e}")

    return JSONResponse(
        content={
            "status": "success",
            "message": f"Successfully disconnected {integration.name}",
            "integrationId": integration_id,
        }
    )


@router.get("/login/{integration_id}")
async def login_integration(
    integration_id: str,
    redirect_path: str,
    user: dict = Depends(get_current_user),
):
    """Dynamic OAuth login for any configured integration."""
    integration = get_integration_by_id(integration_id)
    composio_service = get_composio_service()

    if not integration:
        raise HTTPException(
            status_code=404, detail=f"Integration {integration_id} not found"
        )

    if not integration.available:
        raise HTTPException(
            status_code=400, detail=f"Integration {integration_id} is not available yet"
        )

    # Create secure state token for OAuth flow
    state_token = await create_oauth_state(
        user_id=user["user_id"],
        redirect_path=redirect_path,
        integration_id=integration_id,
    )

    # Streamlined composio integration handling
    composio_providers = set([k for k in COMPOSIO_SOCIAL_CONFIGS.keys()])
    if integration.provider in composio_providers:
        # Ensure user_integrations record exists with status "created"
        await update_user_integration_status(
            str(user["user_id"]), integration_id, "created"
        )
        provider_key = integration.provider
        url = await composio_service.connect_account(
            provider_key, user["user_id"], state_token=state_token
        )
        return RedirectResponse(url=url["redirect_url"])
    elif integration.managed_by == "mcp":
        # MCP integrations use dedicated /mcp/connect endpoint
        raise HTTPException(
            status_code=400,
            detail=f"Use POST /api/v1/mcp/connect/{integration_id} to connect MCP integrations.",
        )
    elif integration.provider == "google":
        # Ensure user_integrations record exists with status "created"
        await update_user_integration_status(
            str(user["user_id"]), integration_id, "created"
        )

        # Get base scopes
        base_scopes = ["openid", "profile", "email"]

        # Get new integration scopes
        new_scopes = get_integration_scopes(integration_id)

        # Get existing scopes from user's current token
        existing_scopes = []
        user_id = user.get("user_id")

        if user_id:
            try:
                token = await token_repository.get_token(
                    str(user_id), "google", renew_if_expired=False
                )
                existing_scopes = str(token.get("scope", "")).split()
            except Exception as e:
                logger.warning(f"Could not get existing scopes: {e}")

        # Combine all scopes (base + existing + new), removing duplicates
        all_scopes = list(set(base_scopes + existing_scopes + new_scopes))

        params = {
            "response_type": "code",
            "client_id": settings.GOOGLE_CLIENT_ID,
            "redirect_uri": settings.GOOGLE_CALLBACK_URL,
            "scope": " ".join(all_scopes),
            "access_type": "offline",
            "prompt": "consent",  # Only force consent for additional scopes
            "include_granted_scopes": "true",  # Include previously granted scopes
            "login_hint": user.get("email"),
            "state": state_token,  # Secure state token for CSRF protection
        }
        auth_url = f"https://accounts.google.com/o/oauth2/auth?{urlencode(params)}"
        return RedirectResponse(url=auth_url)

    raise HTTPException(
        status_code=400,
        detail=f"OAuth provider {integration.provider} not implemented",
    )


@router.post("/connect/{integration_id}", response_model=ConnectIntegrationResponse)
async def connect_integration(
    integration_id: str,
    request: ConnectIntegrationRequest,
    user: dict = Depends(get_current_user),
):
    """
    Unified endpoint to connect any integration type.

    This is the single entry point for all integration connections.
    The backend determines the appropriate connection method based on:
    - managed_by: mcp, composio, self
    - requires_auth: whether OAuth is needed
    - source: platform or custom

    Response statuses:
    - connected: Integration is ready to use (no auth needed or already authed)
    - redirect: OAuth required, frontend should redirect to redirect_url
    - error: Connection failed

    For OAuth flows, the frontend should redirect the browser to redirect_url.
    After OAuth completes, the callback will redirect back to redirect_path.
    """
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")

    # Try to find integration in platform config first
    platform_integration = get_integration_by_id(integration_id)

    # If not found, check custom integrations in MongoDB
    custom_integration = None
    if not platform_integration:
        custom_integration = await get_integration_details(integration_id)
        if not custom_integration:
            raise HTTPException(
                status_code=404, detail=f"Integration {integration_id} not found"
            )

    # Determine integration properties
    if platform_integration:
        managed_by = platform_integration.managed_by
        requires_auth = False
        provider = platform_integration.provider

        if platform_integration.mcp_config:
            requires_auth = platform_integration.mcp_config.requires_auth
        elif platform_integration.composio_config:
            requires_auth = True
        elif managed_by == "self":
            requires_auth = True

        if not platform_integration.available:
            return ConnectIntegrationResponse(
                status="error",
                integration_id=integration_id,
                error=f"Integration {integration_id} is not available yet",
            )
    else:
        # Custom integration (always MCP)
        managed_by = custom_integration.managed_by
        requires_auth = custom_integration.requires_auth
        provider = None

    # Handle based on managed_by type
    try:
        if managed_by == "mcp":
            return await _connect_mcp_integration(
                user_id=str(user_id),
                integration_id=integration_id,
                requires_auth=requires_auth,
                redirect_path=request.redirect_path,
                bearer_token=request.bearer_token,
            )

        elif managed_by == "composio":
            return await _connect_composio_integration(
                user_id=str(user_id),
                integration_id=integration_id,
                provider=provider,
                redirect_path=request.redirect_path,
            )

        elif managed_by == "self":
            return await _connect_self_integration(
                user=user,
                integration_id=integration_id,
                provider=provider,
                redirect_path=request.redirect_path,
            )

        else:
            return ConnectIntegrationResponse(
                status="error",
                integration_id=integration_id,
                error=f"Unsupported integration type: {managed_by}",
            )

    except Exception as e:
        logger.error(f"Failed to connect {integration_id}: {e}")
        return ConnectIntegrationResponse(
            status="error",
            integration_id=integration_id,
            error=str(e),
        )


async def _connect_mcp_integration(
    user_id: str,
    integration_id: str,
    requires_auth: bool,
    redirect_path: str,
    bearer_token: Optional[str] = None,
) -> ConnectIntegrationResponse:
    """Handle MCP integration connection."""
    mcp_client = get_mcp_client(user_id=user_id)

    if requires_auth:
        # OAuth required - return redirect URL
        await update_user_integration_status(user_id, integration_id, "created")

        auth_url = await mcp_client.build_oauth_auth_url(
            integration_id=integration_id,
            redirect_uri=f"{get_api_base_url()}/api/v1/mcp/oauth/callback",
            redirect_path=redirect_path,
        )

        return ConnectIntegrationResponse(
            status="redirect",
            integration_id=integration_id,
            redirect_url=auth_url,
            message="OAuth authentication required",
        )

    # No auth required - connect directly
    await update_user_integration_status(user_id, integration_id, "connected")

    tools = await mcp_client.connect(integration_id)
    tools_count = len(tools) if tools else 0

    # Store tools globally for frontend visibility
    if tools:
        global_store = get_mcp_tools_store()
        tool_metadata = [
            {"name": t.name, "description": t.description or ""} for t in tools
        ]
        await global_store.store_tools(integration_id, tool_metadata)

    await invalidate_mcp_status_cache(user_id)

    return ConnectIntegrationResponse(
        status="connected",
        integration_id=integration_id,
        tools_count=tools_count,
        message="Integration connected successfully",
    )


async def _connect_composio_integration(
    user_id: str,
    integration_id: str,
    provider: str,
    redirect_path: str,
) -> ConnectIntegrationResponse:
    """Handle Composio integration connection."""
    composio_service = get_composio_service()

    # Create state token for OAuth
    state_token = await create_oauth_state(
        user_id=user_id,
        redirect_path=redirect_path,
        integration_id=integration_id,
    )

    await update_user_integration_status(user_id, integration_id, "created")

    url = await composio_service.connect_account(
        provider, user_id, state_token=state_token
    )

    return ConnectIntegrationResponse(
        status="redirect",
        integration_id=integration_id,
        redirect_url=url["redirect_url"],
        message="OAuth authentication required",
    )


async def _connect_self_integration(
    user: dict,
    integration_id: str,
    provider: str,
    redirect_path: str,
) -> ConnectIntegrationResponse:
    """Handle self-managed integration connection (Google)."""
    user_id = user.get("user_id")

    if provider != "google":
        return ConnectIntegrationResponse(
            status="error",
            integration_id=integration_id,
            error=f"Provider {provider} not implemented",
        )

    # Create state token for OAuth
    state_token = await create_oauth_state(
        user_id=user_id,
        redirect_path=redirect_path,
        integration_id=integration_id,
    )

    await update_user_integration_status(str(user_id), integration_id, "created")

    # Build Google OAuth URL
    base_scopes = ["openid", "profile", "email"]
    new_scopes = get_integration_scopes(integration_id)

    # Get existing scopes
    existing_scopes = []
    try:
        token = await token_repository.get_token(
            str(user_id), "google", renew_if_expired=False
        )
        existing_scopes = str(token.get("scope", "")).split()
    except Exception as e:
        logger.debug(f"Could not get existing scopes for user {user_id}: {e}")

    all_scopes = list(set(base_scopes + existing_scopes + new_scopes))

    params = {
        "response_type": "code",
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_CALLBACK_URL,
        "scope": " ".join(all_scopes),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "login_hint": user.get("email"),
        "state": state_token,
    }
    auth_url = f"https://accounts.google.com/o/oauth2/auth?{urlencode(params)}"

    return ConnectIntegrationResponse(
        status="redirect",
        integration_id=integration_id,
        redirect_url=auth_url,
        message="OAuth authentication required",
    )


@router.get("/marketplace", response_model=MarketplaceResponse)
async def list_marketplace_integrations(
    category: Optional[str] = None,
):
    """
    Get all available integrations for the marketplace.

    This is a public endpoint that returns:
    - Platform integrations from code (OAUTH_INTEGRATIONS)
    - Public custom integrations from MongoDB
    """
    try:
        result = await get_all_integrations(category=category)
        return result
    except Exception as e:
        logger.error(f"Error fetching marketplace integrations: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch integrations")


@router.get("/marketplace/{integration_id}", response_model=IntegrationResponse)
async def get_marketplace_integration(integration_id: str):
    """
    Get details for a single integration.
    """
    integration = await get_integration_details(integration_id)
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    return integration


@router.get("/users/me/integrations", response_model=UserIntegrationsListResponse)
async def list_user_integrations(
    user: dict = Depends(get_current_user),
):
    """
    Get all integrations the current user has added to their workspace.
    """
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")

    try:
        result = await get_user_integrations(str(user_id))
        return result
    except Exception as e:
        logger.error(f"Error fetching user integrations for {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch user integrations")


@router.post("/users/me/integrations")
async def add_integration_to_workspace(
    request: AddUserIntegrationRequest,
    user: dict = Depends(get_current_user),
):
    """
    Add an integration to the current user's workspace.

    If the integration doesn't require authentication, it will be
    immediately connected. Otherwise, status will be 'created' until
    the user completes OAuth.
    """
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")

    try:
        user_integration = await add_user_integration(
            str(user_id), request.integration_id
        )
        return JSONResponse(
            content={
                "status": "success",
                "message": "Integration added to workspace",
                "integration_id": user_integration.integration_id,
                "connection_status": user_integration.status,
            }
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error adding integration for {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to add integration")


@router.delete("/users/me/integrations/{integration_id}")
async def remove_integration_from_workspace(
    integration_id: str,
    user: dict = Depends(get_current_user),
):
    """
    Remove an integration from the current user's workspace.

    This does NOT disconnect OAuth - it just removes the integration
    from the user's workspace list.
    """
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")

    try:
        removed = await remove_user_integration(str(user_id), integration_id)
        if not removed:
            raise HTTPException(
                status_code=404, detail="Integration not found in workspace"
            )

        return JSONResponse(
            content={
                "status": "success",
                "message": "Integration removed from workspace",
                "integration_id": integration_id,
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error removing integration for {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to remove integration")


@router.post("/custom")
async def create_custom_mcp_integration(
    request: CreateCustomIntegrationRequest,
    user: dict = Depends(get_current_user),
):
    """
    Create a custom MCP integration.

    The integration will be automatically added to the creator's workspace.
    If is_public=True, it will be visible in the marketplace.

    After creation, immediately probes the server and attempts connection:
    - No auth required: Connects and returns tools_count
    - OAuth required: Returns oauth_url for frontend to redirect
    - Connection failed: Returns error message
    """
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")

    try:
        integration = await create_custom_integration(str(user_id), request)

        # Immediately test connection after creation
        connection_result = {"status": "created"}
        mcp_client = get_mcp_client(user_id=str(user_id))

        try:
            # Probe for auth requirements
            probe_result = await mcp_client.probe_connection(request.server_url)

            if probe_result.get("error"):
                # Probe failed - server may be unreachable
                connection_result = {
                    "status": "failed",
                    "error": probe_result["error"],
                }
            elif not probe_result.get("requires_auth"):
                # No auth needed - connect immediately
                tools = await mcp_client.connect(integration.integration_id)
                await update_user_integration_status(
                    str(user_id), integration.integration_id, "connected"
                )
                connection_result = {
                    "status": "connected",
                    "tools_count": len(tools) if tools else 0,
                }
                logger.info(
                    f"Auto-connected custom MCP {integration.integration_id}: "
                    f"{connection_result['tools_count']} tools"
                )
            else:
                # OAuth required - build auth URL for frontend
                # Status remains "created" until OAuth completes successfully
                auth_url = await mcp_client.build_oauth_auth_url(
                    integration_id=integration.integration_id,
                    redirect_uri=f"{get_api_base_url()}/api/v1/mcp/oauth/callback",
                    redirect_path="/integrations",
                )
                connection_result = {
                    "status": "requires_oauth",
                    "oauth_url": auth_url,
                }
                logger.info(f"Custom MCP {integration.integration_id} requires OAuth")

        except Exception as conn_err:
            logger.warning(
                f"Auto-connect failed for {integration.integration_id}: {conn_err}"
            )
            connection_result = {
                "status": "failed",
                "error": str(conn_err),
            }

        return JSONResponse(
            content={
                "status": "success",
                "message": "Custom integration created",
                "integration_id": integration.integration_id,
                "name": integration.name,
                "connection": connection_result,
            }
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating custom integration for {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to create integration")


@router.patch("/custom/{integration_id}")
async def update_custom_mcp_integration(
    integration_id: str,
    request: UpdateCustomIntegrationRequest,
    user: dict = Depends(get_current_user),
):
    """
    Update a custom MCP integration.

    Only the creator of the integration can update it.
    """
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")

    try:
        updated = await update_custom_integration(str(user_id), integration_id, request)
        if not updated:
            raise HTTPException(
                status_code=404,
                detail="Integration not found or you are not the owner",
            )

        return JSONResponse(
            content={
                "status": "success",
                "message": "Integration updated",
                "integration_id": updated.integration_id,
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating integration {integration_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to update integration")


@router.delete("/custom/{integration_id}")
async def delete_custom_mcp_integration(
    integration_id: str,
    user: dict = Depends(get_current_user),
):
    """
    Delete a custom MCP integration.

    Only the creator can delete it. This also removes it from
    all users' workspaces.
    """
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")

    try:
        deleted = await delete_custom_integration(str(user_id), integration_id)
        if not deleted:
            raise HTTPException(
                status_code=404,
                detail="Integration not found or you are not the owner",
            )

        return JSONResponse(
            content={
                "status": "success",
                "message": "Integration deleted",
                "integration_id": integration_id,
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting integration {integration_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete integration")
