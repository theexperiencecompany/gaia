"""Whether the user has written in a Gmail thread, read from the thread's own labels."""

from app.constants.integrations import GMAIL_INTEGRATION_ID
from app.models.agent_config import ComposioAccountSelection
from app.models.integrations.gmail import GmailThreadData
from app.services.composio.account_scope import account_scope
from app.services.composio.custom_tools.gmail_constants import GMAIL_API_BASE, GMAIL_TOOLKIT
from app.services.composio.proxy_client import ProxyRequest, proxy_request
from app.services.integrations.integration_accounts import get_account_record

GMAIL_SENT_LABEL = "SENT"
# Only each message's id and labels: a long thread costs one small read.
_THREAD_LABELS_QUERY = {"format": "minimal", "fields": "messages(id,labelIds)"}


async def _account(user_id: str, account_id: str | None) -> ComposioAccountSelection | None:
    """Return the connected account a GAIA account id names; None reads the primary account."""
    if account_id is None:
        return None
    record = await get_account_record(user_id, GMAIL_INTEGRATION_ID)
    account = record.find_account(account_id) if record else None
    if account is None:
        raise LookupError(f"Gmail account {account_id} is not connected for this user")
    return ComposioAccountSelection(
        toolkit=GMAIL_TOOLKIT, connected_account_id=account.connected_account_id
    )


async def user_wrote_in_thread(
    user_id: str, thread_id: str, *, message_id: str | None, account_id: str | None
) -> bool:
    """Whether a message other than message_id in the thread carries Gmail's SENT label.

    Reads the account the event arrived on; raises when Gmail cannot say.
    """
    with account_scope(await _account(user_id, account_id)):
        data = await proxy_request(
            ProxyRequest(
                user_id=user_id,
                toolkit=GMAIL_TOOLKIT,
                endpoint=f"{GMAIL_API_BASE}/users/me/threads/{thread_id}",
                method="GET",
                query=_THREAD_LABELS_QUERY,
            )
        )
    thread = GmailThreadData.model_validate(data)
    return any(
        GMAIL_SENT_LABEL in (message.label_ids or ())
        for message in thread.messages
        if message.id != message_id
    )
