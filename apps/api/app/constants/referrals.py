"""
Referral Program Constants.

Single source of truth for the referral program's tunable values: the points
weights, the milestone reward ladder, anti-fraud caps, the friend/referrer Dodo
discount configuration, attribution-cookie settings, and vanity-code rules.

All values that carry product meaning live here so the program can be re-tuned in
one place without hunting through service code.
"""

from typing import Final

# ---------------------------------------------------------------------------
# Points engine
# ---------------------------------------------------------------------------
# A referred friend who signs up AND activates (real product usage) earns the
# referrer a small number of points. A friend who upgrades to PRO earns far more
# — that is the event that maps to real revenue. A first renewal earns a bonus.
POINTS_PER_ACTIVATION: Final[int] = 10
POINTS_PER_UPGRADE: Final[int] = 100
POINTS_PER_RENEWAL: Final[int] = 50

# Anti-fraud: points earned purely from activations (without a paid conversion)
# are capped over a referrer's lifetime, so fake signups can never mint more than
# the very first reward. Every goal beyond the first requires real conversions.
SIGNUP_POINTS_LIFETIME_CAP: Final[int] = 150

# ---------------------------------------------------------------------------
# Milestone reward ladder (cumulative, endless)
# ---------------------------------------------------------------------------
# Each milestone is keyed by its points threshold (the stable identifier used in
# the rewards ledger to guarantee idempotency). ``reward_months`` is the number
# of free PRO months granted when the referrer crosses that threshold.
FIXED_MILESTONES: Final[tuple[dict[str, int], ...]] = (
    {"threshold": 100, "reward_months": 1},
    {"threshold": 300, "reward_months": 2},
    {"threshold": 600, "reward_months": 3},
    {"threshold": 1000, "reward_months": 6},
)
# After the last fixed milestone the ladder continues forever: every additional
# ``RECURRING_STEP_POINTS`` points grants ``RECURRING_REWARD_MONTHS`` more months.
RECURRING_STEP_POINTS: Final[int] = 500
RECURRING_REWARD_MONTHS: Final[int] = 3

# How many goals to project beyond the referrer's current points when rendering
# the (otherwise endless) ladder in the UI.
LADDER_LOOKAHEAD_GOALS: Final[int] = 2

# ---------------------------------------------------------------------------
# Reward delivery (Dodo discounts)
# ---------------------------------------------------------------------------
# Dodo discounts are percentage-only, expressed in basis points (10000 = 100%).
DODO_PERCENT_BASIS: Final[int] = 100  # 1% == 100 basis points

# Friend incentive: 50% off the first 2 billing cycles ("a $30 gift" on a $30
# plan). Generated as a unique, single-use code per friend at checkout.
FRIEND_DISCOUNT_BASIS_POINTS: Final[int] = 50 * DODO_PERCENT_BASIS  # 5000
FRIEND_DISCOUNT_CYCLES: Final[int] = 2

# Referrer reward: each earned free month is delivered as a 100%-off,
# single-cycle code. ``subscription_cycles`` equals the number of months granted.
REFERRER_REWARD_BASIS_POINTS: Final[int] = 100 * DODO_PERCENT_BASIS  # 10000

# Single-use redemption guard on every generated code.
DISCOUNT_USAGE_LIMIT: Final[int] = 1

# ---------------------------------------------------------------------------
# Clawback
# ---------------------------------------------------------------------------
# A referrer's reward is only safe once the friend's payment survives the refund
# window. A refund/chargeback inside this window reverts the conversion.
REFUND_CLAWBACK_WINDOW_DAYS: Final[int] = 14

# ---------------------------------------------------------------------------
# Attribution cookie
# ---------------------------------------------------------------------------
# Set first-party on the API origin when a friend opens an invite link, read back
# on the WorkOS signup callback. SameSite=Lax so it survives the top-level OAuth
# redirect while staying off cross-site requests.
REFERRAL_COOKIE_NAME: Final[str] = "gaia_ref"
REFERRAL_COOKIE_TTL_DAYS: Final[int] = 30
REFERRAL_COOKIE_MAX_AGE_SECONDS: Final[int] = REFERRAL_COOKIE_TTL_DAYS * 24 * 60 * 60

# ---------------------------------------------------------------------------
# Referral codes (vanity slugs)
# ---------------------------------------------------------------------------
# Auto-generated codes: a readable name slug + a short random suffix.
REFERRAL_CODE_RANDOM_SUFFIX_LENGTH: Final[int] = 4
# Unambiguous alphabet (no 0/O/1/l/i) for the random suffix.
REFERRAL_CODE_ALPHABET: Final[str] = "abcdefghjkmnpqrstuvwxyz23456789"

# Vanity-slug validation.
REFERRAL_CODE_MIN_LENGTH: Final[int] = 3
REFERRAL_CODE_MAX_LENGTH: Final[int] = 32
# Lowercase letters, digits and single hyphens (not leading/trailing).
REFERRAL_CODE_PATTERN: Final[str] = r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$"

# Slugs that would collide with app routes or enable impersonation.
RESERVED_REFERRAL_CODES: Final[frozenset[str]] = frozenset(
    {
        "admin",
        "api",
        "app",
        "auth",
        "billing",
        "blog",
        "c",
        "chat",
        "dashboard",
        "dev",
        "docs",
        "gaia",
        "help",
        "invite",
        "login",
        "logout",
        "mail",
        "me",
        "new",
        "oauth",
        "payment",
        "payments",
        "pricing",
        "pro",
        "referral",
        "referrals",
        "settings",
        "signin",
        "signup",
        "support",
        "team",
        "user",
        "workflows",
    }
)

# ---------------------------------------------------------------------------
# Email invites
# ---------------------------------------------------------------------------
MAX_INVITES_PER_REQUEST: Final[int] = 20
MAX_INVITES_PER_DAY: Final[int] = 50

# ---------------------------------------------------------------------------
# Google contacts import (invite suggestions)
# ---------------------------------------------------------------------------
# How many Google contacts to fetch from the People API in one page, and the
# upper bound on suggestions returned to populate the multi-address invite field
# after deduping. The cap keeps the response light while covering most address
# books worth suggesting from.
IMPORT_CONTACTS_PAGE_SIZE: Final[int] = 100
MAX_IMPORT_CONTACTS: Final[int] = 100

# Composio tool that reads the signed-in user's Google contacts (People API).
GMAIL_GET_CONTACTS_TOOL: Final[str] = "GMAIL_GET_CONTACTS"
