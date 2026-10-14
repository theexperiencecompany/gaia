"""Contract tests for NotificationRepository (business-key identity = UUID id)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.db.repositories.notifications import NotificationRepository
from app.models.notification.notification_models import (
    ChannelDeliveryStatus,
    NotificationContent,
    NotificationListFilters,
    NotificationRecord,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationStatus,
)


def _record(**overrides: object) -> NotificationRecord:
    data: dict[str, object] = {
        "id": "n1",
        "user_id": "u1",
        "created_at": datetime.now(UTC),
        "original_request": NotificationRequest(
            user_id="u1",
            source=NotificationSourceEnum.AI_AGENT,
            content=NotificationContent(title="t", body="b"),
        ),
    }
    data.update(overrides)
    return NotificationRecord(**data)


@pytest.fixture
def repo(raw_collection) -> NotificationRepository:
    return NotificationRepository()


class TestNotificationRepository:
    async def test_create_preserves_uuid_id_and_reads_by_it(self, repo, raw_collection):
        created = await repo.create(_record(id="uuid-1"))
        assert created.id == "uuid-1"  # the UUID id is not clobbered by the ObjectId
        # stored doc carries a distinct ObjectId _id
        raw = await raw_collection.find_one({"id": "uuid-1"})
        assert raw["_id"] != "uuid-1"
        fetched = await repo.get_for_user("uuid-1", "u1")
        assert fetched is not None and fetched.id == "uuid-1"
        assert await repo.get_for_user("uuid-1", "attacker") is None  # user isolation
        assert (await repo.get_for_user("uuid-1", None)).id == "uuid-1"

    async def test_update_fields_applies_free_form_patch(self, repo):
        await repo.create(_record(id="uuid-2"))
        await repo.update_fields("uuid-2", status="read")
        fetched = await repo.get_for_user("uuid-2", "u1")
        assert fetched is not None and fetched.status == NotificationStatus.READ

    async def test_list_and_count_for_user(self, repo):
        await repo.create(_record(id="a", user_id="lister"))
        await repo.create(_record(id="b", user_id="lister"))
        await repo.create(_record(id="c", user_id="other"))
        items = await repo.list_for_user("lister")
        assert {i.id for i in items} == {"a", "b"}
        assert await repo.count_for_user("lister") == 2

    async def test_list_filters_by_status(self, repo):
        await repo.create(_record(id="p", user_id="f", status=NotificationStatus.PENDING))
        await repo.create(_record(id="r", user_id="f", status=NotificationStatus.READ))
        read = await repo.list_for_user(
            "f", filters=NotificationListFilters(status=NotificationStatus.READ)
        )
        assert [i.id for i in read] == ["r"]


class TestMarkAllReadForUser:
    async def test_marks_every_delivered_notification_not_just_a_page(self, repo):
        # Regression: "mark all as read" must cover every DELIVERED notification for the
        # user, not only however many a paginated client loaded. 5 is arbitrary but exceeds
        # any single-item/page assumption a caller could silently rely on.
        ids = [f"bulk-{i}" for i in range(5)]
        for notification_id in ids:
            await repo.create(
                _record(
                    id=notification_id, user_id="bulk-user", status=NotificationStatus.DELIVERED
                )
            )

        updated_count = await repo.mark_all_read_for_user("bulk-user")

        assert updated_count == 5
        for notification_id in ids:
            fetched = await repo.get_for_user(notification_id, "bulk-user")
            assert fetched is not None
            assert fetched.status == NotificationStatus.READ
            assert fetched.read_at is not None

    async def test_only_touches_the_target_user(self, repo):
        await repo.create(_record(id="mine", user_id="owner", status=NotificationStatus.DELIVERED))
        await repo.create(
            _record(id="theirs", user_id="other", status=NotificationStatus.DELIVERED)
        )

        updated_count = await repo.mark_all_read_for_user("owner")

        assert updated_count == 1
        theirs = await repo.get_for_user("theirs", "other")
        assert theirs is not None
        assert theirs.status == NotificationStatus.DELIVERED

    async def test_leaves_non_delivered_statuses_untouched(self, repo):
        await repo.create(
            _record(id="already-read", user_id="statuses", status=NotificationStatus.READ)
        )
        await repo.create(
            _record(id="pending", user_id="statuses", status=NotificationStatus.PENDING)
        )

        updated_count = await repo.mark_all_read_for_user("statuses")

        assert updated_count == 0
        pending = await repo.get_for_user("pending", "statuses")
        assert pending is not None
        assert pending.status == NotificationStatus.PENDING

    async def test_channel_type_filter_scopes_the_update(self, repo):
        await repo.create(
            _record(
                id="inapp",
                user_id="channels",
                status=NotificationStatus.DELIVERED,
                channels=[
                    ChannelDeliveryStatus(channel_type="inapp", status=NotificationStatus.DELIVERED)
                ],
            )
        )
        await repo.create(
            _record(
                id="email",
                user_id="channels",
                status=NotificationStatus.DELIVERED,
                channels=[
                    ChannelDeliveryStatus(channel_type="email", status=NotificationStatus.DELIVERED)
                ],
            )
        )

        updated_count = await repo.mark_all_read_for_user("channels", channel_type="inapp")

        assert updated_count == 1
        email_notification = await repo.get_for_user("email", "channels")
        assert email_notification is not None
        assert email_notification.status == NotificationStatus.DELIVERED
