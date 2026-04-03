"""Unit tests for UsageService."""

from datetime import datetime, timedelta, timezone
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.usage_models import (
    CreditUsage,
    FeatureUsage,
    UsagePeriod,
    UserUsageSnapshot,
)
from app.services.usage_service import UsageService


class _AsyncIterator:
    """Helper to create a proper async iterator from a list of items."""

    def __init__(self, items: List):
        self._items = iter(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._items)
        except StopIteration:
            raise StopAsyncIteration


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_usage_collection():
    with patch("app.services.usage_service.usage_snapshots_collection") as mock_col:
        yield mock_col


@pytest.fixture
def sample_snapshot():
    now = datetime.now(timezone.utc)
    return UserUsageSnapshot(
        user_id="user123",
        plan_type="pro",
        features=[
            FeatureUsage(
                feature_key="messages",
                feature_title="Messages",
                period=UsagePeriod.DAY,
                used=10,
                limit=100,
                reset_time=now + timedelta(hours=12),
            ),
            FeatureUsage(
                feature_key="images",
                feature_title="Images",
                period=UsagePeriod.MONTH,
                used=5,
                limit=50,
                reset_time=now + timedelta(days=15),
            ),
        ],
        credits=[
            CreditUsage(
                credits_used=1.5,
                period=UsagePeriod.MONTH,
                reset_time=now + timedelta(days=15),
            )
        ],
    )


@pytest.fixture
def sample_mongo_doc():
    from bson import ObjectId

    now = datetime.now(timezone.utc)
    return {
        "_id": ObjectId(),
        "user_id": "user123",
        "plan_type": "pro",
        "features": [
            {
                "feature_key": "messages",
                "feature_title": "Messages",
                "period": "day",
                "used": 10,
                "limit": 100,
                "reset_time": now + timedelta(hours=12),
                "updated_at": now,
            }
        ],
        "credits": [
            {
                "credits_used": 1.5,
                "period": "month",
                "reset_time": now + timedelta(days=15),
                "updated_at": now,
            }
        ],
        "snapshot_date": now,
        "created_at": now,
    }


# ---------------------------------------------------------------------------
# UsageService._prepare_doc_for_model
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPrepareDocForModel:
    def test_converts_objectid_to_string(self):
        from bson import ObjectId

        oid = ObjectId()
        doc = {"_id": oid, "user_id": "u1"}

        result = UsageService._prepare_doc_for_model(doc)

        assert result["_id"] == str(oid)

    def test_mutates_doc_in_place(self):
        from bson import ObjectId

        doc = {"_id": ObjectId(), "user_id": "u1"}
        result = UsageService._prepare_doc_for_model(doc)
        assert result is doc


# ---------------------------------------------------------------------------
# UsageService.save_usage_snapshot
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSaveUsageSnapshot:
    async def test_updates_existing_hourly_doc(
        self, mock_usage_collection, sample_snapshot
    ):
        from bson import ObjectId

        existing_id = ObjectId()
        mock_usage_collection.find_one = AsyncMock(
            return_value={"_id": existing_id, "user_id": "user123"}
        )
        mock_usage_collection.update_one = AsyncMock()

        result = await UsageService.save_usage_snapshot(sample_snapshot)

        assert result == str(existing_id)
        mock_usage_collection.update_one.assert_awaited_once()

    async def test_inserts_new_doc_when_no_existing(
        self, mock_usage_collection, sample_snapshot
    ):
        from bson import ObjectId

        inserted_id = ObjectId()
        mock_usage_collection.find_one = AsyncMock(return_value=None)
        mock_usage_collection.insert_one = AsyncMock(
            return_value=MagicMock(inserted_id=inserted_id)
        )

        result = await UsageService.save_usage_snapshot(sample_snapshot)

        assert result == str(inserted_id)
        mock_usage_collection.insert_one.assert_awaited_once()

    async def test_filter_query_uses_hourly_bucket(
        self, mock_usage_collection, sample_snapshot
    ):
        mock_usage_collection.find_one = AsyncMock(return_value=None)
        mock_usage_collection.insert_one = AsyncMock(
            return_value=MagicMock(inserted_id=MagicMock())
        )

        await UsageService.save_usage_snapshot(sample_snapshot)

        call_args = mock_usage_collection.find_one.call_args[0][0]
        assert call_args["user_id"] == "user123"
        assert "$gte" in call_args["snapshot_date"]
        assert "$lt" in call_args["snapshot_date"]


