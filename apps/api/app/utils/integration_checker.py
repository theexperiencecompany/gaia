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

from langgraph.config import get_config, get_stream_writer

from app.config.settings import settings
from app.db.repositories.user_integrations import user_integration_repository
from app.models.agent_models import AgentConfigurableView, read_agent_configurable
from app.models.chat_models import SourceCategory
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


async def request_integration_connection(
    integration_id: str,
    integration_name: str,
    user_id: str,
    *,
    force_reconnect: bool = False,
) -> str:
    """Show the reconnect card for an unusable integration and return the agent instruction.

    UI clients get a URL-free text; text-only clients relay the single-use
    link (valid 1 hour) or the integrations page. A background run gets the
    integrations page, read after any single-use link has died, and carries on.
    force_reconnect presents reauthorization even when stored status is connected.
    """
    # Only Composio grants ever reach the ``expired`` status, so MCP integrations
    # fall through to the never-connected wording without needing a special case.
    expired = await user_integration_repository.is_expired(user_id, integration_id)
    reconnect = expired or force_reconnect
    run = _current_run()
    source_category = run.source_category if run is not None else None

    # None means no runnable context at all (e.g. the dev direct-invocation
    # endpoints), so there is no stream for a card to travel on.
    if source_category is not None:
        if force_reconnect and not expired:
            card_message = (
                f"Your {integration_name} connection needs fresh authorization. "
                "Reauthorize to keep using it."
            )
        elif expired:
            card_message = (
                f"Your {integration_name} connection expired. Sign in again to keep using it."
            )
        else:
            card_message = f"To use {integration_name} features, please connect your account first."
        get_stream_writer()(
            {
                "integration_connection_required": {
                    "integration_id": integration_id,
                    "integration_name": integration_name,
                    "expired": reconnect,
                    "message": card_message,
                }
            }
        )

    if force_reconnect and not expired:
        lead = (
            f"The user's {integration_name} connection needs fresh authorization; they need to "
            "reconnect to refresh access."
        )
        verb = "reconnect"
        gap = f"the {integration_name} connection needs a refresh"
    elif expired:
        lead = (
            f"The user's {integration_name} connection EXPIRED. They had it connected and the "
            f"access has since died, so they must sign in again. Do NOT tell them to connect "
            f"{integration_name} for the first time."
        )
        verb = "reconnect"
        gap = f"the {integration_name} connection expired"
    else:
        lead = f"{integration_name} needs to be connected."
        verb = "connect"
        gap = f"{integration_name} is not connected"

    # Login-required but permanent: the fallback when no single-use link applies.
    integrations_url = f"{settings.FRONTEND_URL.rstrip('/')}/integrations"

    if run is not None and run.execution_mode == "background":
        return (
            f"{lead} This is a background run and no user is present to {verb} it, so "
            f"retrying {integration_name} this run cannot succeed. Record in your result that "
            f"{gap} (the user can {verb} it at {integrations_url}), then carry on with the rest "
            "of the task."
        )

    if source_category == SourceCategory.UI.value:
        return (
            f"{lead} A {verb} button has been shown to the user, so do NOT include any URL in "
            f"your reply, the UI card handles it. Ask the user to click it, then try again."
        )

    connect_url = await build_connect_link_url(user_id, integration_id)
    if not connect_url:
        return (
            f"{lead} The user is on a text-only platform (no UI). Ask them to open "
            f"{integrations_url} and {verb} {integration_name} there."
        )

    return (
        f"{lead} The user is on a text-only platform (no UI). "
        f"Include this URL verbatim in your result so the comms agent can relay it to the user, "
        f"and tell them it is valid for 1 hour: {connect_url}"
    )
