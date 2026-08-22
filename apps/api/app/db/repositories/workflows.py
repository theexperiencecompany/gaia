"""Repository for the workflows collection.

A global (non-user-scoped) repository: its hottest paths cross users — the
scheduler scans every due workflow, webhook routing matches by Composio trigger
id, the community/explore marketplace reads are public, and system provisioning
runs per user without a request in context. Identity is the string business key
``id`` (persisted as ``_id``; the two are equal ``wf_…`` UUIDs), so
``uses_object_id=False`` and Mongo filters key on ``_id``/``slug`` (both indexed),
never the redundant persisted ``id`` field.

Owned CRUD is expressed as ``*_for_user`` named methods that add the ``user_id``
guard. Nested (``trigger_config.*``) and operator (``$inc`` stats, the atomic
status claim) writes go through the raw-update seam — a flat ``WorkflowUpdate``
``$set`` cannot express them.

No ``CachePolicy``: workflows are written on nearly every scheduler tick (status
claim, re-arm, execution-count ``$inc``), so an entity/generation cache would
churn its generation constantly for little read benefit, and the cross-user
scan/routing reads are not keyed by id. Matches the ``workflow_executions``
repository. Revisit only with evidence of a hot by-id read path.
"""

from datetime import UTC, datetime
import re
from typing import Any

from app.constants.cache import REPO_GLOBAL_SCOPE
from app.db.repositories.base import MongoRepository
from app.models.scheduler_models import ScheduledTaskStatus
from app.models.workflow_models import (
    DeactivationReason,
    PublicWorkflowRow,
    TriggerConfig,
    TriggerType,
    WorkflowDocument,
    WorkflowStep,
    WorkflowUpdate,
)
from app.utils.creator import creator_lookup_stage

# The scheduler's occurrence field, written by every arm/re-arm path and pinned
# by the stale-fire claim gate. One constant keeps the dotted key from drifting
# between the writers and the gate.
NEXT_RUN_FIELD = "trigger_config.next_run"

# Cron-driven workflows only carry a non-empty ``repeat``; manual / integration /
# todo workflows default to status="scheduled" with ``scheduled_at=now``, so the
# pending scan must exclude them or it would re-run the agent every pass.
_RECURRING_REPEAT_FILTER: dict[str, Any] = {"repeat": {"$nin": [None, ""]}}

# ``_aggregate`` validates each raw row straight into the result model, and the
# raw carries ``_id`` (not ``id``); this stage surfaces the string business key as
# ``id`` so the row validates. Appended to every public-read pipeline.
_ADD_ID_STAGE: dict[str, Any] = {"$addFields": {"id": "$_id"}}

# The community marketplace shows public workflows that are NOT explore/featured;
# the same match drives both the paged aggregation and its total count so the two
# can never diverge.
_COMMUNITY_MATCH: dict[str, Any] = {
    "is_public": True,
    "$or": [{"is_explore": {"$exists": False}}, {"is_explore": False}],
}


class _Unset:
    """Sentinel for a ``set_status`` field that was not provided — distinct from an
    explicit ``None``, which the recovery scan legitimately writes (a reaped
    non-recurring workflow clears its ``scheduled_at``)."""


UNSET = _Unset()


