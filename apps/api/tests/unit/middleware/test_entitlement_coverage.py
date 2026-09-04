"""Deny-by-default proof for the paid-only gate.

The point of these tests is not that the middleware works on one route — it is
that NO route escapes it. Every path in the app's OpenAPI schema is either named
in ``FREE_PATH_PREFIXES`` (with a reason, in that file) or 402s a free caller.
Adding a new endpoint therefore cannot silently create a free paid surface: it
is gated by default, and making it free requires editing the allowlist, which
the snapshot test below turns into a reviewed diff.
"""

from collections.abc import AsyncGenerator, Iterator
from typing import Any
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, Request, Response
from httpx import ASGITransport, AsyncClient
import pytest
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.v1.middleware.entitlement import EntitlementMiddleware
from app.api.v1.middleware.entitlement_allowlist import FREE_PATH_PREFIXES, is_free_path
from app.decorators.entitlements import SubscriptionRequiredException
from app.models.payment_models import PlanType
from tests.conftest import FAKE_USER, _create_test_app

pytestmark = pytest.mark.unit

# Methods worth exercising. HEAD/OPTIONS are handled by Starlette and CORS
# respectively and never reach a paid handler.
GATED_METHODS = ("get", "post", "put", "patch", "delete")

# Gated routes with a required request body: FastAPI would 422 them before any
# handler logic runs, so a PRO caller can be checked against a real paid route
# without the test needing Mongo, Redis or an LLM.
PRO_SAMPLE: tuple[tuple[str, str], ...] = (
    ("POST", "/api/v1/chat-stream"),
    ("POST", "/api/v1/image/generate"),
    ("POST", "/api/v1/mcp/proxy/tool-call"),
    ("POST", "/api/v1/reminders"),
    ("POST", "/api/v1/skills/install/github"),
)


class _StubAuthMiddleware(BaseHTTPMiddleware):
    """Stand in for ``WorkOSAuthMiddleware``: publish an authenticated user.

    The gate reads ``request.state.user`` and nothing else, so a stub is a
    faithful substitute for the auth middleware here and keeps the test off
    WorkOS.
    """

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        request.state.user = FAKE_USER
        return await call_next(request)


@pytest.fixture(scope="module")
def gated_app() -> FastAPI:
    """The real app with the real gate, behind a stub authenticator."""
    app = _create_test_app()
    # Added last == outermost, so the user is on request.state before the gate
    # runs — the same relative order as production.
    app.add_middleware(EntitlementMiddleware)
    app.add_middleware(_StubAuthMiddleware)
    return app


