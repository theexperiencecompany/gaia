"""Device-onboarding card utils.

Covers the streamed card payload and the source-category-aware agent copy
(URL-free on UI, inline on text-only).
"""

from unittest.mock import patch

import pytest

from app.constants.device_bridge import (
    CLI_INSTALL_COMMANDS,
    DEVICE_BRIDGE_DOCS_URL,
    DEVICE_PAIR_COMMAND,
    DEVICE_UP_COMMAND,
)
from app.models.chat_models import SourceCategory
from app.utils import device_onboarding as mod

_UI = SourceCategory.UI.value


def _capture():
    captured: dict = {}
    return captured, lambda payload: captured.update(payload)


@pytest.mark.unit
def test_onboarding_streams_card_and_stays_url_free_on_ui():
    captured, writer = _capture()
    with (
        patch.object(mod, "_current_source_category", return_value=_UI),
        patch.object(mod, "get_stream_writer", return_value=writer),
    ):
        ret = mod.request_device_onboarding()

    card = captured["device_onboarding_required"]
    # Every field the card carries is asserted exactly, so a mutated key/value dies.
    assert card["install_commands"] == CLI_INSTALL_COMMANDS
    assert card["docs_url"] == DEVICE_BRIDGE_DOCS_URL
    assert card["pair_command"] == DEVICE_PAIR_COMMAND
    assert card["up_command"] == DEVICE_UP_COMMAND
    assert card["message"] == (
        "Connect a computer so I can run commands and reach local "
        "servers on it. Follow the steps below."
    )
    # UI card carries the steps, so the agent copy must not leak a URL/command,
    # and its exact wording is the contract (kills string-content mutants).
    assert ret == (
        "A device setup card has been shown to the user with the install and pairing "
        "steps. Do NOT include any commands or URLs in your reply, the card handles it. "
        "Ask them to follow it and paste the pairing code once they have it, then call "
        "approve_device_pairing with that code."
    )


@pytest.mark.unit
def test_onboarding_text_copy_inlines_command_and_docs_off_ui():
    with patch.object(mod, "_current_source_category", return_value=None):
        ret = mod.request_device_onboarding()
    assert ret == (
        f"Ask the user to install the GAIA CLI with `{CLI_INSTALL_COMMANDS['npm']}` "
        f"(Node 20+, macOS/Linux/Windows-WSL2), run `{DEVICE_PAIR_COMMAND}`, and paste the "
        f"code it prints so you can call approve_device_pairing. Full guide: "
        f"{DEVICE_BRIDGE_DOCS_URL}"
    )


@pytest.mark.unit
def test_approval_streams_link_and_normalizes_code_on_ui():
    captured, writer = _capture()
    with (
        patch.object(mod, "_current_source_category", return_value=_UI),
        patch.object(mod, "get_stream_writer", return_value=writer),
    ):
        ret = mod.request_device_approval("ns2v-yc5s")

    card = captured["device_approval_required"]
    assert card["code"] == "NS2V-YC5S"  # normalized upper
    assert card["approve_url"].endswith("/settings/devices/approve?code=NS2V-YC5S")
    assert card["message"] == "Review and approve linking this device to your account."
    # The link rides the card, not the agent's user-facing text; wording is the contract.
    assert "http" not in ret
    assert ret == (
        "An approve button for device code NS2V-YC5S has been shown to the user. Do NOT "
        "include the URL in your reply, the card handles it. Ask them to click it and "
        f"confirm on the page that opens, then to run `{DEVICE_UP_COMMAND}` to bring the "
        "device online."
    )


@pytest.mark.unit
def test_approval_text_copy_inlines_the_url_off_ui():
    with patch.object(mod, "_current_source_category", return_value=None):
        ret = mod.request_device_approval("ns2v-yc5s")
    approve_url = mod.build_device_approve_url("NS2V-YC5S")
    assert ret == (
        f"Ask the user to open this link while signed in to approve device NS2V-YC5S, "
        f"then run `{DEVICE_UP_COMMAND}`: {approve_url}"
    )


@pytest.mark.unit
def test_no_stream_when_outside_a_runnable_context():
    """Dev direct-invocation paths have no stream; the util must not try to write."""
    captured, writer = _capture()
    with (
        patch.object(mod, "_current_source_category", return_value=None),
        patch.object(mod, "get_stream_writer", return_value=writer) as gsw,
    ):
        mod.request_device_onboarding()
    assert captured == {}
    gsw.assert_not_called()
