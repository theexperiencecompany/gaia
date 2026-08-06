"""Agent-facing copy for getting an integration connected.

The wording depends on the client: UI clients render a connect card, so the
agent text must stay URL-free; text-only clients (bots, background runs) need
the link inline because there is no card to click.
"""

from typing import cast

from langgraph.config import get_config

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


def build_integration_connection_message(
    integration_name: str, connect_url: str | None = None
) -> str:
    """Agent-facing instruction for getting an integration connected.

    On UI clients a one-click connect card is rendered alongside the reply, so
    the agent text must stay URL-free — the card handles it. On bot/background
    (text-only) clients there is no UI, so the agent relays the single-use
    login-free link (valid for 1 hour) directly. When no link could be minted
    (``connect_url is None`` — e.g. Redis down) the user is pointed at the
    integrations page, which requires a normal GAIA login.
    """
    if _current_source_category() == SourceCategory.UI.value:
        return (
            f"{integration_name} needs to be connected. A connect button has been shown to the "
            f"user — do NOT include any URL in your reply, the UI card handles it. "
            f"Ask the user to click the connect button, then try again."
        )

    if not connect_url:
        integrations_url = f"{settings.FRONTEND_URL.rstrip('/')}/integrations"
        return (
            f"{integration_name} needs to be connected. The user is on a text-only platform "
            f"(no UI). Ask them to open {integrations_url} and connect {integration_name} there."
        )

    return (
        f"{integration_name} needs to be connected. The user is on a text-only platform (no UI). "
        f"Include this URL verbatim in your result so the comms agent can relay it to the user, "
        f"and tell them it is valid for 1 hour: {connect_url}"
    )
