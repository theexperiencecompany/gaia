"""Deny-by-default paid-only gate for every authenticated HTTP request.

The per-route ``@require_subscription()`` decorator this replaced was opt-in: a route was
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

#: Body of the 503 an unanswerable plan read returns. Deliberately says nothing
#: about the caller's billing state — that is the fact we failed to read.
ENTITLEMENT_UNAVAILABLE_MESSAGE = "Could not verify your subscription. Please try again."
#: Long enough to outlast a Redis restart or a Mongo failover, short enough that
#: a user who retries by hand beats it.
ENTITLEMENT_RETRY_AFTER_SECONDS = 5


class EntitlementMiddleware(BaseHTTPMiddleware):
    """402 every authenticated non-PRO request that is not explicitly free.

    A plan read that cannot be answered at all is a 503, not a 402 — see the
    ``except`` branch in ``dispatch``.
    """

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
            # Still fails CLOSED — the request never reaches its handler, so no
            # paid surface goes free — but it does NOT claim the caller is
            # unsubscribed. "We could not read your plan" and "you are not on
            # PRO" are different facts, and only the second one is a 402.
            #
            # The distinction is worth a status code because the blast radius
            # changed with this middleware: the plan read touches Redis, and on
            # a miss Mongo, on EVERY authenticated request. Answering 402 there
            # showed every paying user in the product a "GAIA is paid only"
            # modal during an infrastructure blip — indistinguishable, from
            # their side, from having been wrongly unsubscribed. 503 says the
            # true thing, and clients already retry it instead of routing the
            # user to a checkout they do not need.
            log.error(
                "Entitlement check failed — denying request (fail-closed)",
                user={"id": str(user_id)},
                payment={"operation": "paywall_gate_error", "feature": request.url.path},
                error_type=type(e).__name__,
                error=str(e),
            )
            return self._entitlement_unavailable()

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

    @staticmethod
    def _entitlement_unavailable() -> JSONResponse:
        """503 for a plan read that could not be answered at all.

        ``Retry-After`` is what makes this recoverable without a reload: the
        gate runs before ``call_next``, so nothing was executed and a retry is
        safe on every method, not just the idempotent ones.
        """
        return JSONResponse(
            status_code=503,
            content={"detail": ENTITLEMENT_UNAVAILABLE_MESSAGE},
            headers={"Retry-After": str(ENTITLEMENT_RETRY_AFTER_SECONDS)},
        )
