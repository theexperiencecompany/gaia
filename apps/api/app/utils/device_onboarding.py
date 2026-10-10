"""Build the device-onboarding card, approval link, and matching agent copy.

Mirrors app/utils/integration_checker.py: the UI card and the agent's
instruction are one operation, and the wording is source-category aware -
URL-free on UI (the card carries the action) and inline on text-only clients
(bots, background) where there is no card. The approve link is only ever
surfaced to the user on the authenticated approval page; the agent never
approves a pairing code itself.
"""

from typing import cast

from langgraph.config import get_config, get_stream_writer

from app.constants.device_bridge import (
    CLI_INSTALL_COMMANDS,
    DEVICE_BRIDGE_DOCS_URL,
    DEVICE_PAIR_COMMAND,
    DEVICE_UP_COMMAND,
)
from app.models.agent_models import agent_configurable
from app.models.chat_models import SourceCategory
from app.services.device.device_service import build_device_approve_url


def _current_source_category() -> str | None:
    """Read the source category (ui/bot/bg) from the active graph run, or None."""
    try:
        config = get_config()
    except RuntimeError:
        return None
    return cast(str | None, agent_configurable(config).get("source_category"))


def request_device_onboarding() -> str:
    """Show the device-onboarding card (install + pair) and return the agent copy."""
    source_category = _current_source_category()
    if source_category is not None:
        get_stream_writer()(
            {
                "device_onboarding_required": {
                    "install_commands": CLI_INSTALL_COMMANDS,
                    "docs_url": DEVICE_BRIDGE_DOCS_URL,
                    "pair_command": DEVICE_PAIR_COMMAND,
                    "up_command": DEVICE_UP_COMMAND,
                    "message": (
                        "Connect a computer so I can run commands and reach local "
                        "servers on it. Follow the steps below."
                    ),
                }
            }
        )
    if source_category == SourceCategory.UI.value:
        return (
            "A device setup card has been shown to the user with the install and pairing "
            "steps. Do NOT include any commands or URLs in your reply, the card handles it. "
            "Ask them to follow it and paste the pairing code once they have it, then call "
            "approve_device_pairing with that code."
        )
    return (
        f"Ask the user to install the GAIA CLI with `{CLI_INSTALL_COMMANDS['npm']}` "
        f"(Node 20+, macOS/Linux/Windows-WSL2), run `{DEVICE_PAIR_COMMAND}`, and paste the "
        f"code it prints so you can call approve_device_pairing. Full guide: "
        f"{DEVICE_BRIDGE_DOCS_URL}"
    )


def request_device_approval(user_code: str) -> str:
    """Surface the trusted approve-page link (code prefilled) for a pairing code.

    The agent never approves a code itself; it hands the user the authenticated
    approval page where they confirm.
    """
    code = user_code.strip().upper()
    approve_url = build_device_approve_url(code)
    source_category = _current_source_category()
    if source_category is not None:
        get_stream_writer()(
            {
                "device_approval_required": {
                    "approve_url": approve_url,
                    "code": code,
                    "message": "Review and approve linking this device to your account.",
                }
            }
        )
    if source_category == SourceCategory.UI.value:
        return (
            f"An approve button for device code {code} has been shown to the user. Do NOT "
            "include the URL in your reply, the card handles it. Ask them to click it and "
            f"confirm on the page that opens, then to run `{DEVICE_UP_COMMAND}` to bring the "
            "device online."
        )
    return (
        f"Ask the user to open this link while signed in to approve device {code}, then run "
        f"`{DEVICE_UP_COMMAND}`: {approve_url}"
    )
