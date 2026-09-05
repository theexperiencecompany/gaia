"""Repository for the todos collection.

The heaviest domain in the migration: alongside plain CRUD it carries the tracked
todo lifecycle (canvas/log bodies, scheduling, retry state), bulk operations, a
text/filter list query, three dashboard aggregations, and system-wide finders the
executor and maintenance sweep use across users. Array, positional, and ``$unset``
mutations go through the base ``_apply_ops`` seam; bulk writes go through
``_bulk_set`` / ``_bulk_delete``; every read returns a typed model.
"""

from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field

from app.constants.cache import TODO_CACHE_PREFIX
from app.constants.todos import (
    FAILED_LABEL,
    ONBOARDING_LABEL,
    gaia_assigned_filter,
    user_assigned_filter,
)
from app.db.repositories.base import UserScopedRepository, cached_query
from app.db.repositories.cache import CachePolicy
from app.models.todo_models import (
    ExecutionStatus,
    SearchMode,
    SubTask,
    TodoCounts,
    TodoDocument,
    TodoLabelCount,
    TodoPage,
    TodoSearchParams,
    TodoStats,
    TodoUpdate,
)
from app.models.trigger_subscription_models import SubscriptionStatus

# Top-N labels surfaced in the stats aggregation (mirrors the legacy pipeline).
_STATS_LABEL_LIMIT = 50


class _FacetCount(BaseModel):
    """One ``{"$count": ...}`` bucket from a ``$facet`` stage."""

    count: int = 0


class _GroupCount(BaseModel):
    """One ``{"$group": {"_id": key, "count": n}}`` row."""

    model_config = ConfigDict(populate_by_name=True)

    key: str | None = Field(default=None, alias="_id")
    count: int = 0


class _StatsFacet(BaseModel):
    total: list[_FacetCount] = Field(default_factory=list)
    completed: list[_FacetCount] = Field(default_factory=list)
    overdue: list[_FacetCount] = Field(default_factory=list)
    by_priority: list[_GroupCount] = Field(default_factory=list)
    by_project: list[_GroupCount] = Field(default_factory=list)
    labels: list[_GroupCount] = Field(default_factory=list)


class _CountsFacet(BaseModel):
    inbox: list[_FacetCount] = Field(default_factory=list)
    today: list[_FacetCount] = Field(default_factory=list)
    upcoming: list[_FacetCount] = Field(default_factory=list)
    overdue: list[_FacetCount] = Field(default_factory=list)
    completed: list[_FacetCount] = Field(default_factory=list)


def _first_count(buckets: list[_FacetCount]) -> int:
    return buckets[0].count if buckets else 0


