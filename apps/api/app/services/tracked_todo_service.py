"""
Tracked todo service — Mongo-backed lifecycle for GAIA's working memory todos.

A tracked todo is a regular todo with:
- vfs_path (display label) set to /users/{user_id}/todos/{todo_id}/
- 'gaia-tracked' label
- canvas_content field (agent-written brain) indexed in ChromaDB
- log_content field (system-written audit trail)

Canvas and log content live on the todo document itself — see
``app/services/todo_canvas_storage.py`` for the storage primitives. No
JuiceFS / FUSE mount is required, so tracked todos work in every dev mode.
"""

from datetime import UTC, datetime, timedelta
import re

from bson import ObjectId

from app.constants.todos import (
    GAIA_TRACKED_LABEL,
)
from app.db.mongodb.collections import todos_collection
from app.models.todo_models import ExecutionStatus, Priority, TodoModel, TodoResponse
from app.services.gaia_tasks_fs import schedule_gaia_tasks_sync
from app.services.todo_canvas_storage import (
    append_log,
    build_vfs_label,
    read_canvas,
    write_canvas,
)
from app.services.todos.todo_service import TodoService
from app.utils.canvas_vector_utils import (
    mark_canvas_completed,
    store_canvas_embedding,
    update_canvas_embedding,
)
from app.utils.redis_utils import RedisPoolManager
from shared.py.wide_events import log

# Execution statuses counted against MAX_GAIA_TODOS_IN_FLIGHT.
_IN_FLIGHT_STATUSES: tuple[str, ...] = (
    ExecutionStatus.QUEUED.value,
    ExecutionStatus.RUNNING.value,
    ExecutionStatus.NEEDS_YOU.value,
)
# Terminal statuses hidden from the "active tracked todos" agent context blocks.
_TERMINAL_CONTEXT_STATUSES: tuple[str, ...] = (
    ExecutionStatus.DISMISSED.value,
    ExecutionStatus.EXPIRED.value,
)
# Labels that are system bookkeeping, never a proposal "kind".
_RESERVED_KIND_LABELS: frozenset[str] = frozenset({GAIA_TRACKED_LABEL, "failed"})
# Parses ``kind: <value>`` out of a stored proposal_rejected memory line.
_REJECTION_KIND_RE = re.compile(r"kind:\s*([^|]+?)\s*(?:\||$)")


class TrackedTodoError(Exception):
    """Base for tracked-todo lifecycle rejections (budget, traceability, transition)."""


class BudgetExceededError(TrackedTodoError):
    """Creation rejected because a GAIA-todo budget cap is already full."""


class TraceabilityError(TrackedTodoError):
    """Creation rejected because ``serves`` was empty (untraceable todo)."""


class InvalidTransitionError(TrackedTodoError):
    """A lifecycle transition was requested from a state that does not allow it."""


class GaiaExecutionQuotaError(TrackedTodoError):
    """Approve blocked because the user is at their metered execution quota.

    Carries the data the API layer needs to render the upgrade-CTA payload
    (the pitch of the staged work, the quota reset time, the required plan).
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


def _derive_proposal_kind(doc: dict) -> str:
    """Best-effort stable category for a proposal, used to group rejection signals.

    Uses the first non-reserved label; falls back to a slug of the title so the
    3-strike rule still groups repeated proposals of the same shape.
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


CANVAS_TEMPLATE = """# {title}

## Key Details
<!-- email addresses, thread IDs, calendar IDs, issue IDs — everything needed to take action -->

## Current State
<!-- what's true RIGHT NOW — updated after every action -->

## Activity Log
<!-- which agent did what, which tools it used, what the outcome was — add entries HERE, not in Learnings -->

## Timeline
<!-- chronological list of actions taken and results -->

## Context
<!-- accumulated context from signals, related information, decisions made -->

## Learnings
<!-- written on completion: what worked, what didn't, key decisions, timing insights, optimizations for next time -->
"""


