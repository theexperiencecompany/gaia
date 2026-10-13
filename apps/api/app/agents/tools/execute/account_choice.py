"""Which connected account a Composio tool call acts as, and how that choice travels with the call."""

from langchain_core.runnables import RunnableConfig

from app.config.oauth_config import get_integration_by_tool_slug
from app.constants.integrations import ConnectMode
from app.models.agent_config import ComposioAccountSelection
from app.models.execute_models import AccountChoice, DispatchError, DispatchErrorKind
from app.models.integration_models import UserIntegrationDocument
from app.services.integrations.integration_accounts import (
    get_account_record,
    match_account,
    primary_account,
)
from app.utils.integration_checker import request_integration_connection
from shared.py.analytics.catalog.agents import ToolUsed


def _account_names(record: UserIntegrationDocument) -> str:
    return ", ".join(
        f'"{a.display_name}" ({"expired" if a.status != "connected" else "connected"})'
        for a in record.accounts
    )


async def choose_account(
    user_id: str | None, tool_name: str, account: str | None
) -> AccountChoice | DispatchError | None:
    """The connected account a Composio tool call acts as; None leaves the call unpinned.

    Unpinned covers non-Composio tools and integrations with no accounts on
    record, where the tool's own not-connected path (the connect card) answers.
    """
    integration = get_integration_by_tool_slug(tool_name)
    composio_config = integration.composio_config if integration else None
    if integration is None or composio_config is None or not user_id:
        if account:
            return DispatchError(
                kind=DispatchErrorKind.UNKNOWN_ACCOUNT,
                detail=f"'{tool_name}' has no connected accounts to choose between.",
                hint="Retry without `account`.",
            )
        return None
    record = await get_account_record(user_id, integration.id)
    if record is None or not record.accounts:
        return None
    chosen = match_account(record, account) if account else primary_account(record)
    if chosen is None:
        return DispatchError(
            kind=DispatchErrorKind.UNKNOWN_ACCOUNT,
            detail=f"No connected {integration.name} account is called '{account}'.",
            hint=(
                f"If the user meant one of these, pass it as `account`: {_account_names(record)}. "
                "Otherwise ask them which account they meant."
            ),
        )
    live = [a for a in record.accounts if a.status == "connected"]
    if chosen.status != "connected" and live:
        return DispatchError(
            kind=DispatchErrorKind.ACCOUNT_EXPIRED,
            detail=f"The {integration.name} account {chosen.display_name} needs reconnecting.",
            # Same card a call that finds the account dead at Composio shows.
            hint=await request_integration_connection(
                integration.id,
                integration.name,
                user_id,
                mode=ConnectMode.RECONNECT,
                account=chosen,
            ),
        )
    return AccountChoice(
        selection=ComposioAccountSelection(
            toolkit=composio_config.toolkit, connected_account_id=chosen.connected_account_id
        ),
        display_name=chosen.display_name,
        is_primary=chosen.id == record.primary_account_id,
        account_count=len(record.accounts),
    )


def tool_used(tool_name: str, choice: AccountChoice | None) -> ToolUsed:
    if choice is None:
        return ToolUsed(tool_name=tool_name, via="execute")
    return ToolUsed(
        tool_name=tool_name,
        via="execute",
        account_count=choice.account_count,
        account_is_primary=choice.is_primary,
    )


def with_account(config: RunnableConfig, choice: AccountChoice | None) -> RunnableConfig:
    if choice is None:
        return config
    metadata = {
        **(config.get("metadata") or {}),
        "composio_account": choice.selection.model_dump(mode="json"),
    }
    return {**config, "metadata": metadata}