class TodosRepository(UserScopedRepository[TodoDocument, TodoUpdate]):
    """The ``todos`` collection repository (user-scoped, cached)."""

    collection_name = "todos"
    document_model = TodoDocument
    update_model = TodoUpdate
    uses_object_id = True
    cache_policy = CachePolicy(prefix=TODO_CACHE_PREFIX)

    # ------------------------------------------------------------------ reads

    async def get_by_id(self, todo_id: str) -> TodoDocument | None:
        """Fetch a todo by id with no user scoping — for the system executor,
        which is handed only a todo id. Prefer ``get(id, user_id=...)`` everywhere
        a user is in context."""
        return await self._find_one({"_id": self._id_value(todo_id)})

    async def list_onboarding_todos(self, user_id: str, *, limit: int) -> list[TodoDocument]:
        """A user's onboarding-seeded todos, most-recently-created first."""
        return await self._find(
            {"user_id": user_id, "labels": ONBOARDING_LABEL},
            sort=[("created_at", -1)],
            limit=limit,
        )

    async def find_by_ids(self, user_id: str, todo_ids: list[str]) -> list[TodoDocument]:
        """The user's todos whose ids are in ``todo_ids`` (order not preserved)."""
        if not todo_ids:
            return []
        return await self._find(
            {"_id": {"$in": [self._id_value(tid) for tid in todo_ids]}, "user_id": user_id}
        )

    async def count_in_project(self, user_id: str, project_id: str) -> int:
        """How many of the user's todos belong to ``project_id``."""
        return await self._count({"user_id": user_id, "project_id": project_id})

    async def count_for_user(self, user_id: str) -> int:
        """Total todos a user has — the feature-usage signal."""
        return await self._count({"user_id": user_id})

    def _list_filter(
        self, user_id: str, params: TodoSearchParams, inbox_project_id: str | None
    ) -> dict[str, object]:
        """Build the Mongo filter for a filtered/text list query.

        ``inbox_project_id`` is resolved by the caller (it may create the Inbox);
        when provided it is the default scope for the unfiltered main list.
        """
        query: dict[str, object] = {"user_id": user_id}

        if params.q and params.mode == SearchMode.TEXT:
            query["$or"] = [
                {"title": {"$regex": params.q, "$options": "i"}},
                {"description": {"$regex": params.q, "$options": "i"}},
                {"labels": {"$in": [params.q]}},
            ]

        if params.project_id is not None:
            query["project_id"] = params.project_id
        elif inbox_project_id is not None and not (
            params.q or params.completed is not None or params.priority or params.labels
        ):
            query["project_id"] = inbox_project_id

        if params.completed is not None:
            query["completed"] = params.completed
        if params.priority:
            query["priority"] = params.priority.value
        if params.labels:
            query["labels"] = {"$in": params.labels}

        # Last: the due-date clauses deliberately override the completed and
        # text-search keys set above (an overdue query is a completed=False
        # query, whatever else was asked for).
        query.update(self._due_date_clause(params))

        return query

    def _due_date_clause(self, params: TodoSearchParams) -> dict[str, object]:
        """The due-date half of the list filter — presence, explicit range and
        the overdue shortcut, in increasing order of precedence."""
        clause: dict[str, object] = {}

        if params.has_due_date is True:
            clause["due_date"] = {"$ne": None}
        elif params.has_due_date is False:
            clause["due_date"] = None

        if params.due_date_start or params.due_date_end:
            date_query: dict[str, datetime] = {}
            if params.due_date_start:
                date_query["$gte"] = params.due_date_start
            if params.due_date_end:
                date_query["$lte"] = params.due_date_end
            clause["due_date"] = date_query

        if params.overdue is True:
            clause["due_date"] = {"$lt": datetime.now(UTC)}
            clause["completed"] = False
        elif params.overdue is False and params.has_due_date is not False:
            clause["$or"] = [
                {"due_date": None},
                {"due_date": {"$gte": datetime.now(UTC)}},
            ]

        return clause

    @cached_query(TodoPage)
    async def list_page(
        self, *, user_id: str, params: TodoSearchParams, inbox_project_id: str | None
    ) -> TodoPage:
        """One page of todos (newest first) plus the unpaginated total for the
        same filter. Covers text and filter queries; semantic/hybrid search is a
        vector concern handled above the repository."""
        query = self._list_filter(user_id, params, inbox_project_id)
        total = await self._count(query)
        skip = (params.page - 1) * params.per_page
        items = await self._find(query, sort=[("created_at", -1)], skip=skip, limit=params.per_page)
        return TodoPage(items=items, total=total)

    @cached_query(TodoStats)
    async def compute_stats(self, *, user_id: str) -> TodoStats:
        """Aggregate todo statistics for a user (totals, buckets, top labels)."""
        now = datetime.now(UTC)
        pipeline: list[dict[str, object]] = [
            {"$match": {"user_id": user_id}},
            {
                "$facet": {
                    "total": [{"$count": "count"}],
                    "completed": [{"$match": {"completed": True}}, {"$count": "count"}],
                    "overdue": [
                        {"$match": {"completed": False, "due_date": {"$lt": now}}},
                        {"$count": "count"},
                    ],
                    "by_priority": [{"$group": {"_id": "$priority", "count": {"$sum": 1}}}],
                    "by_project": [{"$group": {"_id": "$project_id", "count": {"$sum": 1}}}],
                    "labels": [
                        {"$match": {"completed": False}},
                        {"$unwind": "$labels"},
                        {"$group": {"_id": "$labels", "count": {"$sum": 1}}},
                        {"$sort": {"count": -1}},
                        {"$limit": _STATS_LABEL_LIMIT},
                    ],
                }
            },
        ]
        facets = await self._aggregate(pipeline, _StatsFacet)
        if not facets:
            return TodoStats()
        facet = facets[0]
        total = _first_count(facet.total)
        completed = _first_count(facet.completed)
        return TodoStats(
            total=total,
            completed=completed,
            pending=total - completed,
            overdue=_first_count(facet.overdue),
            by_priority={g.key: g.count for g in facet.by_priority if g.key is not None},
            by_project={g.key: g.count for g in facet.by_project if g.key is not None},
            completion_rate=round((completed / total * 100) if total > 0 else 0, 2),
            labels=[
                TodoLabelCount(name=g.key, count=g.count) for g in facet.labels if g.key is not None
            ],
        )

    @cached_query(TodoCounts)
    async def compute_counts(self, *, user_id: str, inbox_project_id: str) -> TodoCounts:
        """Dashboard/sidebar counts (inbox, today, upcoming, overdue, completed)."""
        now = datetime.now(UTC)
        today = now.date()
        today_start = datetime.combine(today, datetime.min.time()).replace(tzinfo=UTC)
        today_end = datetime.combine(today, datetime.max.time()).replace(tzinfo=UTC)
        upcoming_end = now + timedelta(days=7)
        pipeline: list[dict[str, object]] = [
            {"$match": {"user_id": user_id}},
            {
                "$facet": {
                    "inbox": [
                        {"$match": {"project_id": inbox_project_id, "completed": False}},
                        {"$count": "count"},
                    ],
                    "today": [
                        {
                            "$match": {
                                "due_date": {"$gte": today_start, "$lte": today_end},
                                "completed": False,
                            }
                        },
                        {"$count": "count"},
                    ],
                    "upcoming": [
                        {
                            "$match": {
                                "due_date": {"$gt": today_end, "$lte": upcoming_end},
                                "completed": False,
                            }
                        },
                        {"$count": "count"},
                    ],
                    "overdue": [
                        {"$match": {"due_date": {"$lt": now}, "completed": False}},
                        {"$count": "count"},
                    ],
                    "completed": [{"$match": {"completed": True}}, {"$count": "count"}],
                }
            },
        ]
        facets = await self._aggregate(pipeline, _CountsFacet)
        if not facets:
            return TodoCounts()
        facet = facets[0]
        return TodoCounts(
            inbox=_first_count(facet.inbox),
            today=_first_count(facet.today),
            upcoming=_first_count(facet.upcoming),
            overdue=_first_count(facet.overdue),
            completed=_first_count(facet.completed),
        )

    @cached_query(list[TodoLabelCount])
    async def top_labels(self, *, user_id: str, limit: int) -> list[TodoLabelCount]:
        """Most-used labels across a user's incomplete todos."""
        pipeline: list[dict[str, object]] = [
            {"$match": {"user_id": user_id, "completed": False}},
            {"$unwind": "$labels"},
            {"$group": {"_id": "$labels", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": limit},
            {"$project": {"name": "$_id", "count": 1, "_id": 0}},
        ]
        return await self._aggregate(pipeline, TodoLabelCount)

    async def list_active_tracked(self, user_id: str, *, limit: int) -> list[TodoDocument]:
        """A user's active (incomplete) GAIA-assigned todos, most-recently-updated first."""
        return await self._find(
            {"user_id": user_id, **gaia_assigned_filter(), "completed": False},
            sort=[("updated_at", -1)],
            limit=limit,
        )

    async def list_active_gaia_for_summary(self, user_id: str, *, limit: int) -> list[TodoDocument]:
        """Active GAIA-assigned todos excluding terminal dismissed/expired proposals —
        the context-injection summary's source (those are terminal and only
        resurface via the rejection-strike summary)."""
        return await self._find(
            {
                "user_id": user_id,
                "completed": False,
                "execution_status": {
                    "$nin": [ExecutionStatus.DISMISSED.value, ExecutionStatus.EXPIRED.value]
                },
                **gaia_assigned_filter(),
            },
            sort=[("updated_at", -1)],
            limit=limit,
        )

    async def list_active_gaia_tracked_since(
        self, user_id: str, *, completed_since: datetime
    ) -> list[TodoDocument]:
        """GAIA-assigned todos that are open OR completed since ``completed_since`` —
        the VFS materialization set for ``/workspace/gaia-tasks/``."""
        return await self._find(
            {
                "user_id": user_id,
                **gaia_assigned_filter(),
                "$or": [
                    {"completed": {"$ne": True}},
                    {"completed_at": {"$gte": completed_since}},
                ],
            }
        )

    async def list_active_user_todos_since(
        self, user_id: str, *, completed_since: datetime
    ) -> list[TodoDocument]:
        """User-assigned todos that are open OR completed since ``completed_since`` —
        the VFS materialization set for ``/workspace/todos/``."""
        return await self._find(
            {
                "user_id": user_id,
                **user_assigned_filter(),
                "$or": [
                    {"completed": {"$ne": True}},
                    {"completed_at": {"$gte": completed_since}},
                ],
            }
        )

    async def list_active_tracked_all_users(self, *, limit: int) -> list[TodoDocument]:
        """Every user's active GAIA-assigned todos — the maintenance sweep's scan set."""
        return await self._find({"completed": False, **gaia_assigned_filter()}, limit=limit)

    async def find_active_by_composio_trigger(self, composio_trigger_id: str) -> list[TodoDocument]:
        """Every user's incomplete todos with an active subscription registered against
        ``composio_trigger_id`` — the per-resource half of trigger dispatch."""
        return await self._find(
            {
                "completed": False,
                "trigger_subscriptions": {
                    "$elemMatch": {
                        "composio_trigger_ids": composio_trigger_id,
                        "status": SubscriptionStatus.ACTIVE.value,
                    }
                },
            }
        )

    async def find_active_by_user_and_trigger(
        self, user_id: str, trigger_name: str
    ) -> list[TodoDocument]:
        """One user's incomplete todos with an active subscription to ``trigger_name``
        — the account-level half of dispatch, for triggers (Gmail) that register no
        per-subscriber Composio instance and can only be found by user."""
        return await self._find(
            {
                "user_id": user_id,
                "completed": False,
                "trigger_subscriptions": {
                    "$elemMatch": {
                        "trigger_name": trigger_name,
                        "status": SubscriptionStatus.ACTIVE.value,
                    }
                },
            }
        )

    async def find_paused_by_user_and_trigger(
        self, user_id: str, trigger_name: str
    ) -> list[TodoDocument]:
        """One user's incomplete todos whose ``trigger_name`` subscription is paused —
        the resync set after the integration behind it is reconnected."""
        return await self._find(
            {
                "user_id": user_id,
                "completed": False,
                "trigger_subscriptions": {
                    "$elemMatch": {
                        "trigger_name": trigger_name,
                        "status": SubscriptionStatus.PAUSED.value,
                    }
                },
            }
        )

    async def count_trigger_references(
        self, composio_trigger_id: str, *, excluding_todo_id: str | None = None
    ) -> int:
        """How many todos still reference ``composio_trigger_id``. Summed with the
        workflow count before a Composio trigger is deleted — the two consumers share
        trigger instances, so either one alone would delete the other's live trigger.

        Counts paused subscriptions too: a paused subscription is resumed on
        reconnect, so its trigger must survive the pause.
        """
        query: dict[str, object] = {
            "trigger_subscriptions.composio_trigger_ids": composio_trigger_id
        }
        if excluding_todo_id:
            # Todos key on ObjectId (workflows key on plain strings), so the id has
            # to go through the identity seam or the $ne matches nothing.
            query["_id"] = {"$ne": self._id_value(excluding_todo_id)}
        return await self._count(query)

    async def find_due_tracked_all_users(
        self, *, now: datetime, max_retries: int, limit: int
    ) -> list[TodoDocument]:
        """Every user's scheduled-and-due GAIA-assigned todos still under their retry
        budget — the executor safety net's re-enqueue candidates."""
        return await self._find(
            {
                "scheduled_at": {"$lte": now},
                "completed": False,
                **gaia_assigned_filter(),
                "gaia_retry_count": {"$lt": max_retries},
            },
            limit=limit,
        )

    # ---------------------------------------------- cross-domain finders
    # Named queries the briefing engine, first-steps checklist, and rollout
    # pass run against the todos domain (ownership rule: they call these,
    # never a raw filter).

    async def count_gaia_assigned(self, user_id: str) -> int:
        """How many todos GAIA owns for this user (any status)."""
        return await self._count({"user_id": user_id, **gaia_assigned_filter()})

    async def count_gaia_completed(self, user_id: str) -> int:
        """How many GAIA-assigned todos have ever completed for this user."""
        return await self._count(
            {"user_id": user_id, "completed_at": {"$ne": None}, **gaia_assigned_filter()}
        )

    async def list_gaia_completed(self, user_id: str) -> list[TodoDocument]:
        """Every completed GAIA-assigned todo (badge checks read completed_at times)."""
        return await self._find(
            {"user_id": user_id, "completed_at": {"$ne": None}, **gaia_assigned_filter()}
        )

    async def has_goal_created_since(self, user_id: str, *, since: datetime) -> bool:
        """Whether a goal lane was created at or after ``since`` (dormancy signal)."""
        return (
            await self._count({"user_id": user_id, "kind": "goal", "created_at": {"$gte": since}})
            > 0
        )

    async def list_open_goals(self, user_id: str) -> list[TodoDocument]:
        """Open goal lanes, oldest first (the nightly pass walks them in order)."""
        return await self._find(
            {"user_id": user_id, "kind": "goal", "completed": False},
            sort=[("created_at", 1)],
        )

    async def list_goal_children(self, user_id: str, goal_id: str) -> list[TodoDocument]:
        """Task todos linked to a goal lane via ``goal_id``."""
        return await self._find({"user_id": user_id, "goal_id": goal_id})

    async def list_completed_since(self, user_id: str, *, since: datetime) -> list[TodoDocument]:
        """Todos (either assignee) completed at or after ``since`` — the look-back set."""
        return await self._find({"user_id": user_id, "completed_at": {"$gte": since}})

    async def list_open_gaia_by_status(
        self, user_id: str, *, statuses: list[str], limit: int
    ) -> list[TodoDocument]:
        """GAIA-assigned todos currently in one of ``statuses``."""
        return await self._find(
            {
                "user_id": user_id,
                **gaia_assigned_filter(),
                "execution_status": {"$in": statuses},
            },
            limit=limit,
        )

    async def list_open_user_todos(self, user_id: str, *, limit: int) -> list[TodoDocument]:
        """The user's own open todos."""
        return await self._find(
            {"user_id": user_id, "completed": False, **user_assigned_filter()},
            limit=limit,
        )

    # -------------------------------------------------- GAIA lifecycle finders
    # Named queries backing ``gaia_todo_lifecycle``'s creation gate, budgets,
    # and rejection bookkeeping.

    async def count_open_goals(self, user_id: str) -> int:
        """How many open (incomplete) goal lanes the user has."""
        return await self._count(
            {"user_id": user_id, "kind": "goal", "completed": False, **gaia_assigned_filter()}
        )

    async def find_pending_proposal_by_title(self, user_id: str, title: str) -> TodoDocument | None:
        """An already-pending proposal with this exact title (duplicate-creation guard)."""
        return await self._find_one(
            {
                "user_id": user_id,
                "execution_status": ExecutionStatus.PROPOSED.value,
                "title": title,
                **gaia_assigned_filter(),
            }
        )

    async def list_budget_bucket(
        self, user_id: str, *, statuses: list[str], limit: int
    ) -> list[TodoDocument]:
        """Non-goal GAIA todos currently in one of ``statuses`` (a budget bucket),
        capped at ``limit`` — the creation gate's over-budget check."""
        return await self._find(
            {
                "user_id": user_id,
                "execution_status": {"$in": statuses},
                "kind": {"$ne": "goal"},
                **gaia_assigned_filter(),
            },
            limit=limit,
        )

    async def count_budget_bucket(self, user_id: str, *, statuses: list[str]) -> int:
        """Count of ``list_budget_bucket`` — the post-insert budget recount."""
        return await self._count(
            {
                "user_id": user_id,
                "execution_status": {"$in": statuses},
                "kind": {"$ne": "goal"},
                **gaia_assigned_filter(),
            }
        )

    async def list_expirable_proposals(
        self, user_id: str, *, before: datetime, now: datetime
    ) -> list[TodoDocument]:
        """Pending proposals created before ``before`` and not an active upgrade
        pitch — the curation pass's expiry candidates."""
        return await self._find(
            {
                "user_id": user_id,
                "execution_status": ExecutionStatus.PROPOSED.value,
                "created_at": {"$lt": before},
                "$and": [
                    {"$or": [{"pitch_expires_at": None}, {"pitch_expires_at": {"$lt": now}}]},
                    gaia_assigned_filter(),
                ],
            }
        )

    async def list_rejected_gaia(self, user_id: str) -> list[TodoDocument]:
        """Dismissed/expired GAIA todos, most-recently-dismissed first — the
        3-strike rejection summary's source."""
        return await self._find(
            {
                "user_id": user_id,
                "execution_status": {
                    "$in": [ExecutionStatus.DISMISSED.value, ExecutionStatus.EXPIRED.value]
                },
                **gaia_assigned_filter(),
            },
            sort=[("dismissed_at", -1)],
        )

    async def retry_failed(
        self, todo_id: str, user_id: str, *, now: datetime, user_retry_count: int
    ) -> TodoDocument | None:
        """Re-queue a failed todo for retry: clears the failure state and the
        ``failed`` label, resets the executor's retry counter, and bumps the
        user-initiated retry counter to ``user_retry_count``."""
        return await self._apply_raw_update(
            self._scoped_filter(todo_id, user_id),
            {
                "$set": {
                    "execution_status": ExecutionStatus.QUEUED.value,
                    "scheduled_at": now,
                    "error_message": None,
                    "gaia_retry_count": 0,
                    "gaia_user_retry_count": user_retry_count,
                },
                "$pull": {"labels": FAILED_LABEL},
            },
            scope=user_id,
        )

    # -------------------------------------------------------- dashboard finders
    # Named queries backing the Today dashboard's five saved-search sections.
    # Deliberately uncached (unlike the aggregations above): the dashboard reads
    # live in-flight/needs-you state on every load.

    async def find_oldest_open_proposal(self, user_id: str) -> TodoDocument | None:
        """Oldest still-open, not-yet-nudged proposed GAIA todo — the completion
        nudge's first-choice suggestion (see ``services.todos.completion_nudge``)."""
        results = await self._find(
            {
                "user_id": user_id,
                "execution_status": ExecutionStatus.PROPOSED.value,
                "kind": {"$ne": "goal"},
                "nudge_shown": {"$ne": True},
                **gaia_assigned_filter(),
            },
            sort=[("created_at", 1)],
            limit=1,
        )
        return results[0] if results else None

    async def list_open_user_todos_with_gaia_offer(
        self, user_id: str, *, limit: int
    ) -> list[TodoDocument]:
        """Open user todos carrying an active, not-yet-nudged GAIA-takeover
        offer — the completion nudge's fallback candidate pool (the caller
        picks the highest-priority one)."""
        return await self._find(
            {
                "user_id": user_id,
                "completed": False,
                "gaia_offer": {"$nin": [None, ""]},
                "gaia_offer_dismissed": {"$ne": True},
                "nudge_shown": {"$ne": True},
                **user_assigned_filter(),
            },
            sort=[("created_at", 1)],
            limit=limit,
        )

    # ----------------------------------------------------------------- writes

    async def bulk_update(self, user_id: str, todo_ids: list[str], update: TodoUpdate) -> int:
        """Apply the same ``$set`` to many of the user's todos; returns the count
        modified. One generation bump invalidates the whole scope."""
        return await self._bulk_set([(tid, update) for tid in todo_ids], scope=user_id)

    async def bulk_delete(self, user_id: str, todo_ids: list[str]) -> int:
        """Delete many of the user's todos in one round trip; returns the count
        deleted."""
        return await self._bulk_delete(todo_ids, scope=user_id)

    async def delete_all_for_user(self, user_id: str) -> int:
        """Delete every todo owned by ``user_id`` (dev-data reset); returns the count."""
        return await self._delete_many({"user_id": user_id}, scope=user_id)

    async def delete_onboarding_todos(self, user_id: str) -> int:
        """Delete the user's onboarding-seeded todos; returns the count deleted."""
        return await self._delete_many(
            {"user_id": user_id, "labels": ONBOARDING_LABEL}, scope=user_id
        )

    async def move_todos_to_project(
        self, user_id: str, from_project_id: str, to_project_id: str
    ) -> int:
        """Reassign every todo in ``from_project_id`` to ``to_project_id`` (used
        when a project is deleted and its todos fall back to Inbox)."""
        todos = await self._find({"user_id": user_id, "project_id": from_project_id})
        ids = [todo.id for todo in todos]
        return await self.bulk_update(user_id, ids, TodoUpdate(project_id=to_project_id))

    def _scoped_filter(self, todo_id: str, user_id: str) -> dict[str, object]:
        return {"_id": self._id_value(todo_id), "user_id": user_id}

    async def add_labels(
        self, todo_id: str, *, user_id: str, labels: list[str]
    ) -> TodoDocument | None:
        """Add labels to a todo without duplicating existing ones ($addToSet)."""
        return await self._apply_raw_update(
            self._scoped_filter(todo_id, user_id),
            {"$addToSet": {"labels": {"$each": labels}}},
            scope=user_id,
        )

    async def add_references(
        self, todo_id: str, *, user_id: str, references: list[str]
    ) -> TodoDocument | None:
        """Link related past tracked todos onto ``references`` ($addToSet)."""
        return await self._apply_raw_update(
            self._scoped_filter(todo_id, user_id),
            {"$addToSet": {"references": {"$each": references}}},
            scope=user_id,
        )

    async def add_subtask(
        self, todo_id: str, *, user_id: str, subtask: SubTask
    ) -> TodoDocument | None:
        """Append a subtask to a todo ($push)."""
        return await self._apply_raw_update(
            self._scoped_filter(todo_id, user_id),
            {"$push": {"subtasks": subtask.model_dump()}},
            scope=user_id,
        )

    async def remove_subtask(
        self, todo_id: str, *, user_id: str, subtask_id: str
    ) -> TodoDocument | None:
        """Remove a subtask by id ($pull)."""
        return await self._apply_raw_update(
            self._scoped_filter(todo_id, user_id),
            {"$pull": {"subtasks": {"id": subtask_id}}},
            scope=user_id,
        )

    async def set_subtask_fields(
        self,
        todo_id: str,
        *,
        user_id: str,
        subtask_id: str,
        title: str | None = None,
        completed: bool | None = None,
    ) -> TodoDocument | None:
        """Update a single subtask's title and/or completion (positional $set)."""
        fields: dict[str, object] = {}
        if title is not None:
            fields["subtasks.$[elem].title"] = title
        if completed is not None:
            fields["subtasks.$[elem].completed"] = completed
        return await self._apply_raw_update(
            self._scoped_filter(todo_id, user_id),
            {"$set": fields},
            scope=user_id,
            array_filters=[{"elem.id": subtask_id}],
        )

    async def clear_workflow_id(self, todo_id: str, *, user_id: str) -> TodoDocument | None:
        """Detach a todo's linked workflow ($unset workflow_id)."""
        return await self._apply_raw_update(
            self._scoped_filter(todo_id, user_id),
            {"$unset": {"workflow_id": ""}},
            scope=user_id,
        )


todo_repository = TodosRepository()
