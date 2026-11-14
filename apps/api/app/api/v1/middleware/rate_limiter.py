"""The application-wide rate limiter and the middleware that applies it.

Every request counts against the ceiling of whoever made it: a signed-in user
by user id, GAIA's web server by the address presenting INTERNAL_API_TOKEN
(plus the viewer it names), and anyone else by address. The token only picks
the bucket; authentication never reads it.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
import inspect
import ipaddress
import secrets

from fastapi import FastAPI
from fastapi.routing import APIRoute, iter_route_contexts
from limits import RateLimitItem, RateLimitItemPerMinute
from limits.errors import StorageError
from limits.storage import MemoryStorage
from limits.strategies import FixedWindowRateLimiter, RateLimiter
from redis.exceptions import RedisError
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from slowapi.wrappers import Limit
from starlette.middleware.base import RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Match
from starlette.types import Scope

from app.config.settings import settings
from app.constants.http import INTERNAL_CALLER_HEADER, VIEWER_IP_HEADER
from app.constants.request_limits import (
    ANONYMOUS_VIEWER_PER_MINUTE,
    INTERNAL_SOURCE_PER_MINUTE,
    SIGNED_IN_USER_PER_MINUTE,
)
from app.db.redis import redis_cache
from app.models.user_models import AuthenticatedUser
from shared.py.wide_events import log


class RequestBucket(StrEnum):
    """Whose ceiling a request counts against."""

    SIGNED_IN_USER = "signed_in_user"
    ANONYMOUS_VIEWER = "anonymous_viewer"
    INTERNAL_SOURCE = "internal_source"


BUCKET_LIMITS: dict[RequestBucket, RateLimitItem] = {
    RequestBucket.SIGNED_IN_USER: RateLimitItemPerMinute(SIGNED_IN_USER_PER_MINUTE),
    RequestBucket.ANONYMOUS_VIEWER: RateLimitItemPerMinute(ANONYMOUS_VIEWER_PER_MINUTE),
    RequestBucket.INTERNAL_SOURCE: RateLimitItemPerMinute(INTERNAL_SOURCE_PER_MINUTE),
}

# Keys every bucket's counters apart from the per-route limits slowapi decorators keep.
_GLOBAL_SCOPE = "global"


@dataclass(frozen=True, slots=True)
class BucketCharge:
    """One counter a request spends from: the bucket and the caller within it."""

    bucket: RequestBucket
    key: str


def carries_internal_token(request: Request) -> bool:
    """Whether the request presents INTERNAL_API_TOKEN, or the one being rotated out (constant-time)."""
    presented = request.headers.get(INTERNAL_CALLER_HEADER)
    if presented is None:
        return False
    accepted = (settings.INTERNAL_API_TOKEN, settings.INTERNAL_API_TOKEN_PREVIOUS)
    # Every accepted value is compared, so the time taken says nothing about which matched.
    matches = [secrets.compare_digest(presented.encode(), t.encode()) for t in accepted if t]
    return any(matches)


def _named_viewer(request: Request) -> str | None:
    try:
        return str(ipaddress.ip_address(request.headers.get(VIEWER_IP_HEADER, "").strip()))
    except ValueError:
        return None


def viewer_ip(request: Request) -> str:
    """Return the address a request is made for: the viewer GAIA's web server names, else the peer."""
    peer: str = get_remote_address(request)
    if not carries_internal_token(request):
        return peer
    return _named_viewer(request) or peer


def request_charges(request: Request) -> list[BucketCharge]:
    """Return every counter this request spends from; empty for a verified bot.

    A token-bearing request always spends from its source's ceiling, so a leaked
    token rotating viewer addresses stays bounded by INTERNAL_SOURCE_PER_MINUTE.
    """
    if getattr(request.state, "bot_api_key_valid", False):
        return []
    peer: str = get_remote_address(request)
    charges: list[BucketCharge] = []
    internal = carries_internal_token(request)
    if internal:
        charges.append(BucketCharge(RequestBucket.INTERNAL_SOURCE, peer))
    user = getattr(request.state, "user", None)
    if isinstance(user, AuthenticatedUser) and user.user_id:
        charges.append(BucketCharge(RequestBucket.SIGNED_IN_USER, user.user_id))
        return charges
    viewer = _named_viewer(request) if internal else peer
    if viewer is not None:
        charges.append(BucketCharge(RequestBucket.ANONYMOUS_VIEWER, viewer))
    return charges


