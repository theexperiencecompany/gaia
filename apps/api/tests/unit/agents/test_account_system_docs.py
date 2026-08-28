"""Account-center system docs: the master GUIDE and per-topic guides.

The read tool's memory fast-path serves these without touching JuiceFS, so a
missing registration means the agent can't read its own instructions for the
area — the registration set is what's under test.
"""

import pytest

from app.agents.workspace.system_files import system_file_body


@pytest.mark.unit
def test_master_account_guide_is_a_system_file() -> None:
    body = system_file_body("account/GUIDE.md")
    assert body is not None
    assert "guides/" in body


@pytest.mark.unit
@pytest.mark.parametrize(
    "rel_path",
    [
        "account/guides/subscription.md",
        "account/guides/usage.md",
        "account/guides/notifications.md",
        "account/guides/preferences.md",
        "account/guides/custom-instructions.md",
        "account/guides/voices.md",
        "account/guides/linked-accounts.md",
    ],
)
def test_every_topic_guide_is_registered(rel_path: str) -> None:
    assert system_file_body(rel_path)


@pytest.mark.unit
def test_guides_tell_the_agent_files_are_read_only_and_tools_are_the_way() -> None:
    notifications = system_file_body("account/guides/notifications.md") or ""
    linked = system_file_body("account/guides/linked-accounts.md") or ""
    subscription = system_file_body("account/guides/subscription.md") or ""
    assert "update_notification_settings" in notifications
    assert "manage_linked_account" in linked
    # The restriction must be stated as a prohibition on GAIA, not merely the
    # word "cancel" appearing anywhere (e.g. "the user cancelled last month").
    lowered = subscription.lower()
    assert "cannot modify or cancel" in lowered or "you cannot" in lowered