def _pin_active_todo(docs: list[dict], active_todo_id: str | None) -> None:
    """Move the matching todo to the front of `docs` in-place (no-op if not found)."""
    if not active_todo_id:
        return
    for i, d in enumerate(docs):
        if str(d["_id"]) == active_todo_id and i > 0:
            docs.insert(0, docs.pop(i))
            return


def _format_due_string(due_date: datetime | None, now: datetime) -> str:
    """Render the due-date suffix: ` due(Nd)`, ` OVERDUE(Nd)`, or empty."""
    if not due_date:
        return ""
    days_until = (due_date - now).days
    if days_until < 0:
        return f" OVERDUE({-days_until}d)"
    return f" due({days_until}d)"


# Capture everything under the "## Key Details" heading up to the next "## "
# heading (or end of text). A tempered greedy token — "any char that does not
# begin a new section" — avoids a reluctant quantifier entirely.
_KEY_DETAILS_RE = re.compile(r"## Key Details\n((?:(?!\n## ).)*)", re.DOTALL)
_KEY_DETAILS_MAX_LINES = 5


async def _extract_canvas_key_details(doc: dict, user_id: str) -> str:
    """Pull the Key Details section text from a tracked todo's canvas (empty on miss)."""
    todo_id = str(doc["_id"])
    try:
        canvas = await read_canvas(todo_id, user_id)
    except Exception as e:
        log.warning(
            "tracked_todo.canvas_read_failed",
            todo_id=todo_id,
            error=str(e),
        )
        return ""
    if not canvas:
        return ""
    match = _KEY_DETAILS_RE.search(canvas)
    return match.group(1).strip() if match else ""


def _format_signal_entry(doc: dict, key_details: str) -> str:
    """Render one tracked todo as a signal-matching context bullet (+ indented key details)."""
    labels = [lbl for lbl in doc.get("labels", []) if lbl != GAIA_TRACKED_LABEL]
    labels_str = f" [{', '.join(labels)}]" if labels else ""
    entry = (
        f'- "{doc.get("title", "")}"{labels_str} '
        f"(ID: {doc['_id']!s}, vfs: {doc.get('vfs_path', '')})"
    )
    if key_details:
        for dl in key_details.split("\n")[:_KEY_DETAILS_MAX_LINES]:
            entry += f"\n    {dl.strip()}"
    return entry


def _format_tracked_todo_line(doc: dict, now: datetime, active_todo_id: str | None) -> str:
    """Format one tracked-todo doc as a context-injection summary line."""
    age_days = (now - doc.get("created_at", now)).days
    last_update = (now - doc.get("updated_at", now)).days
    labels = [lbl for lbl in doc.get("labels", []) if lbl != GAIA_TRACKED_LABEL]
    labels_str = f" [{', '.join(labels)}]" if labels else ""
    todo_id = str(doc["_id"])
    prefix = "⭐ ACTIVE " if todo_id == active_todo_id else ""
    return (
        f'  {prefix}"{doc["title"]}"{labels_str}{_format_due_string(doc.get("due_date"), now)}'
        f" — {age_days}d old, updated {last_update}d ago"
        f" | ID: {todo_id} | VFS: {doc.get('vfs_path', 'none')}"
    )


