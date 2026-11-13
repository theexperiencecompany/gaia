"""Push Notification Constants."""

import re

from shared.py.voice_call import CALL_HEARTBEAT_SECONDS

# Maximum devices a user can register for push notifications
MAX_DEVICES_PER_USER = 10

# Expo push token format: ExponentPushToken[xxx] or ExpoPushToken[xxx]
EXPO_TOKEN_PATTERN = re.compile(r"^Expo(nent)?PushToken\[[a-zA-Z0-9_-]+\]$")

CHANNEL_TYPE_TELEGRAM = "telegram"
CHANNEL_TYPE_DISCORD = "discord"
CHANNEL_TYPE_WHATSAPP = "whatsapp"
CHANNEL_TYPE_SLACK = "slack"
CHANNEL_TYPE_IMESSAGE = "imessage"
CHANNEL_TYPE_EMAIL = "email"

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

# A live call is renewed by the voice worker's heartbeat; a worker that died without
# ending the call stops being "in a call" after two missed beats.
CALL_PRESENCE_TTL_SECONDS = 2 * CALL_HEARTBEAT_SECONDS + 30

# How often a GAIA app that is visible, focused and in use tells the API so (the web client's own
# constant names the same number). One missed beat is forgiven; a client that went quiet is not looked at.
FOCUS_HEARTBEAT_SECONDS = 60
FOCUS_PRESENCE_TTL_SECONDS = 2 * FOCUS_HEARTBEAT_SECONDS + 30
