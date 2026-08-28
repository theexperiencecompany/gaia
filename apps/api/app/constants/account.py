"""Account-center workspace paths — the single map of the ``account/`` subtree.

One entry per projected file: which area it belongs to and where it lands under
the user's workspace root. read_tool / write_tool / edit_tool / policy all read
from here so the set cannot drift.

Every file in ``account/`` is a read-only projection of Mongo/Postgres truth —
editing a file accomplishes nothing. Mutations go through the account mutation
tools (``app/agents/tools/account_tools.py``, registered ``always_gate``).
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

# Executor tools that mutate account state live in
# app/agents/tools/account_tools.py; their forced-ask HIL posture is stamped on
# the tool registry at registration (Tool.always_gate) — the single source of
# truth for gating.


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


# The mutation tool for each area — what the write/edit refusal points at
# instead of an edit. Empty string = no agent tool exists (billing truth).
AREA_MUTATION_TOOL: dict[AccountArea, str] = {
    AccountArea.NOTIFICATIONS: "update_notification_settings",
    AccountArea.PREFERENCES: "update_preferences",
    AccountArea.CUSTOM_INSTRUCTIONS: "update_custom_instructions",
    AccountArea.VOICE: "set_selected_voice",
    AccountArea.LINKED_ACCOUNTS: "manage_linked_account",
    AccountArea.SUBSCRIPTION: "",
    AccountArea.USAGE: "",
}


def account_mutation_refusal(rel_path: str) -> str | None:
    """Refusal text for an attempted write/edit under ``account/``, else None.

    The files are projections: editing one changes nothing, so every mutation
    attempt is answered with the tool that actually performs it.
    """
    if not rel_path.startswith(f"{ACCOUNT_DIR}/"):
        return None
    area = account_area_for(rel_path) or _resolve_loose(rel_path)
    tool = AREA_MUTATION_TOOL.get(area) if area is not None else None
    if tool:
        return (
            f"Error: {rel_path} is a read-only projection of your settings — "
            f"editing it changes nothing. To change this, call the {tool} tool."
        )
    return (
        f"Error: {rel_path} is a read-only projection of the user's account "
        "and cannot be modified by editing it."
    )


def _resolve_loose(rel_path: str) -> AccountArea | None:
    """Area for account paths outside the fixed data registry (subtree files)."""
    name = rel_path.removeprefix(f"{ACCOUNT_DIR}/")
    if name.startswith(f"{ACCOUNT_VOICES_DIRNAME}/"):
        return AccountArea.VOICE
    if name.startswith(f"{ACCOUNT_LINKED_ACCOUNTS_DIRNAME}/"):
        return AccountArea.LINKED_ACCOUNTS
    return None


__all__ = [
    "ACCOUNT_DIR",
    "ACCOUNT_GUIDES_DIRNAME",
    "ACCOUNT_LINKED_ACCOUNTS_DIRNAME",
    "ACCOUNT_READ_ONLY_PATHS",
    "ACCOUNT_VOICES_DIRNAME",
    "AREA_MUTATION_TOOL",
    "AccountArea",
    "account_area_for",
    "account_mutation_refusal",
]
