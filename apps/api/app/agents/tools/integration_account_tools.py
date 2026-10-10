"""Tools the agent uses to manage the accounts a user connected to one integration."""

from pydantic import BaseModel, Field

from app.agents.tools.core.mutations import define_mutation_tool
from app.config.oauth_config import get_integration_by_id
from app.constants.integrations import (
    DISCONNECT_INTEGRATION_TOOL,
    MAX_ACCOUNT_NICKNAME_LENGTH,
    RENAME_INTEGRATION_ACCOUNT_TOOL,
    SET_PRIMARY_INTEGRATION_ACCOUNT_TOOL,
)
from app.models.integration_models import IntegrationAccount, UserIntegrationDocument
from app.services.analytics_service import capture
from app.services.integrations import integration_connection_service
from app.services.integrations.integration_account_lifecycle import (
    list_accounts,
    remove_account,
    update_account,
)
from app.services.integrations.integration_accounts import match_account, primary_account
from app.utils.errors import AppError
from shared.py.analytics import UserId
from shared.py.analytics.catalog.integrations import IntegrationDisconnected

_INTEGRATION_ID = (
    "The integration's id, as shown in parentheses in the connected integrations list "
    "(e.g. 'googlecalendar')."
)


class IntegrationAccountArgs(BaseModel):
    integration_id: str = Field(description=_INTEGRATION_ID)
    account: str = Field(
        description="The account, by its current name, address or label exactly as listed "
        "in the user's accounts."
    )


class RenameIntegrationAccountArgs(IntegrationAccountArgs):
    name: str = Field(
        max_length=MAX_ACCOUNT_NICKNAME_LENGTH,
        description="The new name, e.g. 'Work' or 'Personal'. An empty string removes "
        "the name, so the account shows its address or label again.",
    )


class DisconnectIntegrationArgs(BaseModel):
    integration_id: str = Field(description=_INTEGRATION_ID)
    account: str | None = Field(
        default=None,
        description="Which account to disconnect, by its name, address or label as listed. "
        "Required when the integration has several accounts; omit it when it has one.",
    )


async def _connected_accounts(user_id: str, integration_id: str) -> UserIntegrationDocument:
    record = await list_accounts(user_id, integration_id)
    if record is None or not record.accounts:
        raise AppError(
            message=f"The user has no connected {integration_id} accounts",
            fix="Check the integration_id against the connected integrations list",
        )
    return record


def _named_account(
    record: UserIntegrationDocument, integration_id: str, account: str
) -> IntegrationAccount:
    target = match_account(record, account)
    if target is None:
        listed = ", ".join(a.display_name for a in record.accounts)
        raise AppError(
            message=f"No {integration_id} account is named {account!r}",
            fix=f"Use one of: {listed}",
        )
    return target


async def _rename_integration_account(
    user_id: str, integration_id: str, account: str, name: str
) -> str:
    target = _named_account(
        await _connected_accounts(user_id, integration_id), integration_id, account
    )
    saved = await update_account(
        user_id,
        integration_id,
        target.connected_account_id,
        nickname=name,
        rename=True,
        make_primary=False,
    )
    renamed = saved.find_account(target.connected_account_id)
    if renamed is None or renamed.nickname is None:
        return f"Cleared the name; the account shows as {target.label} again."
    return f"Renamed {target.display_name} to {renamed.nickname}."


async def _set_primary_integration_account(user_id: str, integration_id: str, account: str) -> str:
    target = _named_account(
        await _connected_accounts(user_id, integration_id), integration_id, account
    )
    await update_account(
        user_id,
        integration_id,
        target.connected_account_id,
        nickname=None,
        rename=False,
        make_primary=True,
    )
    return f"{target.display_name} is now the primary {integration_id} account."


async def _disconnect_single_connection(user_id: str, integration_id: str) -> str:
    try:
        await integration_connection_service.disconnect_integration(user_id, integration_id)
    except ValueError as e:
        raise AppError(message=str(e), fix="Check the integration_id") from e
    capture(UserId(user_id), IntegrationDisconnected(integration_id=integration_id))
    return f"Disconnected {integration_id}."


async def _disconnect_integration(user_id: str, integration_id: str, account: str | None) -> str:
    integration = get_integration_by_id(integration_id)
    if integration is None or integration.composio_config is None:
        if account is not None:
            raise AppError(
                message=f"{integration_id} has one connection, not separate accounts",
                fix="Omit account to disconnect it",
            )
        return await _disconnect_single_connection(user_id, integration_id)

    record = await _connected_accounts(user_id, integration_id)
    if account is not None:
        target = _named_account(record, integration_id, account)
    elif len(record.accounts) == 1:
        target = record.accounts[0]
    else:
        listed = ", ".join(a.display_name for a in record.accounts)
        raise AppError(
            message=f"The user has {len(record.accounts)} {integration_id} accounts",
            fix=f"Pass account as one of: {listed}, or ask the user which one",
        )

    remaining = await remove_account(user_id, integration_id, target.connected_account_id)
    if remaining is None:
        return (
            f"Disconnected {target.display_name}, the only {integration_id} account, "
            f"so {integration_id} is no longer connected."
        )
    primary = primary_account(remaining)
    primary_note = f" The primary account is {primary.display_name}." if primary else ""
    return f"Disconnected {target.display_name}.{primary_note}"


rename_integration_account = define_mutation_tool(
    name=RENAME_INTEGRATION_ACCOUNT_TOOL,
    area="integration_accounts",
    description=(
        "Give one of the user's connected accounts on an integration a clear name, such as "
        "'Work' or 'Personal'. Use it when the user asks, or when an account only has a "
        "generic name like 'Google Calendar account 2' and you have learned who it is "
        "(for example from the address in data a tool returned). Do not replace a name the "
        "user chose unless they ask. Tool calls then accept the new name as `account`."
    ),
    args_model=RenameIntegrationAccountArgs,
    apply=_rename_integration_account,
)

set_primary_integration_account = define_mutation_tool(
    name=SET_PRIMARY_INTEGRATION_ACCOUNT_TOOL,
    area="integration_accounts",
    description=(
        "Make one of the user's connected accounts on an integration the primary one. The "
        "primary is used when a call names no account, and its triggers are the ones "
        "watched. Use it only when the user asks to change which account is the default."
    ),
    args_model=IntegrationAccountArgs,
    apply=_set_primary_integration_account,
)

disconnect_integration = define_mutation_tool(
    name=DISCONNECT_INTEGRATION_TOOL,
    area="integration_accounts",
    description=(
        "Disconnect an integration, or one account of it, when the user asks to remove, "
        "disconnect or unlink it. For an integration with several accounts, pass the account "
        "the user meant; the others stay connected, and the oldest working one becomes "
        "primary if the primary is removed. Removing the last account disconnects the "
        "integration."
    ),
    args_model=DisconnectIntegrationArgs,
    apply=_disconnect_integration,
)


tools = [rename_integration_account, set_primary_integration_account, disconnect_integration]
