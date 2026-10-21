"""Connecting, removing and re-ranking a user's accounts on one Composio integration.

The primary is the account workflow triggers are registered against, so any
change of primary re-registers them.
"""

from dataclasses import dataclass

from app.config.oauth_config import get_integration_by_id
from app.constants.integrations import (
    INTEGRATION_STATUS_CONNECTED,
    MAX_ACCOUNTS_PER_INTEGRATION,
    AccountConnectOutcome,
)
from app.constants.log_tags import LogTag
from app.models.integration_models import (
    IntegrationAccount,
    UserIntegrationDocument,
    new_account_id,
)
from app.models.oauth_models import OAuthIntegration
from app.services.analytics_service import capture
from app.services.composio.composio_service import get_composio_service
from app.services.integrations.account_identity import account_label, fetch_account_identity
from app.services.integrations.integration_accounts import (
    get_account_record,
    pick_primary,
    save_accounts,
    set_account_nickname,
)
from app.services.integrations.integration_connection_service import disconnect_integration
from app.services.triggers.subscription_service import (
    AccountScope,
    resync_subscriptions_for_trigger_names,
)
from app.services.workflow.trigger_service import TriggerService
from app.utils.errors import AppError
from shared.py.analytics import UserId
from shared.py.analytics.catalog.integrations import (
    IntegrationAccountAdded,
    IntegrationAccountRemoved,
    IntegrationAccountRenamed,
    IntegrationPrimaryChanged,
)
from shared.py.wide_events import log


@dataclass(frozen=True)
class AccountConnected:
    account: IntegrationAccount
    primary_changed: bool
    outcome: AccountConnectOutcome
    # The primary signed back in (in place, or as a new provider account for the same
    # identity), so what is bound to its provider account must be bound again.
    primary_restored: bool = False


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
    await resync_subscriptions_for_trigger_names(
        user_id, set(names), AccountScope(account_id=None, every_account=True)
    )


async def _restore_account(
    user_id: str,
    integration: OAuthIntegration,
    record: UserIntegrationDocument,
    account: IntegrationAccount,
) -> AccountConnected:
    """Bring an account signed back in under its own id to life; its name and role stay."""
    if account.status == INTEGRATION_STATUS_CONNECTED:
        return AccountConnected(
            account=account, primary_changed=False, outcome=AccountConnectOutcome.ALREADY_CONNECTED
        )
    identity = await _identity_or_empty(user_id, integration, account.connected_account_id)
    others = [a for a in record.accounts if a is not account]
    if not identity or _same_identity(account.identity, identity):
        update: dict[str, object] = {}
    else:
        # Signed in as someone else: the account is now that person.
        twin = next((a for a in others if _same_identity(a.identity, identity)), None)
        if twin is not None:
            await remove_account(user_id, integration.id, account.id)
            log.set_ns("integration_account", outcome="reconnected_as_existing")
            return AccountConnected(
                account=twin,
                primary_changed=record.primary_account_id == account.id,
                outcome=AccountConnectOutcome.ALREADY_CONNECTED,
            )
        update = {
            "identity": identity,
            "label": account_label(integration, identity, {a.label for a in others}),
            "nickname": None,
        }
    restored = account.model_copy(
        update={
            **update,
            "status": INTEGRATION_STATUS_CONNECTED,
            "expired_at": None,
            "expired_reason": None,
        }
    )
    accounts = [restored if a is account else a for a in record.accounts]
    await save_accounts(user_id, integration.id, accounts, record.primary_account_id)
    log.set_ns("integration_account", outcome="restored", identity_changed=bool(update))
    return AccountConnected(
        account=restored,
        primary_changed=False,
        outcome=AccountConnectOutcome.RECONNECTED,
        primary_restored=record.primary_account_id == account.id,
    )


