"""Integration config, catalog, and connection routes."""

from typing import cast

from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.api.v1.dependencies.oauth_dependencies import get_current_user, get_user_id
from app.api.v1.middleware.rate_limiter import limiter
from app.config.settings import settings
from app.constants.auth import AUDIT_ACTOR_UNAUTHENTICATED
from app.constants.log_tags import LogTag
from app.db.repositories.users import user_repository
from app.models.user_models import AuthenticatedUser
from app.schemas.integrations.requests import ConnectIntegrationRequest
from app.schemas.integrations.responses import (
    ConnectIntegrationResponse,
    IntegrationsConfigResponse,
    IntegrationSuccessResponse,
    IntegrationToolsResponse,
    MyIntegrationsResponse,
)
from app.services.analytics_service import AnalyticsEvents, capture_context_event
from app.services.connect_link_service import resolve_and_consume_connect_code
from app.services.integrations.integration_connection_service import (
    build_integrations_config,
    connect_composio_integration,
    connect_mcp_integration,
    connect_self_integration,
    disconnect_integration,
    initiate_integration_connection,
)
from app.services.integrations.integration_resolver import IntegrationResolver
from app.services.integrations.my_integrations import (
    get_integration_tools,
    get_my_integrations,
)
from shared.py.wide_events import log

router = APIRouter()


@router.get("/config", response_model=IntegrationsConfigResponse)
async def get_integrations_config() -> IntegrationsConfigResponse:
    """Return the static integrations catalog used to render the integrations UI."""
    log.set(operation="get_integrations_config")
    result = build_integrations_config()
    log.set(outcome="success")
    return result


@router.get("/me")
async def get_my_integrations_endpoint(
    user_id: str = Depends(get_user_id),
) -> MyIntegrationsResponse:
    """The current user's full integration catalog (platform + their custom),
    each with connection status and tool count. One call replaces the old
    /config + /status + /users/me/integrations merge."""
    log.set(operation="get_my_integrations", user={"id": user_id})
    result = await get_my_integrations(user_id)
    log.set(result_count=result.total, outcome="success")
    # Cacheable erases the wrapped function's return type; get_my_integrations is
    # declared -> MyIntegrationsResponse, so this is correct by construction.
    return cast(MyIntegrationsResponse, result)


@router.get("/{integration_id}/tools")
async def get_integration_tools_endpoint(
    integration_id: str,
    user_id: str = Depends(get_user_id),
) -> IntegrationToolsResponse:
    """Full tool list for one integration, fetched on demand (sidebar, mentions).

    A private custom integration the caller can't access raises AppError(403),
    handled by the global exception handler.
    """
    log.set(operation="get_integration_tools", integration={"id": integration_id})
    result = await get_integration_tools(integration_id, user_id)
    log.set(result_count=result.count, outcome="success")
    return result


@router.delete("/{integration_id}", response_model=IntegrationSuccessResponse)
async def disconnect_integration_endpoint(
    integration_id: str,
    user_id: str = Depends(get_user_id),
) -> IntegrationSuccessResponse:
    """Disconnect an integration from the current user's account."""
    try:
        log.set(
            operation="disconnect_integration",
            integration_id=integration_id,
            user={"id": user_id},
            integration={"id": integration_id},
        )
        result = await disconnect_integration(user_id, integration_id)
        log.set(outcome="success")
        capture_context_event(
            AnalyticsEvents.INTEGRATION_DISCONNECTED,
            {"integration_id": integration_id},
        )
        return result
    except ValueError as e:
        error_message = str(e)
        # Only return 404 if the integration itself doesn't exist
        if "not found" in error_message.lower() and "account" not in error_message.lower():
            raise HTTPException(status_code=404, detail=error_message) from e
        # For "no active connected account" or other cases, return 400
        raise HTTPException(status_code=400, detail=error_message) from e
    except Exception as e:
        log.error(
            f"{LogTag.INTEGRATION} Error disconnecting integration",
            integration_id=integration_id,
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail="Failed to disconnect integration") from e


