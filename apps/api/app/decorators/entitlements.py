"""Paywall gate: blocks non-PRO users from spend-incurring endpoints.

Distinct from ``app.decorators.rate_limiting`` — that caps HOW MUCH a plan may
use; this blocks access outright for a plan with none at all. Mirrors the
``tiered_rate_limit`` decorator / ``enforce_tiered_limit`` imperative-helper
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

    Wire contract is fixed (the frontend is built against it): the body is the
    error envelope ``{code, message, checkout_url, discount_code}``. No
    dedicated exception handler is registered for this — like
    ``RateLimitExceededException``, it rides the app's generic
    ``StarletteHTTPException`` handler, which flattens ``detail`` onto the
    envelope.

    ``checkout_url`` is always ``None``: a Dodo session is minted on user
    intent, not on refusal. See ``require_active_subscription``. The key stays
    in the body because the shipped clients parse this exact shape and already
    handle a null — the web popup mints its own on the Subscribe click, mobile
    falls back to the pricing page.
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
    """Whether ``user_id`` is on Pro — the one entitlement rule in the codebase.

    A cached PRO is trusted. A cached FREE is confirmed against the database
    once before anything is refused: the cached tier lags a payment by up to
    its TTL, and every surface that read it alone — the HTTP gate, the
    system-workflow provisioner, the device tunnel, the bot turn — turned a
    user who had just paid away for those minutes, in the provisioner's case
    for good, since nothing ever re-asked. A live subscription found here also
    drops the stale key, so the next read is right. The extra read happens
    only where the cache says FREE on a gated surface, which is bounded by the
    refusal it would otherwise produce.
    """
    if await payment_service.get_cached_plan_type(user_id) == PlanType.PRO:
        return True
    status = await payment_service.get_user_subscription_status(user_id)
    if status.plan_type != PlanType.PRO:
        return False
    await invalidate_plan_cache(user_id)
    return True


async def require_active_subscription(user_id: str, feature: str) -> None:
    """Raise ``SubscriptionRequiredException`` unless ``user_id`` is on PRO.

    ``feature`` names the surface that turned the caller away; it is required
    so every block is attributable in the funnel rather than anonymous.

    Refusing costs one cached plan read and nothing else. It used to mint a
    Dodo checkout session first, which was affordable while a handful of routes
    opted in and is not now that ``EntitlementMiddleware`` runs this on every
    authenticated request: an unpaid user's app shell fires several blocked
    calls, the web retries each twice, and every one of them was a ``get_plans``
    call, an HTTP round-trip to Dodo and a ``checkout_sessions`` insert for a
    link nobody asked for. Dodo sessions are single-use, so those are pure
    waste — and under that self-inflicted load Dodo rate-limits, which took out
    the link on the one response that needed it. Clients mint on user intent
    instead, from the allowlisted ``POST /api/v1/payments/checkout-session``.
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
