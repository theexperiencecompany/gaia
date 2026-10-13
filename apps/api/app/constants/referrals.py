"""Referral program constants: economics, codes, attribution, invites and suggestions."""

from datetime import timedelta
from enum import StrEnum
from string import ascii_lowercase, digits


class ReferralCopyVariant(StrEnum):
    """The copy angle a referral surface speaks in; the PostHog experiment picks one."""

    GIFT = "gift"
    EARN = "earn"
    TIME_BACK = "time_back"
    INSIDER = "insider"


class ReferralSource(StrEnum):
    """What brought a friend in: someone's invite link, or a creator's public workflow."""

    INVITE_LINK = "invite_link"
    WORKFLOW = "workflow"


class ReferralLayoutVariant(StrEnum):
    """The referral page layout the PostHog experiment picks."""

    TICKET = "ticket"
    PROGRESS = "progress"
    MINIMAL = "minimal"


# ---- Economics ---------------------------------------------------------------

# Dodo percentage discounts are in basis points: 10_000 is 100%.
BASIS_POINTS_WHOLE = 10_000

# Monthly friend gift: half off the first two monthly charges.
FRIEND_MONTHLY_DISCOUNT_BASIS_POINTS = 5_000
FRIEND_MONTHLY_INTRO_CYCLES = 2

# Yearly friend gift: one monthly price off the first yearly charge, so it is
# worth exactly what the monthly gift is (two half months).
FRIEND_YEARLY_DISCOUNT_CYCLES = 1

# Each single-use gift code is redeemable once.
GIFT_DISCOUNT_USAGE_LIMIT = 1

# What one paying friend earns the referrer.
REWARD_MONTHS_PER_FRIEND = 1

# ---- Codes and links ---------------------------------------------------------

CODE_SUFFIX_LENGTH = 4
# No 0/o/1/l, so a code read aloud or retyped survives.
CODE_SUFFIX_ALPHABET = "".join(c for c in ascii_lowercase + digits if c not in "0o1l")
CODE_NAME_MAX_LENGTH = 12
CODE_NAME_FALLBACK = "friend"
CODE_SEPARATOR = "-"
# A clash needs the same first name and suffix; a handful of draws always lands.
CODE_MINT_ATTEMPTS = 5
# Upper bound on a code a client may send: the longest one mint_code can produce.
CODE_MAX_LENGTH = CODE_NAME_MAX_LENGTH + len(CODE_SEPARATOR) + CODE_SUFFIX_LENGTH

INVITE_PATH = "/invite/"

# ---- Attribution -------------------------------------------------------------

REFERRAL_COOKIE_NAME = "gaia_ref"
ATTRIBUTION_WINDOW = timedelta(days=30)
# The cookie carries "<code>.<landing variant>.<source>"; a code never contains a dot.
REFERRAL_COOKIE_VARIANT_SEPARATOR = "."

# ---- Sent with GAIA ----------------------------------------------------------

# Appended to the HTML body of mail GAIA writes, for a user who turned it on.
SENT_WITH_GAIA_HTML = (
    '<p style="margin-top:24px;color:#71717a;font-size:12px;">'
    'Sent with <a href="{link}" style="color:#00bbff;text-decoration:none;">GAIA</a></p>'
)
# The compose hook waits this long for the user's setting and link before sending without it.
SENT_WITH_GAIA_LOOKUP_TIMEOUT_SECONDS = 5.0

# ---- Weekly stats card -------------------------------------------------------

# Monday is weekday 0: the card recaps the week that just ended.
WEEKLY_CARD_WEEKDAY = 0

# ---- Invites -----------------------------------------------------------------

