"""Billing events: checkout, payments, subscriptions, paywalls, rate limits, pricing and usage."""

from datetime import timedelta
from typing import ClassVar, Literal

from shared.py.analytics.catalog.base import ServerEvent, WebEvent
from shared.py.analytics.catalog.properties import CurrencyCode, Identifier, UrlPath

__all__ = [
    "CheckoutFailureReason",
    "PaymentCheckoutAbandoned",
    "PaymentCheckoutStarted",
    "PaymentFailed",
    "PaymentSucceeded",
    "PaywallBlocked",
    "PaywallModalViewed",
    "LimitWindow",
    "PaywallSource",
    "RateLimitHit",
    "SubscriptionActivated",
    "SubscriptionCancellationRequested",
    "SubscriptionCancelled",
    "SubscriptionExpired",
    "SubscriptionFailed",
    "SubscriptionLapsed",
    "SubscriptionPageViewed",
    "SubscriptionPlanViewed",
    "SubscriptionRenewed",
    "UsageQueried",
]

#: Which limit refused the request: a cost budget's day or month, one request's token
#: ceiling, or the bots' per-sender burst limit. None is a count limit on a feature.
LimitWindow = Literal["day", "month", "request", "burst"]

#: Which surface put the paid-only wall on screen; every member is a call site this repo owns.
PaywallSource = Literal[
    "composer_submit",
    "voice_mode",
    "workflow_autosend",
    "workflow_activation",
    "api_402",
    "composer_notice",
    "rate_limit_card",
    "rate_limit_toast",
    "founder_letter",
    "sidebar",
    "settings_menu",
    "settings_subscription",
    "settings_upsell",
    "settings_linked_accounts",
    "settings_usage",
    # Not a surface: the desktop feed window mirroring a wall whose snapshot lost its source.
    "desktop_popup_mirror",
]

CheckoutFailureReason = Literal["declined", "confirmation_timeout", "verification_error"]


class PaymentCheckoutStarted(ServerEvent):
    """A user started a Dodo checkout, by redirect or the embedded overlay."""

    event: ClassVar[str] = "payment:checkout_started"
    budget_per_user_day: ClassVar[int] = 20

    checkout_flow: Literal["redirect", "overlay"]
    quantity: int | None = None
    source: Identifier | None = None
    billing_cycle: Identifier | None = None
    # The Dodo product id of the plan being bought; replaces the client's pricing:plan_selected.
    plan_id: Identifier | None = None


class PaymentCheckoutAbandoned(WebEvent):
    """The embedded checkout closed without a charge; only the browser sees the sheet go away."""

    event: ClassVar[str] = "payment:checkout_abandoned"
    budget_per_user_day: ClassVar[int] = 20

    source: Literal[
        "paywall_modal", "pricing_card", "payment_retry", "checkout_resume", "onboarding"
    ]
    billing_cycle: Literal["monthly", "yearly"]
    # The last overlay step reached; "not_loaded" means the sheet never rendered and was closed for the user.
    furthest_step: Literal[
        "not_loaded", "opened", "details_submitted", "payment_page", "pay_pressed"
    ]


class PaymentSucceeded(ServerEvent):
    """Dodo reported a successful payment for a GAIA user."""

    event: ClassVar[str] = "payment:succeeded"
    budget_per_user_day: ClassVar[int] = 10

    payment_id: Identifier
    currency: CurrencyCode
    amount: float | None = None
    # Pre-tax revenue in the charge's own currency (#1332); a 0 is a real discount-code charge.
    amount_charged_pre_tax: float | None = None
    currency_charged: CurrencyCode | None = None
    # Pre-tax USD that reached GAIA, sent only when Dodo settles in USD (#1332).
    amount_usd_pre_tax: float | None = None


class PaymentFailed(ServerEvent):
    """Dodo reported a failed payment for a GAIA user."""

    event: ClassVar[str] = "payment:failed"
    budget_per_user_day: ClassVar[int] = 10

    payment_id: Identifier
    currency: CurrencyCode
    amount: float | None = None
    # Pre-tax revenue in the charge's own currency (#1332); a 0 is a real discount-code charge.
    amount_charged_pre_tax: float | None = None
    currency_charged: CurrencyCode | None = None
    # Pre-tax USD that reached GAIA, sent only when Dodo settles in USD (#1332).
    amount_usd_pre_tax: float | None = None


class SubscriptionCancellationRequested(ServerEvent):
    """A user asked to cancel their subscription at the end of the billing period."""

    event: ClassVar[str] = "subscription:cancellation_requested"
    budget_per_user_day: ClassVar[int] = 10