class WorkflowsRepository(MongoRepository[WorkflowDocument, WorkflowUpdate]):
    collection_name = "workflows"
    document_model = WorkflowDocument
    update_model = WorkflowUpdate
    uses_object_id = False
    identity_field = "_id"
    cache_policy = None

    # ------------------------------------------------------------------ reads

    async def get_for_user(self, workflow_id: str, user_id: str) -> WorkflowDocument | None:
        """A workflow by id, scoped to its owner — the owned-read path."""
        return await self._find_one({"_id": workflow_id, "user_id": user_id})

    @staticmethod
    def _list_query(user_id: str, *, exclude_todo_workflows: bool) -> dict[str, Any]:
        """The shared filter for a user's listed workflows — the single source of
        truth for both ``list_for_user`` and ``count_for_user`` so a paginated
        list and its total can never drift out of the same predicate."""
        query: dict[str, Any] = {"user_id": user_id}
        if exclude_todo_workflows:
            query["$or"] = [
                {"is_todo_workflow": {"$exists": False}},
                {"is_todo_workflow": False},
            ]
        return query

    async def list_for_user(
        self,
        user_id: str,
        *,
        exclude_todo_workflows: bool = True,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[WorkflowDocument]:
        """A user's workflows, newest first. Auto-generated todo workflows are
        excluded by default (they are an implementation detail, not user-authored).
        ``limit=None`` fetches every match; pass ``limit``/``offset`` to paginate
        (``count_for_user`` gives the full match count for the same filter).

        A single legacy-malformed row is skipped and logged loudly rather than
        failing the whole read — one corrupt document must not blank a user's
        entire workflow list. This graceful degradation is scoped to the LIST read
        only: the single-document reads (``get``/``get_for_user``) stay strict so a
        fetch of a known id surfaces the corruption instead of hiding it.
        """
        return await self._find_lenient(
            self._list_query(user_id, exclude_todo_workflows=exclude_todo_workflows),
            sort=[("created_at", -1)],
            limit=limit or 0,
            skip=offset,
        )

    async def count_for_user(self, user_id: str, *, exclude_todo_workflows: bool = True) -> int:
        """Total workflows a user has under the same filter as ``list_for_user`` —
        the ``total`` a paginated list reports, independent of ``limit``/``offset``."""
        return await self._count(
            self._list_query(user_id, exclude_todo_workflows=exclude_todo_workflows)
        )

    async def find_by_ids(self, workflow_ids: list[str]) -> list[WorkflowDocument]:
        """Workflows whose ids are in ``workflow_ids`` (no user scoping)."""
        if not workflow_ids:
            return []
        return await self._find({"_id": {"$in": workflow_ids}})

    async def find_by_ids_for_user(
        self, workflow_ids: list[str], user_id: str
    ) -> list[WorkflowDocument]:
        """The user's workflows whose ids are in ``workflow_ids``."""
        if not workflow_ids:
            return []
        return await self._find({"_id": {"$in": workflow_ids}, "user_id": user_id})

    async def find_system_workflow(
        self, user_id: str, system_workflow_key: str
    ) -> WorkflowDocument | None:
        """The user's system workflow for ``system_workflow_key`` — the provisioner's
        idempotency probe (a partial-unique index guards concurrent creation)."""
        return await self._find_one(
            {
                "user_id": user_id,
                "system_workflow_key": system_workflow_key,
                "is_system_workflow": True,
            }
        )

    async def get_system_workflow_for_user(
        self, workflow_id: str, user_id: str
    ) -> WorkflowDocument | None:
        """A user's system workflow by id — the reset-to-default load."""
        return await self._find_one(
            {"_id": workflow_id, "user_id": user_id, "is_system_workflow": True}
        )

    async def find_active_integration_workflows(
        self, user_id: str, trigger_names: list[str]
    ) -> list[WorkflowDocument]:
        """A user's activated integration workflows for the given trigger slugs — the
        set re-registered against a fresh Composio account after a (re)connect."""
        if not trigger_names:
            return []
        return await self._find(
            {
                "user_id": user_id,
                "activated": True,
                "trigger_config.type": TriggerType.INTEGRATION.value,
                "trigger_config.enabled": True,
                "trigger_config.trigger_name": {"$in": trigger_names},
            }
        )

    async def find_active_by_composio_trigger(
        self, trigger_id: str, *, trigger_name: str | None = None
    ) -> list[WorkflowDocument]:
        """Activated integration workflows registered under a Composio ``trigger_id`` —
        the fan-out target when a webhook arrives for that id. ``trigger_name`` narrows
        to a single trigger slug for the caller that must disambiguate (Gmail's poll
        path, where account-level and poll workflows share the handler)."""
        query: dict[str, Any] = {
            "activated": True,
            "trigger_config.type": TriggerType.INTEGRATION.value,
            "trigger_config.enabled": True,
            "trigger_config.composio_trigger_ids": trigger_id,
        }
        if trigger_name is not None:
            query["trigger_config.trigger_name"] = trigger_name
        return await self._find(query)

    async def find_activated_for_user(self, user_id: str) -> list[WorkflowDocument]:
        """Every activated workflow a user owns — the dormancy sweep's pause set."""
        return await self._find({"user_id": user_id, "activated": True})

    async def find_paused_for_reason(
        self, user_id: str, reason: DeactivationReason
    ) -> list[WorkflowDocument]:
        """A user's workflows the system paused for ``reason`` — the only ones an
        automatic resume may touch. A workflow the user switched off themselves
        carries no reason and is therefore never matched."""
        return await self._find(
            {"user_id": user_id, "activated": False, "deactivated_reason": reason.value}
        )

    async def find_stale_executing(self, cutoff: datetime) -> list[WorkflowDocument]:
        """Activated workflows wedged in EXECUTING since before ``cutoff`` — the
        recovery sweep's re-arm candidates (a worker died mid-fire)."""
        return await self._find(
            {
                "activated": True,
                "status": ScheduledTaskStatus.EXECUTING.value,
                "updated_at": {"$lt": cutoff},
            }
        )

    async def find_pending_before(self, current_time: datetime) -> list[WorkflowDocument]:
        """Recurring (cron) workflows that are scheduled and due at ``current_time``.

        The due filter (``status="scheduled"`` and ``scheduled_at <= now``) is the
        shared scheduler semantics — kept identical to ``ReminderRepository`` so the
        two scans can never diverge on the ``$lte`` operator again.
        """
        return await self._find(
            {
                "status": ScheduledTaskStatus.SCHEDULED.value,
                "scheduled_at": {"$lte": current_time},
                "activated": True,
                **_RECURRING_REPEAT_FILTER,
            }
        )

    async def count_trigger_references(
        self, composio_trigger_id: str, *, excluding_workflow_id: str | None = None
    ) -> int:
        """How many workflows still reference ``composio_trigger_id`` — a Composio
        trigger is only safe to delete at zero. ``excluding_workflow_id`` drops the
        workflow being deleted/updated from the count."""
        query: dict[str, Any] = {"trigger_config.composio_trigger_ids": composio_trigger_id}
        if excluding_workflow_id:
            query["_id"] = {"$ne": excluding_workflow_id}
        return await self._count(query)

    async def find_public_slug_conflict(
        self, slug: str, *, exclude_id: str | None = None
    ) -> WorkflowDocument | None:
        """A public workflow already holding ``slug`` (excluding ``exclude_id``), or
        ``None`` when the slug is free — the pre-write uniqueness probe."""
        query: dict[str, Any] = {"slug": slug, "is_public": True}
        if exclude_id:
            query["_id"] = {"$ne": exclude_id}
        return await self._find_one(query)

    # ------------------------------------------------- public marketplace reads

    async def get_public_with_creator(self, ref: str, *, by_slug: bool) -> PublicWorkflowRow | None:
        """A single public workflow by id (``by_slug=False``) or slug, with its
        creator hydrated. ``None`` when no public workflow matches ``ref``."""
        match: dict[str, Any] = (
            {"slug": ref, "is_public": True} if by_slug else {"_id": ref, "is_public": True}
        )
        rows = await self._aggregate(
            [{"$match": match}, creator_lookup_stage(), {"$limit": 1}, _ADD_ID_STAGE],
            PublicWorkflowRow,
        )
        return rows[0] if rows else None

    async def find_community(self, *, limit: int, offset: int) -> list[PublicWorkflowRow]:
        """A page of community-marketplace workflows (public, non-explore), newest
        first, each with its creator hydrated."""
        return await self._aggregate(
            [
                {"$match": _COMMUNITY_MATCH},
                {"$sort": {"created_at": -1}},
                {"$skip": offset},
                {"$limit": limit},
                creator_lookup_stage(),
                _ADD_ID_STAGE,
            ],
            PublicWorkflowRow,
        )

    async def count_community(self) -> int:
        """Total community-marketplace workflows (matches ``find_community``)."""
        return await self._count(_COMMUNITY_MATCH)

    async def find_explore(self, *, limit: int, offset: int) -> list[PublicWorkflowRow]:
        """A page of explore/featured workflows, most-run first.

        Uses a plain ``localField``/``foreignField`` ``$lookup``: ``created_by`` is
        a string while ``users._id`` is an ``ObjectId``, so this never matches and
        ``creator_info`` is always empty — explore (GAIA-curated) workflows resolve
        to the ``SYSTEM_CREATOR_NAME`` fallback by design. Preserved verbatim from
        the pre-repository aggregation.
        """
        return await self._aggregate(
            [
                {"$match": {"is_explore": True}},
                {"$sort": {"total_executions": -1, "updated_at": -1}},
                {"$skip": offset},
                {"$limit": limit},
                {
                    "$lookup": {
                        "from": "users",
                        "localField": "created_by",
                        "foreignField": "_id",
                        "as": "creator_info",
                    }
                },
                _ADD_ID_STAGE,
            ],
            PublicWorkflowRow,
        )

    async def count_explore(self) -> int:
        """Total explore/featured workflows (matches ``find_explore``)."""
        return await self._count({"is_explore": True})

    async def find_public_by_step_category(
        self, category: str, *, limit: int, offset: int
    ) -> list[PublicWorkflowRow]:
        """Public or explore workflows with a step whose ``category`` matches
        ``category`` (case-insensitive), most-run first, each with its creator
        hydrated. ``category`` is regex-escaped here so it is matched literally —
        the boundary owns the ReDoS/injection guard."""
        return await self._aggregate(
            [
                {"$match": self._step_category_match(category)},
                {"$sort": {"total_executions": -1, "created_at": -1}},
                {"$skip": offset},
                {"$limit": limit},
                creator_lookup_stage(),
                _ADD_ID_STAGE,
            ],
            PublicWorkflowRow,
        )

    async def count_public_by_step_category(self, category: str) -> int:
        """Total workflows matching ``find_public_by_step_category``."""
        return await self._count(self._step_category_match(category))

    @staticmethod
    def _step_category_match(category: str) -> dict[str, Any]:
        return {
            "$or": [{"is_public": True}, {"is_explore": True}],
            "steps": {"$elemMatch": {"category": {"$regex": re.escape(category), "$options": "i"}}},
        }

    # ----------------------------------------------------------------- writes

    async def update_for_user(
        self, workflow_id: str, user_id: str, update: WorkflowUpdate
    ) -> WorkflowDocument | None:
        """Apply a flat ``$set`` update to the user's workflow. Returns the after
        state, or ``None`` when no matching workflow exists."""
        return await self._apply_update(
            workflow_id, REPO_GLOBAL_SCOPE, {"user_id": user_id}, update
        )

    async def touch(self, workflow_id: str, user_id: str) -> WorkflowDocument | None:
        """Bump only ``updated_at`` on the user's workflow (execute/generation
        heartbeat). Returns the after state, or ``None`` if not found."""
        return await self._apply_raw_update(
            {"_id": workflow_id, "user_id": user_id}, {}, scope=REPO_GLOBAL_SCOPE
        )

    async def mark_error(
        self, workflow_id: str, user_id: str, *, deactivate: bool = False
    ) -> WorkflowDocument | None:
        """Record an error heartbeat (bump ``updated_at``), optionally deactivating
        the workflow so an unrunnable one stops firing."""
        ops: dict[str, dict[str, Any]] = {}
        if deactivate:
            ops["$set"] = {"activated": False}
        return await self._apply_raw_update(
            {"_id": workflow_id, "user_id": user_id}, ops, scope=REPO_GLOBAL_SCOPE
        )

    async def set_error_message(
        self, workflow_id: str, user_id: str, message: str
    ) -> WorkflowDocument | None:
        """Persist a step-generation failure message for the status endpoint."""
        return await self._apply_raw_update(
            {"_id": workflow_id, "user_id": user_id},
            {"$set": {"error_message": message}},
            scope=REPO_GLOBAL_SCOPE,
        )

    async def set_steps(
        self,
        workflow_id: str,
        user_id: str,
        steps: list[WorkflowStep],
        *,
        deactivate: bool = False,
        integration_ids: list[str] | None = None,
    ) -> WorkflowDocument | None:
        """Replace a workflow's steps (LLM generation/regeneration). When the new
        steps need integrations the user hasn't connected, ``deactivate`` forces the
        workflow inactive so an enabled-but-unrunnable workflow can't keep firing."""
        set_fields: dict[str, Any] = {"steps": [s.model_dump() for s in steps]}
        if integration_ids is not None:
            set_fields["integration_ids"] = integration_ids
        if deactivate:
            set_fields["activated"] = False
            set_fields["trigger_config.enabled"] = False
        return await self._apply_raw_update(
            {"_id": workflow_id, "user_id": user_id},
            {"$set": set_fields},
            scope=REPO_GLOBAL_SCOPE,
        )

    async def record_execution(
        self, workflow_id: str, user_id: str, *, successful: bool = False
    ) -> bool:
        """Bump execution counters and stamp ``last_executed_at``. Returns whether a
        workflow was matched."""
        inc_fields: dict[str, Any] = {"total_executions": 1}
        if successful:
            inc_fields["successful_executions"] = 1
        result = await self._apply_raw_update(
            {"_id": workflow_id, "user_id": user_id},
            {"$inc": inc_fields, "$set": {"last_executed_at": datetime.now(UTC)}},
            scope=REPO_GLOBAL_SCOPE,
        )
        return result is not None

    async def activate(
        self,
        workflow_id: str,
        user_id: str,
        *,
        trigger_ids: list[str],
        next_run: datetime | None,
    ) -> WorkflowDocument | None:
        """Activate the user's workflow: set liveness (``activated``) and re-arm its
        run-state to idle (``status="scheduled"``) with a freshly recomputed run
        time. Returns the after state, or ``None`` when not found."""
        return await self._apply_raw_update(
            {"_id": workflow_id, "user_id": user_id},
            {
                "$set": {
                    "activated": True,
                    "trigger_config.enabled": True,
                    "trigger_config.composio_trigger_ids": trigger_ids,
                    "status": ScheduledTaskStatus.SCHEDULED.value,
                    "scheduled_at": next_run,
                    NEXT_RUN_FIELD: next_run,
                    "deactivated_reason": None,
                }
            },
            scope=REPO_GLOBAL_SCOPE,
        )

    async def deactivate(
        self, workflow_id: str, user_id: str, *, reason: DeactivationReason | None = None
    ) -> WorkflowDocument | None:
        """Deactivate the user's workflow (disable its trigger and clear Composio
        ids). Liveness is governed by ``activated``; a deferred fire is rejected by
        the claim gate. ``reason`` marks a system pause so an automatic resume can
        tell it apart from a user switching the workflow off (which passes none).
        Returns the after state, or ``None`` when not found."""
        return await self._apply_raw_update(
            {"_id": workflow_id, "user_id": user_id},
            {
                "$set": {
                    "activated": False,
                    "trigger_config.enabled": False,
                    "trigger_config.composio_trigger_ids": [],
                    "deactivated_reason": reason.value if reason else None,
                }
            },
            scope=REPO_GLOBAL_SCOPE,
        )

    async def mark_activated_with_triggers(
        self, workflow_id: str, *, trigger_ids: list[str]
    ) -> WorkflowDocument | None:
        """Flip a freshly-created pending workflow live (``activated`` + trigger
        ``enabled``), storing any registered Composio ids. Keyed by id alone — the
        create saga owns the row and no other user can hold this id."""
        set_fields: dict[str, Any] = {"activated": True, "trigger_config.enabled": True}
        if trigger_ids:
            set_fields["trigger_config.composio_trigger_ids"] = trigger_ids
        return await self._apply_raw_update(
            {"_id": workflow_id}, {"$set": set_fields}, scope=REPO_GLOBAL_SCOPE
        )

    async def claim_for_execution(
        self, workflow_id: str, *, expected_next_run: datetime | None = None
    ) -> bool:
        """Atomically claim a live, idle workflow for a fire (SCHEDULED -> EXECUTING).

        Returns ``False`` — and the caller skips the fire — when the workflow is not
        both ``activated`` and ``status="scheduled"`` (a concurrent recovery scan
        already claimed it, or it was deactivated but a deferred job fired anyway).

        ``expected_next_run`` pins the occurrence the fire was armed for: ARQ has
        no job cancellation, so after a reschedule the old deferred job still
        fires — but ``trigger_config.next_run`` has moved on, and the mismatch
        rejects it. Jobs enqueued before this stamp existed pass ``None`` and
        claim exactly as before.
        """
        filter_: dict[str, Any] = {
            "_id": workflow_id,
            "activated": True,
            "status": ScheduledTaskStatus.SCHEDULED.value,
        }
        if expected_next_run is not None:
            filter_[NEXT_RUN_FIELD] = expected_next_run
        result = await self._apply_raw_update(
            filter_,
            {"$set": {"status": ScheduledTaskStatus.EXECUTING.value}},
            scope=REPO_GLOBAL_SCOPE,
        )
        return result is not None

    async def set_status(
        self,
        workflow_id: str,
        status: ScheduledTaskStatus,
        *,
        user_id: str | None = None,
        scheduled_at: datetime | _Unset | None = UNSET,
        occurrence_count: int | None = None,
        repeat: str | None = None,
        next_run: datetime | _Unset | None = UNSET,
    ) -> bool:
        """Set a workflow's run-state ``status`` plus the scheduler's re-arm fields.
        Returns whether a workflow matched. ``user_id`` adds the owner guard where
        the caller has one; the worker paths update by id alone.

        ``scheduled_at`` and ``next_run`` (written as ``trigger_config.next_run``)
        take an ``UNSET`` sentinel because ``None`` is a meaningful value the recovery
        scan writes — omitted fields are left untouched; an explicit ``None`` clears
        them. ``occurrence_count``/``repeat`` are only set when provided (they never
        need clearing to ``None``)."""
        filter_: dict[str, Any] = {"_id": workflow_id}
        if user_id:
            filter_["user_id"] = user_id
        set_fields: dict[str, Any] = {"status": status.value}
        if not isinstance(scheduled_at, _Unset):
            set_fields["scheduled_at"] = scheduled_at
        if occurrence_count is not None:
            set_fields["occurrence_count"] = occurrence_count
        if repeat is not None:
            set_fields["repeat"] = repeat
        if not isinstance(next_run, _Unset):
            set_fields[NEXT_RUN_FIELD] = next_run
        result = await self._apply_raw_update(
            filter_, {"$set": set_fields}, scope=REPO_GLOBAL_SCOPE
        )
        return result is not None

    async def set_composio_trigger_ids(
        self, workflow_id: str, trigger_ids: list[str]
    ) -> WorkflowDocument | None:
        """Repoint a workflow's registered Composio trigger ids after a resync."""
        return await self._apply_raw_update(
            {"_id": workflow_id},
            {"$set": {"trigger_config.composio_trigger_ids": trigger_ids}},
            scope=REPO_GLOBAL_SCOPE,
        )

    async def backfill_public_slug(self, workflow_id: str, slug: str) -> WorkflowDocument | None:
        """Set ``slug`` on a public workflow only while it is still unset — the lazy
        legacy backfill. Returns the after state on success, or ``None`` when another
        writer won the race (matched nothing). May raise ``DuplicateKeyError`` on a
        true slug collision; the caller retries with a fresh slug."""
        return await self._apply_raw_update(
            {"_id": workflow_id},
            {"$set": {"slug": slug}},
            scope=REPO_GLOBAL_SCOPE,
            extra_filter={"$or": [{"slug": None}, {"slug": ""}]},
        )

    async def publish(
        self, workflow_id: str, *, created_by: str, slug: str
    ) -> WorkflowDocument | None:
        """Publish a workflow to the community marketplace. May raise
        ``DuplicateKeyError`` on a slug collision; the caller retries."""
        return await self._apply_raw_update(
            {"_id": workflow_id},
            {"$set": {"is_public": True, "created_by": created_by, "slug": slug}},
            scope=REPO_GLOBAL_SCOPE,
        )

    async def unpublish(self, workflow_id: str) -> WorkflowDocument | None:
        """Remove a workflow from the community marketplace."""
        return await self._apply_raw_update(
            {"_id": workflow_id},
            {"$set": {"is_public": False}},
            scope=REPO_GLOBAL_SCOPE,
        )

    async def reset_system_workflow(
        self,
        workflow_id: str,
        *,
        title: str,
        description: str,
        steps: list[WorkflowStep],
        trigger_config: TriggerConfig,
        composio_trigger_ids: list[str],
    ) -> WorkflowDocument | None:
        """Re-apply a system workflow's original definition (title/description/steps/
        trigger_config), preserving liveness, stats and ``created_at``. ``next_run``
        stays a native datetime (python-mode dump), consistent with create/re-arm."""
        trigger_doc = trigger_config.model_dump()
        trigger_doc["composio_trigger_ids"] = composio_trigger_ids
        return await self._apply_raw_update(
            {"_id": workflow_id},
            {
                "$set": {
                    "title": title,
                    "description": description,
                    "steps": [s.model_dump() for s in steps],
                    "trigger_config": trigger_doc,
                }
            },
            scope=REPO_GLOBAL_SCOPE,
        )

    async def delete_for_user(self, workflow_id: str, user_id: str) -> bool:
        """Delete the user's workflow. Returns whether a document was removed."""
        return await self._remove(workflow_id, REPO_GLOBAL_SCOPE, {"user_id": user_id})

    async def delete_many_for_user(self, workflow_ids: list[str], user_id: str) -> int:
        """Delete many of the user's workflows in one round trip (idempotency purge
        of stale suggestions). Returns the count deleted."""
        if not workflow_ids:
            return 0
        return await self._delete_many(
            {"_id": {"$in": workflow_ids}, "user_id": user_id}, scope=REPO_GLOBAL_SCOPE
        )


workflow_repository = WorkflowsRepository()
