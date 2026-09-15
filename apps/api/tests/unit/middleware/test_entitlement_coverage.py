"""Deny-by-default proof for the paid-only gate.

The point of these tests is not that the middleware works on one route — it is
that NO route escapes it. Every path in the app's OpenAPI schema is either named
in FREE_PATH_PREFIXES (with a reason, in that file) or 402s a free caller.
Adding a new endpoint therefore cannot silently create a free paid surface: it
is gated by default, and making it free requires editing the allowlist, which
the snapshot test below turns into a reviewed diff.
"""

from collections.abc import AsyncGenerator, Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, Request, Response
from httpx import ASGITransport, AsyncClient
import pytest
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.v1.middleware.entitlement import (
    ENTITLEMENT_UNAVAILABLE_MESSAGE,
    EntitlementMiddleware,
)
from app.api.v1.middleware.entitlement_allowlist import (
    FREE_EXACT_PATHS,
    FREE_PATH_PREFIXES,
    is_free_path,
)
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
    """Stand in for WorkOSAuthMiddleware: publish an authenticated user.

    The gate reads request.state.user and nothing else, so a stub is a
    faithful substitute for the auth middleware here and keeps the test off
    WorkOS.
    """

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        request.state.user = FAKE_USER
        return await call_next(request)


@pytest.fixture(scope="module")
def gated_app() -> FastAPI:
    """Build the real app with the real gate, behind a stub authenticator."""
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
    """Make the caller FREE, with nothing else stubbed.

    Refusing costs exactly one cached plan read; Dodo is untouched — see
    test_entitlement_checkout_minting.
    """
    with patch(
        "app.decorators.entitlements.payment_service.get_cached_plan_type",
        new_callable=AsyncMock,
        return_value=PlanType.FREE,
    ):
        yield


def _routes(app: FastAPI) -> list[tuple[str, str]]:
    """Every (METHOD, path) the app exposes, with params filled in."""
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
    body = response.json()
    assert body["code"] == "subscription_required"
    # Present and null: the key is still part of the shape three clients parse,
    # but the gate never mints a session to fill it.
    assert body["checkout_url"] is None
    assert set(body) == {"code", "message", "checkout_url", "discount_code"}
    assert body["message"]


def test_allowlist_snapshot(gated_app: FastAPI) -> None:
    """A prefix frees a whole subtree; adding a route under /api/v1/payments would quietly ship un-monetised without this."""
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
        "/api/v1/device/servers/server_key",
        "/api/v1/device/token",
        "/api/v1/integrations/connect-link",
        "/api/v1/mcp/oauth/callback",
        "/api/v1/notifications/unregister-device",
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
        "/api/v1/platform-auth/discord/callback",
        "/api/v1/platform-auth/slack/callback",
        "/api/v1/support/rate-limit-status",
        "/api/v1/support/requests",
        "/api/v1/support/requests/my",
        "/api/v1/support/requests/with-attachments",
        "/api/v1/user/first-steps",
        "/api/v1/user/first-steps/collapse",
        "/api/v1/user/holo-card/card_id",
        "/api/v1/user/holo-card/colors",
        "/api/v1/user/logout",
        "/api/v1/user/me",
        "/api/v1/user/name",
        "/api/v1/user/timezone",
        "/api/v1/webhook/composio",
        "/api/v1/workflows/explore",
        "/health",
    ]


async def test_llm_spend_under_a_free_prefix_keeps_its_own_gate(gated_client: AsyncClient) -> None:
    """The handler calls the same fail-closed gate itself, since the allowlist prefix is a blunt instrument covering this paid route too."""
    assert is_free_path("/api/v1/onboarding/writing-style/regenerate-example")
    with patch(
        "app.decorators.entitlements.payment_service.get_cached_plan_type",
        new_callable=AsyncMock,
        return_value=PlanType.FREE,
    ):
        response = await gated_client.post(
            "/api/v1/onboarding/writing-style/regenerate-example",
            json={"edited_summary": "short and warm", "profession": "founder"},
        )
    assert response.status_code == 402


@pytest.mark.usefixtures("free_caller")
@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", "/api/v1/user/first-steps"), ("POST", "/api/v1/user/first-steps/collapse")],
)
async def test_the_activation_checklist_never_raises_the_paywall(
    gated_client: AsyncClient, method: str, path: str
) -> None:
    """A 402 here opens the app-wide non-dismissible paywall for up to 5 minutes on a user who just paid, off the stale plan cache."""
    response = await gated_client.request(method, path, json={"collapsed": True})

    assert response.status_code != 402


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
    """Outside WorkOSAuthMiddleware every request looks anonymous; outside CORSMiddleware the 402 blocks CORS headers and the modal never opens."""
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
    """Closed, but not as a paywall — the body must not claim a billing verdict that was never read."""
    with patch(
        "app.decorators.entitlements.payment_service.get_cached_plan_type",
        new_callable=AsyncMock,
        side_effect=ConnectionError("redis down"),
    ):
        response = await _get(_minimal_app(FAKE_USER), "/api/v1/paid")

    assert response.status_code == 503
    assert response.json() == {
        "message": ENTITLEMENT_UNAVAILABLE_MESSAGE,
        "code": "entitlement_unavailable",
    }


