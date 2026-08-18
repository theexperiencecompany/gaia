"""Getting an integration connected: the connect card and the agent-facing copy.

Both halves of one contract, so they live together. The wording depends on the
client: UI clients render the connect card, so the agent text must stay URL-free;
text-only clients (bots, background runs) need the link inline because there is
no card to click.

Both halves also take ``expired`` — whether the user *had* this connected and the
grant died, versus never connected it at all. The two need different copy ("sign
in again" vs "connect this"), and only the caller can tell them apart, so it is a
required argument rather than a defaulted one.
"""

from typing import cast

from langgraph.config import get_config, get_stream_writer

from app.config.settings import settings
from app.models.agent_models import agent_configurable
from app.models.chat_models import SourceCategory


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


def emit_integration_connection_required(
    integration_id: str, integration_name: str, *, expired: bool
) -> None:
    """Stream the connect-card event for an integration the user has to (re)connect.

    The single emitter of ``integration_connection_required`` — the payload is the
    contract for ``IntegrationConnectionPrompt.tsx`` and the mobile renderer, so it
    is built in exactly one place.
    """
    writer = get_stream_writer()
    writer(
        {
            "integration_connection_required": {
                "integration_id": integration_id,
                "expired": expired,
                "message": (
                    f"Your {integration_name} connection expired. Sign in again to keep using it."
                    if expired
                    else f"To use {integration_name} features, please connect your account first."
                ),
            }
        }
    )


def build_integration_connection_message(
    integration_name: str, connect_url: str | None = None, *, expired: bool
) -> str:
    """Agent-facing instruction for getting an integration connected.

    On UI clients a one-click connect card is rendered alongside the reply, so
    the agent text must stay URL-free — the card handles it. On bot/background
    (text-only) clients there is no UI, so the agent relays the single-use
    login-free link (valid for 1 hour) directly. When no link could be minted
    (``connect_url is None`` — e.g. Redis down) the user is pointed at the
    integrations page, which requires a normal GAIA login.
    """
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

    if _current_source_category() == SourceCategory.UI.value:
        return (
            f"{lead} A {verb} button has been shown to the user — do NOT include any URL in "
            f"your reply, the UI card handles it. Ask the user to click it, then try again."
        )

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
