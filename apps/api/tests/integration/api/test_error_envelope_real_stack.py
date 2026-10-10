"""Every non-2xx the real stack emits is a readable ErrorEnvelope.

The unit suite proves the envelope for handlers registered on a bare app. This
tier drives the real create_app() with the real middleware stack, nothing
patched out, because three error paths only exist there: the default-limit 429
answered by SlowAPIMiddleware, the 500 that has to carry CORS headers to be
readable at all, and the serializer coping with whatever an AppError puts on
the wire.
"""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import anyio
from fastapi import APIRouter, FastAPI, Form
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
import pytest
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.api.v1.middleware import timeout as timeout_middleware
from app.api.v1.middleware.auth import WorkOSAuthMiddleware
from app.core.app_factory import create_app
from app.models.payment_models import PlanType, UserSubscriptionStatus
from app.schemas.errors import ERROR_RESPONSES, ErrorEnvelope
from app.utils.errors import AppError
from tests.factories import make_authenticated_user

ALLOWED_ORIGIN = "http://localhost:3000"
ORIGIN_HEADER = {"Origin": ALLOWED_ORIGIN}
PROBE_PREFIX = "/api/v1/envelope-probe"

#: Non-standard status a provider can forward through the Composio proxy.
#: ``HTTPStatus(499)`` raises, which is the whole point of exercising it.
UPSTREAM_STATUS = 499


class _Payload(BaseModel):
    count: int


def _probe_router() -> APIRouter:
    router = APIRouter(prefix=PROBE_PREFIX, tags=["EnvelopeProbe"])

    @router.get("/ok")
    async def _ok() -> _Payload:
        return _Payload(count=1)

    @router.get("/boom")
    async def _boom() -> _Payload:
        raise RuntimeError("probe crash")

    @router.get("/slow")
    async def _slow() -> _Payload:
        await anyio.sleep(5)
        return _Payload(count=0)

    @router.get("/upstream")
    async def _upstream() -> _Payload:
        raise AppError(
            message="probe API error (499)",
            why="The provider rejected the request",
            status_code=UPSTREAM_STATUS,
            public={"toolkit": "probe"},
        )

    @router.get("/public-datetime")
    async def _public_datetime() -> _Payload:
        raise AppError(
            message="Retry after the window closes",
            status_code=409,
            public={"observed_at": datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)},
        )

    @router.post("/validate")
    async def _validate(payload: _Payload) -> _Payload:
        return payload

    @router.post("/form")
    async def _form(count: int = Form()) -> _Payload:
        return _Payload(count=count)

    return router


def _build_app(*, limit: str = "120/minute", timeout: float = 300.0) -> FastAPI:
    """Build the production app, with only the two knobs a test must turn.

    The limiter and the timeout budget are replaced with tiny values; every
    middleware, exception handler and serializer is the real one.
    """
    timeout_middleware.DEFAULT_TIMEOUT_SECONDS = timeout
    app = create_app()
    app.include_router(_probe_router(), responses=ERROR_RESPONSES)
    app.state.limiter = Limiter(
        key_func=get_remote_address, default_limits=[limit], storage_uri="memory://"
    )
    return app


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",  # NOSONAR
    )


@pytest.fixture
def restore_timeout_default():
    original = timeout_middleware.DEFAULT_TIMEOUT_SECONDS
    yield
    timeout_middleware.DEFAULT_TIMEOUT_SECONDS = original


@pytest.fixture
async def stack(restore_timeout_default):
    async with _client(_build_app()) as client:
        yield client


@pytest.fixture
def free_plan():
    """Make the payments client answer FREE, so the real gate 402s deterministically."""
    with (
        patch(
            "app.services.payments.payment_service.payment_service.get_cached_plan_type",
            new_callable=AsyncMock,
            return_value=PlanType.FREE,
        ),
        patch(
            "app.services.payments.payment_service.payment_service.get_user_subscription_status",
            new_callable=AsyncMock,
            return_value=UserSubscriptionStatus(user_id="probe-user", plan_type=PlanType.FREE),
        ),
    ):
        yield


@pytest.fixture
async def authed_stack(restore_timeout_default):
    # Only the WorkOS SSO round trip is stubbed — the one step no automated
    # test can perform — so the paywall gate reads what the real auth path wrote.
    with patch.object(
        WorkOSAuthMiddleware,
        "_authenticate_session",
        new=AsyncMock(return_value=(make_authenticated_user(user_id="probe-user"), None)),
    ):
        async with _client(_build_app()) as client:
            client.cookies.set("wos_session", "probe-session")
            yield client


