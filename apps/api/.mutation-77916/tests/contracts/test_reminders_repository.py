"""Contract tests for RemindersRepository (global, ObjectId _id).

Runs against real Mongo (never mocks). Every fixture user id is per-run unique so
a concurrent run against the shared test DB can't collide.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import uuid

import pytest

from app.db.repositories.reminders import RemindersRepository
from app.models.reminder_models import (
    AgentType,
    ReminderDocument,
    ReminderStatus,
    ReminderUpdate,
    StaticReminderPayload,
)

_MISSING_OBJECT_ID = "0" * 24


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _reminder(**overrides: object) -> ReminderDocument:
    data: dict[str, object] = {
        "user_id": _uid("u"),
        "agent": AgentType.STATIC,
        "payload": StaticReminderPayload(title="Drink water", body="stay hydrated"),
        "scheduled_at": datetime.now(UTC) + timedelta(hours=1),
        "status": ReminderStatus.SCHEDULED,
    }
    data.update(overrides)
    return ReminderDocument(**data)


@pytest.fixture
def repo(raw_collection) -> RemindersRepository:
    return RemindersRepository()


class TestRemindersCore:
    async def test_create_assigns_objectid_and_reads_back(self, repo, raw_collection):
        created = await repo.create(_reminder())
        assert created.id and len(created.id) == 24  # stringified ObjectId
        raw = await raw_collection.find_one({"user_id": created.user_id})
        assert raw is not None and str(raw["_id"]) == created.id
        fetched = await repo.get(created.id)
        assert fetched is not None and fetched.id == created.id
        assert fetched.payload.title == "Drink water"

    async def test_get_missing_returns_none(self, repo):
        assert await repo.get(_MISSING_OBJECT_ID) is None

    async def test_get_for_user_isolates(self, repo):
        created = await repo.create(_reminder(user_id="owner"))
        assert await repo.get_for_user(created.id, "owner") is not None
        assert await repo.get_for_user(created.id, "attacker") is None

    async def test_list_for_user_with_status_and_pagination(self, repo):
        owner = _uid("owner")
        await repo.create(_reminder(user_id=owner, status=ReminderStatus.SCHEDULED))
        await repo.create(_reminder(user_id=owner, status=ReminderStatus.SCHEDULED))
        await repo.create(_reminder(user_id=owner, status=ReminderStatus.COMPLETED))
        await repo.create(_reminder(user_id=_uid("other")))
        assert len(await repo.list_for_user(owner)) == 3
        scheduled = await repo.list_for_user(owner, status=ReminderStatus.SCHEDULED)
        assert len(scheduled) == 2
        page = await repo.list_for_user(owner, limit=1, skip=0)
        assert len(page) == 1


class TestRemindersScheduler:
    async def test_find_pending_before_only_due_scheduled(self, repo):
        now = datetime.now(UTC)
        due = await repo.create(
            _reminder(scheduled_at=now - timedelta(minutes=5), status=ReminderStatus.SCHEDULED)
        )
        # future — not due
        await repo.create(
            _reminder(scheduled_at=now + timedelta(hours=1), status=ReminderStatus.SCHEDULED)
        )
        # due but already completed — excluded
        await repo.create(
            _reminder(scheduled_at=now - timedelta(minutes=5), status=ReminderStatus.COMPLETED)
        )
        pending = await repo.find_pending_before(now)
        assert [r.id for r in pending] == [due.id]

    async def test_set_status_reschedule_fields_and_user_guard(self, repo):
        owner = _uid("owner")
        rem = await repo.create(_reminder(user_id=owner))
        run_at = datetime.now(UTC) + timedelta(days=1)
        ok = await repo.set_status(
            rem.id, ReminderStatus.SCHEDULED, occurrence_count=4, scheduled_at=run_at
        )
        assert ok is True
        fetched = await repo.get(rem.id)
        assert fetched.status == ReminderStatus.SCHEDULED
        assert fetched.occurrence_count == 4
        # wrong user does not match; worker path (no user) does
        assert await repo.set_status(rem.id, ReminderStatus.COMPLETED, user_id="x") is False
        assert await repo.set_status(rem.id, ReminderStatus.COMPLETED) is True
        assert (await repo.get(rem.id)).status == ReminderStatus.COMPLETED

    async def test_set_status_missing_returns_false(self, repo):
        assert await repo.set_status(_MISSING_OBJECT_ID, ReminderStatus.COMPLETED) is False


class TestRemindersUpdate:
    async def test_update_for_user_partial_and_scoped(self, repo):
        owner = _uid("owner")
        rem = await repo.create(_reminder(user_id=owner, repeat=None))
        before = rem.updated_at
        updated = await repo.update_for_user(
            rem.id, owner, ReminderUpdate(repeat="0 9 * * *", max_occurrences=5)
        )
        assert updated is not None
        assert updated.repeat == "0 9 * * *"
        assert updated.max_occurrences == 5
        assert updated.payload.title == "Drink water"  # untouched
        assert updated.updated_at >= before
        # cross-user is a no-op
        assert (
            await repo.update_for_user(rem.id, "attacker", ReminderUpdate(repeat="0 8 * * *"))
            is None
        )

    async def test_delete_finished_before(self, repo, raw_collection):
        now = datetime.now(UTC)
        old_done = await repo.create(_reminder(status=ReminderStatus.COMPLETED))
        old_cancelled = await repo.create(_reminder(status=ReminderStatus.CANCELLED))
        active = await repo.create(_reminder(status=ReminderStatus.SCHEDULED))
        # base._insert stamps updated_at=now, so age the rows directly. The active
        # one is old too — proving the status filter, not just the date, gates it.
        await raw_collection.update_many(
            {"_id": {"$in": [repo._id_value(r.id) for r in (old_done, old_cancelled, active)]}},
            {"$set": {"updated_at": now - timedelta(days=40)}},
        )
        # A recently-finished reminder (updated_at=now) must survive the cutoff.
        recent_done = await repo.create(_reminder(status=ReminderStatus.COMPLETED))

        deleted = await repo.delete_finished_before(now - timedelta(days=30))
        assert deleted == 2
        assert await repo.get(active.id) is not None
        assert await repo.get(recent_done.id) is not None

    async def test_update_replaces_payload(self, repo):
        owner = _uid("owner")
        rem = await repo.create(_reminder(user_id=owner))
        updated = await repo.update_for_user(
            rem.id,
            owner,
            ReminderUpdate(payload=StaticReminderPayload(title="New", body="body")),
        )
        assert updated is not None and updated.payload.title == "New"
