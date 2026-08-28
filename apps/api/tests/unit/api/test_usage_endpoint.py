"""Unit tests for the usage API endpoints.

Tests cover:
- GET /api/v1/usage/summary
- GET /api/v1/usage/history
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient
import pytest

from app.schemas.usage import UsageActivityResponse, UsageBudget, UsageSummary
from app.services.analytics_service import AnalyticsEvents

SUMMARY_URL = "/api/v1/usage/summary"
HISTORY_URL = "/api/v1/usage/history"
ACTIVITY_URL = "/api/v1/usage/activity"
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
_BUILD_USAGE_SUMMARY = "app.api.v1.endpoints.usage.build_usage_summary"
_USAGE_SERVICE = "app.api.v1.endpoints.usage.usage_service"

_MOCK_BUDGET = {
    "daily": {"percentage": 12.0, "reset_time": "2025-01-02T00:00:00+00:00"},
    "monthly": None,
    "per_request_token_ceiling": 300_000,
}


def _mock_summary(plan_type: str = "free") -> UsageSummary:
    return UsageSummary(
        user_id="507f1f77bcf86cd799439011",
        plan_type=plan_type,
        primary_feature="chat_messages",
        features={},
        budget=UsageBudget.model_validate(_MOCK_BUDGET),
        last_updated="2025-01-01T00:00:00+00:00",
    )


# ---------------------------------------------------------------------------
# GET /usage/summary
# ---------------------------------------------------------------------------


class TestGetUsageSummary:
    """Tests for the get usage summary endpoint."""

    async def test_get_summary_returns_200(self, client: AsyncClient):
        with patch(
            _BUILD_USAGE_SUMMARY,
            new_callable=AsyncMock,
            return_value=_mock_summary(),
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
        with (
            patch(
                _BUILD_USAGE_SUMMARY,
                new_callable=AsyncMock,
                return_value=_mock_summary(),
            ),
            patch(ANALYTICS_PATCH) as mock_capture,
        ):
            response = await client.get(SUMMARY_URL)

        assert response.status_code == 200
        mock_capture.assert_called_once_with(AnalyticsEvents.USAGE_QUERIED, {"plan_type": "free"})
        assert type(mock_capture.call_args.args[1]["plan_type"]) is str

    async def test_get_summary_pro_plan(self, client: AsyncClient):
        with patch(
            _BUILD_USAGE_SUMMARY,
            new_callable=AsyncMock,
            return_value=_mock_summary("pro"),
        ):
            response = await client.get(SUMMARY_URL)

        assert response.status_code == 200
        data = response.json()
        assert data["plan_type"] == "pro"

    async def test_summary_is_built_for_the_authenticated_user(self, client: AsyncClient):
        with patch(
            _BUILD_USAGE_SUMMARY,
            new_callable=AsyncMock,
            return_value=_mock_summary(),
        ) as mock_build:
            response = await client.get(SUMMARY_URL)

        assert response.status_code == 200
        mock_build.assert_awaited_once_with("507f1f77bcf86cd799439011")

    async def test_summary_records_period_and_feature_count_in_event(self, client: AsyncClient):
        with (
            patch(
                _BUILD_USAGE_SUMMARY,
                new_callable=AsyncMock,
                return_value=_mock_summary(),
            ),
            patch("app.api.v1.endpoints.usage.log") as mock_log,
        ):
            response = await client.get(SUMMARY_URL)

        assert response.status_code == 200
        mock_log.set.assert_any_call(period="realtime", result_count=0)

    async def test_get_summary_service_error_returns_500(self, client: AsyncClient):
        with patch(
            _BUILD_USAGE_SUMMARY,
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


# ---------------------------------------------------------------------------
# GET /usage/activity
# ---------------------------------------------------------------------------


class TestGetUsageActivity:
    """Tests for the get usage activity endpoint."""

    async def test_get_activity_returns_200(self, client: AsyncClient):
        activity = UsageActivityResponse(days=[], total=0, total_tokens=0, streak=0)
        with patch(
            "app.api.v1.endpoints.usage.get_activity",
            new_callable=AsyncMock,
            return_value=activity,
        ):
            response = await client.get(ACTIVITY_URL)

        assert response.status_code == 200
        assert response.json()["total"] == 0

    async def test_get_activity_service_error_returns_500(self, client: AsyncClient):
        with patch(
            "app.api.v1.endpoints.usage.get_activity",
            new_callable=AsyncMock,
            side_effect=Exception("DB error"),
        ):
            response = await client.get(ACTIVITY_URL)

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to get usage activity"
