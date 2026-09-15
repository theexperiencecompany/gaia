"""The gate must not mint a Dodo checkout session per blocked request.

``test_entitlement_coverage`` sweeps the route table for what 402s; nothing
there watches what a 402 *costs*. This file does: it counts the checkout
sessions minted underneath a shell's worth of blocked requests.

Every mint is a ``get_plans`` call, an HTTP round-trip to Dodo and an insert
into ``checkout_sessions``. Minting inside the deny path puts all three on the
latency of every 402, and an unpaid user's shell load is many 402s, so the cost
is paid per blocked request rather than per user who actually wants to pay —
and Dodo sessions are single-use, so every one of them is waste. Under that
self-inflicted load Dodo rate-limits, which used to strip the link from the one
response that needed it (``"Could not mint checkout link for paywall
response"`` recurs through the local logs of 2026-09-06/07).
"""

from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, Request, Response
from httpx import ASGITransport, AsyncClient
import pytest
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.v1.middleware.entitlement import EntitlementMiddleware
from app.models.payment_models import PlanType
from tests.conftest import FAKE_USER, _create_test_app

pytestmark = pytest.mark.unit

ENT = "app.decorators.entitlements"

# Gated paths an authenticated shell fires on mount. None is allowlisted, so a
# free caller gets a 402 from each one before any feature page mounts.
SHELL_STARTUP_PATHS = (
    "/api/v1/conversations",
    "/api/v1/notifications",
    "/api/v1/todos",
)


class _StubAuthMiddleware(BaseHTTPMiddleware):
    """Publish an authenticated user, as ``WorkOSAuthMiddleware`` would."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        request.state.user = FAKE_USER
        return await call_next(request)


@pytest.fixture(scope="module")
def gated_app() -> FastAPI:
    app = _create_test_app()
    app.add_middleware(EntitlementMiddleware)
    app.add_middleware(_StubAuthMiddleware)
    return app


@pytest.fixture
async def gated_client(gated_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=gated_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:  # NOSONAR
        yield ac


def _checkout(payment_link: str) -> MagicMock:
    checkout = MagicMock()
    checkout.checkout.payment_link = payment_link
    return checkout


class TestGateDoesNotMintPerBlockedRequest:
    async def test_a_shell_load_of_402s_mints_no_checkout_sessions(
        self, gated_client: AsyncClient
    ) -> None:
        """Three blocked startup calls must not become three Dodo sessions.

        The paywall body carries no checkout link: the client mints one from
        the allowlisted ``POST /api/v1/payments/checkout-session`` when the user
        actually asks to subscribe. Dodo sessions are single-use, so minting one
        the user never visits is pure waste at Dodo and in Mongo.
        """
        mint = AsyncMock(return_value=_checkout("https://checkout.dodo.test/abc"))
        with (
            patch(
                f"{ENT}.payment_service.get_cached_plan_type",
                new_callable=AsyncMock,
                return_value=PlanType.FREE,
            ),
            patch(f"{ENT}.payment_service.create_pro_checkout", new=mint),
        ):
            for path in SHELL_STARTUP_PATHS:
                response = await gated_client.get(path)
                assert response.status_code == 402, path

        assert mint.await_count == 0, (
            f"gate minted {mint.await_count} Dodo checkout session(s) for "
            f"{len(SHELL_STARTUP_PATHS)} blocked requests; it must mint none"
        )

    async def test_the_402_body_still_names_the_paywall(self, gated_client: AsyncClient) -> None:
        """Dropping the minted link must not change the code clients match on."""
        with (
            patch(
                f"{ENT}.payment_service.get_cached_plan_type",
                new_callable=AsyncMock,
                return_value=PlanType.FREE,
            ),
            patch(
                f"{ENT}.payment_service.create_pro_checkout",
                new=AsyncMock(return_value=_checkout("https://checkout.dodo.test/abc")),
            ),
        ):
            response = await gated_client.get("/api/v1/conversations")

        assert response.status_code == 402
        assert response.json()["code"] == "subscription_required"
