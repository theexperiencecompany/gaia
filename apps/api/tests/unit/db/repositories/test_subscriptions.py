"""Unit tests for the subscriptions repository: the per-user wipe and the event-fenced update."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from app.constants.cache import REPO_GLOBAL_SCOPE
from app.db.repositories.subscriptions import SubscriptionsRepository
from app.models.payment_models import SubscriptionUpdate


class TestDeleteAllForUser:
    async def test_deletes_every_status_of_that_user_only(self) -> None:
        repo = SubscriptionsRepository()
        with patch.object(repo, "_delete_many", new=AsyncMock(return_value=3)) as delete_many:
            deleted = await repo.delete_all_for_user("user-1")

        delete_many.assert_awaited_once_with({"user_id": "user-1"}, scope=REPO_GLOBAL_SCOPE)
        assert deleted == 3


class TestApplyUpdateByDodoId:
    async def test_the_write_is_fenced_on_the_stored_event_clock(self) -> None:
        """The stale-event check is enforced in the filter, so a newer row is never overwritten."""
        repo = SubscriptionsRepository()
        seen_at = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
        with patch.object(
            repo, "_apply_raw_update", new=AsyncMock(return_value={"_id": "s1"})
        ) as raw:
            matched = await repo.apply_update_by_dodo_id(
                "sub_1", SubscriptionUpdate(status="expired"), if_not_newer_than=seen_at
            )

        assert matched is True
        raw.assert_awaited_once_with(
            {"dodo_subscription_id": "sub_1"},
            {"$set": {"status": "expired"}},
            extra_filter={"$or": [{"last_event_at": None}, {"last_event_at": {"$lte": seen_at}}]},
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )

    async def test_no_document_matching_the_fence_reports_a_stale_write(self) -> None:
        repo = SubscriptionsRepository()
        with patch.object(repo, "_apply_raw_update", new=AsyncMock(return_value=None)):
            matched = await repo.apply_update_by_dodo_id(
                "sub_1", SubscriptionUpdate(status="active"), if_not_newer_than=datetime.now(UTC)
            )
        assert matched is False

    async def test_an_empty_patch_writes_nothing(self) -> None:
        repo = SubscriptionsRepository()
        with patch.object(repo, "_apply_raw_update", new=AsyncMock()) as raw:
            matched = await repo.apply_update_by_dodo_id(
                "sub_1", SubscriptionUpdate(), if_not_newer_than=datetime.now(UTC)
            )
        assert matched is False
        raw.assert_not_awaited()
