"""Unit tests for cleanup_tasks ARQ worker."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.models.user_models import UserDocument
from app.workers.tasks.cleanup_tasks import cleanup_stuck_personalization

_FIND = "app.workers.tasks.cleanup_tasks.user_repository.find_stuck_personalization"


def _make_stuck_user(
    user_id: str = "507f1f77bcf86cd799439011",
    updated_at_minutes_ago: int = 60,
) -> UserDocument:
    """Build a minimal stuck-user document as returned by the repository."""
    updated_at = datetime.now(UTC) - timedelta(minutes=updated_at_minutes_ago)
    return UserDocument(
        id=user_id,
        onboarding={"phase": "personalization_pending"},
        updated_at=updated_at,
    )


class TestCleanupStuckPersonalization:
    """Tests for cleanup_stuck_personalization ARQ task."""

    @pytest.fixture
    def ctx(self) -> dict:
        return {}

    # ------------------------------------------------------------------
    # Boundary: 0 users
    # ------------------------------------------------------------------

    async def test_no_stuck_users_returns_early(self, ctx):
        with patch(_FIND, new_callable=AsyncMock, return_value=[]):
            result = await cleanup_stuck_personalization(ctx)

        assert "No stuck users found" in result

    async def test_zero_stuck_users_never_enqueues_job(self, ctx):
        """When there are 0 stuck users, enqueue_gmail_personalization must never be called."""
        with (
            patch(_FIND, new_callable=AsyncMock, return_value=[]),
            patch(
                "app.workers.tasks.cleanup_tasks.enqueue_gmail_personalization",
                new_callable=AsyncMock,
            ) as mock_enqueue,
        ):
            await cleanup_stuck_personalization(ctx)

        mock_enqueue.assert_not_called()

    # ------------------------------------------------------------------
    # Boundary: 1 user
    # ------------------------------------------------------------------

    async def test_one_stuck_user_is_requeued_with_correct_id(self, ctx):
        """Exactly the one user's ID must be passed to enqueue_gmail_personalization."""
        with (
            patch(_FIND, new_callable=AsyncMock, return_value=[_make_stuck_user("only_user_id")]),
            patch(
                "app.workers.tasks.cleanup_tasks.is_intelligence_job_live",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.workers.tasks.cleanup_tasks.enqueue_gmail_personalization",
                new_callable=AsyncMock,
                return_value="job_solo",
            ) as mock_enqueue,
        ):
            result = await cleanup_stuck_personalization(ctx)

        mock_enqueue.assert_awaited_once_with("only_user_id")
        assert "1 re-queued" in result
        assert "0 errors" in result

    # ------------------------------------------------------------------
    # Pagination limit validation
    # ------------------------------------------------------------------

    async def test_finder_called_with_limit_50(self, ctx):
        """The finder MUST be called with limit=50 — changing it to any other
        value must cause this test to fail."""
        with patch(_FIND, new_callable=AsyncMock, return_value=[]) as mock_find:
            await cleanup_stuck_personalization(ctx)

        assert mock_find.await_count == 1
        assert mock_find.call_args.kwargs["limit"] == 50

    async def test_pagination_limit_50_processes_exactly_50_users(self, ctx):
        """The finder is capped at 50; the task must process exactly those 50 users."""
        users = [_make_stuck_user(f"user_{i}") for i in range(50)]
        with (
            patch(_FIND, new_callable=AsyncMock, return_value=users) as mock_find,
            patch(
                "app.workers.tasks.cleanup_tasks.is_intelligence_job_live",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.workers.tasks.cleanup_tasks.enqueue_gmail_personalization",
                new_callable=AsyncMock,
                return_value="j",
            ) as mock_enqueue,
        ):
            result = await cleanup_stuck_personalization(ctx)

        assert mock_enqueue.await_count == 50
        assert mock_find.call_args.kwargs["limit"] == 50
        assert "50 re-queued" in result
        assert "found 50 candidates" in result

    # ------------------------------------------------------------------
    # Which users are re-queued
    # ------------------------------------------------------------------

    async def test_stuck_users_are_requeued_with_correct_ids(self, ctx):
        """Both user IDs must appear as arguments to enqueue_gmail_personalization."""
        users = [_make_stuck_user("id_1"), _make_stuck_user("id_2")]
        with (
            patch(_FIND, new_callable=AsyncMock, return_value=users),
            patch(
                "app.workers.tasks.cleanup_tasks.is_intelligence_job_live",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.workers.tasks.cleanup_tasks.enqueue_gmail_personalization",
                new_callable=AsyncMock,
                return_value="job_abc",
            ) as mock_enqueue,
        ):
            result = await cleanup_stuck_personalization(ctx)

        assert "2 re-queued" in result
        assert "0 errors" in result

        enqueued_ids = [c.args[0] for c in mock_enqueue.await_args_list]
        assert "id_1" in enqueued_ids
        assert "id_2" in enqueued_ids
        assert mock_enqueue.await_count == 2

    async def test_enqueue_called_with_correct_user_id(self, ctx):
        with (
            patch(_FIND, new_callable=AsyncMock, return_value=[_make_stuck_user("id_1")]),
            patch(
                "app.workers.tasks.cleanup_tasks.is_intelligence_job_live",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.workers.tasks.cleanup_tasks.enqueue_gmail_personalization",
                new_callable=AsyncMock,
                return_value="job_123",
            ) as mock_enqueue,
        ):
            await cleanup_stuck_personalization(ctx)

        mock_enqueue.assert_awaited_once_with("id_1")

    # ------------------------------------------------------------------
    # Error counting
    # ------------------------------------------------------------------

    async def test_failed_enqueue_returns_none_counts_as_error(self, ctx):
        with (
            patch(_FIND, new_callable=AsyncMock, return_value=[_make_stuck_user("id_1")]),
            patch(
                "app.workers.tasks.cleanup_tasks.is_intelligence_job_live",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.workers.tasks.cleanup_tasks.enqueue_gmail_personalization",
                new_callable=AsyncMock,
                return_value=None,  # enqueue failure
            ),
        ):
            result = await cleanup_stuck_personalization(ctx)

        assert "0 re-queued" in result
        assert "1 errors" in result

    async def test_enqueue_exception_counts_as_error_not_raised(self, ctx):
        with (
            patch(_FIND, new_callable=AsyncMock, return_value=[_make_stuck_user("id_1")]),
            patch(
                "app.workers.tasks.cleanup_tasks.is_intelligence_job_live",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.workers.tasks.cleanup_tasks.enqueue_gmail_personalization",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Redis down"),
            ),
        ):
            # Must NOT raise — per-user errors are swallowed
            result = await cleanup_stuck_personalization(ctx)

        assert "0 re-queued" in result
        assert "1 errors" in result

    async def test_mixed_success_and_failure_counts_correctly(self, ctx):
        users = [_make_stuck_user("id_ok"), _make_stuck_user("id_fail")]

        async def selective_enqueue(user_id):
            if user_id == "id_ok":
                return "job_ok"
            raise RuntimeError("enqueue failed")

        with (
            patch(_FIND, new_callable=AsyncMock, return_value=users),
            patch(
                "app.workers.tasks.cleanup_tasks.is_intelligence_job_live",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.workers.tasks.cleanup_tasks.enqueue_gmail_personalization",
                new_callable=AsyncMock,
                side_effect=selective_enqueue,
            ) as mock_enqueue,
        ):
            result = await cleanup_stuck_personalization(ctx)

        assert "1 re-queued" in result
        assert "1 errors" in result
        assert "found 2 candidates" in result

        enqueued_ids = [c.args[0] for c in mock_enqueue.await_args_list]
        assert "id_ok" in enqueued_ids
        assert "id_fail" in enqueued_ids

    # ------------------------------------------------------------------
    # Query validation
    # ------------------------------------------------------------------

    async def test_custom_max_age_minutes_passed_as_cutoff(self, ctx):
        with patch(_FIND, new_callable=AsyncMock, return_value=[]) as mock_find:
            before_call = datetime.now(UTC)
            await cleanup_stuck_personalization(ctx, max_age_minutes=60)
            after_call = datetime.now(UTC)

        cutoff = mock_find.call_args.args[0]
        expected_lower = before_call - timedelta(minutes=60)
        expected_upper = after_call - timedelta(minutes=60)
        assert (
            expected_lower - timedelta(seconds=5) <= cutoff <= expected_upper + timedelta(seconds=5)
        )

    # ------------------------------------------------------------------
    # Exception handling
    # ------------------------------------------------------------------

    async def test_db_exception_returns_error_string_not_raises(self, ctx):
        with patch(_FIND, new_callable=AsyncMock, side_effect=RuntimeError("MongoDB down")):
            result = await cleanup_stuck_personalization(ctx)

        # Unlike other workers this task catches the outer exception and returns it
        assert "Error in cleanup_stuck_personalization" in result

    # ------------------------------------------------------------------
    # Result message contents
    # ------------------------------------------------------------------

    async def test_result_message_contains_found_count(self, ctx):
        users = [_make_stuck_user("id_1"), _make_stuck_user("id_2"), _make_stuck_user("id_3")]
        with (
            patch(_FIND, new_callable=AsyncMock, return_value=users),
            patch(
                "app.workers.tasks.cleanup_tasks.is_intelligence_job_live",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.workers.tasks.cleanup_tasks.enqueue_gmail_personalization",
                new_callable=AsyncMock,
                return_value="j1",
            ) as mock_enqueue,
        ):
            result = await cleanup_stuck_personalization(ctx)

        assert "found 3 candidates" in result
        assert "3 re-queued" in result

        enqueued_ids = [c.args[0] for c in mock_enqueue.await_args_list]
        assert set(enqueued_ids) == {"id_1", "id_2", "id_3"}
