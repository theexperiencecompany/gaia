"""State machine for GAIA-assigned todos.

Owns every ``execution_status`` transition and the gates around them:

- creation gate — traceability (``serves``) + server-side budgets (the junk-todo fix)
- ``approve`` — the ONLY ``proposed → queued`` path; meters the free tier and
  turns an at-quota tap into the upgrade pitch instead of a silent failure
- ``dismiss`` / ``expire`` — rejection paths that teach memory (3-strike rule)
- ``handoff`` — user todo → GAIA-assigned
- worker transitions — ``queued → running → done | failed | needs_you``

Canvas/context formatting lives in ``tracked_todo_service``, which depends on
this module — never the reverse.
"""

from datetime import UTC, datetime, timedelta
import re

from bson import ObjectId

from app.api.v1.middleware.tiered_rate_limiter import (
    RateLimitExceededException,
    tiered_limiter,
)
from app.constants.memory import MemorySourceType
from app.constants.todos import (
    ASSIGNEE_GAIA,
    DELIVERABLE_TEMPLATE,
    FACET_LOG,
    GAIA_TODO_EXECUTIONS_FEATURE,
    GAIA_TRACKED_LABEL,
    MAX_ACTIVE_GOALS,
    MAX_GAIA_TODOS_IN_FLIGHT,
    MAX_PENDING_PROPOSALS,
    NOTES_TEMPLATE,
    PITCH_TTL_DAYS,
    PROPOSAL_REJECTED_MEMORY_CATEGORY,
    PROPOSAL_TTL_HOURS,
    REJECTION_STRIKE_THRESHOLD,
    gaia_assigned_filter,
)
from app.db.mongodb.collections import todos_collection
from app.memory.engine import memory_engine
from app.models.payment_models import PlanType
from app.models.todo_models import ExecutionStatus
from app.services import first_steps_service
from app.services.gaia_tasks_fs import schedule_gaia_tasks_sync
from app.services.todo_canvas_storage import append_facet, build_vfs_label
from app.utils.analytics import track
from app.utils.redis_utils import RedisPoolManager
from shared.py.wide_events import log

# Statuses counted against MAX_GAIA_TODOS_IN_FLIGHT.
IN_FLIGHT_STATUSES: tuple[str, ...] = (
    ExecutionStatus.QUEUED.value,
    ExecutionStatus.RUNNING.value,
    ExecutionStatus.NEEDS_YOU.value,
)
# Labels that are system bookkeeping, never a proposal "kind".
_RESERVED_KIND_LABELS: frozenset[str] = frozenset({GAIA_TRACKED_LABEL, "failed"})


class GaiaTodoError(Exception):
    """Base for GAIA-todo lifecycle rejections (budget, traceability, transition)."""


class BudgetExceededError(GaiaTodoError):
    """Creation rejected because a GAIA-todo budget cap is already full."""


class TraceabilityError(GaiaTodoError):
    """Creation rejected because ``serves`` was empty (untraceable todo)."""


class InvalidTransitionError(GaiaTodoError):
    """A lifecycle transition was requested from a state that does not allow it."""


class ExecutionQuotaError(GaiaTodoError):
    """Approve blocked at the metered execution quota.

    Carries what the API layer needs to render the upgrade CTA: the pitch of
    the specific staged work, the quota reset time, and the required plan.
    """

    def __init__(
        self,
        *,
        todo_id: str,
        reset_time: str | None,
        pitch: str,
        plan_required: str = "pro",
    ) -> None:
        self.todo_id = todo_id
        self.reset_time = reset_time
        self.pitch = pitch
        self.plan_required = plan_required
        super().__init__(f"GAIA execution quota reached for todo {todo_id}")


def derive_proposal_kind(doc: dict) -> str:
    """Stable category for a proposal, used to group rejection signals.

    First non-reserved label, else a slug of the title — so the 3-strike rule
    still groups repeated proposals of the same shape.
    """
    for label in doc.get("labels", []):
        if label not in _RESERVED_KIND_LABELS:
            return label
    title = (doc.get("title") or "untitled").strip().lower()
    return re.sub(r"[^a-z0-9]+", "-", title).strip("-")[:60] or "untitled"


