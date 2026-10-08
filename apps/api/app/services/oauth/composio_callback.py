"""What the Composio OAuth callback does once the route has consumed its state.

The route owns the redirect URLs; this module resolves the connected account
and records the connection.
"""

from dataclasses import dataclass
from typing import Literal

from fastapi import BackgroundTasks

from app.config.oauth_config import get_integration_by_config
from app.constants.log_tags import LogTag
from app.db.repositories.user_integrations import user_integration_repository
from app.models.oauth_models import OAuthStateData
from app.services.analytics_service import capture
from app.services.composio.composio_service import get_composio_service
from app.services.oauth.oauth_service import handle_oauth_connection
from shared.py.analytics import UserId
from shared.py.analytics.catalog.integrations import IntegrationConnected
from shared.py.wide_events import log


@dataclass(frozen=True)
class ConnectionCompleted:
    user_id: str
    integration_id: str
    provider: str


@dataclass(frozen=True)
class ConnectionRejected:
    reason: Literal["account_not_found", "user_missing", "config_missing", "user_mismatch"]


async def stored_connected_account_id(state_data: OAuthStateData) -> str | None:
    """Return the id minted at initiate time — the source of truth for the callback.

    Composio's hosted Connect Link redirects back without the connectedAccountId
    the retired initiate() flow appended, and the parameter is documented
    nowhere, so it cannot be relied on either way. Failing on the query string
    alone rejected connections that had actually succeeded.
    """
    record = await user_integration_repository.get_for_user(
        state_data["user_id"], state_data["integration_id"]
    )
    connected_account_id = record.connected_account_id if record else None
    log.set_ns(
        "oauth",
        connected_account_id_source="stored_record" if connected_account_id else "missing",
    )
    return connected_account_id


async def complete_composio_connection(
    connected_account_id: str,
    *,
    expected_user_id: str,
    background_tasks: BackgroundTasks,
) -> ConnectionCompleted | ConnectionRejected:
    """Verify the connected account against the state token and record the connection."""
    composio_service = get_composio_service()
    connected_account = composio_service.get_connected_account_by_id(connected_account_id)
    if not connected_account:
        log.error(
            f"{LogTag.OAUTH} Connected account not found",
            connected_account_id=connected_account_id,
        )
        return ConnectionRejected(reason="account_not_found")

    config_id = connected_account.auth_config.id
    user_id = connected_account.user_id
    if not user_id:
        log.error(
            f"{LogTag.OAUTH} User ID missing for account",
            connected_account_id=connected_account_id,
        )
        return ConnectionRejected(reason="user_missing")

    integration_config = get_integration_by_config(config_id)
    if not integration_config:
        log.error(
            f"{LogTag.OAUTH} Integration config not found",
            auth_config_id=config_id,
            connected_account_id=connected_account_id,
        )
        return ConnectionRejected(reason="config_missing")

    log.set(user={"id": str(user_id)})
    log.set_ns(
        "oauth",
        provider=integration_config.provider,
        integration_id=integration_config.id,
    )

    # Verify user_id matches the state token (security check)
    if str(user_id) != expected_user_id:
        log.error(
            f"{LogTag.OAUTH} User ID mismatch between state and account",
            state_user_id=expected_user_id,
            account_user_id=str(user_id),
            connected_account_id=connected_account_id,
        )
        return ConnectionRejected(reason="user_mismatch")

    is_reconnect = await user_integration_repository.has_connected_before(
        str(user_id), integration_config.id
    )
    await handle_oauth_connection(
        user_id=str(user_id),
        integration_config=integration_config,
        background_tasks=background_tasks,
        connected_account_id=connected_account_id,
    )
    capture(
        UserId(str(user_id)),
        IntegrationConnected(
            integration_id=integration_config.id,
            provider=integration_config.provider,
            is_reconnect=is_reconnect,
        ),
    )
    log.info(
        f"{LogTag.OAUTH} Composio connection successful",
        user_id=str(user_id),
        integration_id=integration_config.id,
        connected_account_id=connected_account_id,
    )
    return ConnectionCompleted(
        user_id=str(user_id),
        integration_id=integration_config.id,
        provider=integration_config.provider,
    )
