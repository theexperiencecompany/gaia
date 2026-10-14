"""The default rate limit has to reach routes that live behind a lazy router.

FastAPI 0.139 defers router inclusion, so app.routes holds wrappers with no
.endpoint: slowapi's own handler lookup returned None for every included route
and _should_exempt then exempted it — the default limit applied to nothing.
"""

from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
import pytest
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.api.v1.middleware.rate_limiter import (
    RouterAwareSlowAPIMiddleware,
    find_route_handler,
)
from app.core.middleware import rate_limit_handler

pytestmark = pytest.mark.unit


class _Payload(BaseModel):
    count: int


def _app(
    limit: str = "1/minute",
    *,
    enabled: bool = True,
    key_style: str = "url",
    headers_enabled: bool = False,
) -> FastAPI:
    app = FastAPI()
    app.add_middleware(RouterAwareSlowAPIMiddleware)
    app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
    app.state.limiter = Limiter(
        key_func=get_remote_address,
        default_limits=[limit],
        storage_uri="memory://",
        enabled=enabled,
        key_style=key_style,
        headers_enabled=headers_enabled,
    )

    router = APIRouter(prefix="/included")

    @router.get("/thing")
    async def thing() -> _Payload:
        return _Payload(count=1)

    app.include_router(router)
    return app


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    )


def test_the_handler_of_an_included_route_is_found() -> None:
    app = _app()
    scope = {"type": "http", "path": "/included/thing", "method": "GET", "headers": []}

    handler = find_route_handler(app, scope)

    assert handler is not None
    assert handler.__name__ == "thing"


def test_an_unmatched_path_has_no_handler() -> None:
    assert (
        find_route_handler(
            _app(), {"type": "http", "path": "/nope", "method": "GET", "headers": []}
        )
        is None
    )


async def test_the_default_limit_applies_to_an_included_route() -> None:
    async with _client(_app()) as client:
        assert (await client.get("/included/thing")).status_code == 200
        second = await client.get("/included/thing")

    assert second.status_code == 429
    assert second.json()["code"] == "rate_limit_exceeded"
    # The hint is the window the caller's own key actually hit, not a floor:
    # a minute window opened moments ago has essentially all of it left.
    assert 55 <= int(second.headers["retry-after"]) <= 60


async def test_a_disabled_limiter_never_refuses() -> None:
    async with _client(_app(enabled=False)) as client:
        for _ in range(3):
            assert (await client.get("/included/thing")).status_code == 200


async def test_the_handler_is_what_identifies_an_endpoint_keyed_limit() -> None:
    """Endpoint keying uses the handler's name; with no handler nothing is counted."""
    async with _client(_app(key_style="endpoint")) as client:
        assert (await client.get("/included/thing")).status_code == 200
        assert (await client.get("/included/thing")).status_code == 429


async def test_rate_limit_headers_are_injected_on_a_successful_response() -> None:
    """The counters ride on request.state; losing them blinds the client to its budget."""
    async with _client(_app("5/minute", headers_enabled=True)) as client:
        response = await client.get("/included/thing")

    assert response.status_code == 200
    assert response.headers["x-ratelimit-limit"] == "5"
    assert response.headers["x-ratelimit-remaining"] == "4"


async def test_an_unrouted_path_is_exempt_rather_than_counted() -> None:
    """With no handler there is no route to limit, and a 404 must not spend budget."""
    async with _client(_app()) as client:
        for _ in range(3):
            assert (await client.get("/nope")).status_code == 404
        assert (await client.get("/included/thing")).status_code == 200
