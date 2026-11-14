"""The app-wide limit: each request counts against its caller's bucket, on every routed path."""

from fastapi import APIRouter, Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from limits import RateLimitItemPerMinute
from limits.storage import RedisStorage
from pydantic import BaseModel
import pytest
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.api.v1.middleware import rate_limiter
from app.api.v1.middleware.auth import WorkOSAuthMiddleware
from app.api.v1.middleware.rate_limiter import (
    RequestBucket,
    RouterAwareSlowAPIMiddleware,
    find_route_handler,
)
from app.config.settings import settings
from app.constants.http import INTERNAL_CALLER_HEADER, VIEWER_IP_HEADER
from app.core.bot_auth_middleware import BotAuthMiddleware
from app.core.middleware import rate_limit_handler
from app.models.user_models import AuthenticatedUser
from tests.conftest import FAKE_USER

pytestmark = pytest.mark.unit

_TOKEN = "t" * 64
_USER_HEADER = "X-Test-User"
_BOT_HEADER = "X-Test-Verified-Bot"


class _Payload(BaseModel):
    count: int


class _FakeAuth(BaseHTTPMiddleware):
    """Stands in for the auth middlewares: names the session user, or a verified bot."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        user_id = request.headers.get(_USER_HEADER)
        if user_id:
            request.state.user = FAKE_USER.model_copy(update={"user_id": user_id})
        if request.headers.get(_BOT_HEADER):
            request.state.bot_api_key_valid = True
        return await call_next(request)


def _app(*, enabled: bool = True, storage_uri: str = "memory://") -> FastAPI:
    """Mount routes the way routes.py does: under an include-time /api/v1 prefix."""
    app = FastAPI()
    app.add_middleware(RouterAwareSlowAPIMiddleware)
    app.add_middleware(_FakeAuth)
    app.exception_handler(RateLimitExceeded)(rate_limit_handler)
    app.state.limiter = rate_limiter.build_limiter(storage_uri)
    app.state.limiter.enabled = enabled

    router = APIRouter(prefix="/included")

    @router.get("/thing")
    async def thing() -> _Payload:
        return _Payload(count=1)

    @router.get("/other")
    async def other() -> _Payload:
        return _Payload(count=2)

    @router.get("/decorated")
    @app.state.limiter.limit("100/minute")
    async def decorated(request: Request) -> _Payload:
        return _Payload(count=len(request.url.path))

    @router.get("/{name}")
    async def by_name(name: str) -> _Payload:
        return _Payload(count=len(name))

    app.include_router(router, prefix="/api/v1")

    links = APIRouter(prefix="/l")

    @links.get("/{slug}/pdf")
    async def link_pdf(slug: str) -> _Payload:
        return _Payload(count=len(slug))

    app.include_router(links, prefix="/api/v1")
    return app


@pytest.fixture
def small_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    """One request a minute per user and viewer, three per token-bearing source."""
    monkeypatch.setattr(settings, "INTERNAL_API_TOKEN", _TOKEN)
    for bucket, per_minute in (
        (RequestBucket.SIGNED_IN_USER, 1),
        (RequestBucket.ANONYMOUS_VIEWER, 1),
        (RequestBucket.INTERNAL_SOURCE, 3),
    ):
        monkeypatch.setitem(rate_limiter.BUCKET_LIMITS, bucket, RateLimitItemPerMinute(per_minute))


def _client(app: FastAPI, peer: str = "203.0.113.1") -> AsyncClient:
    transport = ASGITransport(app=app, raise_app_exceptions=False, client=(peer, 1234))
    return AsyncClient(transport=transport, base_url="http://test")


def _server(viewer: str | None = None, token: str = _TOKEN) -> dict[str, str]:
    headers = {INTERNAL_CALLER_HEADER: token}
    if viewer is not None:
        headers[VIEWER_IP_HEADER] = viewer
    return headers


THING = "/api/v1/included/thing"
OTHER = "/api/v1/included/other"


def test_the_handler_of_a_route_under_an_include_time_prefix_is_found() -> None:
    """Regression: matching the unprefixed original route found no handler for any /api/v1 route."""
    scope = {"type": "http", "path": THING, "method": "GET", "headers": []}

    handler = find_route_handler(_app(), scope)

    assert handler is not None
    assert handler.__name__ == "thing"


def test_the_handler_is_the_route_starlette_dispatches_to_not_a_later_match() -> None:
    """Regression: /workflows/explore resolved to the later /workflows/{id} handler."""
    scope = {"type": "http", "path": THING, "method": "GET", "headers": []}

    handler = find_route_handler(_app(), scope)

    assert handler is not None
    assert handler.__name__ == "thing"


@pytest.mark.usefixtures("small_limits")
async def test_a_route_with_its_own_limit_still_counts_against_the_callers_ceiling() -> None:
    async with _client(_app()) as client:
        assert (await client.get("/api/v1/included/decorated")).status_code == 200
        assert (await client.get(THING)).status_code == 429


def test_an_unmatched_path_has_no_handler() -> None:
    scope = {"type": "http", "path": "/nope", "method": "GET", "headers": []}

    assert find_route_handler(_app(), scope) is None


@pytest.mark.regression
@pytest.mark.usefixtures("small_limits")
async def test_the_app_wide_limit_applies_to_routes_under_api_v1() -> None:
    """Regression: every /api/v1 route was exempt, so the app-wide limit limited nothing."""
    async with _client(_app()) as client:
        assert (await client.get(THING)).status_code == 200
        refused = await client.get(THING)

    assert refused.status_code == 429
    assert refused.json()["code"] == "rate_limit_exceeded"
    # The hint is the window the caller's own key hit: a fresh minute window.
    assert 55 <= int(refused.headers["retry-after"]) <= 60


@pytest.mark.usefixtures("small_limits")
async def test_one_ceiling_covers_every_route_a_caller_hits() -> None:
    async with _client(_app()) as client:
        assert (await client.get(THING)).status_code == 200
        assert (await client.get(OTHER)).status_code == 429


@pytest.mark.usefixtures("small_limits")
async def test_signed_in_users_count_by_user_id_not_address() -> None:
    """Two users behind one office address each get a ceiling; one user on two networks shares one."""
    app = _app()
    async with _client(app) as office, _client(app, peer="198.51.100.9") as phone:
        assert (await office.get(THING, headers={_USER_HEADER: "user-a"})).status_code == 200
        assert (await office.get(THING, headers={_USER_HEADER: "user-b"})).status_code == 200
        assert (await phone.get(THING, headers={_USER_HEADER: "user-a"})).status_code == 429


@pytest.mark.usefixtures("small_limits")
async def test_anonymous_callers_count_by_address() -> None:
    app = _app()
    async with _client(app) as one, _client(app, peer="198.51.100.9") as two:
        assert (await one.get(THING)).status_code == 200
        assert (await two.get(THING)).status_code == 200
        assert (await one.get(THING)).status_code == 429


@pytest.mark.usefixtures("small_limits")
async def test_the_web_server_counts_each_viewer_it_renders_for() -> None:
    async with _client(_app()) as web:
        assert (await web.get(THING, headers=_server("198.51.100.1"))).status_code == 200
        assert (await web.get(THING, headers=_server("198.51.100.2"))).status_code == 200
        assert (await web.get(THING, headers=_server("198.51.100.1"))).status_code == 429


@pytest.mark.usefixtures("small_limits")
async def test_a_leaked_token_rotating_viewers_stays_under_the_source_ceiling() -> None:
    async with _client(_app()) as web:
        codes = [
            (await web.get(THING, headers=_server(f"198.51.100.{i}"))).status_code
            for i in range(1, 6)
        ]

    assert codes == [200, 200, 200, 429, 429]


@pytest.mark.usefixtures("small_limits")
async def test_the_web_servers_own_requests_spend_only_the_source_ceiling() -> None:
    """Prerendering fetches name no viewer, so they are not held to one viewer's ceiling."""
    async with _client(_app()) as web:
        codes = [(await web.get(THING, headers=_server())).status_code for _ in range(4)]

    assert codes == [200, 200, 200, 429]


