"""Unit tests for the checkout-sessions repository's recent-sessions read."""

from unittest.mock import AsyncMock, patch

from app.db.repositories.checkout_sessions import CheckoutSessionsRepository


class TestListRecentForUser:
    async def test_reads_this_users_sessions_newest_first_up_to_the_limit(self) -> None:
        """Payment verification walks this list newest-first and stops at the
        first session Dodo calls paid. Sorted the other way it would walk into
        the user's oldest sessions and give up before reaching the one they just
        paid, which is invisible to every caller that mocks this repository."""
        repo = CheckoutSessionsRepository()
        with patch.object(repo, "_find", new=AsyncMock(return_value=[])) as find:
            await repo.list_recent_for_user("user-1", limit=10)

        find.assert_awaited_once_with(
            {"user_id": "user-1"},
            sort=[("created_at", -1)],
            limit=10,
        )
