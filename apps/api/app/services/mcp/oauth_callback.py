"""What the MCP OAuth callback does once the route has parsed the redirect.

The route owns the redirect URLs; this module owns the provider-error
recovery, the code exchange and the bookkeeping that follows it.
"""

from dataclasses import dataclass

from app.constants.log_tags import LogTag
from app.services.analytics_service import AnalyticsEvents, capture_context_event
from app.services.integrations.user_integrations import invalidate_user_integration_caches
from app.services.mcp.mcp_client import MCPClient
from shared.py.wide_events import log

KNOWN_OAUTH_ERRORS = frozenset(
    {
        "access_denied",
        "invalid_request",
        "unauthorized_client",
        "unsupported_response_type",
        "invalid_scope",
        "server_error",
        "temporarily_unavailable",
    }
)


@dataclass(frozen=True)
class ScopeRetry:
    """The provider rejected a scope; send the browser back through authorization."""

    url: str


@dataclass(frozen=True)
class ProviderError:
    """The provider's OAuth error, as the code the frontend displays."""

    code: str


async def resolve_provider_error(
    client: MCPClient,
    *,
    integration_id: str,
    redirect_uri: str,
    redirect_path: str,
    error: str,
    error_description: str | None,
) -> ScopeRetry | ProviderError:
    """Retry a rejected scope, else map the provider's error to a user-facing code."""
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
                return ScopeRetry(url=retry_url)
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
    if error == "server_error":
        return ProviderError(code="oauth_server_error")
    if error in KNOWN_OAUTH_ERRORS:
        return ProviderError(code=error)
    return ProviderError(code="authorization_failed")


def sanitized_error_code(exc: Exception) -> str:
    """A generic code for the redirect instead of the raw exception message."""
    message = str(exc).lower()
    if "state" in message:
        return "invalid_state"
    if "token" in message:
        return "token_exchange_failed"
    if "discovery" in message:
        return "discovery_failed"
    return "connection_failed"


async def complete_oauth(
    client: MCPClient,
    *,
    user_id: str,
    integration_id: str,
    code: str,
    state_token: str,
    redirect_uri: str,
) -> None:
    """Exchange the code, then dispatch the full connect to the background."""
    # handle_oauth_callback stores tokens, flips status to connected, and
    # dispatches the full MCP connect (handshake + tools/list + schema
    # conversion + Chroma indexing) as a background task. Returns immediately —
    # the callback fires the redirect in ~1-2s instead of 8-29s.
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
    await invalidate_user_integration_caches(user_id)
    capture_context_event(
        AnalyticsEvents.INTEGRATION_CONNECTED,
        {"integration_id": integration_id, "connection_method": "oauth"},
    )