def _build_upgrade_pitch(doc: dict) -> str:
    """One-line pitch naming the specific staged work behind an at-quota Approve."""
    what = doc.get("serves") or doc.get("title") or "this work"
    return (
        f"GAIA has '{doc.get('title', 'this todo')}' staged and ready ({what}) — upgrade to run it."
    )


def _is_gaia_assigned(doc: dict) -> bool:
    # Dual-read during the migration window (legacy label OR assignee field).
    return doc.get("assignee") == ASSIGNEE_GAIA or GAIA_TRACKED_LABEL in doc.get("labels", [])


async def _get_gaia_todo(todo_id: str, user_id: str) -> dict:
    doc = await todos_collection.find_one({"_id": ObjectId(todo_id), "user_id": user_id})
    if not doc:
        raise InvalidTransitionError(f"Todo {todo_id} not found")
    if not _is_gaia_assigned(doc):
        raise InvalidTransitionError(f"Todo {todo_id} is not GAIA-assigned")
    return doc


async def _require_status(
    todo_id: str, user_id: str, expected: ExecutionStatus, action: str
) -> dict:
    doc = await _get_gaia_todo(todo_id, user_id)
    if doc.get("execution_status") != expected.value:
        raise InvalidTransitionError(
            f"Only {expected.value} todos can be {action} "
            f"(todo {todo_id} is {doc.get('execution_status')!r})"
        )
    return doc


async def system_log(todo_id: str, user_id: str, event_type: str, details: str) -> None:
    """Append an audit entry to the todo's log.md (code-written, not agent)."""
    now = datetime.now(UTC)
    await append_facet(
        todo_id, user_id, FACET_LOG, f"\n## {now.isoformat()} [{event_type}]\n- {details}\n"
    )


async def schedule_execution(todo_id: str, scheduled_at: datetime) -> bool:
    """Enqueue the ARQ deferred job that executes this todo at ``scheduled_at``."""
    try:
        pool = await RedisPoolManager.get_pool()
        await pool.enqueue_job("execute_tracked_todo", todo_id, _defer_until=scheduled_at)
        return True
    except Exception as e:
        log.warning("gaia_todo.schedule_failed", todo_id=todo_id, error=str(e))
        return False


async def reschedule_execution(todo_id: str, new_scheduled_at: datetime) -> bool:
    """Enqueue a replacement job; the task's Redis lock prevents double-execution."""
    return await schedule_execution(todo_id, new_scheduled_at)


