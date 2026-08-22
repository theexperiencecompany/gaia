"""Contract tests for WorkflowsRepository (global, string business-key id = _id).

Runs against real Mongo (never mocks). Every fixture id is per-run unique so a
concurrent run against the shared test DB can't collide.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
import uuid

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorCollection
from pydantic import ValidationError
from pymongo.errors import DuplicateKeyError
import pytest

from app.db.repositories.workflows import WorkflowsRepository
from app.models.scheduler_models import ScheduledTaskStatus
from app.models.workflow_models import (
    TriggerConfig,
    TriggerType,
    WorkflowDocument,
    WorkflowStep,
    WorkflowUpdate,
)


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _workflow(**overrides: object) -> WorkflowDocument:
    data: dict[str, object] = {
        "user_id": _uid("u"),
        "title": "Test Workflow",
        "prompt": "do the thing",
        "steps": [WorkflowStep(title="step", category="gmail", description="d")],
        "trigger_config": TriggerConfig(type=TriggerType.MANUAL),
    }
    data.update(overrides)
    return WorkflowDocument(**data)


@pytest.fixture
def repo(raw_collection) -> WorkflowsRepository:
    return WorkflowsRepository()


class TestWorkflowsCore:
    async def test_create_preserves_string_id_and_reads_back(self, repo, raw_collection):
        doc = _workflow()
        created = await repo.create(doc)
        assert created.id == doc.id and created.id.startswith("wf_")
        # The persisted _id IS the business key (string), not an ObjectId.
        raw = await raw_collection.find_one({"_id": doc.id})
        assert raw is not None and raw["_id"] == doc.id
        fetched = await repo.get(doc.id)
        assert fetched is not None and fetched.id == doc.id

    async def test_create_then_get_roundtrips(self, repo):
        created = await repo.create(_workflow(title="Round", description="desc"))
        fetched = await repo.get(created.id)
        assert fetched is not None
        assert fetched.title == "Round"
        assert fetched.description == "desc"
        assert fetched.user_id == created.user_id

    async def test_get_missing_returns_none(self, repo):
        assert await repo.get(_uid("missing")) is None

    async def test_reads_legacy_iso_string_datetimes_as_tz_aware(self, repo, raw_collection):
        # A handful of legacy rows persist created_at/scheduled_at as ISO strings.
        wid = _uid("wf")
        await raw_collection.insert_one(
            {
                "_id": wid,
                "id": wid,
                "user_id": _uid("u"),
                "title": "Legacy",
                "prompt": "p",
                "steps": [],
                "trigger_config": {"type": "manual", "enabled": True},
                "created_at": "2026-05-04T20:00:55.367416+00:00",
                "scheduled_at": "2026-05-04T20:00:55.367381+00:00",
                "updated_at": datetime.now(UTC),
                "status": "scheduled",
                "activated": True,
            }
        )
        doc = await repo.get(wid)
        assert doc is not None
        assert isinstance(doc.created_at, datetime) and doc.created_at.tzinfo is not None
        assert isinstance(doc.scheduled_at, datetime) and doc.scheduled_at.tzinfo is not None


class TestWorkflowsOwnedCrud:
    async def test_get_for_user_isolates(self, repo):
        created = await repo.create(_workflow(user_id="owner"))
        assert await repo.get_for_user(created.id, "owner") is not None
        assert await repo.get_for_user(created.id, "attacker") is None

    async def test_update_for_user_partial_and_scoped(self, repo):
        created = await repo.create(_workflow(user_id="owner", title="Old", prompt="keep"))
        before = created.updated_at
        updated = await repo.update_for_user(created.id, "owner", WorkflowUpdate(title="New"))
        assert updated is not None
        assert updated.title == "New"
        assert updated.prompt == "keep"  # untouched field preserved
        assert updated.updated_at >= before
        # cross-user update is a no-op
        assert await repo.update_for_user(created.id, "attacker", WorkflowUpdate(title="X")) is None
        assert (await repo.get(created.id)).title == "New"

    async def test_delete_for_user_scoped(self, repo):
        created = await repo.create(_workflow(user_id="owner"))
        assert await repo.delete_for_user(created.id, "attacker") is False
        assert await repo.get(created.id) is not None
        assert await repo.delete_for_user(created.id, "owner") is True
        assert await repo.get(created.id) is None

    async def test_delete_many_for_user(self, repo):
        owner = _uid("owner")
        a = await repo.create(_workflow(user_id=owner))
        b = await repo.create(_workflow(user_id=owner))
        other = await repo.create(_workflow(user_id=_uid("other")))
        deleted = await repo.delete_many_for_user([a.id, b.id, other.id], owner)
        assert deleted == 2  # other user's row is not touched
        assert await repo.get(other.id) is not None

    async def test_list_for_user_newest_first_excludes_todo(self, repo):
        owner = _uid("owner")
        older = await repo.create(
            _workflow(user_id=owner, created_at=datetime.now(UTC) - timedelta(hours=1))
        )
        newer = await repo.create(_workflow(user_id=owner, created_at=datetime.now(UTC)))
        await repo.create(_workflow(user_id=owner, is_todo_workflow=True))
        await repo.create(_workflow(user_id=_uid("other")))
        listed = await repo.list_for_user(owner)
        assert [w.id for w in listed] == [newer.id, older.id]
        # opt-in includes the todo workflow
        assert len(await repo.list_for_user(owner, exclude_todo_workflows=False)) == 3

    async def test_find_by_ids_variants(self, repo):
        owner = _uid("owner")
        a = await repo.create(_workflow(user_id=owner))
        b = await repo.create(_workflow(user_id=_uid("other")))
        assert {w.id for w in await repo.find_by_ids([a.id, b.id])} == {a.id, b.id}
        assert {w.id for w in await repo.find_by_ids_for_user([a.id, b.id], owner)} == {a.id}
        assert await repo.find_by_ids([]) == []

    async def test_list_for_user_skips_malformed_row_but_get_stays_strict(
        self, repo, raw_collection
    ):
        owner = _uid("owner")
        valid = await repo.create(_workflow(user_id=owner, title="Valid"))
        # A legacy row missing required fields (title/steps/trigger_config) fails
        # WorkflowDocument validation. The LIST read must skip it (logging loudly)
        # so one corrupt document can't blank the user's whole workflow list.
        bad_id = _uid("bad")
        await raw_collection.insert_one({"_id": bad_id, "user_id": owner})
        listed = await repo.list_for_user(owner)
        assert [w.id for w in listed] == [valid.id]
        # The single-document read of the same corrupt row stays strict — a fetch of
        # a known id surfaces the corruption rather than silently returning nothing.
        with pytest.raises(ValidationError):
            await repo.get_for_user(bad_id, owner)


class TestWorkflowsScheduler:
    async def test_find_pending_before_only_due_recurring_active(self, repo):
        now = datetime.now(UTC)
        due = await repo.create(
            _workflow(
                scheduled_at=now - timedelta(minutes=5),
                repeat="0 9 * * *",
                activated=True,
                status=ScheduledTaskStatus.SCHEDULED,
            )
        )
        # future — not due
        await repo.create(
            _workflow(scheduled_at=now + timedelta(hours=1), repeat="0 9 * * *", activated=True)
        )
        # not recurring — excluded even though due
        await repo.create(
            _workflow(scheduled_at=now - timedelta(minutes=5), repeat=None, activated=True)
        )
        # deactivated — excluded
        await repo.create(
            _workflow(scheduled_at=now - timedelta(minutes=5), repeat="0 9 * * *", activated=False)
        )
        pending = await repo.find_pending_before(now)
        assert [w.id for w in pending] == [due.id]

    async def test_claim_for_execution_is_atomic(self, repo):
        wf = await repo.create(_workflow(activated=True, status=ScheduledTaskStatus.SCHEDULED))
        assert await repo.claim_for_execution(wf.id) is True
        # second claim fails — already EXECUTING
        assert await repo.claim_for_execution(wf.id) is False
        assert (await repo.get(wf.id)).status == ScheduledTaskStatus.EXECUTING

    async def test_claim_rejects_deactivated(self, repo):
        wf = await repo.create(_workflow(activated=False, status=ScheduledTaskStatus.SCHEDULED))
        assert await repo.claim_for_execution(wf.id) is False

    async def test_claim_pin_rejects_stale_fire_after_reschedule(self, repo):
        """The bug-2 gate against real Mongo: a deferred ARQ job armed for 16:00
        that fires after the workflow was rescheduled to 21:00 must be rejected,
        and the rejection must leave the row claimable by the 21:00 job."""
        old_fire = (datetime.now(UTC) + timedelta(hours=5)).replace(microsecond=0)
        new_fire = old_fire + timedelta(hours=5)
        wf = await repo.create(
            _workflow(
                activated=True,
                status=ScheduledTaskStatus.SCHEDULED,
                scheduled_at=old_fire,
                trigger_config=TriggerConfig(
                    type=TriggerType.SCHEDULE,
                    enabled=True,
                    cron_expression="0 16 * * *",
                    timezone="UTC",
                    next_run=old_fire,
                ),
            )
        )

        # The reschedule itself: update_workflow persists the new cron's next_run.
        assert (
            await repo.set_status(
                wf.id, ScheduledTaskStatus.SCHEDULED, scheduled_at=new_fire, next_run=new_fire
            )
            is True
        )

        # Old job fires: armed for 16:00 but next_run is now 21:00 -> rejected...
        assert await repo.claim_for_execution(wf.id, expected_next_run=old_fire) is False
        # ...and the rejection changed nothing — the row is still idle/scheduled.
        after_stale = await repo.get(wf.id)
        assert after_stale.status == ScheduledTaskStatus.SCHEDULED

        # New job fires: matches the current occurrence -> claims cleanly.
        assert await repo.claim_for_execution(wf.id, expected_next_run=new_fire) is True
        assert (await repo.get(wf.id)).status == ScheduledTaskStatus.EXECUTING

    async def test_claim_without_pin_stays_ungated(self, repo):
        """Jobs enqueued before the stamp existed carry no expected time; they
        must keep claiming across a deploy."""
        wf = await repo.create(
            _workflow(
                activated=True,
                status=ScheduledTaskStatus.SCHEDULED,
                trigger_config=TriggerConfig(
                    type=TriggerType.SCHEDULE,
                    enabled=True,
                    cron_expression="0 16 * * *",
                    timezone="UTC",
                    next_run=datetime.now(UTC).replace(microsecond=0),
                ),
            )
        )
        assert await repo.claim_for_execution(wf.id) is True

    async def test_find_stale_executing(self, repo, raw_collection):
        now = datetime.now(UTC)
        stale = await repo.create(_workflow(activated=True, status=ScheduledTaskStatus.EXECUTING))
        # ``_insert`` always stamps updated_at=now, so age the stale row directly.
        await raw_collection.update_one(
            {"_id": stale.id}, {"$set": {"updated_at": now - timedelta(hours=2)}}
        )
        # fresh executing — not stale
        await repo.create(_workflow(activated=True, status=ScheduledTaskStatus.EXECUTING))
        found = await repo.find_stale_executing(now - timedelta(hours=1))
        assert [w.id for w in found] == [stale.id]

    async def test_set_status_rearm_fields_and_user_guard(self, repo):
        owner = _uid("owner")
        wf = await repo.create(_workflow(user_id=owner, status=ScheduledTaskStatus.EXECUTING))
        # Whole seconds: Mongo stores datetimes at millisecond precision, so a
        # microsecond-bearing value would not survive the round-trip for equality.
        run_at = (datetime.now(UTC) + timedelta(hours=1)).replace(microsecond=0)
        ok = await repo.set_status(
            wf.id,
            ScheduledTaskStatus.SCHEDULED,
            user_id=owner,
            scheduled_at=run_at,
            occurrence_count=3,
            next_run=run_at,
        )
        assert ok is True
        fetched = await repo.get(wf.id)
        assert fetched.status == ScheduledTaskStatus.SCHEDULED
        assert fetched.occurrence_count == 3
        assert fetched.trigger_config.next_run == run_at
        # wrong user does not match
        assert await repo.set_status(wf.id, ScheduledTaskStatus.COMPLETED, user_id="x") is False

    async def test_set_status_unset_leaves_scheduled_at_untouched(self, repo):
        run_at = (datetime.now(UTC) + timedelta(hours=1)).replace(microsecond=0)
        wf = await repo.create(_workflow(scheduled_at=run_at))
        # status-only change (scheduled_at defaults to UNSET) must not clear it.
        assert await repo.set_status(wf.id, ScheduledTaskStatus.EXECUTING) is True
        assert (await repo.get(wf.id)).scheduled_at == run_at
        # an explicit None clears it (the reap path for a non-recurring workflow).
        assert (
            await repo.set_status(wf.id, ScheduledTaskStatus.SCHEDULED, scheduled_at=None) is True
        )
        assert (await repo.get(wf.id)).scheduled_at is None

    async def test_set_status_missing_returns_false(self, repo):
        assert await repo.set_status(_uid("missing"), ScheduledTaskStatus.COMPLETED) is False


class TestWorkflowsTriggersAndSystem:
    async def test_count_trigger_references(self, repo):
        tid = _uid("trig")
        a = await repo.create(
            _workflow(
                trigger_config=TriggerConfig(
                    type=TriggerType.INTEGRATION, composio_trigger_ids=[tid]
                )
            )
        )
        await repo.create(
            _workflow(
                trigger_config=TriggerConfig(
                    type=TriggerType.INTEGRATION, composio_trigger_ids=[tid]
                )
            )
        )
        assert await repo.count_trigger_references(tid) == 2
        assert await repo.count_trigger_references(tid, excluding_workflow_id=a.id) == 1
        assert await repo.count_trigger_references(_uid("none")) == 0

    async def test_find_active_integration_workflows(self, repo):
        owner = _uid("owner")
        match = await repo.create(
            _workflow(
                user_id=owner,
                activated=True,
                trigger_config=TriggerConfig(
                    type=TriggerType.INTEGRATION, enabled=True, trigger_name="gmail_new_message"
                ),
            )
        )
        # wrong trigger_name
        await repo.create(
            _workflow(
                user_id=owner,
                activated=True,
                trigger_config=TriggerConfig(
                    type=TriggerType.INTEGRATION, enabled=True, trigger_name="github_commit"
                ),
            )
        )
        # deactivated
        await repo.create(
            _workflow(
                user_id=owner,
                activated=False,
                trigger_config=TriggerConfig(
                    type=TriggerType.INTEGRATION, enabled=True, trigger_name="gmail_new_message"
                ),
            )
        )
        found = await repo.find_active_integration_workflows(owner, ["gmail_new_message"])
        assert [w.id for w in found] == [match.id]
        assert await repo.find_active_integration_workflows(owner, []) == []

    async def test_find_active_by_composio_trigger(self, repo):
        tid = _uid("tid")
        match = await repo.create(
            _workflow(
                activated=True,
                trigger_config=TriggerConfig(
                    type=TriggerType.INTEGRATION,
                    enabled=True,
                    trigger_name="gmail_poll_inbox",
                    composio_trigger_ids=[tid],
                ),
            )
        )
        # deactivated — excluded
        await repo.create(
            _workflow(
                activated=False,
                trigger_config=TriggerConfig(
                    type=TriggerType.INTEGRATION, enabled=True, composio_trigger_ids=[tid]
                ),
            )
        )
        found = await repo.find_active_by_composio_trigger(tid)
        assert [w.id for w in found] == [match.id]
        # trigger_name narrows to a single slug
        assert (
            await repo.find_active_by_composio_trigger(tid, trigger_name="gmail_poll_inbox")
            == found
        )
        assert await repo.find_active_by_composio_trigger(tid, trigger_name="other") == []
        assert await repo.find_active_by_composio_trigger(_uid("none")) == []

    async def test_set_composio_trigger_ids(self, repo):
        wf = await repo.create(
            _workflow(
                trigger_config=TriggerConfig(
                    type=TriggerType.INTEGRATION, composio_trigger_ids=["old"]
                )
            )
        )
        updated = await repo.set_composio_trigger_ids(wf.id, ["new1", "new2"])
        assert updated is not None
        assert updated.trigger_config.composio_trigger_ids == ["new1", "new2"]

    async def test_system_workflow_finders(self, repo):
        owner = _uid("owner")
        key = _uid("key")
        sys_wf = await repo.create(
            _workflow(user_id=owner, is_system_workflow=True, system_workflow_key=key)
        )
        assert (await repo.find_system_workflow(owner, key)).id == sys_wf.id
        assert await repo.find_system_workflow("other", key) is None
        assert (await repo.get_system_workflow_for_user(sys_wf.id, owner)).id == sys_wf.id
        # a non-system workflow is not resettable
        plain = await repo.create(_workflow(user_id=owner))
        assert await repo.get_system_workflow_for_user(plain.id, owner) is None

    async def test_reset_system_workflow(self, repo):
        wf = await repo.create(
            _workflow(title="Old", description="old desc", is_system_workflow=True)
        )
        updated = await repo.reset_system_workflow(
            wf.id,
            title="Fresh",
            description="fresh desc",
            steps=[WorkflowStep(title="s2", category="notion", description="d2")],
            trigger_config=TriggerConfig(
                type=TriggerType.SCHEDULE, enabled=True, cron_expression="0 9 * * *"
            ),
            composio_trigger_ids=["t1"],
        )
        assert updated is not None
        assert updated.title == "Fresh"
        assert updated.description == "fresh desc"
        assert [s.title for s in updated.steps] == ["s2"]
        assert updated.trigger_config.type == TriggerType.SCHEDULE
        assert updated.trigger_config.composio_trigger_ids == ["t1"]


class TestWorkflowsPublishAndWrites:
    async def test_find_public_slug_conflict(self, repo):
        slug = _uid("slug")
        pub = await repo.create(_workflow(is_public=True, slug=slug))
        assert (await repo.find_public_slug_conflict(slug)).id == pub.id
        assert await repo.find_public_slug_conflict(slug, exclude_id=pub.id) is None
        assert await repo.find_public_slug_conflict(_uid("free")) is None

    async def test_publish_unpublish(self, repo):
        wf = await repo.create(_workflow(is_public=False))
        slug = _uid("slug")
        published = await repo.publish(wf.id, created_by=wf.user_id, slug=slug)
        assert published is not None
        assert published.is_public is True and published.slug == slug
        assert published.created_by == wf.user_id
        unpublished = await repo.unpublish(wf.id)
        assert unpublished is not None and unpublished.is_public is False

    async def test_backfill_public_slug_races(self, repo):
        wf = await repo.create(_workflow(is_public=True, slug=None))
        slug = _uid("slug")
        first = await repo.backfill_public_slug(wf.id, slug)
        assert first is not None and first.slug == slug
        # slug now set — a second backfill matches nothing (race lost)
        assert await repo.backfill_public_slug(wf.id, _uid("other")) is None

    async def test_activate_deactivate(self, repo):
        owner = _uid("owner")
        wf = await repo.create(_workflow(user_id=owner, activated=False))
        run_at = datetime.now(UTC) + timedelta(hours=1)
        activated = await repo.activate(wf.id, owner, trigger_ids=["t1"], next_run=run_at)
        assert activated is not None
        assert activated.activated is True
        assert activated.trigger_config.enabled is True
        assert activated.trigger_config.composio_trigger_ids == ["t1"]
        assert activated.status == ScheduledTaskStatus.SCHEDULED
        deactivated = await repo.deactivate(wf.id, owner)
        assert deactivated is not None
        assert deactivated.activated is False
        assert deactivated.trigger_config.enabled is False
        assert deactivated.trigger_config.composio_trigger_ids == []

    async def test_mark_activated_with_triggers(self, repo):
        wf = await repo.create(_workflow(activated=False))
        updated = await repo.mark_activated_with_triggers(wf.id, trigger_ids=["t1", "t2"])
        assert updated is not None
        assert updated.activated is True
        assert updated.trigger_config.enabled is True
        assert updated.trigger_config.composio_trigger_ids == ["t1", "t2"]

    async def test_record_execution(self, repo):
        owner = _uid("owner")
        wf = await repo.create(_workflow(user_id=owner))
        assert await repo.record_execution(wf.id, owner, successful=True) is True
        assert await repo.record_execution(wf.id, owner, successful=False) is True
        fetched = await repo.get(wf.id)
        assert fetched.total_executions == 2
        assert fetched.successful_executions == 1
        assert fetched.last_executed_at is not None
        assert await repo.record_execution(_uid("missing"), owner) is False

    async def test_set_steps_and_deactivate(self, repo):
        owner = _uid("owner")
        wf = await repo.create(_workflow(user_id=owner, activated=True))
        updated = await repo.set_steps(
            wf.id,
            owner,
            [WorkflowStep(title="new", category="todos", description="d")],
            deactivate=True,
            integration_ids=["gmail"],
        )
        assert updated is not None
        assert [s.title for s in updated.steps] == ["new"]
        assert updated.activated is False
        assert updated.trigger_config.enabled is False
        assert updated.integration_ids == ["gmail"]

    async def test_touch_and_mark_error(self, repo):
        owner = _uid("owner")
        wf = await repo.create(_workflow(user_id=owner, activated=True))
        touched = await repo.touch(wf.id, owner)
        assert touched is not None and touched.updated_at >= wf.updated_at
        errored = await repo.mark_error(wf.id, owner, deactivate=True)
        assert errored is not None and errored.activated is False
        with_msg = await repo.set_error_message(wf.id, owner, "boom")
        assert with_msg is not None and with_msg.error_message == "boom"
        assert await repo.touch(_uid("missing"), owner) is None


class TestScheduledWorkflowToolPayloadJsonSafety:
    """Bug-1 gate against real Mongo: a persisted scheduled workflow read back
    through the repository carries native datetimes (BSON dates), so the tool
    payloads the workflow tools emit must be built with ``model_dump(mode="json")``
    — their consumers (the LLM ToolMessage and the stream writer) plain
    ``json.dumps`` them."""

    async def test_get_workflow_tool_payload_is_json_safe(self, repo):
        import json

        next_run = (datetime.now(UTC) + timedelta(hours=5)).replace(microsecond=0)
        wf = await repo.create(
            _workflow(
                activated=True,
                scheduled_at=next_run,
                last_executed_at=next_run - timedelta(days=1),
                trigger_config=TriggerConfig(
                    type=TriggerType.SCHEDULE,
                    enabled=True,
                    cron_expression="0 16 * * *",
                    timezone="UTC",
                    next_run=next_run,
                ),
            )
        )

        doc = await repo.get_for_user(wf.id, wf.user_id)
        assert doc is not None
        # The document really does carry native datetimes after the round-trip.
        assert isinstance(doc.trigger_config.next_run, datetime)

        # Exactly what get_workflow emits (workflow_tool.py).
        payload = {"success": True, "data": doc.model_dump(mode="json")}
        dumped = json.dumps(payload)
        assert doc.trigger_config.next_run.isoformat() in dumped

        # The old python-mode dump is what raised TypeError in production —
        # keep this assertion so a regression to model_dump() fails here too.
        with pytest.raises(TypeError, match="not JSON serializable"):
            json.dumps({"success": True, "data": doc.model_dump()})


class TestWorkflowsUniqueIndexSurface:
    """The concurrency-guard indexes live on the real collection, not the ephemeral
    fixture — recreate them here to prove the exact DuplicateKeyError surface the
    provisioner / publish paths depend on (they catch pymongo's DuplicateKeyError)."""

    async def _create_indexes(self, raw_collection) -> None:
        # Mirrors app/db/mongodb/indexes.py::create_workflow_indexes.
        await raw_collection.create_index(
            [("user_id", 1), ("system_workflow_key", 1)],
            unique=True,
            partialFilterExpression={"system_workflow_key": {"$type": 2}},
        )
        await raw_collection.create_index(
            [("slug", 1)],
            unique=True,
            partialFilterExpression={"is_public": True, "slug": {"$type": 2}},
            name="slug_public_unique_idx",
        )

    async def test_create_duplicate_system_workflow_key_raises(self, repo, raw_collection):
        await self._create_indexes(raw_collection)
        owner = _uid("owner")
        key = _uid("key")
        await repo.create(
            _workflow(user_id=owner, is_system_workflow=True, system_workflow_key=key)
        )
        # Same (user_id, system_workflow_key) → the provisioner relies on this raising.
        with pytest.raises(DuplicateKeyError):
            await repo.create(
                _workflow(user_id=owner, is_system_workflow=True, system_workflow_key=key)
            )

    async def test_publish_duplicate_public_slug_raises(self, repo, raw_collection):
        await self._create_indexes(raw_collection)
        slug = _uid("slug")
        a = await repo.create(_workflow(is_public=False))
        b = await repo.create(_workflow(is_public=False))
        assert await repo.publish(a.id, created_by=a.user_id, slug=slug) is not None
        # Second publish onto the same public slug → the endpoint retries on this.
        with pytest.raises(DuplicateKeyError):
            await repo.publish(b.id, created_by=b.user_id, slug=slug)

    async def test_backfill_duplicate_public_slug_raises(self, repo, raw_collection):
        await self._create_indexes(raw_collection)
        slug = _uid("slug")
        # An existing public workflow already holds the slug.
        await repo.create(_workflow(is_public=True, slug=slug))
        pending = await repo.create(_workflow(is_public=True, slug=None))
        with pytest.raises(DuplicateKeyError):
            await repo.backfill_public_slug(pending.id, slug)


@pytest.fixture
async def seeded_creator(
    raw_collection: AsyncIOMotorCollection,
) -> AsyncIterator[tuple[str, dict[str, object]]]:
    """A real user document in the shared ``gaia_test.users`` collection, keyed by a
    unique ObjectId so a concurrent run can't collide, dropped on teardown.

    The ``creator_lookup_stage`` ``$lookup`` (``from: "users"``) resolves against
    this collection server-side — the patched repository accessor only redirects
    the ``workflows`` handle, so the join reads the genuine ``users`` collection.
    Returns the creator's string id (what a workflow stores in ``created_by``) and
    the seeded document.
    """
    users = raw_collection.database["users"]
    oid = ObjectId()
    doc: dict[str, object] = {
        "_id": oid,
        "name": f"Creator {uuid.uuid4().hex[:6]}",
        "email": f"{uuid.uuid4().hex[:8]}@example.com",
        "picture": "https://example.com/avatar.png",
    }
    await users.insert_one(doc)
    try:
        yield str(oid), doc
    finally:
        await users.delete_one({"_id": oid})


class TestWorkflowsPublicMarketplaceReads:
    async def test_get_public_with_creator_by_id_and_slug(self, repo, seeded_creator):
        creator_id, creator = seeded_creator
        slug = _uid("slug")
        wf = await repo.create(
            _workflow(is_public=True, slug=slug, created_by=creator_id, title="Public One")
        )

        by_id = await repo.get_public_with_creator(wf.id, by_slug=False)
        assert by_id is not None
        assert by_id.id == wf.id and by_id.title == "Public One"
        # The creator $lookup resolved the real user (assert membership — the shared
        # users collection may hold unrelated rows, but the unique OID match is ours).
        names = [c.name for c in by_id.creator_info]
        assert creator["name"] in names
        pictures = [c.picture for c in by_id.creator_info]
        assert creator["picture"] in pictures

        by_slug = await repo.get_public_with_creator(slug, by_slug=True)
        assert by_slug is not None and by_slug.id == wf.id

        # creator_info is excluded from the response serialization.
        assert "creator_info" not in by_id.model_dump()

    async def test_get_public_with_creator_excludes_private_and_missing(self, repo):
        private = await repo.create(_workflow(is_public=False))
        assert await repo.get_public_with_creator(private.id, by_slug=False) is None
        assert await repo.get_public_with_creator(_uid("nope"), by_slug=False) is None
        assert await repo.get_public_with_creator(_uid("nope"), by_slug=True) is None

    async def test_find_community_excludes_explore_and_private(self, repo, raw_collection):
        now = datetime.now(UTC)
        older = await repo.create(_workflow(is_public=True, created_at=now - timedelta(hours=1)))
        newer = await repo.create(_workflow(is_public=True, created_at=now))
        # public but explore → excluded from community
        explore = await repo.create(_workflow(is_public=True))
        await raw_collection.update_one({"_id": explore.id}, {"$set": {"is_explore": True}})
        # private → excluded
        await repo.create(_workflow(is_public=False))

        rows = await repo.find_community(limit=20, offset=0)
        assert [r.id for r in rows] == [newer.id, older.id]  # newest first
        assert await repo.count_community() == 2
        # pagination
        page2 = await repo.find_community(limit=1, offset=1)
        assert [r.id for r in page2] == [older.id]

    async def test_find_explore_orders_and_creator_always_empty(
        self, repo, raw_collection, seeded_creator
    ):
        creator_id, _ = seeded_creator
        # created_by is a real user id, but explore's plain lookup can't match a
        # string against an ObjectId — creator_info stays empty by design.
        hot = await repo.create(_workflow(total_executions=10, created_by=creator_id))
        cold = await repo.create(_workflow(total_executions=1, created_by=creator_id))
        for wf in (hot, cold):
            await raw_collection.update_one({"_id": wf.id}, {"$set": {"is_explore": True}})
        # non-explore → excluded
        await repo.create(_workflow(is_public=True, total_executions=99))

        rows = await repo.find_explore(limit=20, offset=0)
        assert [r.id for r in rows] == [hot.id, cold.id]  # most-run first
        assert all(r.creator_info == [] for r in rows)
        assert await repo.count_explore() == 2

    async def test_find_explore_reads_use_case_categories(self, repo, raw_collection):
        wf = await repo.create(_workflow())
        await raw_collection.update_one(
            {"_id": wf.id},
            {"$set": {"is_explore": True, "use_case_categories": ["email", "ops"]}},
        )
        rows = await repo.find_explore(limit=20, offset=0)
        assert rows[0].use_case_categories == ["email", "ops"]
        # a row without the field falls back to the ["featured"] default.
        bare = await repo.create(_workflow())
        await raw_collection.update_one({"_id": bare.id}, {"$set": {"is_explore": True}})
        rows = await repo.find_explore(limit=20, offset=0)
        bare_row = next(r for r in rows if r.id == bare.id)
        assert bare_row.use_case_categories == ["featured"]

    async def test_find_public_by_step_category_matches_and_escapes(self, repo, seeded_creator):
        creator_id, creator = seeded_creator
        gmail_wf = await repo.create(
            _workflow(
                is_public=True,
                created_by=creator_id,
                steps=[WorkflowStep(title="s", category="gmail", description="d")],
            )
        )
        # a private workflow with a matching step must not surface
        await repo.create(
            _workflow(
                is_public=False,
                steps=[WorkflowStep(title="s", category="notion", description="d")],
            )
        )

        rows = await repo.find_public_by_step_category("gmail", limit=20, offset=0)
        assert [r.id for r in rows] == [gmail_wf.id]
        assert creator["name"] in [c.name for r in rows for c in r.creator_info]
        assert await repo.count_public_by_step_category("gmail") == 1

        # notion_wf is not public — a category search must not surface it.
        assert await repo.find_public_by_step_category("notion", limit=20, offset=0) == []

        # the pattern is escaped: "g.ail" is literal, not a regex matching "gmail".
        assert await repo.count_public_by_step_category("g.ail") == 0
