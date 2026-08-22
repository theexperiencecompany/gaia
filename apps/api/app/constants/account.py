"""Account-center workspace paths — the single map of the ``account/`` subtree.

One entry per projected file: which area it belongs to and where it lands under
the user's workspace root. read_tool / write_tool / edit_tool / policy all read
from here so the set cannot drift.

Every file in ``account/`` is a read-only projection of Mongo/Postgres truth —
editing a file accomplishes nothing. Mutations go through the account mutation
tools (``ACCOUNT_MUTATION_TOOLS``), which are always HIL-gated.
"""

from enum import StrEnum


class AccountArea(StrEnum):
    SUBSCRIPTION = "subscription"
    USAGE = "usage"
    NOTIFICATIONS = "notifications"
    PREFERENCES = "preferences"
    CUSTOM_INSTRUCTIONS = "custom_instructions"
    VOICE = "voice"
    LINKED_ACCOUNTS = "linked_accounts"


ACCOUNT_DIR = "account"
ACCOUNT_GUIDES_DIRNAME = "guides"
ACCOUNT_VOICES_DIRNAME = "voices"
ACCOUNT_LINKED_ACCOUNTS_DIRNAME = "linked-accounts"

# Every projected data file, workspace-relative. All read-only: the projection
# is a view, never an input.
ACCOUNT_READ_ONLY_PATHS: frozenset[str] = frozenset(
    {
        f"{ACCOUNT_DIR}/subscription.json",
        f"{ACCOUNT_DIR}/usage.json",
        f"{ACCOUNT_DIR}/notifications.json",
        f"{ACCOUNT_DIR}/preferences.json",
        f"{ACCOUNT_DIR}/custom-instructions.json",
        f"{ACCOUNT_DIR}/{ACCOUNT_VOICES_DIRNAME}/catalog.json",
        f"{ACCOUNT_DIR}/{ACCOUNT_VOICES_DIRNAME}/selected.json",
        *(
            f"{ACCOUNT_DIR}/{ACCOUNT_LINKED_ACCOUNTS_DIRNAME}/{platform}.json"
            for platform in ("telegram", "whatsapp", "discord", "slack", "imessage")
        ),
    }
)

# Executor tools that mutate account state — each is always HIL-gated
# (see app/constants/hil.py). manage_linked_account is action-dependent
# (disconnect gated, generate_link not) so it gates itself in policy.
ACCOUNT_MUTATION_TOOLS: frozenset[str] = frozenset(
    {
        "update_notification_settings",
        "update_preferences",
        "update_custom_instructions",
        "set_selected_voice",
    }
)


def account_area_for(rel_path: str) -> AccountArea | None:
    """Map a workspace-relative account data path to its area, else None."""
    if rel_path not in ACCOUNT_READ_ONLY_PATHS:
        return None
    name = rel_path.removeprefix(f"{ACCOUNT_DIR}/")
    if name == "subscription.json":
        return AccountArea.SUBSCRIPTION
    if name == "usage.json":
        return AccountArea.USAGE
    if name == "notifications.json":
        return AccountArea.NOTIFICATIONS
    if name == "preferences.json":
        return AccountArea.PREFERENCES
    if name == "custom-instructions.json":
        return AccountArea.CUSTOM_INSTRUCTIONS
    if name.startswith(f"{ACCOUNT_VOICES_DIRNAME}/"):
        return AccountArea.VOICE
    return AccountArea.LINKED_ACCOUNTS


__all__ = [
    "ACCOUNT_DIR",
    "ACCOUNT_GUIDES_DIRNAME",
    "ACCOUNT_LINKED_ACCOUNTS_DIRNAME",
    "ACCOUNT_MUTATION_TOOLS",
    "ACCOUNT_READ_ONLY_PATHS",
    "ACCOUNT_VOICES_DIRNAME",
    "AccountArea",
    "account_area_for",
]
