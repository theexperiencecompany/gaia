"""Unit tests for the usage API endpoints.

Tests cover:
- GET /api/v1/usage/summary
- GET /api/v1/usage/history
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient
import pytest

from app.models.payment_models import PlanType
from app.services.analytics_service import AnalyticsEvents

SUMMARY_URL = "/api/v1/usage/summary"
HISTORY_URL = "/api/v1/usage/history"
ANALYTICS_PATCH = "app.api.v1.endpoints.usage.capture_context_event"


@pytest.fixture(autouse=True)
def _noop_analytics():
    """Neutralize capture_context_event for every test in this module.

    The test app runs a no-op lifespan, so the PostHog provider is never
    registered; a bare capture_context_event call would raise KeyError on the
    missing provider. Tests that assert on captures patch the call site again
    and assert on their own mock.
    """
    with patch(ANALYTICS_PATCH):
        yield


# Patch targets
_PAYMENT_SERVICE = (
    "app.services.payments.payment_service.payment_service.get_user_subscription_status"
)
_GET_REALTIME_USAGE = "app.api.v1.endpoints.usage._get_realtime_usage"
_GET_BUDGET_STATUS = "app.api.v1.endpoints.usage.get_budget_status"
_USAGE_SERVICE = "app.api.v1.endpoints.usage.usage_service"

_MOCK_BUDGET = {
    "daily": {"percentage": 12.0, "reset_time": "2025-01-02T00:00:00+00:00"},
    "monthly": None,
    "per_request_token_ceiling": 300_000,
}


def _mock_subscription(plan_type: str = "free") -> MagicMock:
    sub = MagicMock()
    sub.plan_type = PlanType(plan_type)
    return sub


# ---------------------------------------------------------------------------
# GET /usage/summary
# ---------------------------------------------------------------------------


class TestGetUsageSummary:
    """Tests for the get usage summary endpoint."""

    async def test_get_summary_returns_200(self, client: AsyncClient):
        mock_sub = _mock_subscription()
        mock_features: dict = {
            "chat": {
                "title": "Chat Messages",
                "description": "AI chat messages",
                # Pro's limits ride every feature so a free UI can show the delta.
                "upgrade": {"day": 0, "month": 60000},
                "periods": {
                    "day": {
                        "used": 5,
                        "limit": 50,
                        "percentage": 10.0,
                        "reset_time": "2025-01-02T00:00:00+00:00",
                        "remaining": 45,
                    }
                },
            }
        }

        with (
            patch(_PAYMENT_SERVICE, new_callable=AsyncMock, return_value=mock_sub),
            patch(
                _GET_REALTIME_USAGE,
                new_callable=AsyncMock,
                return_value=mock_features,
            ),
            patch(_GET_BUDGET_STATUS, new_callable=AsyncMock, return_value=_MOCK_BUDGET),
        ):
            response = await client.get(SUMMARY_URL)

        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == "507f1f77bcf86cd799439011"
        assert data["plan_type"] == "free"
        # The usage UI leads with the cost-walled chat feature, sourced from config.
        assert data["primary_feature"] == "chat_messages"
        assert "features" in data
        assert data["budget"] == _MOCK_BUDGET
        assert "last_updated" in data

    async def test_summary_captures_usage_queried(self, client: AsyncClient):
        mock_sub = _mock_subscription()
        mock_features: dict = {
            "chat": {
                "title": "Chat Messages",
                "description": "AI chat messages",
                "upgrade": {"day": 0, "month": 60000},
                "periods": {
                    "day": {
                        "used": 5,
                        "limit": 50,
                        "percentage": 10.0,
                        "reset_time": "2025-01-02T00:00:00+00:00",
                        "remaining": 45,
                    }
                },
            }
        }

        with (
            patch(_PAYMENT_SERVICE, new_callable=AsyncMock, return_value=mock_sub),
            patch(
                _GET_REALTIME_USAGE,
                new_callable=AsyncMock,
                return_value=mock_features,
            ),
            patch(_GET_BUDGET_STATUS, new_callable=AsyncMock, return_value=_MOCK_BUDGET),
            patch(ANALYTICS_PATCH) as mock_capture,
        ):
            response = await client.get(SUMMARY_URL)

        assert response.status_code == 200
        mock_capture.assert_called_once_with(AnalyticsEvents.USAGE_QUERIED, {"plan_type": "free"})
        assert type(mock_capture.call_args.args[1]["plan_type"]) is str

    async def test_get_summary_pro_plan(self, client: AsyncClient):
        mock_sub = _mock_subscription("pro")

        with (
            patch(_PAYMENT_SERVICE, new_callable=AsyncMock, return_value=mock_sub),
            patch(_GET_REALTIME_USAGE, new_callable=AsyncMock, return_value={}),
            patch(_GET_BUDGET_STATUS, new_callable=AsyncMock, return_value=_MOCK_BUDGET),
        ):
            response = await client.get(SUMMARY_URL)

        assert response.status_code == 200
        data = response.json()
        assert data["plan_type"] == "pro"

    async def test_get_summary_service_error_returns_500(self, client: AsyncClient):
        with patch(
            _PAYMENT_SERVICE,
            new_callable=AsyncMock,
            side_effect=Exception("Redis down"),
        ):
            response = await client.get(SUMMARY_URL)

        assert response.status_code == 500


# ---------------------------------------------------------------------------
# GET /usage/history
# ---------------------------------------------------------------------------


class TestGetUsageHistory:
    """Tests for the get usage history endpoint."""

    async def test_get_history_returns_200(self, client: AsyncClient):
        mock_feature = MagicMock()
        mock_feature.feature_key = "chat"
        mock_feature.period = "day"
        mock_feature.used = 10
        mock_feature.limit = 50

        mock_snapshot = MagicMock()
        mock_snapshot.created_at = datetime(2025, 1, 1, tzinfo=UTC)
        mock_snapshot.plan_type = "free"
        mock_snapshot.features = [mock_feature]

        with patch(
            f"{_USAGE_SERVICE}.get_usage_history",
            new_callable=AsyncMock,
            return_value=[mock_snapshot],
        ):
            response = await client.get(HISTORY_URL, params={"days": 7})

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    async def test_get_history_default_days(self, client: AsyncClient):
        with patch(
            f"{_USAGE_SERVICE}.get_usage_history",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_get:
            response = await client.get(HISTORY_URL)

        assert response.status_code == 200
        # Default is 7 days
        mock_get.assert_awaited_once_with("507f1f77bcf86cd799439011", None, 7)

    async def test_get_history_with_feature_filter(self, client: AsyncClient):
        with (
            patch(
                "app.api.v1.endpoints.usage.FEATURE_LIMITS",
                {"chat": MagicMock()},
            ),
            patch(
                f"{_USAGE_SERVICE}.get_usage_history",
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_get,
        ):
            response = await client.get(HISTORY_URL, params={"feature_key": "chat"})

        assert response.status_code == 200
        mock_get.assert_awaited_once_with("507f1f77bcf86cd799439011", "chat", 7)

    async def test_get_history_unknown_feature_returns_400(self, client: AsyncClient):
        with patch(
            "app.api.v1.endpoints.usage.FEATURE_LIMITS",
            {"chat": MagicMock()},
        ):
            response = await client.get(HISTORY_URL, params={"feature_key": "nonexistent"})

        assert response.status_code == 400
        assert "Unknown feature" in response.json()["detail"]

    async def test_get_history_days_below_min_returns_422(self, client: AsyncClient):
        response = await client.get(HISTORY_URL, params={"days": 0})
        assert response.status_code == 422

    async def test_get_history_days_above_max_returns_422(self, client: AsyncClient):
        response = await client.get(HISTORY_URL, params={"days": 91})
        assert response.status_code == 422

    async def test_get_history_service_error_returns_500(self, client: AsyncClient):
        with patch(
            f"{_USAGE_SERVICE}.get_usage_history",
            new_callable=AsyncMock,
            side_effect=Exception("DB error"),
        ):
            response = await client.get(HISTORY_URL)

        assert response.status_code == 500