async def record_connected_account(
    user_id: str, integration: OAuthIntegration, connected_account_id: str
) -> AccountConnected | AccountLimitReached:
    """Add a freshly authorized account, or let it supersede the account with the same identity."""
    record = await get_account_record(user_id, integration.id)
    accounts = list(record.accounts) if record else []
    previous_primary = record.primary_account_id if record else None

    existing = record.find_provider_account(connected_account_id) if record else None
    if record is not None and existing is not None:
        return await _restore_account(user_id, integration, record, existing)

    identity = await _identity_or_empty(user_id, integration, connected_account_id)
    superseded = next((a for a in accounts if _same_identity(a.identity, identity)), None)
    composio = get_composio_service()

    if superseded is None and len(accounts) >= MAX_ACCOUNTS_PER_INTEGRATION:
        await composio.delete_connected_account(connected_account_id)
        log.set_ns("integration_account", outcome="limit_reached", count=len(accounts))
        return AccountLimitReached(limit=MAX_ACCOUNTS_PER_INTEGRATION)

    # Same identity, same GAIA account: what refers to it outlives the provider account swap.
    account = IntegrationAccount(
        id=superseded.id if superseded else new_account_id(),
        connected_account_id=connected_account_id,
        identity=identity,
        label=account_label(
            integration, identity, {a.label for a in accounts if a is not superseded}
        ),
        nickname=superseded.nickname if superseded else None,
    )
    if superseded is not None:
        accounts = [account if a is superseded else a for a in accounts]
    else:
        accounts.append(account)
    primary = pick_primary(accounts, previous_primary)

    await save_accounts(user_id, integration.id, accounts, primary)
    if superseded is not None:
        await composio.delete_connected_account(superseded.connected_account_id)

    log.set_ns(
        "integration_account",
        outcome="replaced" if superseded else "added",
        count=len(accounts),
        is_primary=primary == account.id,
    )
    capture(
        UserId(user_id),
        IntegrationAccountAdded(
            integration_id=integration.id,
            account_count=len(accounts),
            replaced=superseded is not None,
            has_identity=bool(identity),
        ),
    )
    if superseded is None:
        outcome = AccountConnectOutcome.ADDED
    elif superseded.status == INTEGRATION_STATUS_CONNECTED:
        outcome = AccountConnectOutcome.ALREADY_CONNECTED
    else:
        outcome = AccountConnectOutcome.RECONNECTED
    return AccountConnected(
        account=account,
        primary_changed=primary != previous_primary,
        outcome=outcome,
        primary_restored=superseded is not None and previous_primary == superseded.id,
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


def _require_account(record: UserIntegrationDocument, account_id: str) -> IntegrationAccount:
    account = record.find_account(account_id)
    if account is None:
        raise _account_not_found(record.integration_id, account_id)
    return account


def _account_not_found(integration_id: str, account_id: str) -> AppError:
    return AppError(
        message="Account not found on this integration",
        status_code=404,
        meta={"integration_id": integration_id, "account": account_id},
    )


async def _set_primary_account(
    user_id: str, integration_id: str, account_id: str
) -> UserIntegrationDocument:
    integration = composio_integration(integration_id)
    record = await _require_record(user_id, integration_id)
    if _require_account(record, account_id).status != "connected":
        raise AppError(
            message="Reconnect this account before making it primary",
            status_code=409,
            meta={"integration_id": integration_id},
        )
    if record.primary_account_id == account_id:
        return record
    saved = await save_accounts(user_id, integration_id, record.accounts, account_id)
    await resync_primary_bound_triggers(user_id, integration)
    capture(
        UserId(user_id),
        IntegrationPrimaryChanged(
            integration_id=integration_id, account_count=len(record.accounts)
        ),
    )
    return saved


async def _rename_account(
    user_id: str, integration_id: str, account_id: str, nickname: str | None
) -> UserIntegrationDocument:
    composio_integration(integration_id)
    _require_account(await _require_record(user_id, integration_id), account_id)
    cleaned = (nickname or "").strip() or None
    saved = await set_account_nickname(user_id, integration_id, account_id, cleaned)
    if saved is None:
        # Removed between the check above and this write.
        raise _account_not_found(integration_id, account_id)
    capture(
        UserId(user_id),
        IntegrationAccountRenamed(integration_id=integration_id, cleared=cleaned is None),
    )
    return saved


async def list_accounts(user_id: str, integration_id: str) -> UserIntegrationDocument | None:
    composio_integration(integration_id)
    return await get_account_record(user_id, integration_id)


async def update_account(
    user_id: str,
    integration_id: str,
    account_id: str,
    *,
    nickname: str | None = None,
    rename: bool = False,
    make_primary: bool = False,
) -> UserIntegrationDocument:
    """Rename and/or promote one account; with neither, return the record unchanged."""
    record = await _require_record(user_id, integration_id)
    if rename:
        record = await _rename_account(user_id, integration_id, account_id, nickname)
    if make_primary:
        record = await _set_primary_account(user_id, integration_id, account_id)
    return record


async def remove_account(
    user_id: str, integration_id: str, account_id: str
) -> UserIntegrationDocument | None:
    """Revoke one account; the oldest live one takes over as primary. None when it was the last."""
    integration = composio_integration(integration_id)
    record = await _require_record(user_id, integration_id)
    target = _require_account(record, account_id)
    remaining = [a for a in record.accounts if a.id != account_id]
    capture(
        UserId(user_id),
        IntegrationAccountRemoved(integration_id=integration_id, account_count=len(remaining)),
    )
    if not remaining:
        # The last account out is a full disconnect: every stale Composio account goes too.
        await disconnect_integration(user_id, integration_id)
        return None

    await get_composio_service().delete_connected_account(target.connected_account_id)
    primary = pick_primary(remaining, record.primary_account_id)
    saved = await save_accounts(user_id, integration_id, remaining, primary)
    if primary != record.primary_account_id:
        await resync_primary_bound_triggers(user_id, integration)
    return saved
