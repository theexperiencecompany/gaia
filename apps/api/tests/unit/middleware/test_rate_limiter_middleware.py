"""The default rate limit has to reach routes that live behind a lazy router.

FastAPI 0.139 defers router inclusion, so app.routes holds wrappers with no
.endpoint: slowapi's own handler lookup returned None for every included route
and _should_exempt then exempted it — the default limit applied to nothing.
"""

from typing import Literal

from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient
from limits.storage import RedisStorage
from pydantic import BaseModel
import pytest
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.api.v1.middleware import rate_limiter
from app.api.v1.middleware.rate_limiter import (
    RouterAwareSlowAPIMiddleware,
    find_route_handler,
)
from app.config.settings import settings
from app.constants.http import INTERNAL_RESOLVER_HEADER, VIEWER_IP_HEADER
from app.core.middleware import rate_limit_handler

pytestmark = pytest.mark.unit


class _Payload(BaseModel):
    count: int


def _app(
    limit: str = "1/minute",
    *,
    enabled: bool = True,
    key_style: Literal["endpoint", "url"] = "url",
    headers_enabled: bool = False,
) -> FastAPI:
    app = FastAPI()
    app.add_middleware(RouterAwareSlowAPIMiddleware)
    app.exception_handler(RateLimitExceeded)(rate_limit_handler)
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


def test_the_limiter_counts_against_the_configured_storage() -> None:
    """Every replica must share one window, so the storage is Redis, not this process's memory."""
    limiter = rate_limiter.build_limiter("redis://127.0.0.1:1")

    assert isinstance(limiter.limiter.storage, RedisStorage)


@pytest.mark.regression
async def test_a_redis_outage_keeps_counting_in_memory_instead_of_crashing() -> None:
    """Regression: a dead Redis reached slowapi's 429 handler, which read .detail off a ConnectionError."""
    app = _app()
    # Nothing listens on port 1, so every Redis call is a real ConnectionError.
    app.state.limiter = rate_limiter.build_limiter("redis://127.0.0.1:1")

    async with _client(app) as client:
        for _ in range(rate_limiter.DEFAULT_LIMIT_PER_MINUTE):
            assert (await client.get("/included/thing")).status_code == 200
        refused = await client.get("/included/thing")

    assert refused.status_code == 429
    assert refused.json()["code"] == "rate_limit_exceeded"


@pytest.mark.regression
async def test_a_probe_is_never_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    """A dead counter storage must not be able to take /health or /metrics down."""
    counted: list[str] = []

    def record(*args: object, **kwargs: object) -> tuple[None, bool]:
        counted.append("called")
        return None, False

    monkeypatch.setattr(rate_limiter, "sync_check_limits", record)
    app = _app()
    app.add_api_route("/health", lambda: {"ok": True}, methods=["GET"])

    async with _client(app) as client:
        for _ in range(3):
            assert (await client.get("/health")).status_code == 200

    assert counted == []


_RESOLVER_TOKEN = "r" * 64


def _viewer_keyed_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    """Build an app behind the production limiter, at one request a minute."""
    monkeypatch.setattr(rate_limiter, "DEFAULT_LIMIT_PER_MINUTE", 1)
    monkeypatch.setattr(settings, "INTERNAL_RESOLVER_TOKEN", _RESOLVER_TOKEN)
    app = _app()
    app.state.limiter = rate_limiter.build_limiter("memory://")
    return app


def _from_web_server(viewer_ip: str, token: str = _RESOLVER_TOKEN) -> dict[str, str]:
    return {VIEWER_IP_HEADER: viewer_ip, INTERNAL_RESOLVER_HEADER: token}


async def test_server_rendered_requests_count_against_each_viewer_not_the_web_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The web app resolves a link page during SSR, so every viewer arrives from its IP."""
    async with _client(_viewer_keyed_app(monkeypatch)) as client:
        first = await client.get("/included/thing", headers=_from_web_server("198.51.100.1"))
        second = await client.get("/included/thing", headers=_from_web_server("198.51.100.2"))
        again = await client.get("/included/thing", headers=_from_web_server("198.51.100.1"))

    assert [first.status_code, second.status_code, again.status_code] == [200, 200, 429]


@pytest.mark.parametrize("token", ["", "not-the-token"])
async def test_a_viewer_ip_without_the_resolver_token_cannot_pick_its_own_key(
    monkeypatch: pytest.MonkeyPatch, token: str
) -> None:
    async with _client(_viewer_keyed_app(monkeypatch)) as client:
        first = await client.get("/included/thing", headers=_from_web_server("198.51.100.1", token))
        rotated = await client.get(
            "/included/thing", headers=_from_web_server("198.51.100.2", token)
        )

    assert [first.status_code, rotated.status_code] == [200, 429]


async def test_an_unset_resolver_token_trusts_no_viewer_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _viewer_keyed_app(monkeypatch)
    monkeypatch.setattr(settings, "INTERNAL_RESOLVER_TOKEN", None)

    async with _client(app) as client:
        await client.get("/included/thing", headers=_from_web_server("198.51.100.1", ""))
        rotated = await client.get("/included/thing", headers=_from_web_server("198.51.100.2", ""))

    assert rotated.status_code == 429


async def test_a_viewer_ip_that_is_not_an_address_is_not_a_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A garbage header from a misconfigured proxy falls back to the peer, never a free bucket."""
    async with _client(_viewer_keyed_app(monkeypatch)) as client:
        await client.get("/included/thing", headers=_from_web_server("not-an-ip"))
        refused = await client.get("/included/thing", headers=_from_web_server("also-not"))

    assert refused.status_code == 429
