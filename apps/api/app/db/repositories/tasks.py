"""Repository for the tasks collection: to-dos and GAIA's work, once or on repeat.

User-scoped and cached under each user's generation. Identity is the string _id (task_,
wf_ or a migrated todo's ObjectId hex), so uses_object_id is False. The cross-user reads
the engine needs (due runs, app-event dispatch, stale runs, sweeps) are uncached finders
named *_all_users; every one is bounded or keyed by an indexed id.
"""

from collections.abc import Collection, Mapping
from datetime import UTC, datetime
import re

from pydantic import BaseModel

from app.constants.cache import TASK_CACHE_PREFIX
from app.constants.tasks import Assignee, TaskFlag, TaskRunState, TaskRunStatus, WhenKind
from app.constants.trigger_gates import GATE_RECENT_SKIPS_KEPT
from app.db.repositories.base import UserScopedRepository, cached_query
from app.db.repositories.cache import CachePolicy
from app.models.scheduler_models import DeactivationReason
from app.models.task_models import (
    OpenSubtaskCount,
    TaskCounts,
    TaskDocument,
    TaskPage,
    TaskQuery,
    TaskUpdate,
    When,
)
from app.models.todo_models import (
    DueRange,
    ExternalRef,
    ExternalRefSource,
    SubTask,
    TodoDayWindow,
)
from app.models.trigger_gate_models import GateSkipRecord, TriggerGate
from app.models.trigger_subscription_models import (
    SubscriptionAction,
    TriggerSubscription,
    TriggerSubscriptionStatus,
)
from app.utils.occurrence import occurrence_window

#: The two fields a GAIA task's next run lives in: a repeating task's schedule, a one-off's next check.
NEXT_RUN_FIELD = "when.next_run"
NEXT_CHECK_FIELD = "next_check_at"
#: The field a to-do's owed nudge lives in.
NUDGE_FIELD = "nudge_at"
_SHORT_ID = re.compile(r"[0-9a-f]{8}")


class _FacetCount(BaseModel):
    count: int = 0


class _CountsFacet(BaseModel):
    today: list[_FacetCount] = []
    upcoming: list[_FacetCount] = []
    overdue: list[_FacetCount] = []
    completed: list[_FacetCount] = []


def _first(buckets: list[_FacetCount]) -> int:
    return buckets[0].count if buckets else 0


def _external_ref_filter(ref: ExternalRef) -> dict[str, object]:
    # $type keeps the query inside the partial unique index; a bare equality scans.
    return {
        "external_ref.source": ref.source.value,
        "external_ref.id": {"$eq": ref.id, "$type": "string"},
    }


def _due_at(field: str, now: datetime) -> dict[str, object]:
    return {field: {"$lte": now, "$type": "date"}}


def _between(due: DueRange) -> dict[str, datetime]:
    return {"$gte": due.start, "$lte": due.end}


def _due_filter(query: TaskQuery) -> dict[str, object]:
    """Build the due-date part of a list filter; an overdue read is of open tasks only."""
    filt: dict[str, object] = {}
    if query.has_due is not None:
        filt["when.kind"] = WhenKind.DATE.value if query.has_due else {"$ne": WhenKind.DATE.value}
    due: dict[str, object] = {}
    if query.due_after is not None:
        due["$gte"] = query.due_after
    if query.due_before is not None:
        due["$lte"] = query.due_before
    if query.overdue:
        if query.day_window is None:
            raise ValueError("an overdue read needs the user's day window")
        due["$lt"] = query.day_window.today_start
        filt["completed"] = False
    if due:
        filt["when.at"] = due
    return filt


def _listening() -> dict[str, object]:
    """Open tasks that are on, or that the system paused and so keep their events."""
    return {
        "completed": False,
        "$or": [{"active": True}, {"pause_reason": {"$ne": None}}],
    }


def _runnable() -> dict[str, object]:
    """Match a GAIA task that may be started: on, idle and open."""
    return {
        "assignee": Assignee.GAIA.value,
        "active": True,
        "completed": False,
        "run_state": TaskRunState.IDLE.value,
    }


