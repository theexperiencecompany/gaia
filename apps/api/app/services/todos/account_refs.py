"""Which of the user's connected accounts a todo's thread or watch belongs to."""

from app.config.oauth_config import get_integration_by_tool_slug
from app.constants.integrations import GMAIL_INTEGRATION_ID
from app.models.todo_models import ExternalRef, ExternalRefSource
from app.services.integrations.integration_accounts import get_account_record, match_account
from app.services.triggers.registry import get_handler_by_name


async def owned_gmail_thread_ref(
    user_id: str, gmail_thread_id: str | None, gmail_account: str | None
) -> ExternalRef | str | None:
    """Pin a thread to the account it is in; a string says why it cannot be pinned."""
    if not gmail_thread_id:
        return None
    record = await get_account_record(user_id, GMAIL_INTEGRATION_ID)
    accounts = record.accounts if record else []
    names = ", ".join(a.display_name for a in accounts)
    if gmail_account is not None:
        account = match_account(record, gmail_account) if record else None
        if account is None:
            return f"Error: no Gmail account is named {gmail_account!r}. Its accounts: {names}."
    elif len(accounts) > 1:
        return (
            f"Error: the user has {len(accounts)} Gmail accounts ({names}). Pass gmail_account "
            "with the one the thread was fetched from."
        )
    else:
        account = accounts[0] if accounts else None
    return ExternalRef(
        source=ExternalRefSource.GMAIL_THREAD,
        id=gmail_thread_id,
        account=account.id if account else None,
    )


async def watched_account_id(user_id: str, trigger_name: str, account: str) -> str | None:
    """GAIA's id for the account a watch names, on the trigger's own integration; None if unknown."""
    handler = get_handler_by_name(trigger_name)
    integration = get_integration_by_tool_slug(next(iter(handler.event_types))) if handler else None
    record = await get_account_record(user_id, integration.id) if integration else None
    target = match_account(record, account) if record else None
    return target.id if target else None
