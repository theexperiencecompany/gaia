"""
MCP Integration API Routes.

Handles MCP OAuth callbacks and connection testing.
Connection/disconnection is handled by the unified /integrations endpoints.
"""

from dataclasses import dataclass
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
from app.services.mcp.oauth_callback import (
    ProviderError,
    ScopeRetry,
    complete_oauth,
    resolve_provider_error,
    sanitized_error_code,
)
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
        capture_context_event(AnalyticsEvents.MCP_CONNECTION_TESTED, {"status": "failed"})
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
            capture_context_event(
                AnalyticsEvents.MCP_CONNECTION_TESTED,
                {"status": "connected", "tools_count": len(tools) if tools else 0},
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
            capture_context_event(AnalyticsEvents.MCP_CONNECTION_TESTED, {"status": "failed"})
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
        capture_context_event(AnalyticsEvents.MCP_CONNECTION_TESTED, {"status": "requires_oauth"})
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


@dataclass(frozen=True, kw_only=True)
class _McpCallback:
    """Where one OAuth callback came from and where it sends the browser next."""

    integration_id: str
    redirect_path: str
    frontend_url: str

    def failure(self, error: str) -> str:
        return (
            f"{self.frontend_url}{self.redirect_path}"
            f"?id={self.integration_id}&status=failed&error={error}"
        )


@router.get("/oauth/callback", response_class=RedirectResponse)
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

    callback = _McpCallback(
        integration_id=integration_id,
        redirect_path=redirect_path,
        frontend_url=frontend_url,
    )
    if error:
        outcome = await resolve_provider_error(
            client,
            integration_id=integration_id,
            redirect_uri=redirect_uri,
            redirect_path=redirect_path,
            error=error,
            error_description=error_description,
        )
        match outcome:
            case ScopeRetry(url=url):
                return RedirectResponse(url=url)
            case ProviderError(code=code):
                return RedirectResponse(url=callback.failure(code))

    # Validate code is present (required for success case)
    if not code:
        log.error(f"{LogTag.MCP} OAuth callback missing code", integration_id=integration_id)
        return RedirectResponse(url=callback.failure("missing_code"))

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
        await complete_oauth(
            client,
            user_id=str(user_id),
            integration_id=integration_id,
            code=code,
            state_token=state_token,
            redirect_uri=redirect_uri,
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
        return RedirectResponse(url=callback.failure(sanitized_error_code(e)))

    log.audit("mcp integration connected via oauth", actor=str(user_id), resource=integration_id)
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