def _assert_envelope(response, status_code: int) -> dict[str, Any]:
    """Every non-2xx is a JSON envelope a browser on an allowed origin can read."""
    assert response.status_code == status_code, response.text
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN, (
        f"{status_code} is unreadable cross-origin: {dict(response.headers)}"
    )
    body = response.json()
    assert "detail" not in body, f"the envelope never nests under detail: {body}"
    ErrorEnvelope.model_validate(body)
    return body


@pytest.mark.integration
class TestEveryErrorIsTheEnvelope:
    async def test_unauthenticated_401(self, stack: AsyncClient) -> None:
        body = _assert_envelope(await stack.get("/api/v1/todos", headers=ORIGIN_HEADER), 401)
        assert body["message"]

    async def test_unknown_route_404(self, stack: AsyncClient) -> None:
        body = _assert_envelope(
            await stack.get("/api/v1/no/such/route/here", headers=ORIGIN_HEADER), 404
        )
        assert body["message"] == "Not Found"

    async def test_wrong_method_405(self, stack: AsyncClient) -> None:
        body = _assert_envelope(
            await stack.get(f"{PROBE_PREFIX}/validate", headers=ORIGIN_HEADER), 405
        )
        assert body["message"] == "Method Not Allowed"

    async def test_json_validation_422(self, stack: AsyncClient) -> None:
        body = _assert_envelope(
            await stack.post(
                f"{PROBE_PREFIX}/validate", json={"count": "many"}, headers=ORIGIN_HEADER
            ),
            422,
        )
        assert body["code"] == "validation_error"
        assert body["errors"][0]["loc"] == ["body", "count"]

    async def test_form_validation_422(self, stack: AsyncClient) -> None:
        body = _assert_envelope(
            await stack.post(
                f"{PROBE_PREFIX}/form", files={"unexpected": ("f.txt", b"x")}, headers=ORIGIN_HEADER
            ),
            422,
        )
        assert body["code"] == "validation_error"
        assert body["errors"][0]["loc"] == ["body", "count"]

    async def test_default_rate_limit_429_through_slowapi(self, restore_timeout_default) -> None:
        async with _client(_build_app(limit="1/minute")) as client:
            first = await client.get(f"{PROBE_PREFIX}/ok", headers=ORIGIN_HEADER)
            assert first.status_code == 200
            response = await client.get(f"{PROBE_PREFIX}/ok", headers=ORIGIN_HEADER)

        body = _assert_envelope(response, 429)
        assert body["code"] == "rate_limit_exceeded"
        assert "retry_after" not in body, "a null retry_after is not a contract"
        assert int(response.headers["retry-after"]) >= 0

    async def test_unhandled_crash_500(self, stack: AsyncClient) -> None:
        body = _assert_envelope(await stack.get(f"{PROBE_PREFIX}/boom", headers=ORIGIN_HEADER), 500)
        assert body["code"] == "internal_server_error"

    async def test_timeout_504(self, restore_timeout_default) -> None:
        async with _client(_build_app(timeout=0.05)) as client:
            response = await client.get(f"{PROBE_PREFIX}/slow", headers=ORIGIN_HEADER)

        body = _assert_envelope(response, 504)
        assert body["code"] == "request_timeout"
        assert response.headers["retry-after"] == "60"

    async def test_non_standard_upstream_status(self, stack: AsyncClient) -> None:
        body = _assert_envelope(
            await stack.get(f"{PROBE_PREFIX}/upstream", headers=ORIGIN_HEADER), UPSTREAM_STATUS
        )
        assert body["toolkit"] == "probe"

    async def test_public_meta_carrying_a_datetime(self, stack: AsyncClient) -> None:
        body = _assert_envelope(
            await stack.get(f"{PROBE_PREFIX}/public-datetime", headers=ORIGIN_HEADER), 409
        )
        assert body["observed_at"] == "2026-01-02T03:04:05Z"

    async def test_entitlement_402(self, authed_stack: AsyncClient, free_plan) -> None:
        body = _assert_envelope(
            await authed_stack.get(f"{PROBE_PREFIX}/ok", headers=ORIGIN_HEADER), 402
        )
        assert body["code"] == "subscription_required"
        assert body["checkout_url"] is None
