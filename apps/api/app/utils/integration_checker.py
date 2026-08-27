"""Surfacing an integration the user has to (re)connect, and the agent copy for it.

The card and the copy are one operation, never two: the UI wording promises a
connect button "has been shown to the user", so anything that produces it must
also produce the card. Splitting them is what left users chasing a button that
was never rendered.

The wording depends on the client: UI clients render a connect card, so the
agent text must stay URL-free; text-only clients (bots, background runs) need
the link inline because there is no card to click.

It also depends on whether the user *had* this connected and the grant died,
versus never connected it at all — "sign in again" and "connect this" are
different asks. Only the stored record tells the two apart, so this module reads
it rather than taking it as an argument; a caller that has to remember to pass it
is a caller that will eventually forget.
"""

from typing import cast

from langgraph.config import get_config, get_stream_writer

from app.config.settings import settings
from app.db.repositories.user_integrations import user_integration_repository
from app.models.agent_models import agent_configurable
from app.models.chat_models import SourceCategory
from app.services.connect_link_service import build_connect_link_url


def _current_source_category() -> str | None:
    """Read the generalized source category (ui/bot/bg) from the active graph run.

    Uses LangGraph's ambient config (same mechanism as ``get_stream_writer``), so
    no config threading is needed. Returns None outside a runnable context.
    """
    try:
        config = get_config()
    except RuntimeError:
        return None
    return cast(str | None, agent_configurable(config).get("source_category"))


async def request_integration_connection(
    integration_id: str, integration_name: str, user_id: str
) -> str:
    """Show the (re)connect card for an unusable integration and return the agent's instruction.

    The single source of both. On UI clients the card carries the connect flow, so
    the returned text stays URL-free. On bot/background (text-only) clients there is
    no UI, so the agent relays the single-use login-free link (valid for 1 hour)
    directly; when no link could be minted (Redis down) the user is pointed at the
    integrations page, which requires a normal GAIA login.
    """
    # Only Composio grants ever reach the ``expired`` status, so MCP integrations
    # fall through to the never-connected wording without needing a special case.
    expired = await user_integration_repository.is_expired(user_id, integration_id)
    source_category = _current_source_category()

    # None means no runnable context at all (e.g. the dev direct-invocation
    # endpoints), so there is no stream for a card to travel on.
    if source_category is not None:
        card_message = (
            f"Your {integration_name} connection expired. Sign in again to keep using it."
            if expired
            else f"To use {integration_name} features, please connect your account first."
        )
        get_stream_writer()(
            {
                "integration_connection_required": {
                    "integration_id": integration_id,
                    "expired": expired,
                    "message": card_message,
                }
            }
        )

    if expired:
        lead = (
            f"The user's {integration_name} connection EXPIRED — they had it connected and the "
            f"access has since died, so they must sign in again. Do NOT tell them to connect "
            f"{integration_name} for the first time."
        )
        verb = "reconnect"
    else:
        lead = f"{integration_name} needs to be connected."
        verb = "connect"

    if source_category == SourceCategory.UI.value:
        return (
            f"{lead} A {verb} button has been shown to the user — do NOT include any URL in "
            f"your reply, the UI card handles it. Ask the user to click it, then try again."
        )

    connect_url = await build_connect_link_url(user_id, integration_id)
    if not connect_url:
        integrations_url = f"{settings.FRONTEND_URL.rstrip('/')}/integrations"
        return (
            f"{lead} The user is on a text-only platform (no UI). Ask them to open "
            f"{integrations_url} and {verb} {integration_name} there."
        )

    return (
        f"{lead} The user is on a text-only platform (no UI). "
        f"Include this URL verbatim in your result so the comms agent can relay it to the user, "
        f"and tell them it is valid for 1 hour: {connect_url}"
    )
