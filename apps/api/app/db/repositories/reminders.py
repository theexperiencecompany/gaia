"""Repository for the reminders collection.

A global (non-user-scoped) repository: the scheduler worker fetches and updates a
reminder by _id alone with no user in context, while user-facing listing and
edits add the owner guard. Identity is Mongo's ObjectId _id
(uses_object_id=True), stringified into id on read.

No CachePolicy: reminders are written on every fire (status transitions,
occurrence-count advance, re-arm), and the hot read is the due-scan across users —
neither benefits from an id-keyed entity cache. Matches the workflows repository.
"""

from datetime import UTC, datetime
from typing import Any

from app.constants.cache import REPO_GLOBAL_SCOPE
from app.db.repositories.base import MongoRepository
from app.models.reminder_models import ReminderDocument, ReminderStatus, ReminderUpdate
from app.utils.occurrence import occurrence_window


class RemindersRepository(MongoRepository[ReminderDocument, ReminderUpdate]):
    collection_name = "reminders"
    document_model = ReminderDocument
    update_model = ReminderUpdate
    uses_object_id = True
    cache_policy = None

    # ------------------------------------------------------------------ reads

    async def get_for_user(self, reminder_id: str, user_id: str) -> ReminderDocument | None:
        """Return a reminder by id, scoped to its owner — the user-facing read."""
        return await self._find_one({"_id": self._id_value(reminder_id), "user_id": user_id})

    async def list_for_user(
        self,
        user_id: str,
        *,
        status: ReminderStatus | None = None,
        limit: int = 100,
        skip: int = 0,
    ) -> list[ReminderDocument]:
        """Return a user's reminders, optionally filtered by status (insertion order, paginated)."""
        query: dict[str, Any] = {"user_id": user_id}
        if status is not None:
            query["status"] = status.value
        return await self._find(query, limit=limit, skip=skip)

    async def find_pending_before(self, current_time: datetime) -> list[ReminderDocument]:
        """Reminders that are scheduled and due at current_time.

        The due filter (status="scheduled" and scheduled_at <= now) is the
        shared scheduler semantics — kept identical to WorkflowsRepository so the
        two scans can never diverge on the $lte operator again (reminders once
        used $gte and silently dropped every overdue task).
        """
        return await self._find(
            {
                "status": ReminderStatus.SCHEDULED.value,
                "scheduled_at": {"$lte": current_time},
            }
        )

    async def find_stale_executing(self, cutoff: datetime) -> list[ReminderDocument]:
        """Reminders wedged in EXECUTING since before cutoff (a worker died mid-fire)."""
        return await self._find(
            {
                "status": ReminderStatus.EXECUTING.value,
                "updated_at": {"$lt": cutoff},
            }
        )

    # ----------------------------------------------------------------- writes

    async def claim_for_execution(
        self, reminder_id: str, *, expected_scheduled_at: datetime | None = None
    ) -> bool:
        """Atomically claim a scheduled reminder for a fire (SCHEDULED -> EXECUTING).

        False means another worker claimed it first; the update's status predicate
        makes this exactly-once despite routine duplicate ARQ jobs. expected_scheduled_at
        pins the occurrence, since a RECURRING reminder re-arms immediately and a late
        sibling job would otherwise double-fire it.
        """
        filter_: dict[str, Any] = {
            "_id": self._id_value(reminder_id),
            "status": ReminderStatus.SCHEDULED.value,
        }
        if expected_scheduled_at is not None:
            filter_["scheduled_at"] = occurrence_window(expected_scheduled_at)
        result = await self._apply_raw_update(
            filter_,
            {"$set": {"status": ReminderStatus.EXECUTING.value, "updated_at": datetime.now(UTC)}},
            scope=REPO_GLOBAL_SCOPE,
        )
        return result is not None

    async def update_for_user(
        self, reminder_id: str, user_id: str, update: ReminderUpdate
    ) -> ReminderDocument | None:
        """Apply a flat $set update to the user's reminder; None when no matching reminder exists."""
        return await self._apply_update(
            reminder_id, REPO_GLOBAL_SCOPE, {"user_id": user_id}, update
        )

    async def set_status(
        self,
        reminder_id: str,
        status: ReminderStatus,
        *,
        user_id: str | None = None,
        occurrence_count: int | None = None,
        scheduled_at: datetime | None = None,
    ) -> bool:
        """Set a reminder's status plus the scheduler's re-arm fields (occurrence_count, scheduled_at).

        user_id adds the owner guard where the caller has one (e.g. cancel);
        the worker paths update by id alone.
        """
        filter_: dict[str, Any] = {"_id": self._id_value(reminder_id)}
        if user_id:
            filter_["user_id"] = user_id
        set_fields: dict[str, Any] = {"status": status.value}
        if occurrence_count is not None:
            set_fields["occurrence_count"] = occurrence_count
        if scheduled_at is not None:
            set_fields["scheduled_at"] = scheduled_at
        result = await self._apply_raw_update(
            filter_, {"$set": set_fields}, scope=REPO_GLOBAL_SCOPE
        )
        return result is not None

    async def delete_finished_before(self, cutoff: datetime) -> int:
        """Delete completed/cancelled reminders last updated before cutoff, returning the count deleted."""
        return await self._delete_many(
            {
                "status": {"$in": [ReminderStatus.COMPLETED.value, ReminderStatus.CANCELLED.value]},
                "updated_at": {"$lt": cutoff},
            },
            scope=REPO_GLOBAL_SCOPE,
        )


reminder_repository = RemindersRepository()
