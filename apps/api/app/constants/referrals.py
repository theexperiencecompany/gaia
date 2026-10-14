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
# The cookie carries "<code>.<landing variant>"; a code never contains a dot.
REFERRAL_COOKIE_VARIANT_SEPARATOR = "."

# ---- Invites -----------------------------------------------------------------

# Far above anything a person does by hand; it exists to protect the sending
# domain's reputation from a script, not to ration real users.
INVITE_DAILY_SEND_CEILING = 200
# One counter per sender per UTC day; it outlives its day so a late release still lands on it.
INVITE_QUOTA_KEY_TEMPLATE = "referral:invite-quota:{user_id}:{day}"
INVITE_QUOTA_TTL_S = 2 * 24 * 60 * 60
# Largest batch one POST /invites may carry.
INVITE_BATCH_MAX = 50
INVITE_FROM_ADDRESS = "invites@heygaia.io"
INVITE_SENDER_NAME_TEMPLATE = "{name} via GAIA"
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
# A local part with one of these as a whole word (split on - . _ +) is a team
# or company inbox: deals@, compliance-team@, aws-activate@.
ROLE_LOCAL_PART_WORDS = frozenset(
    {
        "startups",
        "deals",
        "compliance",
        "team",
        "support",
        "help",
        "hello",
        "info",
        "sales",
        "billing",
        "admin",
        "contact",
        "partners",
        "partnerships",
        "activate",
        "careers",
        "jobs",
        "press",
        "marketing",
        "accounts",
        "finance",
        "legal",
        "security",
        "community",
        "feedback",
        "invoices",
        "orders",
    }
)
LOCAL_PART_WORD_SEPARATORS = r"[-._+]"
# Gmail's send-as list: the mailbox's own address and every alias it sends from.
GMAIL_LIST_SEND_AS_TOOL = "GMAIL_LIST_SEND_AS"
SEND_AS_READ_FAILED_MESSAGE = "We couldn't read your Gmail addresses"
SEND_AS_READ_FAILED_WHY = "Gmail refused the send-as list, so your own aliases can't be left out"
# Mailing-list and group hosts: an address there is a list, not a person.
AUTOMATED_DOMAIN_MARKERS = (
    "googlegroups.com",
    "group.calendar.google.com",
    "resource.calendar.google.com",
    "lists.",
    "list.",
    "unsubscribe",
)

# A mailbox whose local part holds every word of the user's full name is another of theirs.
SELF_NAME_MIN_WORDS = 2
SELF_NAME_MIN_WORD_LENGTH = 3

# ---- Locks -------------------------------------------------------------------

# One referrer's billing date is moved by one reward at a time.
REWARD_LOCK_KEY_TEMPLATE = "referral:reward-lock:{user_id}"
REWARD_LOCK_LEASE_S = 60
REWARD_LOCK_RENEW_S = 20
REWARD_LOCK_WAIT_S = 30
# A banked batch makes two Dodo calls per month; ten minutes covers far more months than anyone banks.
REWARD_LOCK_MAX_HOLD_S = 600
REWARD_LOCK_UNAVAILABLE = (
    "could not take the referral reward lease (Redis unavailable or contended)"
)

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