# ---------------------------------------------------------------------------
# UsageService.get_latest_usage_snapshot
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetLatestUsageSnapshot:
    async def test_returns_snapshot_when_found(
        self, mock_usage_collection, sample_mongo_doc
    ):
        mock_usage_collection.find_one = AsyncMock(return_value=sample_mongo_doc)

        result = await UsageService.get_latest_usage_snapshot("user123")

        assert result is not None
        assert isinstance(result, UserUsageSnapshot)
        assert result.user_id == "user123"
        assert result.plan_type == "pro"

    async def test_returns_none_when_not_found(self, mock_usage_collection):
        mock_usage_collection.find_one = AsyncMock(return_value=None)

        result = await UsageService.get_latest_usage_snapshot("user_nonexistent")

        assert result is None

    async def test_sort_by_created_at_desc(self, mock_usage_collection):
        mock_usage_collection.find_one = AsyncMock(return_value=None)

        await UsageService.get_latest_usage_snapshot("user123")

        mock_usage_collection.find_one.assert_awaited_once_with(
            {"user_id": "user123"}, sort=[("created_at", -1)]
        )


# ---------------------------------------------------------------------------
# UsageService.get_usage_history
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetUsageHistory:
    async def test_returns_all_snapshots_no_filter(self, mock_usage_collection):
        from bson import ObjectId

        now = datetime.now(timezone.utc)
        docs = [
            {
                "_id": ObjectId(),
                "user_id": "user123",
                "plan_type": "pro",
                "features": [
                    {
                        "feature_key": "messages",
                        "feature_title": "Messages",
                        "period": "day",
                        "used": 10,
                        "limit": 100,
                        "reset_time": now,
                        "updated_at": now,
                    }
                ],
                "credits": [],
                "snapshot_date": now,
                "created_at": now,
            }
        ]

        mock_cursor = MagicMock()
        mock_cursor.sort = MagicMock(return_value=_AsyncIterator(docs))
        mock_usage_collection.find = MagicMock(return_value=mock_cursor)

        result = await UsageService.get_usage_history("user123")

        assert len(result) == 1
        assert result[0].user_id == "user123"

    async def test_filters_by_feature_key(self, mock_usage_collection):
        from bson import ObjectId

        now = datetime.now(timezone.utc)
        docs = [
            {
                "_id": ObjectId(),
                "user_id": "user123",
                "plan_type": "pro",
                "features": [
                    {
                        "feature_key": "messages",
                        "feature_title": "Messages",
                        "period": "day",
                        "used": 10,
                        "limit": 100,
                        "reset_time": now,
                        "updated_at": now,
                    },
                    {
                        "feature_key": "images",
                        "feature_title": "Images",
                        "period": "month",
                        "used": 5,
                        "limit": 50,
                        "reset_time": now,
                        "updated_at": now,
                    },
                ],
                "credits": [],
                "snapshot_date": now,
                "created_at": now,
            }
        ]

        mock_cursor = MagicMock()
        mock_cursor.sort = MagicMock(return_value=_AsyncIterator(docs))
        mock_usage_collection.find = MagicMock(return_value=mock_cursor)

        result = await UsageService.get_usage_history("user123", feature_key="messages")

        assert len(result) == 1
        assert len(result[0].features) == 1
        assert result[0].features[0].feature_key == "messages"

    async def test_excludes_snapshots_without_matching_feature(
        self, mock_usage_collection
    ):
        from bson import ObjectId

        now = datetime.now(timezone.utc)
        docs = [
            {
                "_id": ObjectId(),
                "user_id": "user123",
                "plan_type": "pro",
                "features": [
                    {
                        "feature_key": "images",
                        "feature_title": "Images",
                        "period": "month",
                        "used": 5,
                        "limit": 50,
                        "reset_time": now,
                        "updated_at": now,
                    }
                ],
                "credits": [],
                "snapshot_date": now,
                "created_at": now,
            }
        ]

        mock_cursor = MagicMock()
        mock_cursor.sort = MagicMock(return_value=_AsyncIterator(docs))
        mock_usage_collection.find = MagicMock(return_value=mock_cursor)

        result = await UsageService.get_usage_history(
            "user123", feature_key="nonexistent"
        )

        assert len(result) == 0

    async def test_returns_empty_list_when_no_docs(self, mock_usage_collection):
        mock_cursor = MagicMock()
        mock_cursor.sort = MagicMock(return_value=_AsyncIterator([]))
        mock_usage_collection.find = MagicMock(return_value=mock_cursor)

        result = await UsageService.get_usage_history("user123")

        assert result == []

    async def test_custom_days_param(self, mock_usage_collection):
        mock_cursor = MagicMock()
        mock_cursor.sort = MagicMock(return_value=_AsyncIterator([]))
        mock_usage_collection.find = MagicMock(return_value=mock_cursor)

        await UsageService.get_usage_history("user123", days=7)

        call_args = mock_usage_collection.find.call_args[0][0]
        assert call_args["user_id"] == "user123"
        assert "$gte" in call_args["created_at"]
