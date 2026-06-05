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
# {title} is the workflow name and {time} the local completion time. One pair
# is picked per run so repeats don't read like a robot.
# Bodies stay action-agnostic on purpose: the result is delivered inline on
# external channels (WhatsApp/Telegram) and behind "View Results" in-app, so
# copy must never promise a specific gesture like "tap" or "come look".
WORKFLOW_DONE_COPY: tuple[tuple[str, str], ...] = (
    ("just wrapped up {title} 🙌", "all done at {time}"),
    ("ok, {title} is done!", "finished at {time}, all yours"),
    ("just finished {title} 🎉", "wrapped it up at {time}"),
    ("sorted {title} for you", "all good as of {time}"),
)


def pick_workflow_done_copy(workflow_id: str, title: str, time_str: str) -> tuple[str, str]:
    """Pick one human completion title/body, varied per run, no RNG.

    Keyed off workflow_id + time so the same workflow doesn't always read the
    same and successive runs rotate naturally.
    """
    seed = sum(ord(c) for c in f"{workflow_id}{time_str}")
    title_tmpl, body_tmpl = WORKFLOW_DONE_COPY[seed % len(WORKFLOW_DONE_COPY)]
    return title_tmpl.format(title=title), body_tmpl.format(time=time_str)
