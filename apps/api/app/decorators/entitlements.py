"""Paywall gate: blocks non-PRO users from spend-incurring endpoints.

Distinct from ``app.decorators.rate_limiting`` — that caps HOW MUCH a plan may
use; this blocks access outright for a plan with none at all. Mirrors the
``tiered_rate_limit`` decorator / ``enforce_tiered_limit`` imperative-helper
split so callers that resolve their own user (bots) can still gate.
"""

from collections.abc import Awaitable, Callable
from functools import wraps
from typing import ParamSpec, TypedDict, TypeVar

from fastapi import HTTPException

from app.config.settings import settings
from app.core.request_context import resolve_caller
from app.models.payment_models import PlanType
from app.services.payments.payment_service import payment_service
from shared.py.wide_events import log

P = ParamSpec("P")
R = TypeVar("R")

PAYWALL_MESSAGE = "GAIA is a paid product. Subscribe to Pro to keep chatting."


class SubscriptionRequiredDetail(TypedDict):
    """The 402 body the web app and bots parse. Changing a key breaks them."""

    code: str
    message: str
    checkout_url: str | None
    discount_code: str | None


class SubscriptionRequiredException(HTTPException):
    """402 raised when a non-PRO user hits a paid-only surface.

    Wire contract is fixed (the frontend is built against it): ``detail`` is
    ``{code, message, checkout_url, discount_code}``. No dedicated exception
    handler is registered for this — like ``RateLimitExceededException``, it
    rides the app's generic ``StarletteHTTPException`` handler, which emits
    ``{"detail": exc.detail}`` unchanged.
    """

    def __init__(self, checkout_url: str | None) -> None:
        detail: SubscriptionRequiredDetail = {
            "code": "subscription_required",
            "message": PAYWALL_MESSAGE,
            "checkout_url": checkout_url,
            "discount_code": settings.PAYWALL_DISCOUNT_CODE,
        }
        super().__init__(status_code=402, detail=detail)


async def is_subscription_active(user_id: str) -> bool:
    """Whether ``user_id`` currently has paid chat access."""
    plan = await payment_service.get_cached_plan_type(user_id)
    return plan == PlanType.PRO


async def get_checkout_url(user_id: str) -> str | None:
    """A personal Dodo checkout link for ``user_id``, or ``None`` if Dodo is unreachable.

    A paywall response must never itself fail because the checkout provider
    is down — the block still stands, just without a one-tap link.
    """
    try:
        pro = await payment_service.create_pro_checkout(user_id)
    except Exception as e:
        log.warning(
            "Could not mint checkout link for paywall response",
            user={"id": user_id},
            payment={"operation": "paywall_checkout_link"},
            error_type=type(e).__name__,
        )
        return None
    return pro.checkout.payment_link


async def require_active_subscription(user_id: str) -> None:
    """Raise ``SubscriptionRequiredException`` unless ``user_id`` is on PRO."""
    if await is_subscription_active(user_id):
        return
    checkout_url = await get_checkout_url(user_id)
    log.warning(
        "Subscription required, blocking request",
        user={"id": user_id},
        payment={"operation": "paywall_gate"},
    )
    raise SubscriptionRequiredException(checkout_url=checkout_url)


def require_subscription() -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Endpoint decorator: 402s a non-PRO user before the handler runs.

    Resolves the caller the same way ``tiered_rate_limit`` does — from
    request-scoped auth context first, falling back to an explicit ``user``
    kwarg/arg for direct (non-HTTP) invocation. A genuinely unauthenticated
    request is left to the route's own auth dependency.
    """

    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            user = resolve_caller(args, kwargs)
            if not user:
                # Fail-open: an endpoint we can't identify a caller for is left
                # to its own auth dependency rather than 401ing here. That means
                # a genuinely paid-only route silently bypasses the paywall if
                # its caller ever fails to resolve — kept observable so that
                # bypass shows up rather than vanishing.
                log.warning(
                    "require_subscription could not resolve a caller — paywall bypassed",
                    payment={"operation": "paywall_gate_unresolved_user"},
                )
                return await func(*args, **kwargs)

            user_id = user.get("user_id")
            if not user_id:
                raise HTTPException(status_code=401, detail="User ID not found")

            await require_active_subscription(user_id)
            return await func(*args, **kwargs)

        return wrapper

    return decorator
