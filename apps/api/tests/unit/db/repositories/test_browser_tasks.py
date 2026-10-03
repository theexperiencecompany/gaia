"""Unit tests for the browser-tasks repository's recent-history read."""

from unittest.mock import AsyncMock, patch

from app.db.repositories.browser_tasks import BrowserTasksRepository


class TestListRecentForUser:
    async def test_reads_this_users_tasks_newest_first_up_to_the_limit(self) -> None:
        """Settings history walks this list newest-first and stops at the given limit."""
        repo = BrowserTasksRepository()
        with patch.object(repo, "list_for_user", new=AsyncMock(return_value=[])) as list_for_user:
            await repo.list_recent_for_user("user-1", limit=10)

        list_for_user.assert_awaited_once_with(
            "user-1",
            sort=[("created_at", -1)],
            limit=10,
        )

    async def test_defaults_to_a_limit_of_twenty(self) -> None:
        repo = BrowserTasksRepository()
        with patch.object(repo, "list_for_user", new=AsyncMock(return_value=[])) as list_for_user:
            await repo.list_recent_for_user("user-1")

        list_for_user.assert_awaited_once_with(
            "user-1",
            sort=[("created_at", -1)],
            limit=20,
        )
