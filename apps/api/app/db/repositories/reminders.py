"""Repository for the reminders collection.

A global (non-user-scoped) repository: the scheduler worker fetches and updates a
reminder by ``_id`` alone with no user in context, while user-facing listing and
edits add the owner guard. Identity is Mongo's ``ObjectId`` ``_id``
(``uses_object_id=True``), stringified into ``id`` on read.

No ``CachePolicy``: reminders are written on every fire (status transitions,
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
        """A reminder by id, scoped to its owner — the user-facing read."""
        return await self._find_one({"_id": self._id_value(reminder_id), "user_id": user_id})

    async def list_for_user(
        self,
        user_id: str,
        *,
        status: ReminderStatus | None = None,
        limit: int = 100,
        skip: int = 0,
    ) -> list[ReminderDocument]:
        """A user's reminders, optionally filtered by status (insertion order,
        paginated) — matches the existing listing query."""
        query: dict[str, Any] = {"user_id": user_id}
        if status is not None:
            query["status"] = status.value
        return await self._find(query, limit=limit, skip=skip)

    async def find_pending_before(self, current_time: datetime) -> list[ReminderDocument]:
        """Reminders that are scheduled and due at ``current_time``.

        The due filter (``status="scheduled"`` and ``scheduled_at <= now``) is the
        shared scheduler semantics — kept identical to ``WorkflowsRepository`` so the
        two scans can never diverge on the ``$lte`` operator again (reminders once
        used ``$gte`` and silently dropped every overdue task).
        """
        return await self._find(
            {
                "status": ReminderStatus.SCHEDULED.value,
                "scheduled_at": {"$lte": current_time},
            }
        )

    async def find_stale_executing(self, cutoff: datetime) -> list[ReminderDocument]:
        """Reminders wedged in EXECUTING since before ``cutoff`` — the recovery
        sweep's re-arm candidates (a worker died mid-fire)."""
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

        Returns ``False`` — and the caller skips the fire — when the reminder is
        no longer ``scheduled``, i.e. another worker already claimed it. Two ARQ
        jobs for one reminder is routine (the startup scan runs in every replica
        and every worker, and re-arms past-due reminders to that process's own
        clock, so the job ids differ and ARQ does not dedup them). The status
        predicate living inside the update is what makes it exactly-once.

        ``expected_scheduled_at`` pins the occurrence the job was armed for, and
        status alone is not enough without it: a RECURRING reminder goes back to
        ``scheduled`` for its NEXT occurrence as soon as the first run re-arms,
        so a sibling pod's late job would find it claimable again and deliver
        the same reminder twice. Jobs enqueued before the stamp existed pass
        ``None`` and claim on status alone, so a deploy never strands them.
        Matched at second resolution (``occurrence_window``) because the stamp
        the job carries is a unix int — see that helper for why equality here
        silently matched nothing.
        Mirrors ``WorkflowsRepository.claim_for_execution``.
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
        """Apply a flat ``$set`` update to the user's reminder. Returns the after
        state, or ``None`` when no matching reminder exists."""
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
        """Set a reminder's ``status`` (plus the scheduler's re-arm fields:
        ``occurrence_count`` and a new ``scheduled_at``). Returns whether a reminder
        was matched. ``user_id`` adds the owner guard where the caller has one (e.g.
        cancel); the worker paths update by id alone."""
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
        """Delete completed/cancelled reminders last updated before ``cutoff`` — the
        cleanup cron. Returns the count deleted."""
        return await self._delete_many(
            {
                "status": {"$in": [ReminderStatus.COMPLETED.value, ReminderStatus.CANCELLED.value]},
                "updated_at": {"$lt": cutoff},
            },
            scope=REPO_GLOBAL_SCOPE,
        )


reminder_repository = RemindersRepository()
