"""The one place an integration connection is started, for every entry point.

Both the authenticated ``POST /connect/{id}`` endpoint and the login-free
``GET /connect-link`` redemption land here, so a transport is wired into all of
them at once. The dispatch itself is transport-agnostic: it resolves the
integration, checks the shared preconditions, and hands off to the registered
provider.
"""

from __future__ import annotations

from app.constants.log_tags import LogTag
from app.schemas.integrations.responses import ConnectIntegrationResponse
from app.services.analytics_service import AnalyticsEvents, capture_context_event
from app.services.integrations.integration_resolver import IntegrationResolver
from app.services.integrations.providers import ConnectContext, get_provider
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
        return _error(str(e))

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