class TasksRepository(UserScopedRepository[TaskDocument, TaskUpdate]):
    """The tasks collection repository (user-scoped, cached)."""

    collection_name = "tasks"
    document_model = TaskDocument
    update_model = TaskUpdate
    uses_object_id = False
    cache_policy = CachePolicy(prefix=TASK_CACHE_PREFIX)

    def _scoped(self, task_id: str, user_id: str) -> dict[str, object]:
        return {"_id": task_id, "user_id": user_id}

    # ------------------------------------------------------------------ reads

    async def get_any(self, task_id: str) -> TaskDocument | None:
        """Fetch a task by id with no user scoping, for a worker that holds only the id."""
        return await self._find_one({"_id": task_id})

    async def find_by_ids(self, user_id: str, task_ids: list[str]) -> list[TaskDocument]:
        """Return the user's tasks among task_ids (order not preserved)."""
        if not task_ids:
            return []
        return await self._find({"_id": {"$in": task_ids}, "user_id": user_id})

    async def count_authored(self, user_id: str) -> int:
        """How many tasks the user made themselves: system tasks left out."""
        return await self._count({"user_id": user_id, "system_key": None})

    def _list_filter(self, user_id: str, query: TaskQuery) -> dict[str, object]:
        filt: dict[str, object] = {"user_id": user_id}
        if query.q:
            pattern = {"$regex": re.escape(query.q), "$options": "i"}
            filt["$or"] = [{"title": pattern}, {"body": pattern}]
        if query.assignee is not None:
            filt["assignee"] = query.assignee.value
        if query.completed is not None:
            filt["completed"] = query.completed
        if query.priority is not None:
            filt["priority"] = query.priority.value
        if query.parent_id is not None:
            filt["parent_id"] = query.parent_id
        elif query.top_level:
            filt["parent_id"] = None
        if query.flags:
            filt["status_flags"] = {"$all": [flag.value for flag in query.flags]}
        return {**filt, **_due_filter(query)}

    @cached_query(TaskPage)
    async def list_page(self, *, user_id: str, query: TaskQuery) -> TaskPage:
        """One page of the user's tasks, newest first, and the total under the same filter."""
        filt = self._list_filter(user_id, query)
        total = await self._count(filt)
        items = await self._find(
            filt,
            sort=[("created_at", -1)],
            skip=(query.page - 1) * query.per_page,
            limit=query.per_page,
        )
        return TaskPage(items=items, total=total)

    @cached_query(TaskCounts)
    async def compute_counts(self, *, user_id: str, window: TodoDayWindow) -> TaskCounts:
        """Count the sidebar buckets on the user's own day: due today, upcoming, overdue, and done."""
        open_dated = {"completed": False, "when.kind": WhenKind.DATE.value}
        facets = await self._aggregate(
            [
                {"$match": {"user_id": user_id}},
                {
                    "$facet": {
                        "today": [
                            {
                                "$match": {
                                    **open_dated,
                                    "when.at": _between(window.today),
                                }
                            },
                            {"$count": "count"},
                        ],
                        "upcoming": [
                            {
                                "$match": {
                                    **open_dated,
                                    "when.at": _between(window.upcoming),
                                }
                            },
                            {"$count": "count"},
                        ],
                        "overdue": [
                            {"$match": {**open_dated, "when.at": {"$lt": window.today_start}}},
                            {"$count": "count"},
                        ],
                        "completed": [{"$match": {"completed": True}}, {"$count": "count"}],
                    }
                },
            ],
            _CountsFacet,
        )
        if not facets:
            return TaskCounts()
        facet = facets[0]
        return TaskCounts(
            today=_first(facet.today),
            upcoming=_first(facet.upcoming),
            overdue=_first(facet.overdue),
            completed=_first(facet.completed),
        )

    async def list_onboarding(self, user_id: str, *, limit: int) -> list[TaskDocument]:
        """Return the user's onboarding-seeded tasks, newest first."""
        return await self._find(
            {"user_id": user_id, "from_onboarding": True}, sort=[("created_at", -1)], limit=limit
        )

    @cached_query(list[TaskDocument])
    async def list_open_gaia(
        self,
        user_id: str,
        *,
        limit: int,
        flags: list[TaskFlag] | None = None,
        external_ref: ExternalRef | None = None,
        parent_id: str | None = None,
        top_level: bool = False,
    ) -> list[TaskDocument]:
        """Return the user's open GAIA tasks, most recently updated first; the context block's read."""
        filt: dict[str, object] = {
            "user_id": user_id,
            "assignee": Assignee.GAIA.value,
            "completed": False,
        }
        if flags:
            filt["status_flags"] = {"$all": [flag.value for flag in flags]}
        if external_ref is not None:
            filt.update(_external_ref_filter(external_ref))
        if parent_id is not None:
            filt["parent_id"] = parent_id
        elif top_level:
            filt["parent_id"] = None
        return await self._find(filt, sort=[("updated_at", -1)], limit=limit)

    async def find_subtasks(self, user_id: str, parent_ids: list[str]) -> list[TaskDocument]:
        """Every subtask, open or done, of the given parents; uncached, for cascades."""
        return await self._find({"user_id": user_id, "parent_id": {"$in": parent_ids}})

    @cached_query(dict[str, int])
    async def count_open_subtasks(self, user_id: str, parent_ids: list[str]) -> dict[str, int]:
        """Open subtasks per parent, for the parents that have any."""
        if not parent_ids:
            return {}
        rows = await self._aggregate(
            [
                {
                    "$match": {
                        "user_id": user_id,
                        "parent_id": {"$in": parent_ids},
                        "completed": False,
                    }
                },
                {"$group": {"_id": "$parent_id", "count": {"$sum": 1}}},
            ],
            OpenSubtaskCount,
        )
        return {row.parent_id: row.count for row in rows}

    async def list_since(
        self, user_id: str, *, assignee: Assignee, completed_since: datetime
    ) -> list[TaskDocument]:
        """Return the user's tasks of one assignee, open or done since completed_since: a workspace view's set."""
        return await self._find(
            {
                "user_id": user_id,
                "assignee": assignee.value,
                "$or": [{"completed": False}, {"completed_at": {"$gte": completed_since}}],
            }
        )

    async def find_gaia_by_short_id(self, user_id: str, *, short_id: str) -> list[TaskDocument]:
        """Return the user's GAIA tasks whose id ends with short_id, the folder suffix of their notes."""
        if _SHORT_ID.fullmatch(short_id) is None:
            return []
        return await self._find(
            {
                "user_id": user_id,
                "assignee": Assignee.GAIA.value,
                "_id": {"$regex": f"{short_id}$"},
            }
        )

    async def find_open_by_external_ref(
        self, user_id: str, ref: ExternalRef
    ) -> TaskDocument | None:
        """Return the user's open task about ref; uncached, as a losing insert reads the winner here."""
        return await self._find_one(
            {"user_id": user_id, **_external_ref_filter(ref), "completed": False}
        )

    async def find_latest_by_external_ref(
        self, user_id: str, ref: ExternalRef
    ) -> TaskDocument | None:
        """Return the user's newest task about ref, open or done; uncached."""
        return await self._find_one(
            {"user_id": user_id, **_external_ref_filter(ref)}, sort=[("created_at", -1)]
        )

    async def list_open_by_external_ref_source_all_users(
        self, source: ExternalRefSource, *, limit: int
    ) -> list[TaskDocument]:
        """Every user's open tasks about one kind of outside object, for one-off repairs."""
        return await self._find(
            {"completed": False, "external_ref.source": source.value}, limit=limit
        )

    async def find_system_task(self, user_id: str, system_key: str) -> TaskDocument | None:
        """Return the user's system task for system_key: the provisioner's idempotency probe."""
        return await self._find_one({"user_id": user_id, "system_key": system_key})

    async def find_live_system_tasks_all_users(
        self, system_key: str, *, limit: int, after_id: str | None = None
    ) -> list[TaskDocument]:
        """Every user's system task for system_key that runs or that GAIA may resume, in id order."""
        filt: dict[str, object] = {
            "system_key": system_key,
            "$or": [{"active": True}, {"pause_reason": {"$ne": None}}],
        }
        if after_id is not None:
            filt["_id"] = {"$gt": after_id}
        return await self._find(filt, sort=[("_id", 1)], limit=limit)

    async def find_active_gaia_for_user(self, user_id: str) -> list[TaskDocument]:
        """Return the user's open GAIA tasks that are on: the set a dormancy or plan pause switches off."""
        return await self._find(
            {
                "user_id": user_id,
                "assignee": Assignee.GAIA.value,
                "active": True,
                "completed": False,
            }
        )

    async def find_paused_for_reason(
        self, user_id: str, reason: DeactivationReason
    ) -> list[TaskDocument]:
        """Return the user's tasks the system paused for reason: the only ones its resume may touch."""
        return await self._find({"user_id": user_id, "pause_reason": reason.value})

    async def distinct_users_with_active_gaia_tasks(self) -> list[str]:
        """Every user id owning a GAIA task that is on."""
        return await self._distinct(
            "user_id", {"assignee": Assignee.GAIA.value, "active": True, "completed": False}
        )

    async def list_open_gaia_all_users(
        self, *, limit: int, after_id: str | None = None
    ) -> list[TaskDocument]:
        """Return a page of every user's open GAIA tasks in id order: the maintenance sweep's scan."""
        filt: dict[str, object] = {"assignee": Assignee.GAIA.value, "completed": False}
        if after_id is not None:
            filt["_id"] = {"$gt": after_id}
        return await self._find(filt, sort=[("_id", 1)], limit=limit)

    async def find_due_all_users(
        self, *, now: datetime, max_retries: int, limit: int
    ) -> list[TaskDocument]:
        """Every user's GAIA tasks whose next run or next check is due: the recovery cron's re-arm set."""
        return await self._find(
            {
                **_runnable(),
                "retry_count": {"$lt": max_retries},
                "status_flags": {"$ne": TaskFlag.FAILED.value},
                "$or": [_due_at(NEXT_RUN_FIELD, now), _due_at(NEXT_CHECK_FIELD, now)],
            },
            limit=limit,
        )

    async def find_due_todos_all_users(self, *, now: datetime, limit: int) -> list[TaskDocument]:
        """Every user's to-dos that came round by now: a repeat's next round, or an owed nudge."""
        return await self._find(
            {
                "assignee": Assignee.USER.value,
                "$or": [_due_at(NEXT_RUN_FIELD, now), _due_at(NUDGE_FIELD, now)],
            },
            limit=limit,
        )

    async def find_stale_running_all_users(
        self, *, cutoff: datetime, limit: int
    ) -> list[TaskDocument]:
        """Every user's tasks wedged mid-run since before cutoff: a worker died holding them."""
        return await self._find(
            {"run_state": TaskRunState.RUNNING.value, "updated_at": {"$lt": cutoff}}, limit=limit
        )

    async def find_listening_by_composio_trigger_all_users(
        self, composio_trigger_id: str
    ) -> list[TaskDocument]:
        """Every user's open tasks an event on a Composio trigger instance reaches (per-resource dispatch).

        A task the system paused is listening too: its events are kept for its resume.
        """
        return await self._find(
            {**_listening(), "subscriptions.composio_trigger_ids": composio_trigger_id}
        )

    async def find_listening_by_user_and_trigger(
        self, user_id: str, trigger_names: Collection[str]
    ) -> list[TaskDocument]:
        """Return the user's open tasks an event on any of trigger_names reaches.

        Account-level dispatch: Gmail registers no per-subscriber instance. A task the
        system paused is listening too: its events are kept for its resume.
        """
        if not trigger_names:
            return []
        return await self._find(
            {
                "user_id": user_id,
                **_listening(),
                "subscriptions.trigger_name": {"$in": list(trigger_names)},
            }
        )

    async def find_paused_by_user_and_trigger(
        self, user_id: str, trigger_name: str
    ) -> list[TaskDocument]:
        """Return the user's open tasks whose subscription to trigger_name lost its app: the resync set."""
        return await self._find(
            {
                "user_id": user_id,
                "completed": False,
                "subscriptions": {
                    "$elemMatch": {
                        "trigger_name": trigger_name,
                        "status": TriggerSubscriptionStatus.PAUSED.value,
                    }
                },
            }
        )

    async def count_trigger_references(
        self, composio_trigger_id: str, *, excluding_task_id: str | None = None
    ) -> int:
        """How many tasks still hold composio_trigger_id; its Composio trigger is deleted only at zero."""
        filt: dict[str, object] = {"subscriptions.composio_trigger_ids": composio_trigger_id}
        if excluding_task_id:
            filt["_id"] = {"$ne": excluding_task_id}
        return await self._count(filt)

    # ----------------------------------------------------------------- writes

    async def bulk_update(self, user_id: str, task_ids: list[str], update: TaskUpdate) -> int:
        """Apply one $set to many of the user's tasks; returns the count modified."""
        return await self._bulk_set([(tid, update) for tid in task_ids], scope=user_id)

    async def bulk_delete(self, user_id: str, task_ids: list[str]) -> int:
        """Delete many of the user's tasks; returns the count deleted."""
        return await self._bulk_delete(task_ids, scope=user_id)

    async def delete_all_for_user(self, user_id: str) -> int:
        """Delete every task the user owns (account deletion, dev reset)."""
        return await self._delete_many({"user_id": user_id}, scope=user_id)

    async def delete_onboarding(self, user_id: str) -> int:
        """Delete the user's onboarding-seeded tasks."""
        return await self._delete_many({"user_id": user_id, "from_onboarding": True}, scope=user_id)

    async def add_flags(
        self, task_id: str, *, user_id: str, flags: Collection[TaskFlag]
    ) -> TaskDocument | None:
        """Set flags on the task without duplicating ones it carries."""
        return await self._apply_raw_update(
            self._scoped(task_id, user_id),
            {"$addToSet": {"status_flags": {"$each": [flag.value for flag in flags]}}},
            scope=user_id,
        )

    async def remove_flags(
        self, task_id: str, *, user_id: str, flags: Collection[TaskFlag]
    ) -> TaskDocument | None:
        """Clear flags off the task."""
        return await self._apply_raw_update(
            self._scoped(task_id, user_id),
            {"$pull": {"status_flags": {"$in": [flag.value for flag in flags]}}},
            scope=user_id,
        )

    async def add_references(
        self, task_id: str, *, user_id: str, references: list[str]
    ) -> TaskDocument | None:
        """Link earlier tasks whose learnings this one reads."""
        return await self._apply_raw_update(
            self._scoped(task_id, user_id),
            {"$addToSet": {"references": {"$each": references}}},
            scope=user_id,
        )

    async def add_subtask(
        self, task_id: str, *, user_id: str, subtask: SubTask
    ) -> TaskDocument | None:
        """Append a checklist item."""
        return await self._apply_raw_update(
            self._scoped(task_id, user_id),
            {"$push": {"subtasks": subtask.model_dump()}},
            scope=user_id,
        )

    async def remove_subtask(
        self, task_id: str, *, user_id: str, subtask_id: str
    ) -> TaskDocument | None:
        """Remove a checklist item by id."""
        return await self._apply_raw_update(
            self._scoped(task_id, user_id),
            {"$pull": {"subtasks": {"id": subtask_id}}},
            scope=user_id,
        )

    async def set_subtask_fields(
        self,
        task_id: str,
        *,
        user_id: str,
        subtask_id: str,
        title: str | None = None,
        completed: bool | None = None,
    ) -> TaskDocument | None:
        """Rename or tick one checklist item."""
        fields: dict[str, object] = {}
        if title is not None:
            fields["subtasks.$[item].title"] = title
        if completed is not None:
            fields["subtasks.$[item].completed"] = completed
        return await self._apply_raw_update(
            self._scoped(task_id, user_id),
            {"$set": fields},
            scope=user_id,
            array_filters=[{"item.id": subtask_id}],
        )

    async def replace_notes(
        self,
        task_id: str,
        user_id: str,
        *,
        update: TaskUpdate,
        expected_updated_at: datetime | None,
        touch: bool = True,
    ) -> TaskDocument | None:
        """Replace note bodies, gated by expected_updated_at when given; None on a mismatch."""
        extra: dict[str, object] = {"user_id": user_id}
        if expected_updated_at is not None:
            extra["updated_at"] = expected_updated_at
        return await self._apply_update(task_id, user_id, extra, update, touch=touch)

    async def append_log(self, task_id: str, user_id: str, *, suffix: str) -> TaskDocument | None:
        """Append to the system log in one atomic update, so concurrent appends cannot lose each other."""
        body: dict[str, object] = {"$ifNull": ["$log", ""]}
        pipeline: list[dict[str, object]] = [
            {
                "$set": {
                    "log": {"$ltrim": {"input": {"$concat": [body, suffix]}, "chars": "\n"}},
                    "updated_at": datetime.now(UTC),
                }
            }
        ]
        return await self._apply_pipeline_update(
            self._scoped(task_id, user_id), pipeline, scope=user_id
        )

    async def update_if_completed(
        self, task_id: str, user_id: str, *, update: TaskUpdate
    ) -> TaskDocument | None:
        """Apply update only while the task is still done (compare-and-set)."""
        return await self._apply_update(
            task_id, user_id, {"user_id": user_id, "completed": True}, update
        )

    async def update_if_open(
        self, task_id: str, user_id: str, *, update: TaskUpdate
    ) -> TaskDocument | None:
        """Apply update only while the task is still open (compare-and-set)."""
        return await self._apply_update(
            task_id, user_id, {"user_id": user_id, "completed": False}, update
        )

    async def update_if_next_check_at(
        self, task_id: str, user_id: str, *, expected: datetime | None, update: TaskUpdate
    ) -> TaskDocument | None:
        """Apply update only while the next check is still expected (compare-and-set)."""
        return await self._apply_update(
            task_id, user_id, {"user_id": user_id, NEXT_CHECK_FIELD: expected}, update
        )

    async def update_if_next_run(
        self, task_id: str, user_id: str, *, expected: datetime, update: TaskUpdate
    ) -> TaskDocument | None:
        """Apply update only while the repeat's next run is still expected (compare-and-set)."""
        return await self._apply_update(
            task_id, user_id, {"user_id": user_id, NEXT_RUN_FIELD: expected}, update
        )

    async def update_if_nudge_at(
        self, task_id: str, user_id: str, *, expected: datetime, update: TaskUpdate
    ) -> TaskDocument | None:
        """Apply update only while the owed nudge is still expected (compare-and-set)."""
        return await self._apply_update(
            task_id, user_id, {"user_id": user_id, NUDGE_FIELD: expected}, update
        )

    async def add_subscription(
        self, task_id: str, *, user_id: str, subscription: TriggerSubscription
    ) -> TaskDocument | None:
        """Append the subscription unless an identical active one is on the task, in one atomic update."""
        current: dict[str, object] = {"$ifNull": ["$subscriptions", []]}
        present: object = (
            {
                "$anyElementTrue": [
                    {
                        "$map": {
                            "input": current,
                            "as": "sub",
                            "in": _same_active_subscription("$$sub", subscription),
                        }
                    }
                ]
            }
            if subscription.status is TriggerSubscriptionStatus.ACTIVE
            else False
        )
        appended = {"$concatArrays": [current, [{"$literal": subscription.model_dump()}]]}
        pipeline: list[dict[str, object]] = [
            {
                "$set": {
                    "subscriptions": {"$cond": [present, current, appended]},
                    "updated_at": {"$cond": [present, "$updated_at", datetime.now(UTC)]},
                }
            }
        ]
        return await self._apply_pipeline_update(
            self._scoped(task_id, user_id), pipeline, scope=user_id
        )

    async def remove_subscriptions(
        self, task_id: str, *, user_id: str, subscription_ids: Collection[str]
    ) -> TaskDocument | None:
        """Pull these subscriptions off; returns the task as it was before, None when it held none."""
        ids = list(subscription_ids)
        return await self._apply_raw_update(
            self._scoped(task_id, user_id),
            {"$pull": {"subscriptions": {"id": {"$in": ids}}}},
            scope=user_id,
            extra_filter={"subscriptions.id": {"$in": ids}},
            return_document=False,
        )

    async def clear_subscriptions(self, task_id: str, *, user_id: str) -> TaskDocument | None:
        """Drop every subscription; returns the task as it was before, None when it had none."""
        return await self._apply_raw_update(
            self._scoped(task_id, user_id),
            {"$set": {"subscriptions": []}},
            scope=user_id,
            extra_filter={"subscriptions.0": {"$exists": True}},
            return_document=False,
        )

    async def pause_subscriptions(
        self, task_id: str, *, user_id: str, subscription_ids: Collection[str]
    ) -> TaskDocument | None:
        """Mark these subscriptions paused and flag the task blocked, in one atomic update."""
        return await self._apply_raw_update(
            self._scoped(task_id, user_id),
            {
                "$set": {"subscriptions.$[sub].status": TriggerSubscriptionStatus.PAUSED.value},
                "$addToSet": {"status_flags": TaskFlag.BLOCKED.value},
            },
            scope=user_id,
            array_filters=[{"sub.id": {"$in": list(subscription_ids)}}],
        )

    async def resume_subscriptions(
        self, task_id: str, *, user_id: str, trigger_ids: Mapping[str, list[str]]
    ) -> TaskDocument | None:
        """Mark these subscriptions active on their new Composio ids, then unblock once none is paused."""
        fields: dict[str, object] = {}
        array_filters: list[dict[str, object]] = []
        for index, (subscription_id, composio_ids) in enumerate(trigger_ids.items()):
            sub = f"sub{index}"
            fields[f"subscriptions.$[{sub}].status"] = TriggerSubscriptionStatus.ACTIVE.value
            fields[f"subscriptions.$[{sub}].composio_trigger_ids"] = composio_ids
            array_filters.append({f"{sub}.id": subscription_id})
        resumed = await self._apply_raw_update(
            self._scoped(task_id, user_id),
            {"$set": fields},
            scope=user_id,
            array_filters=array_filters,
        )
        if resumed is None:
            return None
        unblocked = await self._apply_raw_update(
            self._scoped(task_id, user_id),
            {"$pull": {"status_flags": TaskFlag.BLOCKED.value}},
            scope=user_id,
            extra_filter={
                "status_flags": TaskFlag.BLOCKED.value,
                "subscriptions": {
                    "$not": {"$elemMatch": {"status": TriggerSubscriptionStatus.PAUSED.value}}
                },
            },
        )
        return unblocked or resumed

    async def release_composio_ids(self, task_id: str, *, user_id: str) -> TaskDocument | None:
        """Forget every subscription's Composio instances; returns the task as it was, None when it held none."""
        return await self._apply_raw_update(
            self._scoped(task_id, user_id),
            {"$set": {"subscriptions.$[].composio_trigger_ids": []}},
            scope=user_id,
            extra_filter={"subscriptions.composio_trigger_ids.0": {"$exists": True}},
            return_document=False,
        )

    async def set_subscription_composio_ids(
        self, task_id: str, *, user_id: str, subscription_id: str, composio_ids: list[str]
    ) -> TaskDocument | None:
        """Repoint one subscription at its registered Composio trigger instances."""
        return await self._apply_raw_update(
            self._scoped(task_id, user_id),
            {"$set": {"subscriptions.$[sub].composio_trigger_ids": composio_ids}},
            scope=user_id,
            array_filters=[{"sub.id": subscription_id}],
        )

    async def set_subscription_gate(
        self, task_id: str, *, user_id: str, subscription_id: str, gate: TriggerGate | None
    ) -> TaskDocument | None:
        """Store or remove the gate on one run subscription; None unless the task has that run subscription."""
        sub = {"id": subscription_id, "action": SubscriptionAction.EXECUTE.value}
        return await self._apply_raw_update(
            self._scoped(task_id, user_id),
            {"$set": {"subscriptions.$[sub].gate": None if gate is None else gate.model_dump()}},
            scope=user_id,
            extra_filter={"subscriptions": {"$elemMatch": sub}},
            array_filters=[{f"sub.{field}": value for field, value in sub.items()}],
        )

    async def remember_gate_skip(
        self, task_id: str, *, user_id: str, subscription_id: str, skip: GateSkipRecord
    ) -> None:
        """Count a skipped event on a subscription's gate and keep it among the newest few."""
        await self._apply_raw_update(
            self._scoped(task_id, user_id),
            {
                "$push": {
                    "subscriptions.$[sub].gate.recent_skips": {
                        "$each": [skip.model_dump()],
                        "$slice": -GATE_RECENT_SKIPS_KEPT,
                    }
                },
                "$inc": {"subscriptions.$[sub].gate.skipped_count": 1},
            },
            scope=user_id,
            extra_filter={
                "subscriptions": {"$elemMatch": {"id": subscription_id, "gate": {"$ne": None}}}
            },
            array_filters=[{"sub.id": subscription_id}],
            return_document=False,
        )

    async def claim_run(self, task_id: str, *, armed_for: datetime | None) -> TaskDocument | None:
        """Atomically take a runnable task from idle to running; None when it is not runnable.

        armed_for pins the occurrence the job was armed for, so a job left behind by a
        reschedule cannot run the task at a time it no longer names.
        """
        filt: dict[str, object] = {"_id": task_id, **_runnable()}
        if armed_for is not None:
            window = occurrence_window(armed_for)
            filt["$or"] = [{NEXT_RUN_FIELD: window}, {NEXT_CHECK_FIELD: window}]
        claimed = await self._apply_raw_update(
            filt, {"$set": {"run_state": TaskRunState.RUNNING.value}}, scope=None
        )
        if claimed is not None:
            await self._evict_many(claimed.user_id, [task_id])
        return claimed

    async def finish_run(
        self, task_id: str, *, user_id: str, ran: TaskRunStatus | None
    ) -> TaskDocument | None:
        """Put a claimed task back to idle; a run that ran (ran is its outcome) is counted.

        The run's next time is not written here: the run itself, or the settling after
        it, moved it with a compare-and-set of its own.
        """
        update: dict[str, dict[str, object]] = {"$set": {"run_state": TaskRunState.IDLE.value}}
        if ran is not None:
            update["$set"]["last_run_at"] = datetime.now(UTC)
            increments: dict[str, object] = {"total_runs": 1, "occurrence_count": 1}
            if ran is TaskRunStatus.SUCCESS:
                increments["successful_runs"] = 1
            update["$inc"] = increments
        return await self._apply_raw_update(self._scoped(task_id, user_id), update, scope=user_id)

    async def activate(self, task_id: str, *, user_id: str, when: When) -> TaskDocument | None:
        """Switch the task on, idle, with its freshly worked out next time."""
        return await self._apply_raw_update(
            self._scoped(task_id, user_id),
            {
                "$set": {
                    "active": True,
                    "pause_reason": None,
                    "run_state": TaskRunState.IDLE.value,
                    "when": when.model_dump(),
                }
            },
            scope=user_id,
        )

    async def deactivate(
        self,
        task_id: str,
        *,
        user_id: str,
        reason: DeactivationReason | None,
        blocked_on_integrations: list[str] | None = None,
    ) -> TaskDocument | None:
        """Switch the task off; reason None means the user stopped it.

        Its Composio instances stay registered, so a resume needs no re-registration and the
        reference count still protects them; whoever stops the task for good releases them.
        """
        fields: dict[str, object] = {
            "active": False,
            "pause_reason": None if reason is None else reason.value,
        }
        if blocked_on_integrations is not None:
            fields["blocked_on_integrations"] = blocked_on_integrations
        return await self._apply_raw_update(
            self._scoped(task_id, user_id), {"$set": fields}, scope=user_id
        )

    async def reset_system_task(
        self,
        task_id: str,
        *,
        user_id: str,
        title: str,
        body: str,
        when: When,
        subscriptions: list[TriggerSubscription],
    ) -> TaskDocument | None:
        """Put a system task back as its definition ships, keeping liveness, counters and created_at."""
        return await self._apply_raw_update(
            {**self._scoped(task_id, user_id), "system_key": {"$type": "string"}},
            {
                "$set": {
                    "title": title,
                    "body": body,
                    "when": when.model_dump(),
                    "subscriptions": [sub.model_dump() for sub in subscriptions],
                }
            },
            scope=user_id,
        )


