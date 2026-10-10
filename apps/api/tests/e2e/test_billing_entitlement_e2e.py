"""Billing gate as the user experiences it: pay, get in; lapse, get walled; outage, get told to retry.

Unit tests prove each half in isolation (payment service math here, middleware
routing there) and every existing e2e bypasses the gate entirely
(test_stream_transport mocks get_user_subscription_status to PRO). Nothing
proved the join: a Dodo-paid user actually passing the real middleware on a
real app, a lapsed user getting the exact 402 body the clients parse, and —
the incident that motivated this — an unreadable plan returning 503 instead of
waving a paying user at a paywall during a Redis blip.

Real: _create_test_app (full route table), EntitlementMiddleware,
require_active_subscription/is_paid, the real allowlist. Doubled: only the
billing backend (cached plan read, subscription status fetch) — Dodo/Mongo/
Redis never involved.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, Request, Response
from httpx import ASGITransport, AsyncClient
import pytest
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.v1.middleware.entitlement import EntitlementMiddleware
from app.decorators.entitlements import PAYWALL_MESSAGE
from app.models.payment_models import PlanType
from tests.conftest import FAKE_USER, _create_test_app

pytestmark = pytest.mark.e2e

ENT = "app.decorators.entitlements"
PAID_PROBE = "/e2e-paid-probe"


class _StubAuthMiddleware(BaseHTTPMiddleware):
    """Publish an authenticated user, as WorkOSAuthMiddleware would."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        request.state.user = FAKE_USER
        return await call_next(request)


@pytest.fixture(scope="module")
def gated_app() -> FastAPI:
    app = _create_test_app()

    @app.get(PAID_PROBE)
    async def _paid_probe() -> dict[str, bool]:
        return {"ok": True}

    app.add_middleware(EntitlementMiddleware)
    app.add_middleware(_StubAuthMiddleware)
    return app


@pytest.fixture
async def gated_client(gated_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=gated_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:  # NOSONAR
        yield ac


def _pro_status() -> SimpleNamespace:
    return SimpleNamespace(plan_type=PlanType.PRO)


def _free_status() -> SimpleNamespace:
    return SimpleNamespace(plan_type=PlanType.FREE)


class TestPaidUserPassesTheRealGate:
    async def test_cached_pro_reaches_the_handler(self, gated_client: AsyncClient) -> None:
        with (
            patch(
                f"{ENT}.payment_service.get_cached_plan_type",
                new_callable=AsyncMock,
                return_value=PlanType.PRO,
            ),
            patch(f"{ENT}.payment_service.get_user_subscription_status", new=AsyncMock()),
        ):
            response = await gated_client.get(PAID_PROBE)

        assert response.status_code == 200
        assert response.json() == {"ok": True}

    async def test_stale_free_cache_is_confirmed_live_before_refusing(
        self, gated_client: AsyncClient
    ) -> None:
        """A cached FREE that lags a fresh payment must not 402 a paying user."""
        with (
            patch(
                f"{ENT}.payment_service.get_cached_plan_type",
                new_callable=AsyncMock,
                return_value=PlanType.FREE,
            ),
            patch(
                f"{ENT}.payment_service.get_user_subscription_status",
                new_callable=AsyncMock,
                return_value=_pro_status(),
            ),
            patch(f"{ENT}.invalidate_plan_cache", new_callable=AsyncMock) as invalidate,
        ):
            response = await gated_client.get(PAID_PROBE)

        assert response.status_code == 200
        invalidate.assert_awaited_once()


class TestLapsedUserSeesThePaywallContract:
    async def test_free_user_gets_402_with_the_parsed_body(self, gated_client: AsyncClient) -> None:
        with (
            patch(
                f"{ENT}.payment_service.get_cached_plan_type",
                new_callable=AsyncMock,
                return_value=PlanType.FREE,
            ),
            patch(
                f"{ENT}.payment_service.get_user_subscription_status",
                new_callable=AsyncMock,
                return_value=_free_status(),
            ),
            patch(f"{ENT}.capture_event") as capture,
        ):
            response = await gated_client.get("/api/v1/todos")

        assert response.status_code == 402
        body = response.json()
        assert body["code"] == "subscription_required"
        assert body["message"] == PAYWALL_MESSAGE
        # Minted on intent, never on refusal — clients already handle null.
        assert body["checkout_url"] is None
        capture.assert_called_once()

    async def test_free_paths_stay_open(self, gated_client: AsyncClient) -> None:
        """The way out of the paywall cannot itself be paywalled."""
        with (
            patch(
                f"{ENT}.payment_service.get_cached_plan_type",
                new_callable=AsyncMock,
                return_value=PlanType.FREE,
            ),
            patch(
                f"{ENT}.payment_service.get_user_subscription_status",
                new_callable=AsyncMock,
                return_value=_free_status(),
            ),
            patch(
                "app.services.payments.payment_service.payment_service.get_plans",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            response = await gated_client.get("/api/v1/payments/plans")

        assert response.status_code == 200
        assert response.json() == []


class TestUnreadablePlanIsRetryableNotRefusal:
    async def test_plan_outage_returns_503_with_retry_after(
        self, gated_client: AsyncClient
    ) -> None:
        """A plan outage is a 503 retry, not a 402 refusal — it once paywalled everyone during a Redis blip."""
        with (
            patch(
                f"{ENT}.payment_service.get_cached_plan_type",
                new_callable=AsyncMock,
                side_effect=RuntimeError("redis down"),
            ),
            patch(
                f"{ENT}.payment_service.get_user_subscription_status",
                new_callable=AsyncMock,
                side_effect=RuntimeError("redis down"),
            ),
        ):
            response = await gated_client.get("/api/v1/todos")

        assert response.status_code == 503
        body = response.json()
        assert body["code"] == "entitlement_unavailable"
        assert "subscription_required" not in response.text
        assert response.headers.get("retry-after") is not None