def build_limiter(storage_uri: str) -> Limiter:
    """Build the limiter: per-route decorator limits, keyed on viewer_ip, against storage_uri."""
    # Without the fallback, slowapi hands a storage ConnectionError to its 429
    # handler, which crashes on exc.detail; with it, each replica counts in
    # memory until the storage answers a ping again.
    return Limiter(key_func=viewer_ip, storage_uri=storage_uri, in_memory_fallback_enabled=True)


# Redis-backed, not slowapi's in-memory default: every replica has to count
# against the same window, or an N-replica deployment silently allows N x the
# limit and the ceiling stops meaning anything.
limiter = build_limiter(redis_cache.redis_url)

# Counts per replica while the shared storage is unreachable, as the decorator limits do.
_FALLBACK_STRATEGY = FixedWindowRateLimiter(MemoryStorage())


def find_route_handler(app: FastAPI, scope: Scope) -> Callable[..., object] | None:
    """Find the endpoint a request will reach, seeing through FastAPI's lazy routers.

    A route context matches on its effective path, so a prefix given at
    include_router time (every router sits under /api/v1) is part of the match.
    """
    for ctx in iter_route_contexts(app.routes):
        if not isinstance(ctx.original_route, APIRoute):
            continue
        match, _ = ctx.matches(scope)
        if match == Match.FULL:
            # The first full match is the route Starlette dispatches to (/explore before /{id}).
            endpoint: Callable[..., object] | None = ctx.endpoint
            return endpoint
    return None


def _hit(strategy: RateLimiter, charge: BucketCharge) -> bool:
    return strategy.hit(BUCKET_LIMITS[charge.bucket], _GLOBAL_SCOPE, charge.bucket, charge.key)


def _spend(limiter_for_app: Limiter, charge: BucketCharge) -> bool:
    """Spend one request from charge's counter; False once it is exhausted."""
    try:
        return _hit(limiter_for_app.limiter, charge)
    except (StorageError, RedisError) as exc:
        log.warning("rate_limit.storage_unreachable", error_type=type(exc).__name__)
        return _hit(_FALLBACK_STRATEGY, charge)


# Operational probes: a Prometheus scrape and an orchestrator's liveness check
# are not user traffic, and counting them means a dead counter storage takes
# monitoring down exactly when it is needed. Matched before the limiter runs.
_PROBE_PATHS = frozenset({"/health", "/metrics"})


class RouterAwareSlowAPIMiddleware(SlowAPIMiddleware):
    """Charge each routed request to its caller's bucket; refuse it once one is exhausted.

    The refusal goes through the app's sync RateLimitExceeded handler, which
    renders the envelope with a real Retry-After.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Count this request against its caller's ceilings, then hand it to the route."""
        if request.url.path in _PROBE_PATHS:
            return await call_next(request)

        app: FastAPI = request.app
        limiter_for_app: Limiter = app.state.limiter
        if not limiter_for_app.enabled:
            return await call_next(request)

        # An unrouted path is a 404 with no route to limit; per-route decorator limits apply on top.
        if find_route_handler(app, request.scope) is None:
            return await call_next(request)

        for charge in request_charges(request):
            if _spend(limiter_for_app, charge):
                continue
            window = BUCKET_LIMITS[charge.bucket]
            request.state.view_rate_limit = (window, [_GLOBAL_SCOPE, charge.bucket, charge.key])
            log.set(rate_limit={"bucket": charge.bucket.value})
            refuse = app.exception_handlers[RateLimitExceeded]
            limit = Limit(window, viewer_ip, _GLOBAL_SCOPE, False, None, None, None, 1, False)
            refused = refuse(request, RateLimitExceeded(limit))
            return await refused if inspect.isawaitable(refused) else refused
        return await call_next(request)
