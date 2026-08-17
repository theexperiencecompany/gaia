"""Constants for platform account linking (Discord, Slack, Telegram, WhatsApp, iMessage)."""

from datetime import timedelta

# How long a Photon shared-pool registration may sit unlinked before the sweep
# releases it. Registering assigns the number a seat in the project's pool, so a
# user who never texts /auth would otherwise hold that seat forever.
IMESSAGE_PENDING_REGISTRATION_TTL = timedelta(hours=24)
