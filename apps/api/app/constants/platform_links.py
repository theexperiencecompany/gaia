"""Constants for platform account linking (Discord, Slack, Telegram, WhatsApp, iMessage)."""

from datetime import timedelta

# How long a Photon shared-pool registration may sit unlinked before the sweep
# releases it. Registering assigns the number a seat in the project's pool, so a
# user who never texts /auth would otherwise hold that seat forever.
IMESSAGE_PENDING_REGISTRATION_TTL = timedelta(hours=24)

# The rate-limit bucket the one-tap mint endpoint spends from. The route and
# ``config/rate_limits.py`` both name it, and a limit configured under a key
# nothing spends is a limit that silently stops applying — so both sites read
# this constant rather than repeating the literal.
PLATFORM_LINK_CODE_FEATURE_KEY = "platform_link_code"

# Why a link was refused with 409, carried in the error body so a caller never
# has to infer the reason from the status. Both are conflicts the user can
# resolve, but in opposite places: one is on the platform side, the other is
# their own GAIA account. See the raise sites in ``platform_link_completion``.
LINK_CONFLICT_PLATFORM_TAKEN = "platform_account_taken"
LINK_CONFLICT_ACCOUNT_HAS_OTHER = "account_has_other_platform_account"