@pytest.mark.parametrize("token", ["", "not-the-token"])
@pytest.mark.usefixtures("small_limits")
async def test_a_wrong_token_is_an_anonymous_caller_that_cannot_pick_its_key(token: str) -> None:
    async with _client(_app()) as caller:
        assert (await caller.get(THING, headers=_server("198.51.100.1", token))).status_code == 200
        rotated = await caller.get(THING, headers=_server("198.51.100.2", token))

    assert rotated.status_code == 429


@pytest.mark.usefixtures("small_limits")
async def test_a_server_with_no_token_configured_trusts_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "INTERNAL_API_TOKEN", None)

    async with _client(_app()) as caller:
        await caller.get(THING, headers=_server("198.51.100.1"))
        rotated = await caller.get(THING, headers=_server("198.51.100.2"))

    assert rotated.status_code == 429


@pytest.mark.usefixtures("small_limits")
async def test_a_viewer_that_is_not_an_address_is_never_its_own_bucket() -> None:
    async with _client(_app()) as web:
        codes = [
            (await web.get(THING, headers=_server(f"garbage-{i}"))).status_code for i in range(4)
        ]

    assert codes == [200, 200, 200, 429]


@pytest.mark.usefixtures("small_limits")
async def test_a_verified_bot_stays_on_its_api_key() -> None:
    async with _client(_app()) as bot:
        for _ in range(4):
            assert (await bot.get(THING, headers={_BOT_HEADER: "1"})).status_code == 200


