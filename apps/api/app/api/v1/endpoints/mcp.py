"""
MCP Integration API Routes.

Handles MCP OAuth callbacks and connection testing.
Connection/disconnection is handled by the unified /integrations endpoints.
"""

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.constants.log_tags import LogTag
from app.helpers.mcp_helpers import (
    get_api_base_url,
    get_frontend_url,
)
from app.models.user_models import AuthenticatedUser
from app.schemas.mcp import MCPConnectionTestResponse
from app.services.analytics_service import AnalyticsEvents, capture_context_event
from app.services.integrations.integration_resolver import IntegrationResolver
from app.services.integrations.user_integrations import invalidate_user_integration_caches
from app.services.mcp.mcp_client import get_mcp_client
from shared.py.wide_events import McpContext, log

router = APIRouter()


@router.post("/test/{integration_id}", response_model_exclude_none=True)
async def test_mcp_connection(
    integration_id: str,
    user: AuthenticatedUser = Depends(get_current_user),  # noqa: PT028 -- contract
) -> MCPConnectionTestResponse:
    """
    Test connection to an MCP server.

    Probes the server and returns auth requirements.
    Can be used to retry failed connections.
    """
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")
    log.set(
        user={"id": user_id},
        operation="test_mcp_connection",
        mcp=McpContext(operation="health", server_id=integration_id),
    )

    client = await get_mcp_client(user_id=str(user_id))

    # Get server URL using IntegrationResolver
    resolved = await IntegrationResolver.resolve(integration_id)
    if not resolved or not resolved.mcp_config:
        raise HTTPException(status_code=404, detail="Integration not found")

    server_url = resolved.mcp_config.server_url

    # Probe the server
    probe_result = await client.probe_connection(server_url)
    log.set(
        probe={
            "requires_auth": probe_result.get("requires_auth", False),
            "has_error": bool(probe_result.get("error")),
        }
    )

    probe_error = probe_result.get("error")
    if probe_error:
        log.set(outcome="failed")
        log.set_ns("mcp", success=False)
        return MCPConnectionTestResponse(status="failed", error=probe_error)

    if not probe_result.get("requires_auth"):
        # Try to connect
        try:
            tools = await client.connect(integration_id)
            # Note: status update now handled in connect()
            await invalidate_user_integration_caches(str(user_id))
            log.set(outcome="connected")
            log.set_ns(
                "mcp",
                operation="connect",
                success=True,
                tools_count=len(tools) if tools else 0,
            )
            return MCPConnectionTestResponse(
                status="connected", tools_count=len(tools) if tools else 0
            )
        except Exception as e:
            log.set(outcome="failed")
            log.set_ns(
                "mcp",
                operation="connect",
                success=False,
                error_type=type(e).__name__,
            )
            return MCPConnectionTestResponse(status="failed", error=str(e))

    # OAuth required - update MongoDB with discovered auth requirements
    auth_type = probe_result.get("auth_type", "oauth")
    await client.update_integration_auth_status(
        integration_id, requires_auth=True, auth_type=auth_type
    )

    try:
        auth_url = await client.build_oauth_auth_url(
            integration_id=integration_id,
            redirect_uri=f"{get_api_base_url()}/api/v1/mcp/oauth/callback",
            redirect_path="/integrations",
        )
        log.set(outcome="requires_oauth")
        return MCPConnectionTestResponse(status="requires_oauth", oauth_url=auth_url)
    except Exception as e:
        log.error(
            f"{LogTag.MCP} OAuth URL build failed",
            integration_id=integration_id,
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        return MCPConnectionTestResponse(status="failed", error=str(e))


@router.get("/oauth/callback")
async def mcp_oauth_callback(
    state: str = Query(...),
    code: str | None = Query(None),  # Optional - may be missing if error
    error: str | None = Query(None),  # OAuth error code
    error_description: str | None = Query(None),  # OAuth error description
    user: AuthenticatedUser = Depends(get_current_user),
) -> RedirectResponse:
    """Handle OAuth callback from MCP server.

    Handles both success (with code) and error responses from OAuth server.
    """
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")
    log.set(user={"id": user_id}, operation="mcp_oauth_callback")

    frontend_url = get_frontend_url()

    # Parse state: "token:integration_id:redirect_path"
    parts = state.split(":", 2)
    if len(parts) < 2:
        log.error(f"{LogTag.MCP} Failed to parse OAuth state", error_type="invalid_state_format")
        return RedirectResponse(
            url=f"{frontend_url}/integrations?status=failed&error=invalid_state"
        )
    state_token = parts[0]
    integration_id = parts[1]
    redirect_path = parts[2] if len(parts) > 2 else "/integrations"
    log.set(mcp=McpContext(operation="connect", server_id=integration_id))

    client = await get_mcp_client(user_id=str(user_id))
    redirect_uri = f"{get_api_base_url()}/api/v1/mcp/oauth/callback"

    # Handle OAuth error response from authorization server
    if error:
        log.warning(
            f"{LogTag.MCP} OAuth error returned by provider",
            integration_id=integration_id,
            oauth_error=error,
            oauth_error_description=error_description,
        )

        # Some servers advertise scopes in their metadata that a dynamically
        # registered client cannot request (e.g. agentmail's "user:org:read").
        # Drop the rejected scope(s) and retry the authorization.
        # Best-effort recovery — a Redis/discovery failure here must not turn the
        # error response into a 500. Fall through to the normal error redirect.
        if error == "invalid_scope":
            try:
                retry_url = await client.build_scope_retry_url(
                    integration_id, error_description, redirect_uri, redirect_path
                )
                if retry_url:
                    return RedirectResponse(url=retry_url)
            except Exception as retry_err:
                log.warning(
                    f"{LogTag.MCP} Scope retry URL build failed",
                    integration_id=integration_id,
                    error_type=type(retry_err).__name__,
                )
        try:
            await client.token_store.clear_excluded_scopes(integration_id)
        except Exception as clear_err:
            log.warning(
                f"{LogTag.MCP} Failed to clear excluded scopes",
                integration_id=integration_id,
                error_type=type(clear_err).__name__,
            )

        # Map common OAuth errors to user-friendly codes
        error_code = error
        if error == "server_error":
            error_code = "oauth_server_error"
        elif error not in [
            "access_denied",
            "invalid_request",
            "unauthorized_client",
            "unsupported_response_type",
            "invalid_scope",
            "server_error",
            "temporarily_unavailable",
        ]:
            error_code = "authorization_failed"  # Generic fallback

        return RedirectResponse(
            url=f"{frontend_url}{redirect_path}?id={integration_id}&status=failed&error={error_code}"
        )

    # Validate code is present (required for success case)
    if not code:
        log.error(f"{LogTag.MCP} OAuth callback missing code", integration_id=integration_id)
        return RedirectResponse(
            url=f"{frontend_url}{redirect_path}?id={integration_id}&status=failed&error=missing_code"
        )

    # Resolve integration name for the frontend toast
    resolved = await IntegrationResolver.resolve(integration_id)
    integration_name = resolved.name if resolved else integration_id

    log.set_ns("mcp", server_name=integration_name)
    log.info(
        f"{LogTag.MCP} mcp_oauth_callback: starting handle_oauth_callback",
        integration_id=integration_id,
        user_id=user_id,
    )
    try:
        # handle_oauth_callback now stores tokens, flips status to connected,
        # and dispatches the full MCP connect (handshake + tools/list +
        # schema conversion + Chroma indexing) as a background task. Returns
        # immediately with an empty list — callback fires the redirect in
        # ~1-2s instead of 8-29s.
        await client.handle_oauth_callback(
            integration_id=integration_id,
            code=code,
            state=state_token,
            redirect_uri=redirect_uri,
        )
        # OAuth succeeded — clear any scope exclusions accumulated during retries.
        # Best-effort: a Redis hiccup must not turn a successful connect into an
        # error redirect (a stale exclusion entry expires on its own).
        try:
            await client.token_store.clear_excluded_scopes(integration_id)
        except Exception as clear_err:
            log.warning(
                f"{LogTag.MCP} Failed to clear excluded scopes after OAuth success",
                integration_id=integration_id,
                error_type=type(clear_err).__name__,
            )

        await invalidate_user_integration_caches(str(user_id))

        log.audit("mcp integration connected via oauth", actor=user_id, resource=integration_id)
        capture_context_event(
            AnalyticsEvents.INTEGRATION_CONNECTED,
            {
                "integration_id": integration_id,
                "connection_method": "oauth",
            },
        )

        frontend_url = get_frontend_url()
        log.set(outcome="connected")
        log.set_ns("mcp", success=True)
        log.info(
            f"{LogTag.MCP} mcp_oauth_callback: OAuth complete; connect dispatched to background, redirecting now",
            integration_id=integration_id,
            user_id=user_id,
        )
        return RedirectResponse(
            url=f"{frontend_url}{redirect_path}?id={integration_id}&status=connected&name={quote(integration_name)}"
        )

    except Exception as e:
        log.set(outcome="failed")
        log.set_ns("mcp", success=False, error_type=type(e).__name__)
        log.error(
            f"{LogTag.MCP} mcp_oauth_callback failed",
            integration_id=integration_id,
            user_id=user_id,
            error_type=type(e).__name__,
        )
        frontend_url = get_frontend_url()
        # Sanitize error - use generic codes instead of raw exception messages
        error_code = "connection_failed"
        if "state" in str(e).lower():
            error_code = "invalid_state"
        elif "token" in str(e).lower():
            error_code = "token_exchange_failed"
        elif "discovery" in str(e).lower():
            error_code = "discovery_failed"
        return RedirectResponse(
            url=f"{frontend_url}{redirect_path}?id={integration_id}&status=failed&error={error_code}"
        )
