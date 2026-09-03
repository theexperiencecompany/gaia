"""The one place an integration connection is started or torn down.

Both the authenticated ``POST /connect/{id}`` endpoint and the login-free
``GET /connect-link`` redemption land here, so a transport is wired into all of
them at once. The dispatch itself is transport-agnostic: it resolves the
integration, checks the shared preconditions, and hands off to the registered
provider.
"""

from __future__ import annotations

from app.constants.log_tags import LogTag
from app.schemas.integrations.responses import (
    ConnectIntegrationResponse,
    IntegrationSuccessResponse,
)
from app.services.analytics_service import AnalyticsEvents, capture_context_event
from app.services.integrations.integration_connection_service import _invalidate_caches
from app.services.integrations.integration_resolver import IntegrationResolver
from app.services.integrations.providers import ConnectContext, get_provider
from app.services.integrations_fs import schedule_user_integrations_sync
from shared.py.wide_events import log


async def initiate_integration_connection(
    user_id: str,
    integration_id: str,
    *,
    user_email: str = "",
    redirect_path: str = "/integrations",
    bearer_token: str | None = None,
) -> ConnectIntegrationResponse | None:
    """Start or advance a connection. ``None`` when the integration is unknown.

    Callers map ``None`` to a 404 (or a friendly bounce). Everything else —
    including a failure — comes back as a response the client can render.
    """
    resolved = await IntegrationResolver.resolve(integration_id)
    if not resolved:
        return None

    log.set(
        user={"id": user_id},
        integration={
            "id": integration_id,
            "managed_by": resolved.managed_by,
            "source": resolved.source,
        },
    )

    def _error(message: str) -> ConnectIntegrationResponse:
        log.set(outcome="error")
        return ConnectIntegrationResponse(
            status="error",
            integration_id=integration_id,
            name=resolved.name,
            error=message,
        )

    if (
        resolved.source == "platform"
        and resolved.platform_integration
        and not resolved.platform_integration.available
    ):
        return _error(f"Integration {integration_id} is not available yet")

    provider = get_provider(resolved.managed_by)
    if provider is None:
        # ``internal`` integrations reach this legitimately: they are always on
        # and have nothing to connect.
        return _error(f"Unsupported integration type: {resolved.managed_by}")

    ctx = ConnectContext(
        user_id=user_id,
        integration_id=integration_id,
        resolved=resolved,
        redirect_path=redirect_path,
        user_email=user_email,
        secret=bearer_token,
    )

    try:
        result = await provider.connect(ctx)
    except Exception as e:
        log.error(
            f"{LogTag.INTEGRATION} Failed to initiate connection",
            integration_id=integration_id,
            user_id=user_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        # The raw text here is an upstream failure ("500: Failed to create
        # sandbox: failed to run reserve script: redis: connection pool
        # timeout") that names GAIA's internals and tells the user nothing they
        # can act on. The detail stays on the wide event above, where it is
        # actually useful; the user gets the one thing they can do.
        return _error(
            f"Something went wrong connecting {resolved.name}. "
            "This is usually temporary; try again in a moment."
        )

    log.set(outcome=result.status)
    if result.status == "connected":
        # Fired here rather than per transport so every way of completing a
        # connection is counted the same. The OAuth transports normally
        # complete at their callback instead, which reports separately.
        capture_context_event(
            AnalyticsEvents.INTEGRATION_CONNECTED,
            {"integration_id": integration_id, "managed_by": resolved.managed_by},
        )
    return result


async def disconnect_integration(user_id: str, integration_id: str) -> IntegrationSuccessResponse:
    """Disconnect an integration for the user."""
    log.set(integration={"provider": integration_id, "action": "disconnect"})
    resolved = await IntegrationResolver.resolve(integration_id)
    if not resolved:
        raise ValueError(f"Integration {integration_id} not found")

    # Same registry the connect path uses. Two hand-written dispatches is how a
    # transport ends up wired into one and not the other -- which is what this
    # function used to be.
    provider = get_provider(resolved.managed_by)
    if provider is None:
        raise ValueError(f"Integration {integration_id} disconnect not supported")
    await provider.disconnect(user_id, resolved)

    await _invalidate_caches(user_id, integration_id, resolved.managed_by)

    # Reflect the reduced connected set in the user's workspace VFS.
    schedule_user_integrations_sync(user_id)

    log.set(
        integration={
            "provider": integration_id,
            "action": "disconnect",
            "managed_by": resolved.managed_by,
            "status": "disconnected",
        }
    )
    return IntegrationSuccessResponse(
        message=f"Successfully disconnected {resolved.name}",
        integration_id=integration_id,
    )
