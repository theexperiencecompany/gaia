"""Surfacing an integration the user has to (re)connect, and the agent copy for it.

The card and the copy are one operation, never two: the UI wording promises a
connect button "has been shown to the user", so anything that produces it must
also produce the card. Splitting them is what left users chasing a button that
was never rendered.

The wording depends on the client: UI clients render a connect card, so the
agent text stays URL-free; bots need the link inline. A background run has no
user present, so it is told to record the gap and carry on.

It also depends on whether the user *had* this connected and the grant died,
versus never connected it at all — "sign in again" and "connect this" are
different asks. Only the stored record tells the two apart, so this module
reads it rather than taking it as an argument.
"""

from typing import NamedTuple

from langgraph.config import get_config

from app.config.settings import settings
from app.constants.integrations import ACCOUNT_NEEDS_RECONNECT_HINT, ConnectMode
from app.db.repositories.user_integrations import user_integration_repository
from app.models.agent_models import (
    AgentConfigurableView,
    current_stream_writer,
    read_agent_configurable,
)
from app.models.chat_models import SourceCategory
from app.models.integration_models import IntegrationAccount
from app.services.connect_link_service import build_connect_link_url


def _current_run() -> AgentConfigurableView | None:
    """Read the active graph run's configurable (source category, execution mode).

    Uses LangGraph's ambient config (same mechanism as get_stream_writer), so
    no config threading is needed. Returns None outside a runnable context.
    """
    try:
        config = get_config()
    except RuntimeError:
        return None
    return read_agent_configurable(config)


class _Ask(NamedTuple):
    """What the user is asked to do, as the card says it and as the agent is told."""

    card: str
    lead: str
    verb: str
    gap: str
    button: str


def _ask(mode: ConnectMode, expired: bool, name: str, account: str | None) -> _Ask:
    if account is not None:
        return _Ask(
            card=f"Your {name} account {account} lost its connection. Sign in as {account} "
            "again to keep using it.",
            lead=f"The user's {name} account {account} lost its connection and must be signed "
            f"in again. {ACCOUNT_NEEDS_RECONNECT_HINT}",
            verb="reconnect",
            gap=f"the {name} account {account} lost its connection",
            button="reconnect button",
        )
    if mode is ConnectMode.ADD_ACCOUNT:
        return _Ask(
            card=f"Add another {name} account. Sign in with the account you want to add.",
            lead=f"The user wants to add another {name} account; their current accounts stay "
            "connected.",
            verb="add another account to",
            gap=f"another {name} account was not added",
            button="button to add the account",
        )
    if mode is ConnectMode.RECONNECT and not expired:
        return _Ask(
            card=f"Your {name} connection needs fresh authorization. Reauthorize to keep using it.",
            lead=f"The user's {name} connection needs fresh authorization; they need to "
            "reconnect to refresh access.",
            verb="reconnect",
            gap=f"the {name} connection needs a refresh",
            button="reconnect button",
        )
    if expired:
        return _Ask(
            card=f"Your {name} connection expired. Sign in again to keep using it.",
            lead=f"The user's {name} connection EXPIRED. They had it connected and the "
            f"access has since died, so they must sign in again. Do NOT tell them to connect "
            f"{name} for the first time.",
            verb="reconnect",
            gap=f"the {name} connection expired",
            button="reconnect button",
        )
    return _Ask(
        card=f"To use {name} features, please connect your account first.",
        lead=f"{name} needs to be connected.",
        verb="connect",
        gap=f"{name} is not connected",
        button="connect button",
    )


async def _connected_account_names(user_id: str, integration_id: str) -> list[str]:
    """Name the accounts already connected, primary first, for a card adding another."""
    record = await user_integration_repository.get_for_user(user_id, integration_id)
    if record is None:
        return []
    ordered = sorted(record.accounts, key=lambda a: a.id != record.primary_account_id)
    return [a.display_name for a in ordered]


async def request_integration_connection(
    integration_id: str,
    integration_name: str,
    user_id: str,
    *,
    mode: ConnectMode = ConnectMode.CONNECT,
    account: IntegrationAccount | None = None,
) -> str:
    """Show the connect card for mode and return the agent instruction.

    With an account, the card and link sign that expired account back in place.
    UI clients get a URL-free text; text-only clients relay the single-use
    link (valid 1 hour) or the integrations page. A background run gets the
    integrations page, read after any single-use link has died, and carries on.
    """
    # Only Composio grants ever reach the ``expired`` status, so MCP integrations
    # fall through to the never-connected wording without needing a special case.
    expired = await user_integration_repository.is_expired(user_id, integration_id)
    ask = _ask(mode, expired, integration_name, account.display_name if account else None)
    run = _current_run()
    source_category = run.source_category if run is not None else None

    # None means no runnable context at all (e.g. the dev direct-invocation
    # endpoints), so there is no stream for a card to travel on.
    if source_category is not None:
        adding = mode is ConnectMode.ADD_ACCOUNT
        current_stream_writer()(
            {
                "integration_connection_required": {
                    "integration_id": integration_id,
                    "integration_name": integration_name,
                    "expired": not adding
                    and (expired or mode is ConnectMode.RECONNECT or account is not None),
                    "add_account": adding,
                    "message": ask.card,
                    "connected_accounts": (
                        await _connected_account_names(user_id, integration_id) if adding else []
                    ),
                    "reconnect_account": (
                        {"id": account.id, "name": account.display_name} if account else None
                    ),
                }
            }
        )

    # Login-required but permanent: the fallback when no single-use link applies.
    integrations_url = f"{settings.FRONTEND_URL.rstrip('/')}/integrations"

    if run is not None and run.execution_mode == "background":
        return (
            f"{ask.lead} This is a background run and no user is present to {ask.verb} it, so "
            f"retrying {integration_name} this run cannot succeed. Record in your result that "
            f"{ask.gap} (the user can {ask.verb} it at {integrations_url}), then carry on with "
            "the rest of the task."
        )

    if source_category == SourceCategory.UI.value:
        return (
            f"{ask.lead} A {ask.button} has been shown to the user, so do NOT include any URL in "
            f"your reply, the UI card handles it. Ask the user to click it, then try again."
        )

    connect_url = await build_connect_link_url(
        user_id, integration_id, account.id if account else None
    )
    if not connect_url:
        return (
            f"{ask.lead} The user is on a text-only platform (no UI). Ask them to open "
            f"{integrations_url} and {ask.verb} {integration_name} there."
        )

    return (
        f"{ask.lead} The user is on a text-only platform (no UI). "
        f"Include this URL verbatim in your result so the comms agent can relay it to the user, "
        f"and tell them it is valid for 1 hour: {connect_url}"
    )