def _same_active_subscription(sub: str, subscription: TriggerSubscription) -> dict[str, object]:
    """Whether the subscription expression is an active twin of subscription, compared as Python does."""
    return {
        "$and": [
            {"$eq": [f"{sub}.trigger_name", {"$literal": subscription.trigger_name}]},
            {
                "$eq": [
                    {"$ifNull": [f"{sub}.account_id", None]},
                    {"$literal": subscription.account_id},
                ]
            },
            {"$eq": [f"{sub}.action", {"$literal": subscription.action.value}]},
            {"$eq": [f"{sub}.match", {"$literal": subscription.match.value}]},
            {"$eq": [f"{sub}.cooldown_seconds", subscription.cooldown_seconds]},
            {"$eq": [f"{sub}.status", TriggerSubscriptionStatus.ACTIVE.value]},
            {
                "$setEquals": [
                    {"$ifNull": [f"{sub}.conditions", []]},
                    {"$literal": [c.model_dump() for c in subscription.conditions]},
                ]
            },
            {
                "$setEquals": [
                    {"$objectToArray": {"$ifNull": [f"{sub}.trigger_data", {}]}},
                    {"$objectToArray": {"$literal": subscription.trigger_data}},
                ]
            },
        ]
    }


task_repository = TasksRepository()