async def gate_creation(
    user_id: str,
    serves: str,
    requires_approval: bool,
    title: str = "",
    kind: str = "task",
) -> tuple[str, ExecutionStatus | None]:
    """Validate a GAIA-todo creation and resolve its entry state.

    Returns the cleaned ``serves`` and the entry status per the approval rule
    (outward-facing → ``proposed``, internal-only → ``queued``). Raises
    ``TraceabilityError`` / ``BudgetExceededError`` — the junk-todo gate.
    Goal lanes (``kind == "goal"``) are long-lived by design: they skip the
    in-flight budget but are capped themselves so nightly attention stays
    focused.
    """
    serves = serves.strip()
    if kind == "goal":
        if not serves:
            raise TraceabilityError(
                "A goal needs `serves`: the user's own words for what they're pursuing."
            )
        active_goals = await todos_collection.count_documents(
            {"user_id": user_id, "kind": "goal", "completed": False, **gaia_assigned_filter()}
        )
        if active_goals >= MAX_ACTIVE_GOALS:
            raise BudgetExceededError(
                f"Already at {active_goals}/{MAX_ACTIVE_GOALS} active goals. A goal "
                "lane costs nightly attention: ask the user which goal to retire "
                "before adding this one."
            )
        # A goal is a lane, not executable work: it never enters the execution
        # pipeline (its children do).
        return serves, None
    if requires_approval and title.strip():
        # One Approve button per piece of work: an identically-titled pending
        # proposal means this is a duplicate (rerun, retry, or model repeat),
        # never a second legitimate ask.
        dupe = await todos_collection.find_one(
            {
                "user_id": user_id,
                "execution_status": ExecutionStatus.PROPOSED.value,
                "title": title.strip(),
                **gaia_assigned_filter(),
            },
            {"_id": 1},
        )
        if dupe:
            raise BudgetExceededError(
                f"A pending proposal titled {title.strip()!r} already exists "
                f"(id {dupe['_id']}). Update or approve that one instead of duplicating it."
            )
    if not serves:
        raise TraceabilityError(
            "GAIA todos must be traceable: pass `serves` naming the goal, "
            "memory item, or explicit user request this todo advances."
        )
    entry_status = ExecutionStatus.PROPOSED if requires_approval else ExecutionStatus.QUEUED
    if entry_status == ExecutionStatus.PROPOSED:
        cap, statuses, bucket = (
            MAX_PENDING_PROPOSALS,
            [ExecutionStatus.PROPOSED.value],
            "pending proposals",
        )
    else:
        cap, statuses, bucket = (
            MAX_GAIA_TODOS_IN_FLIGHT,
            list(IN_FLIGHT_STATUSES),
            "GAIA todos in flight",
        )
    query = {
        "user_id": user_id,
        "execution_status": {"$in": statuses},
        "kind": {"$ne": "goal"},
        **gaia_assigned_filter(),
    }
    existing = await todos_collection.find(query, {"title": 1}).to_list(length=cap + 1)
    if len(existing) >= cap:
        titles = "; ".join(doc.get("title", "untitled") for doc in existing[:cap])
        raise BudgetExceededError(
            f"Budget full: {len(existing)}/{cap} {bucket} ({titles}). "
            "Complete, dismiss, or let items expire before creating more."
        )
    return serves, entry_status


async def enforce_budget_post_insert(
    user_id: str, todo_id: str, entry_status: ExecutionStatus
) -> None:
    """Recount after insert and roll back the overshoot.

    The creation gate's check-then-insert is not atomic and the executor issues
    tool calls in parallel, so N creations can each pass the same count. The
    recount after insert makes the cap hold: the todo that tipped the bucket
    over deletes itself and surfaces the same budget error.
    """
    if entry_status is ExecutionStatus.PROPOSED:
        cap, statuses, bucket = (
            MAX_PENDING_PROPOSALS,
            [ExecutionStatus.PROPOSED.value],
            "pending proposals",
        )
    else:
        cap, statuses, bucket = (
            MAX_GAIA_TODOS_IN_FLIGHT,
            list(IN_FLIGHT_STATUSES),
            "GAIA todos in flight",
        )
    count = await todos_collection.count_documents(
        {
            "user_id": user_id,
            "execution_status": {"$in": statuses},
            "kind": {"$ne": "goal"},
            **gaia_assigned_filter(),
        }
    )
    if count > cap:
        await todos_collection.delete_one({"_id": ObjectId(todo_id), "user_id": user_id})
        raise BudgetExceededError(
            f"Budget full: {count - 1}/{cap} {bucket} already in place (parallel "
            "creations raced). Finish or dismiss existing items before adding more."
        )


async def _record_rejection_signal(
    user_id: str, doc: dict, source: str, reason: str | None = None
) -> None:
    """Persist a structured proposal_rejected memory signal (dismiss/expiry teach)."""
    content = (
        f"proposal_rejected | kind: {derive_proposal_kind(doc)} "
        f"| title: {doc.get('title', 'untitled')} | serves: {doc.get('serves', '')} "
        f"| source: {source}"
    )
    if reason:
        content += f" | reason: {reason}"
    try:
        await memory_engine.retain_single(
            user_id,
            content,
            category_path=PROPOSAL_REJECTED_MEMORY_CATEGORY,
            source_type=MemorySourceType.MANUAL,
        )
    except Exception as e:
        # The mongo-derived strike count still enforces the 3-strike rule;
        # losing the memory copy only weakens organic recall — log it.
        log.warning("gaia_todo.rejection_signal_failed", todo_id=str(doc.get("_id")), error=str(e))


