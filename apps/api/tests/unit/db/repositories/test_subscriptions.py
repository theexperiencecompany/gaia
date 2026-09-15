"""Unit tests for the subscriptions repository's per-user wipe."""

from unittest.mock import AsyncMock, patch

from app.constants.cache import REPO_GLOBAL_SCOPE
from app.db.repositories.subscriptions import SubscriptionsRepository


class TestDeleteAllForUser:
    async def test_deletes_every_status_of_that_user_only(self) -> None:
        repo = SubscriptionsRepository()
        with patch.object(repo, "_delete_many", new=AsyncMock(return_value=3)) as delete_many:
            deleted = await repo.delete_all_for_user("user-1")

        delete_many.assert_awaited_once_with({"user_id": "user-1"}, scope=REPO_GLOBAL_SCOPE)
        assert deleted == 3