class TrackedTodoService:
    """Manages VFS lifecycle for tracked (GAIA working memory) todos.

    All methods are static — the service holds no instance state. The
    ``tracked_todo_service`` singleton is kept for call-site compatibility.
    """

    @staticmethod
    async def create_tracked_todo(
        user_id: str,
        title: str,
        serves: str,
        requires_approval: bool,
        description: str | None = None,
        project_id: str | None = None,
        due_date: datetime | None = None,
        priority: Priority = Priority.NONE,
        labels: list[str] | None = None,
        initial_canvas: str | None = None,
    ) -> TodoResponse:
        """Create a GAIA-assigned todo with VFS canvas and ChromaDB indexing.

        Creation is gated (the junk-todo fix): ``serves`` must trace the todo to
        a goal/memory/user request, and server-side budgets cap proposals and
        in-flight work. Entry state follows the approval rule:
        ``requires_approval`` (outward-facing) → ``proposed``; internal-only →
        ``queued``.
        """
        serves = serves.strip()
        if not serves:
            raise TraceabilityError(
                "GAIA todos must be traceable: pass `serves` naming the goal, "
                "memory item, or explicit user request this todo advances."
            )
        entry_status = ExecutionStatus.PROPOSED if requires_approval else ExecutionStatus.QUEUED
        await TrackedTodoService._enforce_creation_budget(user_id, entry_status)

        # Keep the legacy label during the dual-read migration window.
        all_labels = list(labels or [])
        if GAIA_TRACKED_LABEL not in all_labels:
            all_labels.append(GAIA_TRACKED_LABEL)

        # Create the todo
        todo = TodoModel(
            title=title,
            description=description,
            project_id=project_id,
            due_date=due_date,
            priority=priority,
            labels=all_labels,
            assignee=ASSIGNEE_GAIA,
            execution_status=entry_status,
            serves=serves,
        )
        result = await TodoService.create_todo(todo, user_id)
        todo_id = result.id

        # Persist canvas + log + display label on the todo doc itself.
        vfs_path = build_vfs_label(user_id, todo_id)
        canvas_content = initial_canvas or CANVAS_TEMPLATE.format(title=title)
        now = datetime.now(UTC)
        log_content = (
            f"# System Log: {title}\n\n"
            f"## {now.isoformat()} [CREATED]\n"
            f"- Source: agent\n"
            f"- Labels: {', '.join(all_labels)}\n"
        )

        await todos_collection.update_one(
            {"_id": ObjectId(todo_id), "user_id": user_id},
            {
                "$set": {
                    "vfs_path": vfs_path,
                    "canvas_content": canvas_content,
                    "log_content": log_content,
                }
            },
        )

        # Index canvas in ChromaDB
        await store_canvas_embedding(
            todo_id=todo_id,
            canvas_content=canvas_content,
            user_id=user_id,
            title=title,
            labels=all_labels,
        )

        # Update result with vfs_path
        result.vfs_path = vfs_path

        log.info(
            "tracked_todo.created",
            todo_id=todo_id,
            user_id=user_id,
            title=title,
            vfs_path=vfs_path,
        )
        schedule_gaia_tasks_sync(user_id)
        if entry_status == ExecutionStatus.PROPOSED:
            track(user_id, "todo_proposed", {"todo_id": todo_id, "serves": serves})
        return result

    @staticmethod
    async def complete_tracked_todo(todo_id: str, user_id: str, summary: str) -> bool:
        """Complete a tracked todo: append completion to log, mark done, archive label."""
        doc = await todos_collection.find_one({"_id": ObjectId(todo_id), "user_id": user_id})
        if not doc:
            return False

        # Guard against double-completion
        if doc.get("completed"):
            return True

        vfs_path = doc.get("vfs_path") or build_vfs_label(user_id, todo_id)
        now = datetime.now(UTC)

        # Append completion to log
        await append_log(
            todo_id,
            user_id,
            f"\n## {now.isoformat()} [COMPLETED]\n- Summary: {summary}\n",
        )

        # Switch the display label to the archived form (purely cosmetic).
        archive_path = vfs_path.replace("/todos/", "/todos/archive/")

        # Update todo
        await todos_collection.update_one(
            {"_id": ObjectId(todo_id), "user_id": user_id},
            {
                "$set": {
                    "completed": True,
                    "completed_at": now,
                    "vfs_path": archive_path,
                    "updated_at": now,
                }
            },
        )

        # Invalidate Redis cache so the frontend reflects completion immediately
        await TodoService._invalidate_cache(
            user_id=user_id,
            project_id=str(doc["project_id"]) if doc.get("project_id") else None,
            todo_id=todo_id,
            operation="update",
        )

        # Mark as completed in ChromaDB (keep embedding but mark completed)
        await mark_canvas_completed(todo_id)

        log.info(
            "tracked_todo.completed",
            todo_id=todo_id,
            user_id=user_id,
            summary=summary,
        )
        schedule_gaia_tasks_sync(user_id)
        return True

    @staticmethod
    async def get_active_tracked_summary(user_id: str, active_todo_id: str | None = None) -> str:
        """Formatted summary of active tracked todos for context injection.

        When active_todo_id is provided, that todo is pinned at the top with
        an ⭐ ACTIVE marker so the agent can quickly identify the run's
        bound canvas.
        """
        cursor = todos_collection.find(
            {
                "user_id": user_id,
                "labels": GAIA_TRACKED_LABEL,
                "completed": False,
            }
        ).sort("updated_at", -1)
        docs = await cursor.to_list(length=15)
        if not docs:
            return ""

        _pin_active_todo(docs, active_todo_id)

        now = datetime.now(UTC)
        lines = ["ACTIVE TRACKED TODOS:"]
        lines.extend(_format_tracked_todo_line(doc, now, active_todo_id) for doc in docs)
        return "\n".join(lines)

    @staticmethod
    async def append_canvas_timeline(todo_id: str, user_id: str, entry: str) -> bool:
        """Append a line to the canvas Timeline section.

        Called by code (not agent) to guarantee a paper trail for scheduled runs
        regardless of what the LLM writes. If the canvas has a "## Timeline"
        section, the line is inserted at the top of its body; otherwise a new
        section is appended at the end of the canvas.
        """
        try:
            current = await read_canvas(todo_id, user_id) or ""
        except Exception as e:
            log.warning(
                "tracked_todo.canvas_read_for_timeline_failed",
                todo_id=todo_id,
                error=str(e),
            )
            return False
        if not current:
            return False

        line = entry if entry.startswith("- ") else f"- {entry}"
        heading = "## Timeline"
        heading_pos = current.find(f"\n{heading}")

        if heading_pos == -1:
            # No Timeline section — append a new one at the end.
            new_canvas = current.rstrip() + f"\n\n{heading}\n{line}\n"
        else:
            insert_pos = heading_pos + len(f"\n{heading}")
            new_canvas = current[:insert_pos] + f"\n{line}" + current[insert_pos:]

        try:
            await write_canvas(todo_id, user_id, new_canvas)
        except Exception as e:
            log.warning(
                "tracked_todo.canvas_timeline_write_failed",
                todo_id=todo_id,
                error=str(e),
            )
            return False
        return True

    @staticmethod
    async def system_log(todo_id: str, user_id: str, event_type: str, details: str) -> None:
        """Append a system log entry to a tracked todo's log.

        Called by code (not agent) for audit trail. Agent writes to canvas.
        """
        now = datetime.now(UTC)
        await append_log(
            todo_id,
            user_id,
            f"\n## {now.isoformat()} [{event_type}]\n- {details}\n",
        )

    @staticmethod
    async def get_signal_matching_context(user_id: str) -> str:
        """Compact tracked todos summary optimized for signal matching.

        Includes key IDs (thread_ids, email addresses, event_ids) so the
        agent can match incoming signals to relevant todos.
        """
        cursor = todos_collection.find(
            {
                "user_id": user_id,
                "labels": GAIA_TRACKED_LABEL,
                "completed": False,
            }
        ).sort("updated_at", -1)
        docs = await cursor.to_list(length=15)
        if not docs:
            return ""

        lines = [
            _format_signal_entry(doc, await _extract_canvas_key_details(doc, user_id))
            for doc in docs
        ]
        return "ACTIVE TRACKED TODOS (check if incoming signal relates to any):\n" + "\n".join(
            lines
        )

    @staticmethod
    async def reindex_canvas(todo_id: str, user_id: str) -> bool:
        """Re-index a todo's canvas in ChromaDB after the agent writes to it."""
        doc = await todos_collection.find_one({"_id": ObjectId(todo_id), "user_id": user_id})
        if not doc:
            return False

        canvas_content = doc.get("canvas_content")
        if not canvas_content:
            return False

        return await update_canvas_embedding(
            todo_id=todo_id,
            canvas_content=canvas_content,
            user_id=user_id,
            title=doc.get("title", ""),
            labels=doc.get("labels"),
        )

    @staticmethod
    async def schedule_execution(todo_id: str, scheduled_at: datetime) -> bool:
        """Enqueue an ARQ deferred job to execute this tracked todo at scheduled_at.

        Returns True if job was enqueued successfully, False otherwise.
        """
        try:
            pool = await RedisPoolManager.get_pool()
            await pool.enqueue_job(
                "execute_tracked_todo",
                todo_id,
                _defer_until=scheduled_at,
            )
            return True
        except Exception as e:
            log.warning("tracked_todo.schedule_failed", todo_id=todo_id, error=str(e))
            return False

    @staticmethod
    async def reschedule_execution(todo_id: str, new_scheduled_at: datetime) -> bool:
        """Cancel any existing ARQ job for this todo and enqueue a new one.

        Note: ARQ does not support cancelling deferred jobs by argument.
        We enqueue a new job; the task itself uses a Redis lock to prevent
        double-execution. This is safe — at most one execution fires per lock window.
        """
        return await TrackedTodoService.schedule_execution(todo_id, new_scheduled_at)

    @staticmethod
    async def archive_tracked_todo(todo_id: str, user_id: str, reason: str) -> bool:
        """Archive a tracked todo by marking it completed with a system-generated summary.

        Used by maintenance sweep when a todo expires cleanly (no action needed).
        Logs the archival reason to log.md before completing.
        """
        try:
            await TrackedTodoService.system_log(
                todo_id,
                user_id,
                "auto_archived",
                f"Archived by maintenance sweep: {reason}",
            )
            return await TrackedTodoService.complete_tracked_todo(
                todo_id, user_id, summary=f"Auto-archived: {reason}"
            )
        except Exception as e:
            log.warning("tracked_todo.archive_failed", todo_id=todo_id, error=str(e))
            return False

    @staticmethod
    async def _enforce_creation_budget(user_id: str, entry_status: ExecutionStatus) -> None:
        """Reject creation when the relevant GAIA-todo budget cap is full.

        The error lists the items occupying the budget so the agent can
        complete, dismiss, or expire before proposing more.
        """
        if entry_status == ExecutionStatus.PROPOSED:
            cap, statuses, bucket = (
                MAX_PENDING_PROPOSALS,
                [ExecutionStatus.PROPOSED.value],
                "pending proposals",
            )
        else:
            cap, statuses, bucket = (
                MAX_GAIA_TODOS_IN_FLIGHT,
                list(_IN_FLIGHT_STATUSES),
                "GAIA todos in flight",
            )
        query = {
            "user_id": user_id,
            "execution_status": {"$in": statuses},
            **gaia_assigned_filter(),
        }
        existing = await todos_collection.find(query, {"title": 1}).to_list(length=cap + 1)
        if len(existing) >= cap:
            titles = "; ".join(doc.get("title", "untitled") for doc in existing[:cap])
            raise BudgetExceededError(
                f"Budget full: {len(existing)}/{cap} {bucket} ({titles}). "
                "Complete, dismiss, or let items expire before creating more."
            )

    @staticmethod
    async def _record_rejection_signal(
        user_id: str, doc: dict, source: str, reason: str | None = None
    ) -> None:
        """Persist a structured proposal_rejected memory signal (dismiss/expiry teach)."""
        kind = _derive_proposal_kind(doc)
        content = (
            f"proposal_rejected | kind: {kind} | title: {doc.get('title', 'untitled')} "
            f"| serves: {doc.get('serves', '')} | source: {source}"
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
            log.warning(
                "tracked_todo.rejection_signal_failed", todo_id=str(doc.get("_id")), error=str(e)
            )

    @staticmethod
    async def _get_gaia_todo(todo_id: str, user_id: str) -> dict:
        doc = await todos_collection.find_one({"_id": ObjectId(todo_id), "user_id": user_id})
        if not doc:
            raise InvalidTransitionError(f"Todo {todo_id} not found")
        is_gaia = doc.get("assignee") == ASSIGNEE_GAIA or GAIA_TRACKED_LABEL in doc.get(
            "labels", []
        )
        if not is_gaia:
            raise InvalidTransitionError(f"Todo {todo_id} is not GAIA-assigned")
        return doc

    @staticmethod
    async def approve_todo(
        todo_id: str, user_id: str, user_plan: PlanType, channel: str = "web"
    ) -> None:
        """Approve a proposed GAIA todo: meter quota, queue, and enqueue execution.

        The only path from ``proposed`` to ``queued``. At-quota free users get a
        ``GaiaExecutionQuotaError`` carrying the upgrade pitch (the staged work),
        and the proposal becomes TTL-exempt while it is the active pitch.
        """
        doc = await TrackedTodoService._get_gaia_todo(todo_id, user_id)
        if doc.get("execution_status") != ExecutionStatus.PROPOSED.value:
            raise InvalidTransitionError(
                f"Only proposed todos can be approved (todo {todo_id} is "
                f"{doc.get('execution_status')!r})"
            )
        now = datetime.now(UTC)
        try:
            await tiered_limiter.check_and_increment(
                user_id, GAIA_TODO_EXECUTIONS_FEATURE, user_plan
            )
        except RateLimitExceededException as e:
            pitch = _build_upgrade_pitch(doc)
            await todos_collection.update_one(
                {"_id": ObjectId(todo_id), "user_id": user_id},
                {"$set": {"pitch_expires_at": now + timedelta(days=PITCH_TTL_DAYS)}},
            )
            track(
                user_id,
                "upgrade_prompt_shown",
                {"todo_id": todo_id, "feature": GAIA_TODO_EXECUTIONS_FEATURE, "channel": channel},
            )
            detail = e.detail if isinstance(e.detail, dict) else {}
            raise GaiaExecutionQuotaError(
                todo_id=todo_id,
                reset_time=detail.get("reset_time"),
                pitch=pitch,
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
        await TrackedTodoService.schedule_execution(todo_id, now)
        await TrackedTodoService.system_log(
            todo_id, user_id, "approved", f"User approved execution via {channel}"
        )
        track(user_id, "todo_approved", {"todo_id": todo_id, "channel": channel})
        schedule_gaia_tasks_sync(user_id)

    @staticmethod
    async def dismiss_todo(
        todo_id: str, user_id: str, reason: str | None = None, channel: str = "web"
    ) -> None:
        """Dismiss a proposed GAIA todo and record the rejection signal."""
        doc = await TrackedTodoService._get_gaia_todo(todo_id, user_id)
        if doc.get("execution_status") != ExecutionStatus.PROPOSED.value:
            raise InvalidTransitionError(
                f"Only proposed todos can be dismissed (todo {todo_id} is "
                f"{doc.get('execution_status')!r})"
            )
        await todos_collection.update_one(
            {"_id": ObjectId(todo_id), "user_id": user_id},
            {"$set": {"execution_status": ExecutionStatus.DISMISSED.value, "completed": True}},
        )
        await TrackedTodoService._record_rejection_signal(user_id, doc, "dismissed", reason)
        track(
            user_id,
            "todo_dismissed",
            {"todo_id": todo_id, "channel": channel, "has_reason": bool(reason)},
        )
        schedule_gaia_tasks_sync(user_id)

    @staticmethod
    async def handoff_todo(todo_id: str, user_id: str) -> None:
        """Convert a user todo to GAIA-assigned and enqueue it (entry state queued).

        Outward-facing steps discovered during execution flip the todo to
        ``needs_you`` per the run's approval contract, so handoff itself never
        needs a tap.
        """
        doc = await todos_collection.find_one({"_id": ObjectId(todo_id), "user_id": user_id})
        if not doc:
            raise InvalidTransitionError(f"Todo {todo_id} not found")
        if doc.get("assignee") == ASSIGNEE_GAIA or GAIA_TRACKED_LABEL in doc.get("labels", []):
            raise InvalidTransitionError(f"Todo {todo_id} is already GAIA-assigned")
        now = datetime.now(UTC)
        title = doc.get("title", "untitled")
        updates: dict = {
            "assignee": ASSIGNEE_GAIA,
            "execution_status": ExecutionStatus.QUEUED.value,
            "serves": f"user handoff: {title}",
            "scheduled_at": now,
        }
        if not doc.get("canvas_content"):
            updates["vfs_path"] = build_vfs_label(user_id, todo_id)
            updates["canvas_content"] = CANVAS_TEMPLATE.format(title=title)
            updates["log_content"] = (
                f"# System Log: {title}\n\n## {now.isoformat()} [HANDOFF]\n- Source: user\n"
            )
        await todos_collection.update_one(
            {"_id": ObjectId(todo_id), "user_id": user_id},
            {"$set": updates, "$addToSet": {"labels": GAIA_TRACKED_LABEL}},
        )
        await TrackedTodoService.schedule_execution(todo_id, now)
        await TrackedTodoService.system_log(
            todo_id, user_id, "handoff", "User handed this todo to GAIA"
        )
        track(user_id, "handoff_created", {"todo_id": todo_id})
        schedule_gaia_tasks_sync(user_id)

    @staticmethod
    async def mark_execution_status(
        todo_id: str, user_id: str, status: ExecutionStatus, error_message: str | None = None
    ) -> None:
        """Worker-owned transitions (queued → running → done | failed | needs_you).

        ``failed`` requires a human-readable cause and is rendered as loudly as
        ``done`` (list + next briefing).
        """
        if status == ExecutionStatus.FAILED and not (error_message or "").strip():
            raise InvalidTransitionError("failed status requires an error_message cause")
        updates: dict = {"execution_status": status.value}
        updates["error_message"] = error_message if status == ExecutionStatus.FAILED else None
        if status == ExecutionStatus.DONE:
            track(user_id, "gaia_todo_completed", {"todo_id": todo_id})
        await todos_collection.update_one(
            {"_id": ObjectId(todo_id), "user_id": user_id}, {"$set": updates}
        )
        schedule_gaia_tasks_sync(user_id)

    @staticmethod
    async def expire_stale_proposals(user_id: str) -> list[str]:
        """Curation pass: expire proposals older than PROPOSAL_TTL_HOURS.

        Active upgrade pitches (``pitch_expires_at`` in the future) are exempt.
        Returns expired titles so the briefing can report the cleanup.
        """
        now = datetime.now(UTC)
        cutoff = now - timedelta(hours=PROPOSAL_TTL_HOURS)
        query = {
            "user_id": user_id,
            "execution_status": ExecutionStatus.PROPOSED.value,
            "created_at": {"$lt": cutoff},
            "$and": [
                {
                    "$or": [
                        {"pitch_expires_at": None},
                        {"pitch_expires_at": {"$lt": now}},
                    ]
                },
                gaia_assigned_filter(),
            ],
        }
        expired_titles: list[str] = []
        async for doc in todos_collection.find(query):
            await todos_collection.update_one(
                {"_id": doc["_id"]},
                {"$set": {"execution_status": ExecutionStatus.EXPIRED.value, "completed": True}},
            )
            await TrackedTodoService._record_rejection_signal(user_id, doc, "expired")
            track(user_id, "proposal_expired", {"todo_id": str(doc["_id"])})
            expired_titles.append(doc.get("title", "untitled"))
        if expired_titles:
            schedule_gaia_tasks_sync(user_id)
        return expired_titles

    @staticmethod
    async def get_rejection_strikes_summary(user_id: str) -> str:
        """Kinds rejected/expired REJECTION_STRIKE_THRESHOLD+ times, for prompt injection.

        Derived deterministically from the todos collection (not memory recall)
        so the 3-strike rule cannot silently degrade.
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
            kind = _derive_proposal_kind(doc)
            strikes[kind] = strikes.get(kind, 0) + 1
        blocked = sorted(k for k, n in strikes.items() if n >= REJECTION_STRIKE_THRESHOLD)
        if not blocked:
            return ""
        return (
            "Do NOT propose these kinds again (rejected 3+ times, unless the user "
            "explicitly asks): " + ", ".join(blocked)
        )


tracked_todo_service = TrackedTodoService()