@pytest.fixture
async def gated_client(gated_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=gated_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:  # NOSONAR
        yield ac


@pytest.fixture
def free_caller() -> Iterator[None]:
    with patch(
        "app.decorators.entitlements.payment_service.get_cached_plan_type",
        new_callable=AsyncMock,
        return_value=PlanType.FREE,
    ):
        # A paywall response tries to mint a personal checkout link; keep that
        # off the network so the sweep stays fast and hermetic.
        with patch(
            "app.decorators.entitlements.get_checkout_url",
            new_callable=AsyncMock,
            return_value="https://checkout.example/pro",
        ):
            yield


def _routes(app: FastAPI) -> list[tuple[str, str]]:
    """Every ``(METHOD, path)`` the app exposes, with params filled in."""
    paths = app.openapi()["paths"]
    return [
        (method.upper(), path.replace("{", "").replace("}", ""))
        for path in sorted(paths)
        for method in GATED_METHODS
        if method in paths[path]
    ]


def test_route_table_is_not_empty(gated_app: FastAPI) -> None:
    """Guard the sweep below from passing because it enumerated nothing."""
    assert len(_routes(gated_app)) > 200


@pytest.mark.usefixtures("free_caller")
async def test_every_route_is_gated_or_allowlisted(
    gated_app: FastAPI, gated_client: AsyncClient
) -> None:
    """No route is reachable by a free authenticated caller unless allowlisted."""
    escaped: list[tuple[str, str]] = []
    for method, path in _routes(gated_app):
        if is_free_path(path):
            continue
        response = await gated_client.request(method, path)
        if response.status_code != 402:
            escaped.append((method, path))

    assert not escaped, (
        "These paid surfaces did NOT 402 a free user. Either the gate missed "
        f"them or they belong in FREE_PATH_PREFIXES with a reason: {escaped}"
    )


@pytest.mark.usefixtures("free_caller")
async def test_block_body_matches_the_documented_wire_contract(
    gated_client: AsyncClient,
) -> None:
    """The web's 402 interceptor matches on these four keys — all must be present."""
    response = await gated_client.post("/api/v1/chat-stream")

    assert response.status_code == 402
    detail = response.json()["detail"]
    assert detail["code"] == "subscription_required"
    assert detail["checkout_url"] == "https://checkout.example/pro"
    assert set(detail) == {"code", "message", "checkout_url", "discount_code"}
    assert detail["message"]


def test_allowlist_snapshot(gated_app: FastAPI) -> None:
    """Freeze which routes are free, so widening the paywall is a reviewed diff.

    A prefix in the allowlist frees a whole subtree; without this, adding a
    route under, say, ``/api/v1/payments`` would quietly ship un-monetised.
    """
    free = sorted({path for _, path in _routes(gated_app) if is_free_path(path)})

    assert free == [
        "/api/v1/blogs",
        "/api/v1/blogs/count",
        "/api/v1/blogs/slug",
        "/api/v1/bot/auth-status/platform/platform_user_id",
        "/api/v1/bot/chat-stream",
        "/api/v1/bot/create-link-token",
        "/api/v1/bot/link-token-info/token",
        "/api/v1/bot/linked-users/platform",
        "/api/v1/bot/redeem-link-code",
        "/api/v1/bot/reset-session",
        "/api/v1/bot/settings/platform/platform_user_id",
        "/api/v1/bot/transcribe",
        "/api/v1/bot/unlink",
        "/api/v1/desktop/releases/latest",
        "/api/v1/device/pair/poll",
        "/api/v1/device/pair/start",
        "/api/v1/device/servers",
        "/api/v1/device/token",
        "/api/v1/integrations/connect-link",
        "/api/v1/notifications/unsubscribe",
        "/api/v1/oauth/client-metadata.json",
        "/api/v1/oauth/composio/callback",
        "/api/v1/oauth/login/google/mobile",
        "/api/v1/oauth/login/workos",
        "/api/v1/oauth/login/workos/desktop",
        "/api/v1/oauth/login/workos/mobile",
        "/api/v1/oauth/workos/callback",
        "/api/v1/oauth/workos/desktop/callback",
        "/api/v1/oauth/workos/mobile/callback",
        "/api/v1/onboarding",
        "/api/v1/onboarding/personalization",
        "/api/v1/onboarding/phase",
        "/api/v1/onboarding/preferences",
        "/api/v1/onboarding/reset",
        "/api/v1/onboarding/social-profiles",
        "/api/v1/onboarding/status",
        "/api/v1/onboarding/writing-style",
        "/api/v1/onboarding/writing-style/regenerate-example",
        "/api/v1/payments/checkout-session",
        "/api/v1/payments/plans",
        "/api/v1/payments/subscription-status",
        "/api/v1/payments/subscriptions",
        "/api/v1/payments/subscriptions/cancel",
        "/api/v1/payments/verify-payment",
        "/api/v1/payments/webhooks/dodo",
        "/api/v1/ping",
        "/api/v1/platform-auth/discord/callback",
        "/api/v1/platform-auth/slack/callback",
        "/api/v1/support/rate-limit-status",
        "/api/v1/support/requests",
        "/api/v1/support/requests/my",
        "/api/v1/support/requests/with-attachments",
        "/api/v1/user/logout",
        "/api/v1/user/me",
        "/api/v1/webhook/composio",
        "/health",
        "/ping",
    ]


def test_llm_spend_under_a_free_prefix_keeps_its_own_gate() -> None:
    """``/api/v1/onboarding`` is free, so its one LLM route gates itself.

    An allowlisted prefix is a blunt instrument. Where a paid action lives
    inside a free subtree, ``@require_subscription()`` is still the mechanism —
    this test exists so removing that decorator fails loudly rather than
    handing free users an LLM endpoint.
    """
    from app.api.v1.endpoints import onboarding

    assert is_free_path("/api/v1/onboarding/writing-style/regenerate-example")
    assert hasattr(onboarding.regenerate_writing_style_example, "__wrapped__")


@pytest.mark.parametrize(("method", "path"), PRO_SAMPLE)
async def test_pro_user_is_not_blocked(gated_client: AsyncClient, method: str, path: str) -> None:
    """A PRO caller passes the gate on real paid routes (and 422s on the body)."""
    with patch(
        "app.decorators.entitlements.payment_service.get_cached_plan_type",
        new_callable=AsyncMock,
        return_value=PlanType.PRO,
    ):
        response = await gated_client.request(method, path)

    assert response.status_code != 402


# ---------------------------------------------------------------------------
# Middleware behaviour in isolation
# ---------------------------------------------------------------------------


def _minimal_app(user: dict[str, Any] | None) -> FastAPI:
    app = FastAPI()

    @app.get("/api/v1/paid")
    async def paid() -> dict[str, str]:
        return {"ok": "yes"}

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"ok": "yes"}

    app.add_middleware(EntitlementMiddleware)

    class _Stub(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next: Any) -> Response:
            request.state.user = user
            return await call_next(request)

    app.add_middleware(_Stub)
    return app


async def _get(app: FastAPI, path: str, method: str = "GET") -> Any:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:  # NOSONAR
        return await ac.request(method, path)


