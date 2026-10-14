"""The application-wide rate limiter and the middleware that applies it."""

from collections.abc import Callable
import hmac

from fastapi import FastAPI
from fastapi.routing import APIRoute, iter_route_contexts
from slowapi import Limiter
from slowapi.middleware import SlowAPIMiddleware, _should_exempt, sync_check_limits
from slowapi.util import get_remote_address
from starlette.middleware.base import RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Match
from starlette.types import Scope

from app.config.settings import settings
from app.constants.http import VIEWER_IP_HEADER, VIEWER_IP_PROOF_HEADER
from app.db.redis import redis_cache

# Redis-backed, not slowapi's in-memory default: every replica has to count
# against the same window, or an N-replica deployment silently allows N x the
# limit and the ceiling stops meaning anything.
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["120/minute"],
    storage_uri=redis_cache.redis_url,
)


def short_link_viewer_key(request: Request) -> str:
    """Return the short-link rate-limit key: the viewer the web server names, else the peer.

    The viewer header counts only beside a proof matching SHORTLINK_VIEWER_IP_SECRET,
    so a spoofed one buys no fresh budget; the peer address is honest only because
    uvicorn takes X-Forwarded-For solely from FORWARDED_ALLOW_IPS (API Dockerfile).
    """
    secret = settings.SHORTLINK_VIEWER_IP_SECRET
    presented = request.headers.get(VIEWER_IP_PROOF_HEADER)
    viewer_ip = request.headers.get(VIEWER_IP_HEADER)
    if secret and presented and viewer_ip and hmac.compare_digest(presented, secret):
        return viewer_ip
    remote: str = get_remote_address(request)
    return remote


def find_route_handler(app: FastAPI, scope: Scope) -> Callable[..., object] | None:
    """Find the endpoint a request will reach, seeing through FastAPI's lazy routers.

    FastAPI 0.139 defers router inclusion, so app.routes holds wrappers with no
    .endpoint and slowapi's own lookup returns None for every included route —
    _should_exempt then exempts it and the default limit applies to nothing.
    Costs one extra routing scan per request.
    """
    handler = None
    for ctx in iter_route_contexts(app.routes):
        route = ctx.original_route
        if not isinstance(route, APIRoute):
            continue
        match, _ = route.matches(scope)
        if match == Match.FULL:
            handler = route.endpoint
    return handler


class RouterAwareSlowAPIMiddleware(SlowAPIMiddleware):
    """SlowAPIMiddleware with handler lookup that sees through lazy routers.

    Identical to the upstream dispatch apart from find_route_handler; the limit
    check stays sync_check_limits, which is what makes an async exception
    handler silently lose the envelope, so that handler must be sync.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        app: FastAPI = request.app
        limiter_for_app: Limiter = app.state.limiter
        if not limiter_for_app.enabled:
            return await call_next(request)

        handler = find_route_handler(app, request.scope)
        if _should_exempt(limiter_for_app, handler):
            return await call_next(request)

        limited_response, should_inject_headers = sync_check_limits(
            limiter_for_app, request, handler, app
        )
        if limited_response is not None:
            return limited_response

        response = await call_next(request)
        if should_inject_headers:
            response = limiter_for_app._inject_headers(response, request.state.view_rate_limit)
        return response
