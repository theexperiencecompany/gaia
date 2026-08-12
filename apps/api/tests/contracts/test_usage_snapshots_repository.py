"""Contract tests for UsageSnapshotsRepository (user-scoped, hourly-aggregated)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.db.repositories.usage_snapshots import UsageSnapshotsRepository
from app.models.usage_models import FeatureUsage, UsagePeriod, UserUsageSnapshot

NOW = datetime.now(UTC)


def _feature(used: int) -> FeatureUsage:
    return FeatureUsage(
        feature_key="chat",
        feature_title="Chat",
        period=UsagePeriod.MONTH,
        used=used,
        limit=100,
        reset_time=NOW,
    )


def _snap(**overrides: object) -> UserUsageSnapshot:
    data: dict[str, object] = {
        "user_id": "u1",
        "plan_type": "free",
        "features": [],
    }
    data.update(overrides)
    return UserUsageSnapshot.model_validate(data)


@pytest.fixture
def repo(raw_collection) -> UsageSnapshotsRepository:
    return UsageSnapshotsRepository()


class TestUsageSnapshotsRepository:
    async def test_upsert_creates_then_merges_within_the_hour(self, repo):
        first = await repo.upsert_hourly(
            _snap(user_id="u", plan_type="free", features=[_feature(1)])
        )
        assert isinstance(first, str) and first

        # A second upsert in the same hour merges into the same row (no explosion).
        second = await repo.upsert_hourly(
            _snap(
                user_id="u",
                plan_type="pro",
                features=[_feature(5)],
            )
        )
        assert second == first

        history = await repo.history_for_user("u", since=NOW - timedelta(days=1))
        assert len(history) == 1
        assert history[0].plan_type == "pro"  # merged latest tier
        assert history[0].features[0].used == 5
        assert history[0].updated_at is not None  # base stamped the merge

    async def test_history_is_scoped_to_user_and_since(self, repo):
        await repo.upsert_hourly(_snap(user_id="a"))
        await repo.upsert_hourly(_snap(user_id="b"))

        a_history = await repo.history_for_user("a", since=NOW - timedelta(days=1))
        assert [s.user_id for s in a_history] == ["a"]  # user isolation

        assert await repo.history_for_user("a", since=NOW + timedelta(days=1)) == []

    async def test_create_roundtrips_string_id(self, repo):
        created = await repo.create(_snap(user_id="rt"))
        assert isinstance(created.id, str) and created.id
        fetched = await repo.get(created.id, user_id="rt")
        assert fetched is not None and fetched.user_id == "rt"
