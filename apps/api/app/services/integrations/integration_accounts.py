"""A user's connected accounts on a Composio integration: which exist, which is primary, which one a call means."""

from app.config.oauth_config import get_integration_by_tool_slug, get_integration_by_toolkit
from app.constants.cache import USER_INTEGRATION_CACHE_PATTERNS
from app.constants.error_codes import INTEGRATION_NOT_CONNECTED
from app.constants.integrations import MAX_ACCOUNTS_PER_INTEGRATION
from app.db.repositories.user_integrations import user_integration_repository
from app.decorators.caching import CacheInvalidator
from app.models.integration_models import (
    IntegrationAccount,
    UserIntegrationDocument,
    UserIntegrationStatus,
)
from app.utils.errors import AppError


def derive_status(accounts: list[IntegrationAccount]) -> UserIntegrationStatus:
    """Report connected while any account works, expired once every account has died."""
    if any(a.status == "connected" for a in accounts):
        return "connected"
    return "expired" if accounts else "created"


def pick_primary(accounts: list[IntegrationAccount], current: str | None) -> str | None:
    """Keep the current primary while it exists; otherwise the oldest live account, then the oldest."""
    if any(a.connected_account_id == current for a in accounts):
        return current
    live = [a for a in accounts if a.status == "connected"]
    pool = live or accounts
    return pool[0].connected_account_id if pool else None


def match_account(record: UserIntegrationDocument, name: str) -> IntegrationAccount | None:
    """Find the account a name refers to by label, nickname or any identity value."""
    wanted = name.strip().casefold()
    for account in record.accounts:
        names = {account.label, account.display_name, *account.identity.values()}
        if wanted in {n.strip().casefold() for n in names if n}:
            return account
    return None


def describe_account(account: IntegrationAccount, primary_id: str | None) -> str:
    """One account as the agent sees it: its names, then primary/expired tags."""
    # Quoted, so a model passing one as `account` copies the name and not the tags after it.
    # A nickname hides the address the user may name the account by, so both are names.
    names = [account.display_name, *([account.label] if account.nickname else [])]
    tags = ["primary"] if account.connected_account_id == primary_id else []
    if account.status != "connected":
        tags.append("expired")
    suffix = f" ({', '.join(tags)})" if tags else ""
    return " or ".join(f'"{name}"' for name in names) + suffix


def at_account_limit(record: UserIntegrationDocument | None) -> bool:
    """Whether a connect must be refused up front: only live accounts count here.

    Reconnecting an expired account replaces it, so the callback, which knows the
    identity, is where every account counts.
    """
    live = [a for a in record.accounts if a.status == "connected"] if record else []
    return len(live) >= MAX_ACCOUNTS_PER_INTEGRATION


def primary_account(record: UserIntegrationDocument) -> IntegrationAccount | None:
    if record.primary_account_id is None:
        return None
    return record.find_account(record.primary_account_id)


async def get_account_record(user_id: str, integration_id: str) -> UserIntegrationDocument | None:
    return await user_integration_repository.get_for_user(user_id, integration_id)


@CacheInvalidator(key_patterns=USER_INTEGRATION_CACHE_PATTERNS)
async def save_accounts(
    user_id: str,
    integration_id: str,
    accounts: list[IntegrationAccount],
    primary_account_id: str | None,
    expired_reason: str | None = None,
) -> UserIntegrationDocument:
    """Persist the account set; the integration status is derived from it, never passed in."""
    return await user_integration_repository.save_accounts(
        user_id,
        integration_id,
        accounts=accounts,
        primary_account_id=primary_account_id,
        status=derive_status(accounts),
        expired_reason=expired_reason,
    )


@CacheInvalidator(key_patterns=USER_INTEGRATION_CACHE_PATTERNS)
async def set_account_nickname(
    user_id: str, integration_id: str, connected_account_id: str, nickname: str | None
) -> UserIntegrationDocument | None:
    """Name one account without rewriting the others; None when the record lacks it."""
    return await user_integration_repository.set_account_nickname(
        user_id, integration_id, connected_account_id, nickname
    )


async def list_multi_account_records(user_id: str) -> list[UserIntegrationDocument]:
    """List the user's integrations that hold more than one account."""
    records = await user_integration_repository.list_for_user(user_id)
    return [r for r in records if len(r.accounts) > 1]


async def event_account_name(
    user_id: str, trigger_slug: str, connected_account_id: str
) -> str | None:
    """Name the account a trigger event arrived on, when the user has more than one to tell apart."""
    integration = get_integration_by_tool_slug(trigger_slug)
    if integration is None or not connected_account_id:
        return None
    record = await get_account_record(user_id, integration.id)
    if record is None or len(record.accounts) < 2:
        return None
    account = record.find_account(connected_account_id)
    return account.display_name if account else None


def _not_connected(toolkit: str, why: str) -> AppError:
    # 403, not 401: a 401 trips the web client's session-expiry interceptor.
    return AppError(
        message=f"No active {toolkit} connection",
        why=why,
        fix=f"Reconnect the {toolkit} integration",
        status_code=403,
        code=INTEGRATION_NOT_CONNECTED,
        # The web interceptor keys its reconnect toast on `toolkit`.
        public={"toolkit": toolkit},
    )


async def primary_connected_account_id(user_id: str, toolkit: str) -> str:
    """Return the primary account's id for a toolkit; raise the reconnect error when it cannot act."""
    integration = get_integration_by_toolkit(toolkit)
    if integration is None:
        raise AppError(
            message=f"Unknown Composio toolkit: {toolkit}",
            why="No registered integration matches this toolkit slug",
            meta={"toolkit": toolkit},
        )
    record = await get_account_record(user_id, integration.id)
    account = primary_account(record) if record else None
    if account is None:
        raise _not_connected(toolkit, "This integration has no connected account")
    if account.status != "connected":
        raise _not_connected(
            toolkit, f"The primary {integration.name} account ({account.display_name}) expired"
        )
    return account.connected_account_id
