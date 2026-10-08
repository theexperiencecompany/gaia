"""Connecting, removing and re-ranking a user's accounts on one Composio integration.

The primary is the account workflow triggers are registered against, so any
change of primary re-registers them.
"""

from dataclasses import dataclass

from app.config.oauth_config import get_integration_by_id
from app.constants.integrations import MAX_ACCOUNTS_PER_INTEGRATION
from app.constants.log_tags import LogTag
from app.models.integration_models import IntegrationAccount, UserIntegrationDocument
from app.models.oauth_models import OAuthIntegration
from app.services.analytics_service import AnalyticsEvents, capture_event
from app.services.composio.composio_service import get_composio_service
from app.services.integrations.account_identity import account_label, fetch_account_identity
from app.services.integrations.integration_accounts import (
    get_account_record,
    pick_primary,
    save_accounts,
    set_account_nickname,
)
from app.services.integrations.integration_connection_service import disconnect_integration
from app.services.triggers.subscription_service import resync_subscriptions_for_trigger_names
from app.services.workflow.trigger_service import TriggerService
from app.utils.errors import AppError
from shared.py.wide_events import log


@dataclass(frozen=True)
class AccountConnected:
    account: IntegrationAccount
    # The account this connect re-authorized (same identity), now revoked.
    replaced_account_id: str | None
    primary_changed: bool


@dataclass(frozen=True)
class AccountLimitReached:
    limit: int