class SubscriptionActivated(ServerEvent):
    """A subscription became active."""

    event: ClassVar[str] = "subscription:activated"
    budget_per_user_day: ClassVar[int] = 10

    subscription_id: Identifier
    plan_name: Literal["Pro"]
    currency: CurrencyCode
    # Dodo's product and interval ("Month", "Year"); absent on a backfill, whose row knows only the current plan.
    product_id: Identifier | None = None
    billing_interval: Identifier | None = None
    amount: float | None = None
    # Pre-tax revenue in the charge's own currency (#1332); a 0 is a real discount-code charge.
    amount_charged_pre_tax: float | None = None
    currency_charged: CurrencyCode | None = None
    # True on an event a backfill sent at its record's own time; new-subscriber tiles exclude it.
    backfilled: bool | None = None


class SubscriptionRenewed(ServerEvent):
    """A subscription renewed for another billing period."""

    event: ClassVar[str] = "subscription:renewed"
    budget_per_user_day: ClassVar[int] = 10

    subscription_id: Identifier
    product_id: Identifier
    billing_interval: Identifier
    currency: CurrencyCode
    # Pre-tax revenue in the charge's own currency (#1332); a 0 is a real discount-code charge.
    amount_charged_pre_tax: float | None = None
    currency_charged: CurrencyCode | None = None


class SubscriptionCancelled(ServerEvent):
    """A subscription was cancelled, now or at the next billing date."""

    event: ClassVar[str] = "subscription:cancelled"
    budget_per_user_day: ClassVar[int] = 10

    subscription_id: Identifier
    product_id: Identifier
    billing_interval: Identifier


class SubscriptionExpired(ServerEvent):
    """A subscription expired and the user fell back to the free plan."""

    event: ClassVar[str] = "subscription:expired"
    budget_per_user_day: ClassVar[int] = 50

    subscription_id: Identifier
    product_id: Identifier
    billing_interval: Identifier


class SubscriptionLapsed(ServerEvent):
    """A subscription's renewal failed or Dodo put it on hold, so the user lost Pro."""

    event: ClassVar[str] = "subscription:lapsed"
    budget_per_user_day: ClassVar[int] = 50

    subscription_id: Identifier
    status: Literal["failed", "on_hold"]
    product_id: Identifier
    billing_interval: Identifier


class SubscriptionPageViewed(WebEvent):
    """The landing pricing page was viewed."""

    event: ClassVar[str] = "subscription:page_viewed"
    budget_per_user_day: ClassVar[int] = 10

    source: Literal["landing_pricing"]


class SubscriptionPlanViewed(WebEvent):
    """A pricing card rendered, on the pricing page or the onboarding payment stage."""

    event: ClassVar[str] = "subscription:plan_viewed"
    budget_per_user_day: ClassVar[int] = 50

    price: float
    is_monthly: bool
    plan_id: Identifier | None = None
    source: Identifier | None = None


class SubscriptionFailed(WebEvent):
    """A checkout returned without a subscription; a declined charge or lost webhook reaches no server."""

    event: ClassVar[str] = "subscription:failed"
    budget_per_user_day: ClassVar[int] = 10

    source: Literal["onboarding", "payment_success_page"]
    reason: CheckoutFailureReason


#: One paywall:blocked per user and feature per window: a page load hits ~5 gated routes and a reload repeats them.
PAYWALL_BLOCKED_WINDOW = timedelta(hours=1)


class PaywallBlocked(ServerEvent):
    """A non-PRO caller was turned away from a paid-only surface, once per feature per window."""

    event: ClassVar[str] = "paywall:blocked"
    at_most_once_ttl: ClassVar[timedelta | None] = PAYWALL_BLOCKED_WINDOW
    budget_per_user_day: ClassVar[int] = 500

    feature: UrlPath | Identifier


class PaywallModalViewed(WebEvent):
    """The paid-only wall rendered; the server sees the 402, only the browser sees the modal."""

    event: ClassVar[str] = "paywall:modal_viewed"
    budget_per_user_day: ClassVar[int] = 10

    dismissible: bool
    has_discount_code: bool
    source: PaywallSource | None = None


class RateLimitHit(ServerEvent):
    """A request was refused by a usage limit: a feature count, a cost budget or a burst limit."""

    event: ClassVar[str] = "rate_limit:hit"
    budget_per_user_day: ClassVar[int] = 500
    previous_names: ClassVar[tuple[str, ...]] = ("rate_limit_hit",)

    feature: Identifier
    #: None only where the refusal comes before the sender is resolved to a user (bot burst limit).
    plan: Identifier | None
    origin: Identifier | None = None
    window: LimitWindow | None = None


class UsageQueried(ServerEvent):
    """A user fetched their usage summary."""

    event: ClassVar[str] = "usage:queried"
    budget_per_user_day: ClassVar[int] = 10

    plan_type: Identifier
