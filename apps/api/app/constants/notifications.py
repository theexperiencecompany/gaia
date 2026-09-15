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
CHANNEL_TYPE_IMESSAGE = "imessage"
CHANNEL_TYPE_EMAIL = "email"

# External channel types a notification can be delivered on
EXTERNAL_NOTIFICATION_CHANNELS = (
    CHANNEL_TYPE_TELEGRAM,
    CHANNEL_TYPE_DISCORD,
    CHANNEL_TYPE_WHATSAPP,
    CHANNEL_TYPE_SLACK,
    CHANNEL_TYPE_IMESSAGE,
)

# inapp is always available; the external platforms respect user preferences.
#: Every channel type a notification may name explicitly (the tool validates
#: against this). A notification that names none goes in-app plus the user's
#: preferred chat platform; see ``NotificationOrchestrator._default_channels``.
NOTIFICATION_CHANNEL_TYPES = (
    CHANNEL_TYPE_INAPP,
    CHANNEL_TYPE_TELEGRAM,
    CHANNEL_TYPE_DISCORD,
    CHANNEL_TYPE_WHATSAPP,
    CHANNEL_TYPE_SLACK,
    CHANNEL_TYPE_IMESSAGE,
)

# Default enabled state for external channels
DEFAULT_CHANNEL_PREFERENCES: dict[str, bool] = {
    CHANNEL_TYPE_TELEGRAM: True,
    CHANNEL_TYPE_DISCORD: True,
    CHANNEL_TYPE_WHATSAPP: True,
    CHANNEL_TYPE_SLACK: True,
    CHANNEL_TYPE_IMESSAGE: True,
    CHANNEL_TYPE_EMAIL: True,
}

# Default order in which a proactive message picks its ONE chat platform. It
# lands on the first platform in this list that the user has linked and enabled,
# never on every linked platform (``users.chat_channel_priority`` overrides it).
DEFAULT_CHAT_CHANNEL_PRIORITY: tuple[str, ...] = (
    CHANNEL_TYPE_TELEGRAM,
    CHANNEL_TYPE_WHATSAPP,
    CHANNEL_TYPE_SLACK,
    CHANNEL_TYPE_DISCORD,
)

# In-app route a notification action redirects to. Shared so the memory-backfill
# and Gmail-personalization notifications can't drift onto different pages.
MEMORY_SETTINGS_URL = "/settings/memory"

# Workflow-completion notification copy. GAIA texts like a friend (first person,
# casual), not a status bar. Each entry is (title, body); {title} is the workflow
# name. One pair is picked per run so repeats don't read like a robot. This is the
# in-app (web) heads-up and it carries a "View Results" button, so bodies stay warm
# and channel-agnostic: they never claim a specific place ("in your chat"), since a
# web user has no external chat and reaches the result through the button.
WORKFLOW_DONE_COPY: tuple[tuple[str, str], ...] = (
    ("sorted {title} for you", "it's all ready whenever you are 🙌"),
    ("{title} is done", "had a proper look — everything's ready for you"),
    ("just wrapped up {title}", "pulled it all together, take a peek"),
    ("handled {title} for you", "all done end to end, give it a look"),
    ("finished {title}", "got everything ready for you to check out"),
    ("{title}: all set", "took care of it, here's what I found"),
)


def pick_workflow_done_copy(workflow_id: str, title: str, salt: str) -> tuple[str, str]:
    """Pick one human completion title/body, rotating per run, no RNG.

    ``salt`` (a per-run value such as a timestamp) only seeds the rotation so the
    same workflow doesn't always read identically; it is never shown to the user.
    """
    seed = sum(ord(c) for c in f"{workflow_id}{salt}")
    title_tmpl, body = WORKFLOW_DONE_COPY[seed % len(WORKFLOW_DONE_COPY)]
    return title_tmpl.format(title=title), body
