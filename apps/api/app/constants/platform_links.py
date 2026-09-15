"""Constants for platform account linking (Discord, Slack, Telegram, WhatsApp, iMessage)."""

from datetime import timedelta

# How long a Photon shared-pool registration may sit unlinked before the sweep
# releases it. Registering assigns the number a seat in the project's pool, so a
# user who never texts /auth would otherwise hold that seat forever.
IMESSAGE_PENDING_REGISTRATION_TTL = timedelta(hours=24)

# The rate-limit bucket the one-tap mint endpoint spends from; the route and
# config/rate_limits.py both read this constant rather than repeating the
# literal, since a key nothing spends from silently stops applying.
PLATFORM_LINK_CODE_FEATURE_KEY = "platform_link_code"

# Why a link was refused with 409, carried in the error body. Both are
# resolvable conflicts but in opposite places: one on the platform side, the
# other on the user's own GAIA account (see platform_link_completion).
LINK_CONFLICT_PLATFORM_TAKEN = "platform_account_taken"
LINK_CONFLICT_ACCOUNT_HAS_OTHER = "account_has_other_platform_account"
