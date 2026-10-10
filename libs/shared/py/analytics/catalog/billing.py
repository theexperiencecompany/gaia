"""Billing events: checkout, payments, subscriptions, paywalls, rate limits, pricing and usage."""

from typing import ClassVar, Literal

from shared.py.analytics.catalog.base import ServerEvent, WebEvent
from shared.py.analytics.catalog.properties import CurrencyCode, Identifier, UrlPath

__all__ = [
    "CheckoutFailureReason",
    "PaymentCheckoutStarted",
    "PaymentFailed",
    "PaymentSucceeded",
    "PaywallBlocked",
    "PaywallModalViewed",
    "PaywallSource",
    "PricingPlanSelected",
    "RateLimitHit",
    "SubscriptionActivated",
    "SubscriptionCancellationRequested",
    "SubscriptionCancelled",
    "SubscriptionExpired",
    "SubscriptionFailed",
    "SubscriptionPageViewed",
    "SubscriptionPlanViewed",
    "SubscriptionRenewed",
    "UsageQueried",
]

#: Which surface put the paid-only wall on screen; every member is a call site this repo owns.
PaywallSource = Literal[
    "composer_submit",
    "voice_mode",
    "workflow_autosend",
    "workflow_activation",
    "api_402",
    "chat_stream_402",
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
    amount: float | None = None
    # Pre-tax revenue in the charge's own currency (#1332); a 0 is a real discount-code charge.
    amount_charged_pre_tax: float | None = None
    currency_charged: CurrencyCode | None = None


class SubscriptionRenewed(ServerEvent):
    """A subscription renewed for another billing period."""

    event: ClassVar[str] = "subscription:renewed"
    budget_per_user_day: ClassVar[int] = 10

    subscription_id: Identifier
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


class PaywallBlocked(ServerEvent):
    """A non-PRO caller was turned away from a paid-only surface."""

    event: ClassVar[str] = "paywall:blocked"
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
    """A user ran into a tiered rate limit."""

    event: ClassVar[str] = "rate_limit:hit"
    budget_per_user_day: ClassVar[int] = 500
    previous_names: ClassVar[tuple[str, ...]] = ("rate_limit_hit",)

    feature: Identifier
    plan: Identifier
    origin: Identifier | None = None


class PricingPlanSelected(WebEvent):
    """A user clicked a pricing card's call to action."""

    event: ClassVar[str] = "pricing:plan_selected"
    budget_per_user_day: ClassVar[int] = 20

    price: float
    is_monthly: bool
    is_current_plan: bool
    has_active_subscription: bool
    is_free_plan: bool
    plan_tier: Literal["free", "pro"]
    plan_id: Identifier | None = None


class UsageQueried(ServerEvent):
    """A user fetched their usage summary."""

    event: ClassVar[str] = "usage:queried"
    budget_per_user_day: ClassVar[int] = 10

    plan_type: Identifier