async def _identity_or_empty(
    user_id: str, integration: OAuthIntegration, connected_account_id: str
) -> dict[str, str]:
    # Identity names the account; a profile-call failure must not void a grant
    # the user just completed, so the account is kept under a numbered label.
    try:
        return await fetch_account_identity(user_id, integration, connected_account_id)
    except Exception as e:
        log.error(
            f"{LogTag.INTEGRATION} Could not read the connected account's identity",
            integration_id=integration.id,
            connected_account_id=connected_account_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        return {}


def _same_identity(a: dict[str, str], b: dict[str, str]) -> bool:
    return bool(a) and a == b


def _workflow_trigger_names(integration: OAuthIntegration) -> list[str]:
    return [
        t.workflow_trigger_schema.slug
        for t in integration.associated_triggers
        if t.workflow_trigger_schema
    ]


async def resync_primary_bound_triggers(user_id: str, integration: OAuthIntegration) -> None:
    """Re-register the integration's workflow and todo triggers on the current primary account."""
    names = _workflow_trigger_names(integration)
    if not names:
        return
    await TriggerService.resync_user_workflow_triggers(user_id, names)
    await resync_subscriptions_for_trigger_names(user_id, set(names))


async def record_connected_account(
    user_id: str, integration: OAuthIntegration, connected_account_id: str
) -> AccountConnected | AccountLimitReached:
    """Add a freshly authorized account, or let it supersede the account with the same identity."""
    record = await get_account_record(user_id, integration.id)
    accounts = list(record.accounts) if record else []
    previous_primary = record.primary_account_id if record else None

    existing = next((a for a in accounts if a.connected_account_id == connected_account_id), None)
    if existing is not None:
        return AccountConnected(account=existing, replaced_account_id=None, primary_changed=False)

    identity = await _identity_or_empty(user_id, integration, connected_account_id)
    superseded = next((a for a in accounts if _same_identity(a.identity, identity)), None)
    composio = get_composio_service()

    if superseded is None and len(accounts) >= MAX_ACCOUNTS_PER_INTEGRATION:
        await composio.delete_connected_account(connected_account_id)
        log.set_ns("integration_account", outcome="limit_reached", count=len(accounts))
        return AccountLimitReached(limit=MAX_ACCOUNTS_PER_INTEGRATION)

    account = IntegrationAccount(
        connected_account_id=connected_account_id,
        identity=identity,
        label=account_label(
            integration, identity, {a.label for a in accounts if a is not superseded}
        ),
        nickname=superseded.nickname if superseded else None,
    )
    if superseded is not None:
        accounts = [account if a is superseded else a for a in accounts]
        primary = (
            connected_account_id
            if previous_primary == superseded.connected_account_id
            else previous_primary
        )
    else:
        accounts.append(account)
        primary = previous_primary
    primary = pick_primary(accounts, primary)

    await save_accounts(user_id, integration.id, accounts, primary)
    if superseded is not None:
        await composio.delete_connected_account(superseded.connected_account_id)

    log.set_ns(
        "integration_account",
        outcome="replaced" if superseded else "added",
        count=len(accounts),
        is_primary=primary == connected_account_id,
    )
    capture_event(
        user_id,
        AnalyticsEvents.INTEGRATION_ACCOUNT_ADDED,
        {
            "integration_id": integration.id,
            "account_count": len(accounts),
            "replaced": superseded is not None,
            "has_identity": bool(identity),
        },
    )
    return AccountConnected(
        account=account,
        replaced_account_id=superseded.connected_account_id if superseded else None,
        primary_changed=primary != previous_primary,
    )


def composio_integration(integration_id: str) -> OAuthIntegration:
    integration = get_integration_by_id(integration_id)
    if integration is None or integration.composio_config is None:
        raise AppError(
            message="This integration does not support multiple accounts",
            status_code=404,
            meta={"integration_id": integration_id},
        )
    return integration


async def _require_record(user_id: str, integration_id: str) -> UserIntegrationDocument:
    record = await get_account_record(user_id, integration_id)
    if record is None or not record.accounts:
        raise AppError(
            message="This integration has no connected accounts",
            status_code=404,
            meta={"integration_id": integration_id},
        )
    return record


def _require_account(
    record: UserIntegrationDocument, connected_account_id: str
) -> IntegrationAccount:
    account = record.find_account(connected_account_id)
    if account is None:
        raise _account_not_found(record.integration_id, connected_account_id)
    return account


def _account_not_found(integration_id: str, connected_account_id: str) -> AppError:
    return AppError(
        message="Account not found on this integration",
        status_code=404,
        meta={"integration_id": integration_id, "account": connected_account_id},
    )


async def _set_primary_account(
    user_id: str, integration_id: str, connected_account_id: str
) -> UserIntegrationDocument:
    integration = composio_integration(integration_id)
    record = await _require_record(user_id, integration_id)
    if _require_account(record, connected_account_id).status != "connected":
        raise AppError(
            message="Reconnect this account before making it primary",
            status_code=409,
            meta={"integration_id": integration_id},
        )
    if record.primary_account_id == connected_account_id:
        return record
    saved = await save_accounts(user_id, integration_id, record.accounts, connected_account_id)
    await resync_primary_bound_triggers(user_id, integration)
    capture_event(
        user_id,
        AnalyticsEvents.INTEGRATION_PRIMARY_CHANGED,
        {"integration_id": integration_id, "account_count": len(record.accounts)},
    )
    return saved


async def _rename_account(
    user_id: str, integration_id: str, connected_account_id: str, nickname: str | None
) -> UserIntegrationDocument:
    composio_integration(integration_id)
    _require_account(await _require_record(user_id, integration_id), connected_account_id)
    cleaned = (nickname or "").strip() or None
    saved = await set_account_nickname(user_id, integration_id, connected_account_id, cleaned)
    if saved is None:
        # Removed between the check above and this write.
        raise _account_not_found(integration_id, connected_account_id)
    capture_event(
        user_id,
        AnalyticsEvents.INTEGRATION_ACCOUNT_RENAMED,
        {"integration_id": integration_id, "cleared": cleaned is None},
    )
    return saved


async def list_accounts(user_id: str, integration_id: str) -> UserIntegrationDocument | None:
    composio_integration(integration_id)
    return await get_account_record(user_id, integration_id)


async def update_account(
    user_id: str,
    integration_id: str,
    connected_account_id: str,
    *,
    nickname: str | None,
    rename: bool,
    make_primary: bool,
) -> UserIntegrationDocument:
    """Rename and/or promote one account; with neither, return the record unchanged."""
    record = await _require_record(user_id, integration_id)
    if rename:
        record = await _rename_account(user_id, integration_id, connected_account_id, nickname)
    if make_primary:
        record = await _set_primary_account(user_id, integration_id, connected_account_id)
    return record


async def remove_account(
    user_id: str, integration_id: str, connected_account_id: str
) -> UserIntegrationDocument | None:
    """Revoke one account; the oldest live one takes over as primary. None when it was the last."""
    integration = composio_integration(integration_id)
    record = await _require_record(user_id, integration_id)
    _require_account(record, connected_account_id)
    remaining = [a for a in record.accounts if a.connected_account_id != connected_account_id]
    capture_event(
        user_id,
        AnalyticsEvents.INTEGRATION_ACCOUNT_REMOVED,
        {"integration_id": integration_id, "account_count": len(remaining)},
    )
    if not remaining:
        # The last account out is a full disconnect: every stale Composio account goes too.
        await disconnect_integration(user_id, integration_id)
        return None

    await get_composio_service().delete_connected_account(connected_account_id)
    primary = pick_primary(remaining, record.primary_account_id)
    saved = await save_accounts(user_id, integration_id, remaining, primary)
    if primary != record.primary_account_id:
        await resync_primary_bound_triggers(user_id, integration)
    return saved