@router.post("/connect/{integration_id}", response_model=ConnectIntegrationResponse)
async def connect_integration_endpoint(
    integration_id: str,
    request: ConnectIntegrationRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> ConnectIntegrationResponse:
    """Connect an integration for the current user, returning the next-step action."""
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
            # OAuth-managed connects complete at their callback; only a direct
            # (no-auth / bearer) connect finishes here.
            if result.status == "connected":
                capture_context_event(
                    AnalyticsEvents.INTEGRATION_CONNECTED,
                    {
                        "integration_id": integration_id,
                        "managed_by": resolved.managed_by,
                    },
                )
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
        log.error(
            f"{LogTag.INTEGRATION} Failed to connect integration",
            integration_id=integration_id,
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        log.set(integration={"id": integration_id, "status": "error"})
        return ConnectIntegrationResponse(
            status="error",
            integration_id=integration_id,
            name=resolved.name,
            error=str(e),
        )


def _connect_link_error(reason: str) -> RedirectResponse:
    """Bounce a failed connect-link open to the public integrations page.

    Goes to the integrations page (not a login wall) so a logged-out bot user
    still lands somewhere useful.
    """
    base = settings.FRONTEND_URL.rstrip("/")
    return RedirectResponse(url=f"{base}/integrations?connect_error={reason}")


@router.get("/connect-link")
@limiter.limit("10/minute")
async def connect_link_endpoint(request: Request, code: str) -> RedirectResponse:  # noqa: ARG001 -- slowapi's @limiter.limit requires request in the handler signature
    """Login-free entry point for bot / non-UI users.

    Resolves the single-use connect code to its bound ``(user, integration)``
    (no session required — the code is the credential) and bounces the user
    straight into the provider OAuth flow. Invalid/expired/used codes redirect
    to a friendly page. Excluded from auth in WorkOSAuthMiddleware; it
    self-authenticates. Per-IP rate limited so the short code can't be brute
    forced online.
    """
    log.set(operation="connect_link")
    verified = await resolve_and_consume_connect_code(code)
    if not verified:
        # Recorded, not swallowed: the redirect is a 307 that reads like success,
        # and this endpoint is auth-excluded and rate-limited precisely because
        # the code is brute-forceable — failed redemptions must be queryable.
        log.set(outcome="rejected")
        log.warning(
            f"{LogTag.INTEGRATION} Connect link redemption rejected",
            failure="unknown_or_consumed_code",
        )
        # The code IS the credential and it resolved to no binding — the record
        # carries the outcome, never the code that was presented.
        log.audit(
            "connect link redemption rejected",
            actor=AUDIT_ACTOR_UNAUTHENTICATED,
            reason="unknown_or_consumed_code",
        )
        return _connect_link_error("invalid_or_expired_link")

    user_id, integration_id = verified
    log.set(user={"id": user_id}, integration={"id": integration_id})
    # The single-use code is spent here: this is the state change, and it grants
    # the holder the bound user's OAuth flow without a session.
    log.audit(
        "connect link redeemed",
        actor=user_id,
        resource=integration_id,
    )

    # Self-managed (Google) connectors use email as an OAuth login hint; others
    # ignore it. user_id is trusted (it came from a server-bound, single-use code).
    user_email = ""
    try:
        user_doc = await user_repository.get(user_id)
    except InvalidId as e:
        # A server-issued code that carries a non-ObjectId user_id means the
        # stored binding is corrupt — same opaque bounce for the client, but a
        # distinct failure in telemetry.
        log.set(outcome="rejected")
        log.warning(
            f"{LogTag.INTEGRATION} Connect link redemption rejected",
            failure="malformed_user_id",
            error_type=type(e).__name__,
        )
        log.audit(
            "connect link redemption rejected",
            actor=user_id,
            resource=integration_id,
            reason="malformed_user_id",
            error_type=type(e).__name__,
        )
        return _connect_link_error("invalid_or_expired_link")
    if user_doc:
        user_email = user_doc.email or ""

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
    return _connect_link_error("could_not_start")
