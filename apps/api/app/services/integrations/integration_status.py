"""Which integrations a user has connected, read once and cached.

Below oauth_service on purpose: the workflow layer asks this question
(integration_requirements) and oauth_service imports the workflow
layer for pause/resume, so the reader lives where both can import it.
"""

from __future__ import annotations

from app.config.oauth_config import OAUTH_INTEGRATIONS, get_integration_scopes
from app.config.token_repository import token_repository
from app.constants.cache import OAUTH_STATUS_KEY
from app.constants.integrations import (
    INTEGRATION_STATUS_CONNECTED,
    MANAGED_BY_COMPOSIO,
    MANAGED_BY_MCP,
    MANAGED_BY_SELF,
)
from app.constants.log_tags import LogTag
from app.db.repositories.user_integrations import user_integration_repository
from app.decorators.caching import Cacheable
from app.models.oauth_models import OAuthIntegration
from app.services.composio.composio_service import get_composio_service
from shared.py.wide_events import OAuthContext, log


@Cacheable(ttl=86400, key_pattern=f"{OAUTH_STATUS_KEY}:{{user_id}}")
async def get_all_integrations_status(user_id: str) -> dict[str, bool]:
    """Return connection status for every integration for user_id.

    Checks MongoDB user_integrations first (canonical), falling back to
    external services for platform integrations connected before it existed.
    """
    result = {}

    user_ints = await user_integration_repository.list_for_user(user_id, limit=100)
    mongo_status = {
        ui.integration_id: ui.status == INTEGRATION_STATUS_CONNECTED for ui in user_ints
    }

    # Track which platform integrations need external verification
    composio_providers = []
    composio_id_to_provider = {}

    for integration in OAUTH_INTEGRATIONS:
        if not integration.available:
            result[integration.id] = False
            continue

        # If user has this integration in MongoDB, use that status
        if integration.id in mongo_status:
            result[integration.id] = mongo_status[integration.id]
            continue

        # Not in MongoDB - check external services (legacy support)
        if integration.managed_by == MANAGED_BY_MCP:
            # All MCPs (auth or not) use MongoDB user_integrations as source of truth
            # If not in mongo_status, they're not connected
            result[integration.id] = False
        elif integration.managed_by == MANAGED_BY_COMPOSIO:
            composio_providers.append(integration.provider)
            composio_id_to_provider[integration.id] = integration.provider
        elif integration.managed_by == MANAGED_BY_SELF:
            result[integration.id] = await _self_managed_connected(user_id, integration)

    if composio_providers:
        result.update(
            await _composio_connected(user_id, composio_providers, composio_id_to_provider)
        )

    # Include custom integrations from MongoDB that are connected
    for integration_id, is_connected in mongo_status.items():
        if integration_id not in result:
            result[integration_id] = is_connected

    log.set(oauth=OAuthContext(operation="status"), result_count=len(result))
    return result


async def _self_managed_connected(user_id: str, integration: OAuthIntegration) -> bool:
    """Return True when the stored token carries every scope the integration needs."""
    try:
        token = await token_repository.get_token(
            user_id, integration.provider, renew_if_expired=True
        )
    except Exception as e:
        log.debug(
            f"{LogTag.OAUTH} Token not found for",
            provider=integration.provider,
            error=str(e),
            error_type=type(e).__name__,
        )
        return False
    granted = token.get("scope")
    authorized_scopes = str(granted).split() if granted else []
    return all(scope in authorized_scopes for scope in get_integration_scopes(integration.id))


async def _composio_connected(
    user_id: str, providers: list[str], id_to_provider: dict[str, str]
) -> dict[str, bool]:
    """Batch-check Composio status; a failed check reads every one as not connected."""
    try:
        status_map = await get_composio_service().check_connection_status(providers, user_id)
    except Exception as e:
        log.error(
            f"{LogTag.OAUTH} Error batch checking Composio integrations",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )
        return dict.fromkeys(id_to_provider, False)
    return {
        integration_id: status_map.get(provider, False)
        for integration_id, provider in id_to_provider.items()
    }
