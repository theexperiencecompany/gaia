"""The admin's view of Composio setup: auth configs in effect and ones detected in their project."""

import composio_client

from app.schemas.integrations.composio_setup import (
    ComposioAuthConfigCandidate,
    ComposioIntegrationSetup,
    ComposioSetupResponse,
)
from app.services.composio.auth_config_resolver import (
    composio_integrations,
    resolve_auth_configs,
)
from app.services.composio.composio_service import get_composio_service
from app.services.providers.provider_credentials_service import (
    resolve as resolve_provider_config,
)
from app.utils.errors import AppError
from shared.py.wide_events import log


async def composio_setup_overview() -> ComposioSetupResponse:
    """List every Composio integration with its auth config in effect and the detected candidates."""
    resolved = await resolve_auth_configs()
    composio_configured = await resolve_provider_config("composio") is not None
    detected = await _detected_by_toolkit() if composio_configured else {}
    integrations: list[ComposioIntegrationSetup] = []
    for integration in composio_integrations():
        if integration.composio_config is None:
            continue  # pragma: no mutate — composio_integrations yields only configured ones
        auth_config = resolved.get(integration.id)
        toolkit = integration.composio_config.toolkit
        integrations.append(
            ComposioIntegrationSetup(
                integration_id=integration.id,
                name=integration.name,
                toolkit=toolkit,
                auth_config_id=auth_config.auth_config_id if auth_config else None,
                source=auth_config.source if auth_config else None,
                detected=detected.get(toolkit.lower(), []),
            )
        )
    log.set_ns(
        "composio_setup",
        integrations=len(integrations),
        set_up=len(resolved),
        detected_toolkits=len(detected),
    )
    return ComposioSetupResponse(composio_configured=composio_configured, integrations=integrations)


async def _detected_by_toolkit() -> dict[str, list[ComposioAuthConfigCandidate]]:
    try:
        configs = await get_composio_service().list_enabled_auth_configs()
    except composio_client.AuthenticationError as e:
        raise AppError(
            message="Composio rejected the saved API key",
            why=str(e),
            fix="Paste a valid API key from the Composio dashboard",
            status_code=422,
            code="composio_key_rejected",
        ) from e
    by_toolkit: dict[str, list[ComposioAuthConfigCandidate]] = {}
    for config in configs:
        by_toolkit.setdefault(config.toolkit.slug.lower(), []).append(
            ComposioAuthConfigCandidate(id=config.id, name=config.name)
        )
    return by_toolkit
