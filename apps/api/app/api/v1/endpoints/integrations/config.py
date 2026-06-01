"""Integration config, status, and connection routes."""

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse

from app.api.v1.dependencies.oauth_dependencies import get_current_user, get_user_id
from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.config.settings import settings
from app.db.mongodb.collections import users_collection
from app.schemas.integrations.requests import ConnectIntegrationRequest
from app.schemas.integrations.responses import (
    ConnectIntegrationResponse,
    IntegrationsConfigResponse,
    IntegrationsStatusResponse,
    IntegrationStatusItem,
    IntegrationSuccessResponse,
)
from app.services.connect_link_service import verify_and_consume_connect_link_token
from app.services.integrations.integration_connection_service import (
    build_integrations_config,
    connect_composio_integration,
    connect_mcp_integration,
    connect_self_integration,
    disconnect_integration,
    initiate_integration_connection,
)
from app.services.integrations.integration_resolver import IntegrationResolver
from app.services.oauth.oauth_service import get_all_integrations_status
from shared.py.wide_events import log

router = APIRouter()


@router.get("/config", response_model=IntegrationsConfigResponse)
async def get_integrations_config() -> IntegrationsConfigResponse:
    log.set(operation="get_integrations_config")
    result = build_integrations_config()
    log.set(outcome="success")
    return result


@router.get("/status", response_model=IntegrationsStatusResponse)
async def get_integrations_status(
    user_id: str = Depends(get_user_id),
) -> IntegrationsStatusResponse:
    try:
        log.set(operation="get_integrations_status", user={"id": user_id})
        status_map = await get_all_integrations_status(user_id)
        log.set(result_count=len(status_map))
        log.set(outcome="success")
        return IntegrationsStatusResponse(
            integrations=[
                IntegrationStatusItem(integration_id=iid, connected=connected)
                for iid, connected in status_map.items()
            ]
        )
    except Exception as e:
        log.error(f"Error checking integration status: {e}")
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
        log.set(
            operation="disconnect_integration",
            integration_id=integration_id,
            user={"id": user_id},
            integration={"id": integration_id},
        )
        result = await disconnect_integration(user_id, integration_id)
        log.set(outcome="success")
        return result
    except ValueError as e:
        error_message = str(e)
        # Only return 404 if the integration itself doesn't exist
        if "not found" in error_message.lower() and "account" not in error_message.lower():
            raise HTTPException(status_code=404, detail=error_message)
        # For "no active connected account" or other cases, return 400
        raise HTTPException(status_code=400, detail=error_message)
    except Exception as e:
        log.error(f"Error disconnecting {integration_id}: {e}")
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

    log.set(
        operation="connect_integration",
        integration_id=integration_id,
        user={"id": user_id},
        integration={"id": integration_id},
    )
    resolved = await IntegrationResolver.resolve(integration_id)
    if not resolved:
        raise HTTPException(status_code=404, detail=f"Integration {integration_id} not found")

    if resolved.source == "platform" and resolved.platform_integration:
        if not resolved.platform_integration.available:
            return ConnectIntegrationResponse(
                status="error",
                integration_id=integration_id,
                name=resolved.name,
                error=f"Integration {integration_id} is not available yet",
            )

    try:
        auth_type: str | None = None
        if resolved.mcp_config:
            auth_type = "oauth2" if resolved.mcp_config.requires_auth else "none"
        elif resolved.managed_by in ("composio", "self"):
            auth_type = "oauth2"

        provider: str | None = (
            resolved.platform_integration.provider if resolved.platform_integration else None
        )

        log.set(
            integration_name=resolved.name,
            integration={
                "id": integration_id,
                "managed_by": resolved.managed_by,
                "auth_type": auth_type,
                "provider": provider or integration_id,
            },
        )
        if resolved.managed_by == "mcp":
            result = await connect_mcp_integration(
                user_id=str(user_id),
                integration_id=integration_id,
                integration_name=resolved.name,
                requires_auth=resolved.requires_auth,
                redirect_path=request.redirect_path,
                server_url=resolved.mcp_config.server_url if resolved.mcp_config else None,
                is_platform=resolved.source == "platform",
                bearer_token=request.bearer_token,
            )
            log.set(outcome="success")
            return result
        if resolved.managed_by == "composio":
            provider = (
                resolved.platform_integration.provider if resolved.platform_integration else None
            )
            if not provider:
                raise HTTPException(status_code=400, detail="Provider not configured")
            result = await connect_composio_integration(
                user_id=str(user_id),
                integration_id=integration_id,
                integration_name=resolved.name,
                provider=provider,
                redirect_path=request.redirect_path,
            )
            log.set(outcome="success")
            return result
        if resolved.managed_by == "self":
            provider = (
                resolved.platform_integration.provider if resolved.platform_integration else None
            )
            if not provider:
                raise HTTPException(status_code=400, detail="Provider not configured")
            result = await connect_self_integration(
                user_id=str(user_id),
                user_email=user.get("email", ""),
                integration_id=integration_id,
                integration_name=resolved.name,
                provider=provider,
                redirect_path=request.redirect_path,
            )
            log.set(outcome="success")
            return result
        return ConnectIntegrationResponse(
            status="error",
            integration_id=integration_id,
            name=resolved.name,
            error=f"Unsupported integration type: {resolved.managed_by}",
        )
    except Exception as e:
        log.error(f"Failed to connect {integration_id}: {e}")
        log.set(integration={"id": integration_id, "status": "error"})
        return ConnectIntegrationResponse(
            status="error",
            integration_id=integration_id,
            name=resolved.name,
            error=str(e),
        )


# Where a login-free connect link sends the user on a bad token. Public-ish so a
# logged-out bot user isn't bounced to a login wall.
_CONNECT_ERROR_REDIRECT = "/integrations?connect_error=invalid_or_expired_link"


@router.get("/connect-link")
async def connect_link_endpoint(t: str) -> RedirectResponse:
    """Login-free entry point for bot / non-UI users.

    Verifies the signed, single-use, connect-scoped token (no session required —
    identity is in the token) and bounces the user straight into the provider
    OAuth flow. Invalid/expired/used tokens redirect to a friendly page.
    Excluded from auth in WorkOSAuthMiddleware; it self-authenticates.
    """
    log.set(operation="connect_link")
    verified = await verify_and_consume_connect_link_token(t)
    if not verified:
        return RedirectResponse(url=f"{settings.FRONTEND_URL.rstrip('/')}{_CONNECT_ERROR_REDIRECT}")

    user_id, integration_id = verified
    log.set(user={"id": user_id}, integration={"id": integration_id})

    # Self-managed (Google) connectors use email as an OAuth login hint; others
    # ignore it. user_id is trusted (it came from a signature-verified token).
    user_email = ""
    try:
        user_doc = await users_collection.find_one({"_id": ObjectId(user_id)})
    except InvalidId:
        return RedirectResponse(url=f"{settings.FRONTEND_URL.rstrip('/')}{_CONNECT_ERROR_REDIRECT}")
    if user_doc:
        user_email = user_doc.get("email", "")

    result = await initiate_integration_connection(
        user_id=user_id,
        integration_id=integration_id,
        user_email=user_email,
        redirect_path="/integrations",
    )
    if result and result.status == "redirect" and result.redirect_url:
        log.set(outcome="redirect")
        return RedirectResponse(url=result.redirect_url)

    log.set(outcome="error")
    return RedirectResponse(
        url=f"{settings.FRONTEND_URL.rstrip('/')}/integrations?connect_error=could_not_start"
    )