@pytest.mark.usefixtures("small_limits")
async def test_a_disabled_limiter_never_refuses() -> None:
    async with _client(_app(enabled=False)) as client:
        for _ in range(3):
            assert (await client.get(THING)).status_code == 200


@pytest.mark.usefixtures("small_limits")
async def test_an_unrouted_path_is_exempt_rather_than_counted() -> None:
    """With no handler there is no route to limit, and a 404 must not spend budget."""
    async with _client(_app()) as client:
        for _ in range(3):
            assert (await client.get("/nope")).status_code == 404
        assert (await client.get(THING)).status_code == 200


@pytest.mark.usefixtures("small_limits")
async def test_a_probe_is_never_counted() -> None:
    """A dead counter storage must not be able to take /health or /metrics down."""
    app = _app(storage_uri="redis://127.0.0.1:1")
    app.add_api_route("/health", lambda: {"ok": True}, methods=["GET"])

    async with _client(app) as client:
        for _ in range(3):
            assert (await client.get("/health")).status_code == 200


def test_the_limiter_counts_against_the_configured_storage() -> None:
    """Every replica must share one window, so the storage is Redis, not this process's memory."""
    limiter: Limiter = rate_limiter.build_limiter("redis://127.0.0.1:1")

    assert isinstance(limiter.limiter.storage, RedisStorage)


@pytest.mark.regression
@pytest.mark.usefixtures("small_limits")
async def test_a_redis_outage_keeps_counting_in_memory_instead_of_crashing() -> None:
    """Regression: a dead Redis reached slowapi's 429 handler, which read .detail off a ConnectionError."""
    # Nothing listens on port 1, so every Redis call is a real ConnectionError.
    async with _client(_app(storage_uri="redis://127.0.0.1:1"), peer="192.0.2.77") as client:
        assert (await client.get(THING)).status_code == 200
        refused = await client.get(THING)

    assert refused.status_code == 429
    assert refused.json()["code"] == "rate_limit_exceeded"


@pytest.mark.usefixtures("small_limits")
async def test_the_token_never_signs_anyone_in() -> None:
    """Behind the real auth middlewares, a token request with no session is still a 401 for user data."""
    app = FastAPI()
    app.add_middleware(RouterAwareSlowAPIMiddleware)
    app.add_middleware(WorkOSAuthMiddleware)
    app.add_middleware(BotAuthMiddleware)
    app.exception_handler(RateLimitExceeded)(rate_limit_handler)
    app.state.limiter = rate_limiter.build_limiter("memory://")

    @app.get("/api/v1/user/me")
    async def me(user: AuthenticatedUser = Depends(get_current_user)) -> _Payload:
        return _Payload(count=len(user.user_id))

    async with _client(app) as web:
        response = await web.get("/api/v1/user/me", headers=_server("198.51.100.1"))

    assert response.status_code == 401


@pytest.mark.usefixtures("small_limits")
async def test_the_previous_token_still_counts_while_a_rotation_rolls_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "INTERNAL_API_TOKEN", "n" * 64)
    monkeypatch.setattr(settings, "INTERNAL_API_TOKEN_PREVIOUS", _TOKEN)

    async with _client(_app()) as web:
        codes = [(await web.get(THING, headers=_server())).status_code for _ in range(4)]

    assert codes == [200, 200, 200, 429]


@pytest.mark.parametrize("headers", [{}, {_USER_HEADER: "user-a"}])
async def test_public_pdf_exports_have_their_own_small_ceiling(
    headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(
        rate_limiter.BUCKET_LIMITS, RequestBucket.PUBLIC_PDF_EXPORT, RateLimitItemPerMinute(1)
    )
    async with _client(_app()) as client:
        assert (await client.get("/api/v1/l/abc/pdf", headers=headers)).status_code == 200
        assert (await client.get("/api/v1/l/abc/pdf", headers=headers)).status_code == 429
        assert (await client.get(THING, headers=headers)).status_code == 200
