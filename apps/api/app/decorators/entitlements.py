"""Paywall gate: blocks non-PRO users from spend-incurring endpoints.

Distinct from app.decorators.rate_limiting — that caps HOW MUCH a plan may
use; this blocks access outright for a plan with none at all. Mirrors the
tiered_rate_limit decorator / enforce_tiered_limit imperative-helper
split so callers that resolve their own user (bots) can still gate.
"""

from typing import ParamSpec, TypedDict, TypeVar

from fastapi import HTTPException

from app.config.settings import settings
from app.models.payment_models import PlanType
from app.services.analytics_service import AnalyticsEvents, capture_event
from app.services.payments.payment_service import payment_service
from app.services.payments.plan_cache import invalidate_plan_cache
from shared.py.wide_events import log

P = ParamSpec("P")
R = TypeVar("R")

PAYWALL_MESSAGE = "GAIA is paid only. Subscribe to GAIA Pro to keep chatting."


class SubscriptionRequiredDetail(TypedDict):
    """The 402 body the web app and bots parse. Changing a key breaks them."""

    code: str
    message: str
    checkout_url: str | None
    discount_code: str | None


class SubscriptionRequiredException(HTTPException):
    """402 raised when a non-PRO user hits a paid-only surface.

    Wire contract is fixed (clients are built against it): the body is
    {code, message, checkout_url, discount_code}, flattened onto the envelope
    by the app's generic StarletteHTTPException handler.

    checkout_url is always None — a Dodo session is minted on user intent, not
    on refusal (see require_active_subscription); clients already handle null.
    """

    def __init__(self) -> None:
        detail: SubscriptionRequiredDetail = {
            "code": "subscription_required",
            "message": PAYWALL_MESSAGE,
            "checkout_url": None,
            "discount_code": settings.PAYWALL_DISCOUNT_CODE,
        }
        super().__init__(status_code=402, detail=detail)


async def is_paid(user_id: str) -> bool:
    """Whether user_id is on Pro — the one entitlement rule in the codebase.

    A cached PRO is trusted; a cached FREE is confirmed against the database
    once before refusing, since the cached tier can lag a payment by up to its
    TTL. A live subscription found here also drops the stale cache key.
    """
    if await payment_service.get_cached_plan_type(user_id) == PlanType.PRO:
        return True
    status = await payment_service.get_user_subscription_status(user_id)
    if status.plan_type != PlanType.PRO:
        return False
    await invalidate_plan_cache(user_id)
    return True


async def require_active_subscription(user_id: str, feature: str) -> None:
    """Raise SubscriptionRequiredException unless user_id is on PRO.

    feature names the surface that turned the caller away, for funnel
    attribution. Refusing costs one cached plan read; minting a Dodo checkout
    session here (as it used to) wasted single-use links and hit Dodo's rate
    limit under EntitlementMiddleware's volume, so clients now mint on intent.
    """
    if await is_paid(user_id):
        return
    log.warning(
        "Subscription required, blocking request",
        user={"id": user_id},
        payment={"operation": "paywall_gate", "feature": feature},
    )
    # capture_event, not capture_context_event: bot routes and worker paths
    # reach this with no authenticated request context to attribute to, and an
    # anonymous paywall block never joins the user's funnel.
    capture_event(user_id, AnalyticsEvents.PAYWALL_BLOCKED, {"feature": feature})
    raise SubscriptionRequiredException()