async def approve(todo_id: str, user_id: str, user_plan: PlanType, channel: str = "web") -> None:
    """Approve a proposed todo: meter quota, queue it, enqueue execution.

    At quota, marks the proposal as the active upgrade pitch (TTL-exempt for
    PITCH_TTL_DAYS) and raises ``ExecutionQuotaError`` with the staged work.
    """
    doc = await _require_status(todo_id, user_id, ExecutionStatus.PROPOSED, "approved")
    now = datetime.now(UTC)
    try:
        await tiered_limiter.check_and_increment(user_id, GAIA_TODO_EXECUTIONS_FEATURE, user_plan)
    except RateLimitExceededException as e:
        await todos_collection.update_one(
            {"_id": ObjectId(todo_id), "user_id": user_id},
            {"$set": {"pitch_expires_at": now + timedelta(days=PITCH_TTL_DAYS)}},
        )
        track(
            user_id,
            "upgrade_prompt_shown",
            {"todo_id": todo_id, "feature": GAIA_TODO_EXECUTIONS_FEATURE, "channel": channel},
        )
        detail: dict = e.detail if isinstance(e.detail, dict) else {}
        raise ExecutionQuotaError(
            todo_id=todo_id,
            reset_time=detail.get("reset_time"),
            pitch=_build_upgrade_pitch(doc),
            plan_required=detail.get("plan_required") or "pro",
        ) from e
    await todos_collection.update_one(
        {"_id": ObjectId(todo_id), "user_id": user_id},
        {
            "$set": {
                "execution_status": ExecutionStatus.QUEUED.value,
                "scheduled_at": now,
                "pitch_expires_at": None,
            }
        },
    )
    await schedule_execution(todo_id, now)
    await system_log(todo_id, user_id, "approved", f"User approved execution via {channel}")
    track(user_id, "todo_approved", {"todo_id": todo_id, "channel": channel})
    await first_steps_service.mark_step(user_id, first_steps_service.STEP_FIRST_APPROVE)
    schedule_gaia_tasks_sync(user_id)


async def dismiss(
    todo_id: str, user_id: str, reason: str | None = None, channel: str = "web"
) -> None:
    """Dismiss a proposed todo; the rejection teaches memory (3-strike rule)."""
    doc = await _require_status(todo_id, user_id, ExecutionStatus.PROPOSED, "dismissed")
    await todos_collection.update_one(
        {"_id": ObjectId(todo_id), "user_id": user_id},
        {"$set": {"execution_status": ExecutionStatus.DISMISSED.value, "completed": True}},
    )
    await _record_rejection_signal(user_id, doc, "dismissed", reason)
    track(
        user_id,
        "todo_dismissed",
        {"todo_id": todo_id, "channel": channel, "has_reason": bool(reason)},
    )
    schedule_gaia_tasks_sync(user_id)


async def handoff(todo_id: str, user_id: str) -> None:
    """Convert a user todo to GAIA-assigned and enqueue it (entry state queued).

    Handoff never needs a tap: outward-facing steps discovered during execution
    flip the todo to ``needs_you`` per the run's approval contract.
    """
    doc = await todos_collection.find_one({"_id": ObjectId(todo_id), "user_id": user_id})
    if not doc:
        raise InvalidTransitionError(f"Todo {todo_id} not found")
    if _is_gaia_assigned(doc):
        raise InvalidTransitionError(f"Todo {todo_id} is already GAIA-assigned")
    now = datetime.now(UTC)
    title = doc.get("title", "untitled")
    updates: dict = {
        "assignee": ASSIGNEE_GAIA,
        "execution_status": ExecutionStatus.QUEUED.value,
        "serves": f"user handoff: {title}",
        "scheduled_at": now,
    }
    # Seed facets only if the todo has no working memory yet — a prep-classified
    # user todo may already carry notes_content (see todo_classification).
    if not doc.get("notes_content") and not doc.get("canvas_content"):
        updates["vfs_path"] = build_vfs_label(user_id, todo_id)
        updates["deliverable_content"] = DELIVERABLE_TEMPLATE.format(title=title)
        updates["notes_content"] = NOTES_TEMPLATE.format(title=title)
        updates["log_content"] = (
            f"# System Log: {title}\n\n## {now.isoformat()} [HANDOFF]\n- Source: user\n"
        )
    # assignee is the discriminator; no gaia-tracked label stamp (see create).
    await todos_collection.update_one(
        {"_id": ObjectId(todo_id), "user_id": user_id}, {"$set": updates}
    )
    await schedule_execution(todo_id, now)
    await system_log(todo_id, user_id, "handoff", "User handed this todo to GAIA")
    track(user_id, "handoff_created", {"todo_id": todo_id})
    schedule_gaia_tasks_sync(user_id)


