"""Unit tests for cleanup_tasks ARQ worker."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.workers.tasks.cleanup_tasks import cleanup_stuck_personalization


def _make_stuck_user(
    user_id: str = "507f1f77bcf86cd799439011",
    updated_at_minutes_ago: int = 60,
) -> dict:
    """Build a minimal stuck-user document as returned by MongoDB."""
    updated_at = datetime.now(UTC) - timedelta(minutes=updated_at_minutes_ago)
    return {
        "_id": MagicMock(__str__=lambda s: user_id),
        "onboarding": {"phase": "personalization_pending"},
        "updated_at": updated_at,
    }


@pytest.mark.unit
class TestCleanupStuckPersonalization:
    """Tests for cleanup_stuck_personalization ARQ task."""

    @pytest.fixture
    def ctx(self) -> dict:
        return {}

    # ------------------------------------------------------------------
    # Boundary: 0 users
    # ------------------------------------------------------------------

    async def test_no_stuck_users_returns_early(self, ctx):
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[])

        with patch("app.workers.tasks.cleanup_tasks.users_collection") as mock_col:
            mock_col.find = MagicMock(return_value=mock_cursor)
            result = await cleanup_stuck_personalization(ctx)

        assert "No stuck users found" in result

    async def test_zero_stuck_users_never_enqueues_job(self, ctx):
        """When there are 0 stuck users, enqueue_intelligence_job must never be called."""
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[])

        with (
            patch("app.workers.tasks.cleanup_tasks.users_collection") as mock_col,
            patch(
                "app.workers.tasks.cleanup_tasks.enqueue_intelligence_job",
                new_callable=AsyncMock,
            ) as mock_enqueue,
        ):
            mock_col.find = MagicMock(return_value=mock_cursor)
            await cleanup_stuck_personalization(ctx)

        mock_enqueue.assert_not_called()

    # ------------------------------------------------------------------
    # Boundary: 1 user
    # ------------------------------------------------------------------

    async def test_one_stuck_user_is_requeued_with_correct_id(self, ctx):
        """Exactly the one user's ID must be passed to enqueue_intelligence_job."""
        users = [_make_stuck_user("only_user_id")]
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=users)

        with (
            patch("app.workers.tasks.cleanup_tasks.users_collection") as mock_col,
            patch(
                "app.workers.tasks.cleanup_tasks.is_intelligence_job_live",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.workers.tasks.cleanup_tasks.enqueue_intelligence_job",
                new_callable=AsyncMock,
                return_value="job_solo",
            ) as mock_enqueue,
        ):
            mock_col.find = MagicMock(return_value=mock_cursor)
            result = await cleanup_stuck_personalization(ctx)

        mock_enqueue.assert_awaited_once_with("only_user_id")
        assert "1 re-queued" in result
        assert "0 errors" in result

    # ------------------------------------------------------------------
    # Pagination limit validation
    # ------------------------------------------------------------------

    async def test_to_list_called_with_length_50(self, ctx):
        """to_list MUST be called with length=50 — changing it to any other
        value must cause this test to fail."""
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[])

        with patch("app.workers.tasks.cleanup_tasks.users_collection") as mock_col:
            mock_col.find = MagicMock(return_value=mock_cursor)
            await cleanup_stuck_personalization(ctx)

        mock_cursor.to_list.assert_awaited_once_with(length=50)

    async def test_pagination_limit_50_processes_exactly_50_users(self, ctx):
        """The DB cursor is capped at 50; the task must process exactly those
        50 users and not request more.  If the limit in the production code is
        changed (e.g. to 100 or removed), the to_list assertion above fails AND
        this test verifies the downstream processing count is still bounded."""
        users = [_make_stuck_user(f"user_{i}") for i in range(50)]
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=users)

        with (
            patch("app.workers.tasks.cleanup_tasks.users_collection") as mock_col,
            patch(
                "app.workers.tasks.cleanup_tasks.is_intelligence_job_live",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.workers.tasks.cleanup_tasks.enqueue_intelligence_job",
                new_callable=AsyncMock,
                return_value="j",
            ) as mock_enqueue,
        ):
            mock_col.find = MagicMock(return_value=mock_cursor)
            result = await cleanup_stuck_personalization(ctx)

        # Exactly 50 enqueue calls — one per user returned from the cursor
        assert mock_enqueue.await_count == 50
        assert "50 re-queued" in result
        assert "found 50 candidates" in result

    async def test_pagination_limit_does_not_exceed_50_even_with_large_mock_return(self, ctx):
        """Simulate the cursor honouring the limit by returning only 50 of 100
        users.  The task itself must enqueue exactly the users it received."""
        # The cursor mock returns only 50 — mirroring MongoDB honouring length=50
        users = [_make_stuck_user(f"user_{i}") for i in range(50)]
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=users)

        with (
            patch("app.workers.tasks.cleanup_tasks.users_collection") as mock_col,
            patch(
                "app.workers.tasks.cleanup_tasks.is_intelligence_job_live",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.workers.tasks.cleanup_tasks.enqueue_intelligence_job",
                new_callable=AsyncMock,
                return_value="j",
            ) as mock_enqueue,
        ):
            mock_col.find = MagicMock(return_value=mock_cursor)
            await cleanup_stuck_personalization(ctx)

        # The task never processes more than what to_list(length=50) returns
        assert mock_enqueue.await_count == 50
        # Verify the DB query used the hard limit of 50
        mock_cursor.to_list.assert_awaited_once_with(length=50)

    # ------------------------------------------------------------------
    # Which users are re-queued
    # ------------------------------------------------------------------

    async def test_stuck_users_are_requeued_with_correct_ids(self, ctx):
        """Both user IDs must appear as arguments to enqueue_intelligence_job."""
        users = [
            _make_stuck_user("id_1"),
            _make_stuck_user("id_2"),
        ]
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=users)

        with (
            patch("app.workers.tasks.cleanup_tasks.users_collection") as mock_col,
            patch(
                "app.workers.tasks.cleanup_tasks.is_intelligence_job_live",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.workers.tasks.cleanup_tasks.enqueue_intelligence_job",
                new_callable=AsyncMock,
                return_value="job_abc",
            ) as mock_enqueue,
        ):
            mock_col.find = MagicMock(return_value=mock_cursor)
            result = await cleanup_stuck_personalization(ctx)

        # Verify the count reported in the result string
        assert "2 re-queued" in result
        assert "0 errors" in result

        # Verify WHICH users were actually enqueued.
        enqueued_ids = [c.args[0] for c in mock_enqueue.await_args_list]
        assert "id_1" in enqueued_ids
        assert "id_2" in enqueued_ids
        assert mock_enqueue.await_count == 2

    # ------------------------------------------------------------------
    # Enqueue function called with correct user id
    # ------------------------------------------------------------------

    async def test_enqueue_called_with_correct_user_id(self, ctx):
        users = [_make_stuck_user("id_1")]
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=users)

        with (
            patch("app.workers.tasks.cleanup_tasks.users_collection") as mock_col,
            patch(
                "app.workers.tasks.cleanup_tasks.is_intelligence_job_live",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.workers.tasks.cleanup_tasks.enqueue_intelligence_job",
                new_callable=AsyncMock,
                return_value="job_123",
            ) as mock_enqueue,
        ):
            mock_col.find = MagicMock(return_value=mock_cursor)
            await cleanup_stuck_personalization(ctx)

        mock_enqueue.assert_awaited_once_with("id_1")

    # ------------------------------------------------------------------
    # Error counting
    # ------------------------------------------------------------------

    async def test_failed_enqueue_returns_none_counts_as_error(self, ctx):
        users = [_make_stuck_user("id_1")]
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=users)

        with (
            patch("app.workers.tasks.cleanup_tasks.users_collection") as mock_col,
            patch(
                "app.workers.tasks.cleanup_tasks.is_intelligence_job_live",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.workers.tasks.cleanup_tasks.enqueue_intelligence_job",
                new_callable=AsyncMock,
                return_value=None,  # enqueue failure
            ),
        ):
            mock_col.find = MagicMock(return_value=mock_cursor)
            result = await cleanup_stuck_personalization(ctx)

        assert "0 re-queued" in result
        assert "1 errors" in result

    async def test_enqueue_exception_counts_as_error_not_raised(self, ctx):
        users = [_make_stuck_user("id_1")]
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=users)

        with (
            patch("app.workers.tasks.cleanup_tasks.users_collection") as mock_col,
            patch(
                "app.workers.tasks.cleanup_tasks.is_intelligence_job_live",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.workers.tasks.cleanup_tasks.enqueue_intelligence_job",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Redis down"),
            ),
        ):
            mock_col.find = MagicMock(return_value=mock_cursor)
            # Must NOT raise — per-user errors are swallowed
            result = await cleanup_stuck_personalization(ctx)

        assert "0 re-queued" in result
        assert "1 errors" in result

    async def test_mixed_success_and_failure_counts_correctly(self, ctx):
        users = [
            _make_stuck_user("id_ok"),
            _make_stuck_user("id_fail"),
        ]
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=users)

        call_count = 0

        async def selective_enqueue(user_id):
            nonlocal call_count
            call_count += 1
            if user_id == "id_ok":
                return "job_ok"
            raise RuntimeError("enqueue failed")

        with (
            patch("app.workers.tasks.cleanup_tasks.users_collection") as mock_col,
            patch(
                "app.workers.tasks.cleanup_tasks.is_intelligence_job_live",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.workers.tasks.cleanup_tasks.enqueue_intelligence_job",
                new_callable=AsyncMock,
                side_effect=selective_enqueue,
            ) as mock_enqueue,
        ):
            mock_col.find = MagicMock(return_value=mock_cursor)
            result = await cleanup_stuck_personalization(ctx)

        assert "1 re-queued" in result
        assert "1 errors" in result
        assert "found 2 candidates" in result

        # The succeeded user must have been enqueued; the failed one attempted
        enqueued_ids = [c.args[0] for c in mock_enqueue.await_args_list]
        assert "id_ok" in enqueued_ids
        assert "id_fail" in enqueued_ids

    # ------------------------------------------------------------------
    # Query validation
    # ------------------------------------------------------------------

    async def test_custom_max_age_minutes_used_in_query(self, ctx):
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[])

        with patch("app.workers.tasks.cleanup_tasks.users_collection") as mock_col:
            mock_col.find = MagicMock(return_value=mock_cursor)
            before_call = datetime.now(UTC)
            await cleanup_stuck_personalization(ctx, max_age_minutes=60)
            after_call = datetime.now(UTC)

        query = mock_col.find.call_args[0][0]
        # The $or clause contains the updated_at cutoff
        or_clauses = query["$or"]
        cutoff_clause = next((c for c in or_clauses if "updated_at" in c), None)
        assert cutoff_clause is not None

        cutoff = cutoff_clause["updated_at"]["$lt"]
        expected_lower = before_call - timedelta(minutes=60)
        expected_upper = after_call - timedelta(minutes=60)
        assert (
            expected_lower - timedelta(seconds=5) <= cutoff <= expected_upper + timedelta(seconds=5)
        )

    async def test_query_uses_personalization_pending_phase(self, ctx):
        """Query must filter by onboarding.phase == PERSONALIZATION_PENDING."""
        from app.models.user_models import OnboardingPhase

        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[])

        with patch("app.workers.tasks.cleanup_tasks.users_collection") as mock_col:
            mock_col.find = MagicMock(return_value=mock_cursor)
            await cleanup_stuck_personalization(ctx)

        query = mock_col.find.call_args[0][0]
        assert query["onboarding.phase"] == OnboardingPhase.PERSONALIZATION_PENDING.value

    # ------------------------------------------------------------------
    # Exception handling
    # ------------------------------------------------------------------

    async def test_db_exception_returns_error_string_not_raises(self, ctx):
        with patch("app.workers.tasks.cleanup_tasks.users_collection") as mock_col:
            mock_col.find = MagicMock(side_effect=RuntimeError("MongoDB down"))
            result = await cleanup_stuck_personalization(ctx)

        # Unlike other workers this task catches the outer exception and returns it
        assert "Error in cleanup_stuck_personalization" in result

    # ------------------------------------------------------------------
    # Result message contents
    # ------------------------------------------------------------------

    async def test_result_message_contains_found_count(self, ctx):
        users = [
            _make_stuck_user("id_1"),
            _make_stuck_user("id_2"),
            _make_stuck_user("id_3"),
        ]
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=users)

        with (
            patch("app.workers.tasks.cleanup_tasks.users_collection") as mock_col,
            patch(
                "app.workers.tasks.cleanup_tasks.is_intelligence_job_live",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.workers.tasks.cleanup_tasks.enqueue_intelligence_job",
                new_callable=AsyncMock,
                return_value="j1",
            ) as mock_enqueue,
        ):
            mock_col.find = MagicMock(return_value=mock_cursor)
            result = await cleanup_stuck_personalization(ctx)

        assert "found 3 candidates" in result
        assert "3 re-queued" in result

        # Verify all three IDs were actually enqueued
        enqueued_ids = [c.args[0] for c in mock_enqueue.await_args_list]
        assert set(enqueued_ids) == {"id_1", "id_2", "id_3"}
