"""Unit tests for cleanup_tasks ARQ worker."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.user_models import UserDocument
from app.workers.tasks.cleanup_tasks import cleanup_stuck_personalization

_FIND = "app.workers.tasks.cleanup_tasks.user_repository.find_stuck_personalization"
_IS_LIVE = "app.workers.tasks.cleanup_tasks.is_intelligence_job_live"
_ENQUEUE = "app.workers.tasks.cleanup_tasks.enqueue_gmail_personalization"
_LOG = "app.workers.tasks.cleanup_tasks.log"


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


def _logged_last_updates(mock_log: MagicMock) -> list[str]:
    """Return the last_update field the task stamped on its wide-event log lines."""
    return [
        c.kwargs["last_update"] for c in mock_log.info.call_args_list if "last_update" in c.kwargs
    ]


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

    # ------------------------------------------------------------------
    # Live pipeline is never aborted
    # ------------------------------------------------------------------

    async def test_live_pipeline_user_is_skipped_not_requeued(self, ctx):
        """A user whose ARQ job is still live must be left alone, not re-queued."""
        user = _make_stuck_user("id_live")
        with (
            patch(_FIND, new_callable=AsyncMock, return_value=[user]),
            patch(_IS_LIVE, new_callable=AsyncMock, return_value=True),
            patch(_ENQUEUE, new_callable=AsyncMock, return_value="job_x") as mock_enqueue,
            patch(_LOG) as mock_log,
        ):
            result = await cleanup_stuck_personalization(ctx)

        mock_enqueue.assert_not_awaited()
        assert "0 re-queued" in result
        assert "1 skipped (live)" in result
        assert _logged_last_updates(mock_log) == [str(user.updated_at)]

    # ------------------------------------------------------------------
    # last_update stamped on the wide event
    # ------------------------------------------------------------------

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