# Far above anything a person does by hand; it exists to protect the sending
# domain's reputation from a script, not to ration real users.
INVITE_DAILY_SEND_CEILING = 200
# Largest batch one POST /invites may carry.
INVITE_BATCH_MAX = 50
INVITE_FROM_ADDRESS = "invites@heygaia.io"
INVITE_SENDER_TEMPLATE = "{name} via GAIA <" + INVITE_FROM_ADDRESS + ">"
INVITE_EMAIL_TEMPLATE = "referral_invite.html"
INVITE_SUBJECT_TEMPLATE = "{name} sent you a gift!"
INVITE_CTA_LABEL = "Open your gift"
INVITE_UNSUBSCRIBE_PATH = "/api/v1/referrals/unsubscribe/"
INVITE_UNSUBSCRIBE_PROMPT = "Stop getting GAIA invites from your friends?"
INVITE_PRICE_LINE = "{intro}/month for your first {cycles} months"
INVITE_REGULAR_PRICE_LINE = "{regular}/month"
# Sent from the referrer's own Gmail, so it reads like them, not like a campaign.
INVITE_GMAIL_BODY = (
    "Hey! I've been using GAIA and it's honestly made my days lighter. "
    "Here's GAIA for {price_line} 💛\n\n{link}\n\n{name}\n\n"
    "Don't want invites like this? {unsubscribe_url}"
)

# ---- Suggestions -------------------------------------------------------------

SUGGESTION_LOOKBACK = timedelta(days=90)
# A meeting bigger than this is an all-hands, not someone you know.
SUGGESTION_MAX_MEETING_SIZE = 10
SUGGESTION_LIMIT = 20
# Gmail's fetch tool returns at most this many per page.
SUGGESTION_GMAIL_PAGE_SIZE = 100
SUGGESTION_GMAIL_MAX_PAGES = 5
SUGGESTION_GMAIL_QUERY = "in:sent newer_than:{days}d"
# Local-part markers of addresses nobody reads.
AUTOMATED_LOCAL_PART_MARKERS = (
    "noreply",
    "no-reply",
    "donotreply",
    "do-not-reply",
    "notifications",
    "notification",
    "mailer-daemon",
    "postmaster",
    "bounce",
    "newsletter",
    "digest",
    "updates",
    "support",
    "billing",
    "invoice",
    "receipts",
    "calendar-notification",
)
# Mailing-list and group hosts: an address there is a list, not a person.
AUTOMATED_DOMAIN_MARKERS = (
    "googlegroups.com",
    "group.calendar.google.com",
    "resource.calendar.google.com",
    "lists.",
    "list.",
)

# ---- Locks -------------------------------------------------------------------

# One referrer's billing date is moved by one reward at a time.
REWARD_LOCK_KEY_TEMPLATE = "referral:reward-lock:{user_id}"
REWARD_LOCK_TIMEOUT_S = 60
REWARD_LOCK_WAIT_S = 30

# ---- Worker ------------------------------------------------------------------

#: Applies a resubscribed referrer's banked months; enqueued by the billing reducer.
APPLY_BANKED_MONTHS_TASK = "apply_banked_referral_months"
APPLY_BANKED_MONTHS_RETRY_DELAY = timedelta(minutes=2)

# ---- Notification copy -------------------------------------------------------

REWARD_APPLIED_TITLE = "Yay, {friend} joined! 🎉"
REWARD_APPLIED_BODY = "Your next bill moves to {date}. Enjoy the free month."
REWARD_BANKED_BODY = "Your free month is saved for whenever you're back."
REWARD_DATE_FORMAT = "%b %-d"

# ---- Errors ------------------------------------------------------------------

SUBSCRIPTION_REQUIRED_MESSAGE = "Subscribe to GAIA to get your invite link"
SUBSCRIPTION_REQUIRED_WHY = "only users with an active subscription get a referral link"
SUBSCRIPTION_REQUIRED_FIX = "Start a subscription, then come back to share GAIA"

INVITE_CEILING_MESSAGE = "You've sent a lot of invites today"
INVITE_CEILING_WHY = "the daily invite limit protects GAIA's email reputation"
INVITE_CEILING_FIX = "Try again tomorrow"

INVITE_NO_SENDER_EMAIL_MESSAGE = "Add an email address to your account to send invites"
INVITE_NO_SENDER_EMAIL_WHY = (
    "an invite replies to its sender, and this account has no email address"
)

INVITE_SEND_FAILED_MESSAGE = "We couldn't send that invite"
INVITE_SEND_FAILED_WHY = "Gmail refused the message"
INVITE_SEND_FAILED_FIX = "Reconnect Gmail in Settings, or try again"
INVITE_PROVIDER_REFUSED_WHY = "the email provider refused the message"

PRO_PLAN_MISSING_MESSAGE = "Referral offer unavailable"
PRO_PLAN_MISSING_WHY = "a Pro plan in the catalogue has no positive price to discount"
