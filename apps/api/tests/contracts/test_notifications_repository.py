"""Contract tests for NotificationRepository (business-key identity = UUID ``id``)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.db.repositories.notifications import NotificationRepository
from app.models.notification.notification_models import (
    NotificationContent,
    NotificationFilters,
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
        items = await repo.list_for_user("lister", filters=NotificationFilters())
        assert {i.id for i in items} == {"a", "b"}
        assert await repo.count_for_user("lister", filters=NotificationFilters()) == 2

    async def test_list_filters_by_status(self, repo):
        await repo.create(_record(id="p", user_id="f", status=NotificationStatus.PENDING))
        await repo.create(_record(id="r", user_id="f", status=NotificationStatus.READ))
        read = await repo.list_for_user(
            "f", filters=NotificationFilters(status=NotificationStatus.READ)
        )
        assert [i.id for i in read] == ["r"]
