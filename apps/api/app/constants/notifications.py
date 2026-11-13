"""Push Notification Constants."""

import re
from typing import Final

# Maximum devices a user can register for push notifications
MAX_DEVICES_PER_USER = 10

# Expo push token format: ExponentPushToken[xxx] or ExpoPushToken[xxx]
EXPO_TOKEN_PATTERN = re.compile(r"^Expo(nent)?PushToken\[[a-zA-Z0-9_-]+\]$")

# Notification channel type identifiers
CHANNEL_TYPE_INAPP: Final = "inapp"
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

# Every channel type a notification may name explicitly (the tool validates
# against this). One naming none goes in-app plus the user's preferred chat
# platform; see ``NotificationOrchestrator._default_channels``.
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

# How long a message the user sent on a platform keeps it "the one they're on":
# inside this window a proactive message follows them there instead of the order above.
PRESENCE_ACTIVE_WINDOW_SECONDS = 3 * 60 * 60

# How long the per-surface "last wrote here" stamps are kept, so the agent can
# still say "last seen on WhatsApp 6 days ago". The window above decides delivery.
PRESENCE_RETENTION_SECONDS = 30 * 24 * 60 * 60

# In-app route a notification action redirects to. Shared so the memory-backfill
# and Gmail-personalization notifications can't drift onto different pages.
MEMORY_SETTINGS_URL = "/settings/memory"
