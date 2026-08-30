"""Contract tests for RemindersRepository (global, ObjectId _id).

Runs against real Mongo (never mocks). Every fixture user id is per-run unique so
a concurrent run against the shared test DB can't collide.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import uuid

from bson import ObjectId
import pytest

from app.db.repositories.reminders import RemindersRepository
from app.models.reminder_models import (
    AgentType,
    ReminderDocument,
    ReminderStatus,
    ReminderUpdate,
    StaticReminderPayload,
)
from app.services.reminder_service import ReminderScheduler
from app.utils.occurrence import parse_occurrence_stamp

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

    async def test_claim_for_execution_is_atomic(self, repo):
        rem = await repo.create(_reminder(status=ReminderStatus.SCHEDULED))
        assert await repo.claim_for_execution(rem.id) is True
        # second claim fails — already EXECUTING
        assert await repo.claim_for_execution(rem.id) is False
        assert (await repo.get(rem.id)).status == ReminderStatus.EXECUTING

    async def test_claim_pin_rejects_a_stale_occurrence(self, repo):
        """A duplicate job armed for an occurrence that already ran must not fire.

        Status alone is not enough for a RECURRING reminder. Two pods booting
        minutes apart each enqueue a job for the same overdue reminder under a
        different id (the past-due re-arm uses each process's own clock), so ARQ
        does not dedup them. The first job claims, runs, and
        ``handle_recurring_task`` puts the row back to SCHEDULED for the NEXT
        occurrence — at which point the second job finds status="scheduled"
        again, claims it, and delivers the same reminder a second time while
        also eating an occurrence out of the series.

        Pinning the armed occurrence is what closes it, exactly as
        ``WorkflowsRepository.claim_for_execution`` pins ``next_run``.
        """
        first_run = (datetime.now(UTC) - timedelta(minutes=5)).replace(microsecond=0)
        next_run = first_run + timedelta(days=1)
        rem = await repo.create(_reminder(scheduled_at=first_run, status=ReminderStatus.SCHEDULED))

        assert await repo.claim_for_execution(rem.id, expected_scheduled_at=first_run) is True
        # The run finishes and re-arms the series for tomorrow.
        assert (
            await repo.set_status(
                rem.id, ReminderStatus.SCHEDULED, occurrence_count=1, scheduled_at=next_run
            )
            is True
        )

        # The sibling pod's job, still armed for the occurrence that already ran.
        assert await repo.claim_for_execution(rem.id, expected_scheduled_at=first_run) is False
        # ...and the rejection leaves tomorrow's occurrence claimable.
        assert await repo.claim_for_execution(rem.id, expected_scheduled_at=next_run) is True

    async def test_find_stale_executing_returns_only_wedged_rows(self, repo, raw_collection):
        """The recovery sweep's candidates: EXECUTING since before the cutoff.

        A claim flips SCHEDULED -> EXECUTING with no lease. If the worker dies
        before re-arming (a rolling deploy SIGKILLs it, or the job is cancelled
        and its retry finds the row already claimed), the row stays EXECUTING
        forever — and ``find_pending_before`` filters on ``status="scheduled"``,
        so nothing can ever see it again. The reminder simply never fires.
        """
        now = datetime.now(UTC)
        wedged = await repo.create(_reminder(status=ReminderStatus.EXECUTING))
        # ``_insert`` always stamps updated_at=now, so age the wedged row directly.
        await raw_collection.update_one(
            {"_id": ObjectId(wedged.id)}, {"$set": {"updated_at": now - timedelta(hours=2)}}
        )
        # Executing but only just claimed — a live run, must not be reaped.
        await repo.create(_reminder(status=ReminderStatus.EXECUTING))
        # Old but not executing — not a candidate.
        aged_scheduled = await repo.create(_reminder(status=ReminderStatus.SCHEDULED))
        await raw_collection.update_one(
            {"_id": ObjectId(aged_scheduled.id)},
            {"$set": {"updated_at": now - timedelta(hours=2)}},
        )

        stale = await repo.find_stale_executing(now - timedelta(hours=1))

        assert [r.id for r in stale] == [wedged.id]

    async def test_claim_without_a_pin_still_claims(self, repo):
        """Jobs enqueued before the stamp existed carry none — a deploy must not
        strand them."""
        rem = await repo.create(_reminder(status=ReminderStatus.SCHEDULED))
        assert await repo.claim_for_execution(rem.id) is True

    async def test_claim_pin_survives_the_real_stamp_round_trip(self, repo):
        """The pin must match the armed occurrence through ARQ's serialized args.

        "Remind me in 10 minutes" arms ``now + delta``, which carries
        microseconds. The stamp the job travels with is a unix int, so it comes
        back floored to the second, while Mongo holds the armed instant at BSON's
        millisecond precision — an equality pin never matched and the reminder
        silently never fired. Driven through the real producer and parser so the
        encoding itself is under test, not a hand-built stamp.
        """
        armed = datetime.now(UTC) + timedelta(minutes=10)
        assert armed.microsecond, "fixture must carry a sub-second component"
        rem = await repo.create(_reminder(scheduled_at=armed, status=ReminderStatus.SCHEDULED))

        _, stamp = ReminderScheduler()._build_job_args(rem.id, armed)
        expected = parse_occurrence_stamp(stamp, rem.id)

        # The neighbouring seconds stay rejected — matching the armed second must
        # not degrade into matching anything.
        for skew in (-1, 1):
            assert (
                await repo.claim_for_execution(
                    rem.id, expected_scheduled_at=expected + timedelta(seconds=skew)
                )
                is False
            )
        assert await repo.claim_for_execution(rem.id, expected_scheduled_at=expected) is True


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
