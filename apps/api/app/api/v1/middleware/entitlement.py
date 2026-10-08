"""Deny-by-default paid-only gate for every authenticated HTTP request.

The per-route @require_subscription() decorator this replaced was opt-in: a route was
paywalled only if someone remembered to decorate it, and it failed *open* when
it could not resolve a caller. Every new endpoint was free until noticed. This
middleware inverts that — a route is paywalled unless it is named in
entitlement_allowlist.FREE_PATH_PREFIXES.

Runs immediately inside WorkOSAuthMiddleware so request.state.user is
already resolved (see app.core.middleware.configure_middleware for the
ordering, which is load-bearing). Unauthenticated requests pass straight
through: auth is the route's own job, and 402ing an anonymous caller would tell
the world which paths exist.
"""

from collections.abc import Awaitable, Callable
from functools import cache
import re

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import iter_route_contexts
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.routing import compile_path
from starlette.types import ASGIApp

from app.api.v1.middleware.auth import get_current_user
from app.api.v1.middleware.entitlement_allowlist import is_free_path
from app.constants.http import RETRY_AFTER_HEADER
from app.decorators.entitlements import (
    SubscriptionRequiredException,
    require_active_subscription,
)
from app.schemas.errors import ErrorEnvelope, error_response
from shared.py.wide_events import log

#: Body of the 503 an unanswerable plan read returns. Deliberately says nothing
#: about the caller's billing state — that is the fact we failed to read.
ENTITLEMENT_UNAVAILABLE_MESSAGE = "Could not verify your subscription. Please try again."
#: Long enough to outlast a Redis restart or a Mongo failover, short enough that
#: a user who retries by hand beats it.
ENTITLEMENT_RETRY_AFTER_SECONDS = 5


#: The paywall feature for a path no route serves; the request 404s once it is let through.
UNMATCHED_ROUTE = "unmatched_route"


@cache
def _route_patterns(app: ASGIApp) -> tuple[tuple[re.Pattern[str], str], ...]:
    """Compile every route's full path once per app, in the router's match order."""
    routes = getattr(app, "routes", ())
    return tuple((compile_path(ctx.path)[0], ctx.path) for ctx in iter_route_contexts(routes))


def gated_route(request: Request) -> str:
    """Name the gated surface by its route template, so no id or email in the raw path reaches analytics."""
    path = request.url.path
    for pattern, template in _route_patterns(request.app):
        if pattern.match(path):
            return template
    return UNMATCHED_ROUTE


class EntitlementMiddleware(BaseHTTPMiddleware):
    """402 every authenticated non-PRO request that is not explicitly free.

    A plan read that cannot be answered at all is a 503, not a 402 — see the
    except branch in dispatch.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # CORS preflight carries no credentials and is answered by CORSMiddleware, which
        # sits *inside* this one — blocking it here breaks cross-origin calls with an
        # opaque CORS failure rather than a readable 402.
        if request.method == "OPTIONS":
            return await call_next(request)

        if is_free_path(request.url.path):
            return await call_next(request)

        user = get_current_user(request)
        user_id = user.user_id if user else None
        if not user_id:
            return await call_next(request)

        try:
            await require_active_subscription(user_id, feature=gated_route(request))
        except SubscriptionRequiredException as exc:
            return self._payment_required(exc)
        except Exception as e:
            # Still fails CLOSED (no paid surface goes free) but does not claim the caller
            # is unsubscribed: "could not read your plan" and "not on PRO" are different
            # facts, and answering 402 here showed every paying user a paywall during a Redis/Mongo blip — clients already retry a 503 instead of routing to an unneeded checkout.
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
        code == "subscription_required"; rendering the same envelope the
        generic handler does keeps that contract byte-identical whether a 402
        comes from here or from an imperative in-handler gate.
        """
        return error_response(exc.status_code, ErrorEnvelope.from_http_exception(exc))

    @staticmethod
    def _entitlement_unavailable() -> JSONResponse:
        """503 for a plan read that could not be answered at all.

        Retry-After is what makes this recoverable without a reload: the
        gate runs before call_next, so nothing was executed and a retry is
        safe on every method, not just the idempotent ones.
        """
        return error_response(
            503,
            ErrorEnvelope(message=ENTITLEMENT_UNAVAILABLE_MESSAGE, code="entitlement_unavailable"),
            headers={RETRY_AFTER_HEADER: str(ENTITLEMENT_RETRY_AFTER_SECONDS)},
        )