async def mark_execution_status(
    todo_id: str, user_id: str, status: ExecutionStatus, error_message: str | None = None
) -> None:
    """Worker-owned transitions (``queued → running → done | failed | needs_you``).

    ``failed`` requires a human-readable cause and renders as loudly as ``done``.
    """
    if status == ExecutionStatus.FAILED and not (error_message or "").strip():
        raise InvalidTransitionError("failed status requires an error_message cause")
    updates = {
        "execution_status": status.value,
        "error_message": error_message if status == ExecutionStatus.FAILED else None,
    }
    await todos_collection.update_one(
        {"_id": ObjectId(todo_id), "user_id": user_id}, {"$set": updates}
    )
    if status == ExecutionStatus.DONE:
        track(user_id, "gaia_todo_completed", {"todo_id": todo_id})
    schedule_gaia_tasks_sync(user_id)


async def expire_stale_proposals(user_id: str) -> list[str]:
    """Curation pass: expire proposals older than PROPOSAL_TTL_HOURS.

    Active upgrade pitches (``pitch_expires_at`` in the future) are exempt.
    Returns expired titles so the briefing can report the cleanup.
    """
    now = datetime.now(UTC)
    query = {
        "user_id": user_id,
        "execution_status": ExecutionStatus.PROPOSED.value,
        "created_at": {"$lt": now - timedelta(hours=PROPOSAL_TTL_HOURS)},
        "$and": [
            {"$or": [{"pitch_expires_at": None}, {"pitch_expires_at": {"$lt": now}}]},
            gaia_assigned_filter(),
        ],
    }
    expired_titles: list[str] = []
    async for doc in todos_collection.find(query):
        await todos_collection.update_one(
            {"_id": doc["_id"]},
            {"$set": {"execution_status": ExecutionStatus.EXPIRED.value, "completed": True}},
        )
        await _record_rejection_signal(user_id, doc, "expired")
        track(user_id, "proposal_expired", {"todo_id": str(doc["_id"])})
        expired_titles.append(doc.get("title", "untitled"))
    if expired_titles:
        schedule_gaia_tasks_sync(user_id)
    return expired_titles


async def get_rejection_strikes_summary(user_id: str) -> str:
    """Kinds rejected/expired REJECTION_STRIKE_THRESHOLD+ times, for prompt injection.

    Derived from the todos collection (not memory recall) so the 3-strike rule
    cannot silently degrade.
    """
    query = {
        "user_id": user_id,
        "execution_status": {
            "$in": [ExecutionStatus.DISMISSED.value, ExecutionStatus.EXPIRED.value]
        },
        **gaia_assigned_filter(),
    }
    strikes: dict[str, int] = {}
    async for doc in todos_collection.find(query, {"title": 1, "labels": 1, "serves": 1}):
        kind = derive_proposal_kind(doc)
        strikes[kind] = strikes.get(kind, 0) + 1
    blocked = sorted(k for k, n in strikes.items() if n >= REJECTION_STRIKE_THRESHOLD)
    if not blocked:
        return ""
    return (
        "Do NOT propose these kinds again (rejected 3+ times, unless the user "
        "explicitly asks): " + ", ".join(blocked)
    )