def test_production_middleware_order_puts_the_gate_inside_auth_and_cors() -> None:
    """Two constraints hold this position, and both are silent when broken.

    Outside ``WorkOSAuthMiddleware`` the gate sees no ``request.state.user``, so
    every request looks anonymous and the paywall is off. Outside
    ``CORSMiddleware`` its 402 short-circuits before CORS headers are attached,
    so a browser refuses to read the checkout link and the modal never opens.
    """
    from app.core.middleware import configure_middleware

    app = FastAPI()
    configure_middleware(app)
    # user_middleware is ordered outermost-first.
    order = [middleware.cls.__name__ for middleware in app.user_middleware]

    assert order.index("WorkOSAuthMiddleware") < order.index("EntitlementMiddleware")
    assert order.index("CORSMiddleware") < order.index("EntitlementMiddleware")


async def test_unauthenticated_requests_pass_through() -> None:
    """Auth is the route's job; a 402 here would leak which paths exist."""
    response = await _get(_minimal_app(None), "/api/v1/paid")

    assert response.status_code == 200


@pytest.mark.usefixtures("free_caller")
async def test_allowlisted_path_is_not_blocked() -> None:
    response = await _get(_minimal_app(FAKE_USER), "/health")

    assert response.status_code == 200


@pytest.mark.usefixtures("free_caller")
async def test_options_preflight_is_not_blocked() -> None:
    """CORSMiddleware runs inside the gate — a 402 here breaks every browser call."""
    response = await _get(_minimal_app(FAKE_USER), "/api/v1/paid", method="OPTIONS")

    assert response.status_code != 402


async def test_plan_lookup_failure_fails_closed() -> None:
    """A Redis/Mongo blip must not hand everyone a free tier."""
    with patch(
        "app.decorators.entitlements.payment_service.get_cached_plan_type",
        new_callable=AsyncMock,
        side_effect=ConnectionError("redis down"),
    ):
        response = await _get(_minimal_app(FAKE_USER), "/api/v1/paid")

    assert response.status_code == 402
    assert response.json()["detail"]["code"] == "subscription_required"
    assert response.json()["detail"]["checkout_url"] is None


async def test_the_gate_asks_about_this_caller_and_names_the_path_it_blocked() -> None:
    """Both arguments are load-bearing and neither shows up in the response.

    A gate that asked about the wrong user id would 402 (or free) everyone
    alike, and ``feature`` is what makes a PAYWALL_BLOCKED event attributable
    to a surface instead of anonymous — so the call is asserted exactly.
    """
    gate = AsyncMock(side_effect=SubscriptionRequiredException(checkout_url=None))
    with patch("app.api.v1.middleware.entitlement.require_active_subscription", gate):
        response = await _get(_minimal_app(FAKE_USER), "/api/v1/paid")

    assert response.status_code == 402
    gate.assert_awaited_once_with(FAKE_USER["user_id"], feature="/api/v1/paid")


async def test_a_gate_error_is_logged_with_the_caller_the_surface_and_the_cause() -> None:
    """Fail-closed is silent by design — every Pro user 402s and nobody reports it.

    The wide event is the only signal that a 402 came from an outage rather
    than a lapsed subscription, and ``log.error`` stores message AND kwargs in
    the event's ``errors[]`` (libs/shared/py/wide_events.py), so all four
    fields are a queried surface. Asserted exactly: a missing ``error_type``
    or a mislabelled operation makes the alert unwritable.
    """
    with (
        patch(
            "app.api.v1.middleware.entitlement.require_active_subscription",
            new_callable=AsyncMock,
            side_effect=ConnectionError("redis down"),
        ),
        patch("app.api.v1.middleware.entitlement.log") as mock_log,
    ):
        response = await _get(_minimal_app(FAKE_USER), "/api/v1/paid")

    assert response.status_code == 402
    mock_log.error.assert_called_once_with(
        "Entitlement check failed — denying request (fail-closed)",
        user={"id": FAKE_USER["user_id"]},
        payment={"operation": "paywall_gate_error", "feature": "/api/v1/paid"},
        error_type="ConnectionError",
        error="redis down",
    )


async def test_a_request_no_auth_middleware_touched_passes_through() -> None:
    """``request.state.user`` is not merely None here — it was never set.

    Routers excluded from ``WorkOSAuthMiddleware`` (``/api/v1/bot``) reach the
    gate with an untouched state, so the user lookup must have a default. Without
    one this raises ``AttributeError`` and the excluded router 500s instead of
    serving.
    """
    app = FastAPI()

    @app.get("/api/v1/paid")
    async def paid() -> dict[str, str]:
        return {"ok": "yes"}

    app.add_middleware(EntitlementMiddleware)

    response = await _get(app, "/api/v1/paid")

    assert response.status_code == 200
    assert response.json() == {"ok": "yes"}


def test_allowlist_entries_are_absolute_paths() -> None:
    """A relative or empty entry would match everything and disable the paywall."""
    assert all(prefix.startswith("/") for prefix in FREE_PATH_PREFIXES)
    assert len(set(FREE_PATH_PREFIXES)) == len(FREE_PATH_PREFIXES)
