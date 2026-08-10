"""Unit tests for UsageService.

The service is a thin orchestration over ``usage_snapshot_repository``; these
tests mock that repository (never the DB) and assert the service's own behaviour
— delegation and the feature-key filter. The repository's hourly-upsert and
scoping behaviour is covered by the real-DB contract suite.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.models.usage_models import FeatureUsage, UsagePeriod, UserUsageSnapshot
from app.services import usage_service as usage_service_module
from app.services.usage_service import UsageService

NOW = datetime.now(UTC)


def _feature(key: str, used: int = 1) -> FeatureUsage:
    return FeatureUsage(
        feature_key=key,
        feature_title=key.title(),
        period=UsagePeriod.DAY,
        used=used,
        limit=100,
        reset_time=NOW,
    )


def _snapshot(
    *, user_id: str = "user123", features: list[FeatureUsage] | None = None
) -> UserUsageSnapshot:
    return UserUsageSnapshot(
        user_id=user_id,
        plan_type="pro",
        features=features if features is not None else [_feature("messages")],
    )


@pytest.fixture
def mock_usage_repo():
    repo = AsyncMock()
    with patch.object(usage_service_module, "usage_snapshot_repository", repo):
        yield repo


class TestSaveUsageSnapshot:
    async def test_delegates_to_upsert_hourly(self, mock_usage_repo):
        mock_usage_repo.upsert_hourly = AsyncMock(return_value="snap-id-1")
        snapshot = _snapshot()

        result = await UsageService.save_usage_snapshot(snapshot)

        assert result == "snap-id-1"
        mock_usage_repo.upsert_hourly.assert_awaited_once_with(snapshot)


class TestGetUsageHistory:
    async def test_returns_all_snapshots_no_filter(self, mock_usage_repo):
        mock_usage_repo.history_for_user = AsyncMock(return_value=[_snapshot()])

        result = await UsageService.get_usage_history("user123")

        assert len(result) == 1
        assert result[0].user_id == "user123"

    async def test_filters_by_feature_key(self, mock_usage_repo):
        snap = _snapshot(features=[_feature("messages"), _feature("images")])
        mock_usage_repo.history_for_user = AsyncMock(return_value=[snap])

        result = await UsageService.get_usage_history("user123", feature_key="messages")

        assert len(result) == 1
        assert len(result[0].features) == 1
        assert result[0].features[0].feature_key == "messages"

    async def test_excludes_snapshots_without_matching_feature(self, mock_usage_repo):
        snap = _snapshot(features=[_feature("images")])
        mock_usage_repo.history_for_user = AsyncMock(return_value=[snap])

        result = await UsageService.get_usage_history("user123", feature_key="nonexistent")

        assert result == []

    async def test_returns_empty_list_when_no_docs(self, mock_usage_repo):
        mock_usage_repo.history_for_user = AsyncMock(return_value=[])

        result = await UsageService.get_usage_history("user123")

        assert result == []

    async def test_custom_days_param_scopes_since(self, mock_usage_repo):
        mock_usage_repo.history_for_user = AsyncMock(return_value=[])

        await UsageService.get_usage_history("user123", days=7)

        call = mock_usage_repo.history_for_user.call_args
        assert call.args[0] == "user123"
        since = call.kwargs["since"]
        # ~7 days before today's midnight (allow a small window for test runtime).
        expected = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
            days=7
        )
        assert abs((since - expected).total_seconds()) < 5
