"""Tools the agent uses to manage the accounts a user connected to one integration."""

from pydantic import BaseModel, Field

from app.agents.tools.core.mutations import define_mutation_tool
from app.constants.integrations import (
    MAX_ACCOUNT_NICKNAME_LENGTH,
    RENAME_INTEGRATION_ACCOUNT_TOOL,
)
from app.services.integrations.integration_account_lifecycle import list_accounts, update_account
from app.services.integrations.integration_accounts import match_account
from app.utils.errors import AppError


class RenameIntegrationAccountArgs(BaseModel):
    integration_id: str = Field(
        description="The integration's id, as shown in parentheses in the connected "
        "integrations list (e.g. 'googlecalendar')."
    )
    account: str = Field(
        description="The account to rename, by its current name, address or label "
        "exactly as listed in the user's accounts."
    )
    name: str = Field(
        max_length=MAX_ACCOUNT_NICKNAME_LENGTH,
        description="The new name, e.g. 'Work' or 'Personal'. An empty string removes "
        "the name, so the account shows its address or label again.",
    )


async def _rename_integration_account(
    user_id: str, integration_id: str, account: str, name: str
) -> str:
    record = await list_accounts(user_id, integration_id)
    if record is None or not record.accounts:
        raise AppError(
            message=f"The user has no connected {integration_id} accounts",
            fix="Check the integration_id against the connected integrations list",
        )
    target = match_account(record, account)
    if target is None:
        listed = ", ".join(a.display_name for a in record.accounts)
        raise AppError(
            message=f"No {integration_id} account is named {account!r}",
            fix=f"Use one of: {listed}",
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


tools = [rename_integration_account]
