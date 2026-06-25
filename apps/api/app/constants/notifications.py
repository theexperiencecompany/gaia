"""
Push Notification Constants
"""

import re

# Maximum devices a user can register for push notifications
MAX_DEVICES_PER_USER = 10

# Expo push token format: ExponentPushToken[xxx] or ExpoPushToken[xxx]
EXPO_TOKEN_PATTERN = re.compile(r"^Expo(nent)?PushToken\[[a-zA-Z0-9_-]+\]$")

# Notification channel type identifiers
CHANNEL_TYPE_INAPP = "inapp"
CHANNEL_TYPE_TELEGRAM = "telegram"
CHANNEL_TYPE_DISCORD = "discord"
CHANNEL_TYPE_WHATSAPP = "whatsapp"
CHANNEL_TYPE_SLACK = "slack"

# External channel types that are auto-injected based on platform links
EXTERNAL_NOTIFICATION_CHANNELS = (
    CHANNEL_TYPE_TELEGRAM,
    CHANNEL_TYPE_DISCORD,
    CHANNEL_TYPE_WHATSAPP,
    CHANNEL_TYPE_SLACK,
)

# All channel types that are auto-injected when no channels are explicitly specified.
# inapp is always available; telegram/discord/whatsapp/slack respect user preferences.
ALL_AUTO_INJECTED_CHANNELS = (
    CHANNEL_TYPE_INAPP,
    CHANNEL_TYPE_TELEGRAM,
    CHANNEL_TYPE_DISCORD,
    CHANNEL_TYPE_WHATSAPP,
    CHANNEL_TYPE_SLACK,
)

# Default enabled state for external channels
DEFAULT_CHANNEL_PREFERENCES: dict[str, bool] = {
    CHANNEL_TYPE_TELEGRAM: True,
    CHANNEL_TYPE_DISCORD: True,
    CHANNEL_TYPE_WHATSAPP: True,
    CHANNEL_TYPE_SLACK: True,
}

# Workflow-completion notification copy. GAIA texts like a friend on WhatsApp
# (first person, casual), not a status bar. Each entry is (title, body);
# {title} is the workflow name. One pair is picked per run so repeats don't read
# like a robot. The workflow's full result is delivered as real messages straight
# into the user's chat, so bodies can warmly point there ("in your chat") and must
# never reference a link or button (there is none).
WORKFLOW_DONE_COPY: tuple[tuple[str, str], ...] = (
    ("sorted {title} for you", "dropped it all in your chat 🙌"),
    ("{title} is done!", "everything's waiting in your chat"),
    ("just wrapped up {title}", "pulled it together and sent it over"),
    ("handled {title} for you", "had a proper look, it's all in your chat"),
)


def pick_workflow_done_copy(workflow_id: str, title: str, salt: str) -> tuple[str, str]:
    """Pick one human completion title/body, rotating per run, no RNG.

    ``salt`` (a per-run value such as a timestamp) only seeds the rotation so the
    same workflow doesn't always read identically; it is never shown to the user.
    """
    seed = sum(ord(c) for c in f"{workflow_id}{salt}")
    title_tmpl, body = WORKFLOW_DONE_COPY[seed % len(WORKFLOW_DONE_COPY)]
    return title_tmpl.format(title=title), body
