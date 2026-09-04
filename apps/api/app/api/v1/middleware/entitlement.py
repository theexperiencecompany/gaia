"""Deny-by-default paid-only gate for every authenticated HTTP request.

The ``@require_subscription()`` decorator this replaces was opt-in: a route was
paywalled only if someone remembered to decorate it, and it failed *open* when
it could not resolve a caller. Every new endpoint was free until noticed. This
middleware inverts that — a route is paywalled unless it is named in
``entitlement_allowlist.FREE_PATH_PREFIXES``.

Runs immediately inside ``WorkOSAuthMiddleware`` so ``request.state.user`` is
already resolved (see ``app.core.middleware.configure_middleware`` for the
ordering, which is load-bearing). Unauthenticated requests pass straight
through: auth is the route's own job, and 402ing an anonymous caller would tell
the world which paths exist.
"""

from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.v1.middleware.entitlement_allowlist import is_free_path
from app.decorators.entitlements import (
    SubscriptionRequiredException,
    require_active_subscription,
)
from shared.py.wide_events import log


class EntitlementMiddleware(BaseHTTPMiddleware):
    """402 every authenticated non-PRO request that is not explicitly free."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # CORS preflight carries no credentials and is answered by
        # CORSMiddleware, which sits *inside* this one. Blocking it here would
        # break every cross-origin call with an opaque CORS failure rather than
        # a readable 402.
        if request.method == "OPTIONS":
            return await call_next(request)

        if is_free_path(request.url.path):
            return await call_next(request)

        user = getattr(request.state, "user", None)
        user_id = user.get("user_id") if user else None
        if not user_id:
            return await call_next(request)

        try:
            await require_active_subscription(str(user_id), feature=request.url.path)
        except SubscriptionRequiredException as exc:
            return self._payment_required(exc)
        except Exception as e:
            # Fail CLOSED. The decorator's fail-open branch is precisely how a
            # paid surface went free without anyone noticing: a Redis blip or a
            # Mongo timeout turned the paywall off. A 402 for a Pro user during
            # an outage is recoverable; a free tier for everyone is not.
            log.error(
                "Entitlement check failed — denying request (fail-closed)",
                user={"id": str(user_id)},
                payment={"operation": "paywall_gate_error", "feature": request.url.path},
                error_type=type(e).__name__,
                error=str(e),
            )
            return self._payment_required(SubscriptionRequiredException(checkout_url=None))

        return await call_next(request)

    @staticmethod
    def _payment_required(exc: SubscriptionRequiredException) -> JSONResponse:
        """Render the exact body the app's HTTPException handler would emit.

        The web's axios interceptor and the chat-stream client both match on
        ``detail.code == "subscription_required"``; wrapping ``detail`` the same
        way the generic handler does keeps that contract byte-identical whether
        a 402 comes from here or from an imperative in-handler gate.
        """
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
