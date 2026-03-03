"""Unit tests for cleanup_tasks ARQ worker."""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.workers.tasks.cleanup_tasks import cleanup_stuck_personalization


def _make_stuck_user(
    user_id: str = "507f1f77bcf86cd799439011",
    bio_status: str = "processing",
    updated_at_minutes_ago: int = 60,
) -> dict:
    """Build a minimal stuck-user document as returned by MongoDB."""
    updated_at = datetime.now(timezone.utc) - timedelta(minutes=updated_at_minutes_ago)
    return {
        "_id": MagicMock(__str__=lambda s: user_id),
        "onboarding": {"bio_status": bio_status, "completed": True},
        "updated_at": updated_at,
    }


@pytest.mark.unit
class TestCleanupStuckPersonalization:
    """Tests for cleanup_stuck_personalization ARQ task."""

    @pytest.fixture
    def ctx(self) -> dict:
        return {}

    async def test_no_stuck_users_returns_early(self, ctx):
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[])

        with patch(
            "app.workers.tasks.cleanup_tasks.users_collection"
        ) as mock_col:
            mock_col.find = MagicMock(return_value=mock_cursor)
            result = await cleanup_stuck_personalization(ctx)

        assert "No stuck users found" in result

    async def test_stuck_users_are_requeued(self, ctx):
        users = [
            _make_stuck_user("id_1", "processing"),
            _make_stuck_user("id_2", "pending"),
        ]
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=users)

        mock_job = MagicMock()
        mock_job.job_id = "job_abc"
        mock_pool = AsyncMock()
        mock_pool.enqueue_job = AsyncMock(return_value=mock_job)

        with (
            patch(
                "app.workers.tasks.cleanup_tasks.users_collection"
            ) as mock_col,
            patch(
                "app.workers.tasks.cleanup_tasks.RedisPoolManager"
            ) as mock_redis_mgr,
        ):
            mock_col.find = MagicMock(return_value=mock_cursor)
            mock_redis_mgr.get_pool = AsyncMock(return_value=mock_pool)

            result = await cleanup_stuck_personalization(ctx)

        assert "2 users re-queued" in result
        assert "0 errors" in result

    async def test_enqueue_called_with_correct_task_name(self, ctx):
        users = [_make_stuck_user("id_1", "processing")]
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=users)

        mock_job = MagicMock()
        mock_job.job_id = "job_123"
        mock_pool = AsyncMock()
        mock_pool.enqueue_job = AsyncMock(return_value=mock_job)

        with (
            patch(
                "app.workers.tasks.cleanup_tasks.users_collection"
            ) as mock_col,
            patch(
                "app.workers.tasks.cleanup_tasks.RedisPoolManager"
            ) as mock_redis_mgr,
        ):
            mock_col.find = MagicMock(return_value=mock_cursor)
            mock_redis_mgr.get_pool = AsyncMock(return_value=mock_pool)

            await cleanup_stuck_personalization(ctx)

        mock_pool.enqueue_job.assert_awaited_once_with(
            "process_personalization_task", "id_1"
        )

    async def test_failed_enqueue_returns_none_counts_as_error(self, ctx):
        users = [_make_stuck_user("id_1", "processing")]
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=users)

        mock_pool = AsyncMock()
        mock_pool.enqueue_job = AsyncMock(return_value=None)  # enqueue failure

        with (
            patch(
                "app.workers.tasks.cleanup_tasks.users_collection"
            ) as mock_col,
            patch(
                "app.workers.tasks.cleanup_tasks.RedisPoolManager"
            ) as mock_redis_mgr,
        ):
            mock_col.find = MagicMock(return_value=mock_cursor)
            mock_redis_mgr.get_pool = AsyncMock(return_value=mock_pool)

            result = await cleanup_stuck_personalization(ctx)

        assert "0 users re-queued" in result
        assert "1 errors" in result

    async def test_enqueue_exception_counts_as_error_not_raised(self, ctx):
        users = [_make_stuck_user("id_1", "processing")]
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=users)

        mock_pool = AsyncMock()
        mock_pool.enqueue_job = AsyncMock(side_effect=RuntimeError("Redis down"))

        with (
            patch(
                "app.workers.tasks.cleanup_tasks.users_collection"
            ) as mock_col,
            patch(
                "app.workers.tasks.cleanup_tasks.RedisPoolManager"
            ) as mock_redis_mgr,
        ):
            mock_col.find = MagicMock(return_value=mock_cursor)
            mock_redis_mgr.get_pool = AsyncMock(return_value=mock_pool)

            # Must NOT raise — per-user errors are swallowed
            result = await cleanup_stuck_personalization(ctx)

        assert "0 users re-queued" in result
        assert "1 errors" in result

    async def test_mixed_success_and_failure_counts_correctly(self, ctx):
        users = [
            _make_stuck_user("id_ok", "processing"),
            _make_stuck_user("id_fail", "pending"),
        ]
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=users)

        success_job = MagicMock()
        success_job.job_id = "job_ok"

        call_count = 0

        async def selective_enqueue(task_name, user_id):
            nonlocal call_count
            call_count += 1
            if user_id == "id_ok":
                return success_job
            raise RuntimeError("enqueue failed")

        mock_pool = AsyncMock()
        mock_pool.enqueue_job = AsyncMock(side_effect=selective_enqueue)

        with (
            patch(
                "app.workers.tasks.cleanup_tasks.users_collection"
            ) as mock_col,
            patch(
                "app.workers.tasks.cleanup_tasks.RedisPoolManager"
            ) as mock_redis_mgr,
        ):
            mock_col.find = MagicMock(return_value=mock_cursor)
            mock_redis_mgr.get_pool = AsyncMock(return_value=mock_pool)

            result = await cleanup_stuck_personalization(ctx)

        assert "1 users re-queued" in result
        assert "1 errors" in result
        assert "2 stuck users" in result

    async def test_custom_max_age_minutes_used_in_query(self, ctx):
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[])

        with patch(
            "app.workers.tasks.cleanup_tasks.users_collection"
        ) as mock_col:
            mock_col.find = MagicMock(return_value=mock_cursor)
            before_call = datetime.now(timezone.utc)
            await cleanup_stuck_personalization(ctx, max_age_minutes=60)
            after_call = datetime.now(timezone.utc)

        query = mock_col.find.call_args[0][0]
        # The $or clause contains the updated_at cutoff
        or_clauses = query["$or"]
        cutoff_clause = next(
            (c for c in or_clauses if "updated_at" in c), None
        )
        assert cutoff_clause is not None

        cutoff = cutoff_clause["updated_at"]["$lt"]
        expected_lower = before_call - timedelta(minutes=60)
        expected_upper = after_call - timedelta(minutes=60)
        assert expected_lower - timedelta(seconds=5) <= cutoff <= expected_upper + timedelta(seconds=5)

    async def test_query_only_looks_at_onboarding_completed_users(self, ctx):
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[])

        with patch(
            "app.workers.tasks.cleanup_tasks.users_collection"
        ) as mock_col:
            mock_col.find = MagicMock(return_value=mock_cursor)
            await cleanup_stuck_personalization(ctx)

        query = mock_col.find.call_args[0][0]
        assert query["onboarding.completed"] is True

    async def test_db_exception_returns_error_string_not_raises(self, ctx):
        with patch(
            "app.workers.tasks.cleanup_tasks.users_collection"
        ) as mock_col:
            mock_col.find = MagicMock(side_effect=RuntimeError("MongoDB down"))
            result = await cleanup_stuck_personalization(ctx)

        # Unlike other workers this task catches the outer exception and returns it
        assert "Error in cleanup_stuck_personalization" in result

    async def test_result_message_contains_found_count(self, ctx):
        users = [
            _make_stuck_user("id_1", "processing"),
            _make_stuck_user("id_2", "pending"),
            _make_stuck_user("id_3", "processing"),
        ]
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=users)

        mock_job = MagicMock()
        mock_job.job_id = "j1"
        mock_pool = AsyncMock()
        mock_pool.enqueue_job = AsyncMock(return_value=mock_job)

        with (
            patch(
                "app.workers.tasks.cleanup_tasks.users_collection"
            ) as mock_col,
            patch(
                "app.workers.tasks.cleanup_tasks.RedisPoolManager"
            ) as mock_redis_mgr,
        ):
            mock_col.find = MagicMock(return_value=mock_cursor)
            mock_redis_mgr.get_pool = AsyncMock(return_value=mock_pool)

            result = await cleanup_stuck_personalization(ctx)

        assert "3 stuck users" in result
        assert "3 users re-queued" in result
