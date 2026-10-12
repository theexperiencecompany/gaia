"""What connect_integration starts for one integration: a connect, an add, a reconnect, or why none."""

from app.constants.integrations import (
    CONNECT_INTEGRATION_TOOL,
    DISCONNECT_INTEGRATION_TOOL,
    INTEGRATION_STATUS_EXPIRED,
    MAX_ACCOUNTS_PER_INTEGRATION,
    ConnectMode,
)
from app.models.integration_models import ConnectStep
from app.models.oauth_models import OAuthIntegration
from app.services.integrations.integration_accounts import (
    at_account_limit,
    get_account_record,
    match_account,
)
from app.services.oauth.oauth_service import check_integration_status


async def _reconnect_step(
    integration: OAuthIntegration, user_id: str, account: str | None
) -> ConnectStep | str:
    """Pick the expired account a reconnect signs back in, or say why there is none."""
    record = await get_account_record(user_id, integration.id)
    if record is None or not record.accounts:
        return ConnectStep(mode=ConnectMode.CONNECT)
    expired = [a for a in record.accounts if a.status == INTEGRATION_STATUS_EXPIRED]
    if account is not None:
        target = match_account(record, account)
        if target is None:
            names = ", ".join(a.display_name for a in record.accounts)
            return f"No {integration.name} account is named {account!r}. Its accounts: {names}."
        if target.status != INTEGRATION_STATUS_EXPIRED:
            return f"✅ {integration.name} account {target.display_name} is connected and working."
        return ConnectStep(mode=ConnectMode.RECONNECT, account=target)
    if len(expired) == 1:
        return ConnectStep(mode=ConnectMode.RECONNECT, account=expired[0])
    if expired:
        names = ", ".join(a.display_name for a in expired)
        return (
            f"Several {integration.name} accounts lost their connection ({names}). Ask the user "
            "which to reconnect, then pass it as account."
        )
    names = ", ".join(a.display_name for a in record.accounts)
    return (
        f"✅ Every {integration.name} account is connected and working ({names}), so there is "
        f"nothing to reconnect. To add another, use mode='{ConnectMode.ADD_ACCOUNT}'."
    )


async def connect_step(
    integration: OAuthIntegration, user_id: str, mode: ConnectMode, account: str | None
) -> ConnectStep | str:
    """Return the connect to start for one integration, or the reason none starts."""
    if mode is ConnectMode.RECONNECT:
        if integration.composio_config is None:
            return ConnectStep(mode=mode)
        return await _reconnect_step(integration, user_id, account)
    if not await check_integration_status(integration.id, user_id):
        return ConnectStep(mode=ConnectMode.CONNECT)
    if integration.composio_config is None:
        if mode is ConnectMode.ADD_ACCOUNT:
            return f"{integration.name} connects a single account; it cannot have several."
        return f"✅ {integration.name} is already connected!"
    record = await get_account_record(user_id, integration.id)
    if mode is ConnectMode.ADD_ACCOUNT:
        if at_account_limit(record):
            return (
                f"{integration.name} already has {MAX_ACCOUNTS_PER_INTEGRATION} accounts, the "
                f"most allowed. One must be disconnected ({DISCONNECT_INTEGRATION_TOOL}) or, if "
                f"expired, reconnected (mode='{ConnectMode.RECONNECT}') first."
            )
        return ConnectStep(mode=mode)
    names = ", ".join(a.display_name for a in record.accounts) if record else ""
    listed = f" ({names})" if names else ""
    return (
        f"✅ {integration.name} is already connected{listed}. If the user wants another "
        f"account, call {CONNECT_INTEGRATION_TOOL} with mode='{ConnectMode.ADD_ACCOUNT}'; if "
        "you're not sure they do, ask them."
    )