async def test_the_gate_asks_about_this_caller_and_names_the_path_it_blocked() -> None:
    """The feature argument makes a PAYWALL_BLOCKED event attributable to a surface instead of anonymous, so both args are asserted exactly."""
    gate = AsyncMock(side_effect=SubscriptionRequiredException())
    with patch("app.api.v1.middleware.entitlement.require_active_subscription", gate):
        response = await _get(_minimal_app(FAKE_USER), "/api/v1/paid")

    assert response.status_code == 402
    gate.assert_awaited_once_with(FAKE_USER.user_id, feature="/api/v1/paid")


async def test_a_gate_error_is_logged_with_the_caller_the_surface_and_the_cause() -> None:
    """The wide event is the only signal distinguishing an outage from a lapsed subscription; a missing error_type or mislabelled operation makes the alert unwritable."""
    with (
        patch(
            "app.api.v1.middleware.entitlement.require_active_subscription",
            new_callable=AsyncMock,
            side_effect=ConnectionError("redis down"),
        ),
        patch("app.api.v1.middleware.entitlement.log") as mock_log,
    ):
        response = await _get(_minimal_app(FAKE_USER), "/api/v1/paid")

    assert response.status_code == 503
    mock_log.error.assert_called_once_with(
        "Entitlement check failed — denying request (fail-closed)",
        user={"id": FAKE_USER.user_id},
        payment={"operation": "paywall_gate_error", "feature": "/api/v1/paid"},
        error_type="ConnectionError",
        error="redis down",
    )


async def test_an_unreadable_plan_is_a_503_not_a_paywall() -> None:
    """The body must not carry subscription_required (clients open the paywall on it); Retry-After lets the client recover since the gate runs before call_next."""
    with patch(
        "app.api.v1.middleware.entitlement.require_active_subscription",
        new_callable=AsyncMock,
        side_effect=ConnectionError("redis down"),
    ):
        response = await _get(_minimal_app(FAKE_USER), "/api/v1/paid")

    assert response.status_code == 503
    assert response.json() == {
        "message": ENTITLEMENT_UNAVAILABLE_MESSAGE,
        "code": "entitlement_unavailable",
    }
    assert response.headers["Retry-After"] == "5"


async def test_a_user_who_just_paid_passes_the_gate_off_the_row_and_refreshes_the_cache() -> None:
    """A cached FREE is confirmed from the row and the stale key dropped, so a just-paid user isn't 402'd until the TTL expires."""
    with (
        patch(
            "app.decorators.entitlements.payment_service.get_cached_plan_type",
            new_callable=AsyncMock,
            return_value=PlanType.FREE,
        ),
        patch(
            "app.decorators.entitlements.payment_service.get_user_subscription_status",
            new_callable=AsyncMock,
            return_value=MagicMock(plan_type=PlanType.PRO),
        ),
        patch(
            "app.decorators.entitlements.invalidate_plan_cache", new_callable=AsyncMock
        ) as invalidate,
    ):
        response = await _get(_minimal_app(FAKE_USER), "/api/v1/paid")

    assert response.status_code == 200
    assert response.json() == {"ok": "yes"}
    invalidate.assert_awaited_once_with(FAKE_USER.user_id)


async def test_a_genuine_free_verdict_is_still_a_402() -> None:
    """The 503 branch must not swallow the real block it sits next to."""
    with patch(
        "app.api.v1.middleware.entitlement.require_active_subscription",
        new_callable=AsyncMock,
        side_effect=SubscriptionRequiredException(),
    ):
        response = await _get(_minimal_app(FAKE_USER), "/api/v1/paid")

    assert response.status_code == 402
    assert response.json()["code"] == "subscription_required"


async def test_a_request_no_auth_middleware_touched_passes_through() -> None:
    """Routers excluded from WorkOSAuthMiddleware (/api/v1/bot) reach the gate with unset state; without a default this raises AttributeError and 500s."""
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
    assert all(path.startswith("/") for path in FREE_EXACT_PATHS)
    assert not any(path.startswith(FREE_PATH_PREFIXES) for path in FREE_EXACT_PATHS)


@pytest.mark.parametrize("path", sorted(FREE_EXACT_PATHS))
def test_exact_free_path_does_not_free_its_subtree(path: str) -> None:
    """/ and /api/v1/ are liveness aliases; as prefixes they would free everything."""
    assert is_free_path(path)
    assert not is_free_path(path + "api/v1/paid")
    assert not is_free_path(path + "paid")
