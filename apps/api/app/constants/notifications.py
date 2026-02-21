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
CHANNEL_TYPE_EMAIL = "email"
CHANNEL_TYPE_TELEGRAM = "telegram"
CHANNEL_TYPE_DISCORD = "discord"

# External channel types that are auto-injected based on platform links
EXTERNAL_NOTIFICATION_CHANNELS = (CHANNEL_TYPE_TELEGRAM, CHANNEL_TYPE_DISCORD)

# Default enabled state for external channels
DEFAULT_CHANNEL_PREFERENCES: dict[str, bool] = {
    CHANNEL_TYPE_TELEGRAM: True,
    CHANNEL_TYPE_DISCORD: True,
}

# External API base URLs
DISCORD_API_BASE = "https://discord.com/api/v10"
TELEGRAM_BOT_API_BASE = "https://api.telegram.org/bot"
