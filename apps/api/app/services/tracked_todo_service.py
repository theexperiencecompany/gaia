"""
Tracked todo service — VFS lifecycle for GAIA's working memory todos.

A tracked todo is a regular todo with:
- vfs_path set to /users/{user_id}/todos/{todo_id}/
- 'gaia-tracked' label
- canvas.md (agent-written brain) indexed in ChromaDB
- log.md (system-written audit trail)
"""

from datetime import UTC, datetime
import re

from bson import ObjectId

from app.db.mongodb.collections import todos_collection
from app.models.todo_models import Priority, TodoModel, TodoResponse
from app.services.todos.todo_service import TodoService
from app.services.vfs.mongo_vfs import MongoVFS
from app.utils.canvas_vector_utils import (
    mark_canvas_completed,
    store_canvas_embedding,
    update_canvas_embedding,
)
from app.utils.redis_utils import RedisPoolManager
from shared.py.wide_events import log

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

GAIA_TRACKED_LABEL = "gaia-tracked"


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


_KEY_DETAILS_RE = re.compile(r"## Key Details\n(.*?)(?:\n## |\Z)", re.DOTALL)
_KEY_DETAILS_MAX_LINES = 5


async def _extract_canvas_key_details(vfs: MongoVFS, doc: dict, user_id: str) -> str:
    """Pull the Key Details section text from a tracked todo's canvas.md (empty on miss)."""
    vfs_path = doc.get("vfs_path", "")
    if not vfs_path:
        return ""
    try:
        canvas = await vfs.read(path=f"{vfs_path}/canvas.md", user_id=user_id)
    except Exception as e:
        log.warning(
            "tracked_todo.canvas_read_failed",
            todo_id=str(doc["_id"]),
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
        description: str | None = None,
        project_id: str | None = None,
        due_date: datetime | None = None,
        priority: Priority = Priority.NONE,
        labels: list[str] | None = None,
        initial_canvas: str | None = None,
    ) -> TodoResponse:
        """Create a todo with VFS canvas and ChromaDB indexing.

        1. Creates a regular todo with 'gaia-tracked' label
        2. Initializes VFS directory with canvas.md + log.md
        3. Sets vfs_path on the todo document
        4. Indexes canvas in ChromaDB
        """
        # Ensure gaia-tracked label is present
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
        )
        result = await TodoService.create_todo(todo, user_id)
        todo_id = result.id

        # Initialize VFS
        vfs_path = f"/users/{user_id}/todos/{todo_id}"
        canvas_content = initial_canvas or CANVAS_TEMPLATE.format(title=title)

        vfs = MongoVFS()
        now = datetime.now(UTC)

        await vfs.write(
            path=f"{vfs_path}/canvas.md",
            content=canvas_content,
            user_id=user_id,
        )

        await vfs.write(
            path=f"{vfs_path}/log.md",
            content=(
                f"# System Log: {title}\n\n"
                f"## {now.isoformat()} [CREATED]\n"
                f"- Source: agent\n"
                f"- Labels: {', '.join(all_labels)}\n"
            ),
            user_id=user_id,
        )

        # Set vfs_path on the todo document
        await todos_collection.update_one(
            {"_id": ObjectId(todo_id), "user_id": user_id},
            {"$set": {"vfs_path": vfs_path}},
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
        return result

    @staticmethod
    async def complete_tracked_todo(todo_id: str, user_id: str, summary: str) -> bool:
        """Complete a tracked todo: archive VFS, remove from ChromaDB index."""
        doc = await todos_collection.find_one({"_id": ObjectId(todo_id), "user_id": user_id})
        if not doc:
            return False

        # Guard against double-completion (VFS already archived)
        if doc.get("completed"):
            return True

        vfs_path = doc.get("vfs_path")
        if not vfs_path:
            return False

        now = datetime.now(UTC)
        vfs = MongoVFS()

        # Append completion to log
        await vfs.append(
            path=f"{vfs_path}/log.md",
            content=f"\n## {now.isoformat()} [COMPLETED]\n- Summary: {summary}\n",
            user_id=user_id,
        )

        # Archive VFS
        archive_path = vfs_path.replace("/todos/", "/todos/archive/")
        await vfs.move(source=vfs_path, dest=archive_path, user_id=user_id)

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
        doc = await todos_collection.find_one({"_id": ObjectId(todo_id), "user_id": user_id})
        if not doc or not doc.get("vfs_path"):
            return False

        vfs = MongoVFS()
        canvas_path = f"{doc['vfs_path']}/canvas.md"
        try:
            current = await vfs.read(path=canvas_path, user_id=user_id) or ""
        except Exception as e:
            log.warning(
                "tracked_todo.canvas_read_for_timeline_failed",
                todo_id=todo_id,
                error=str(e),
            )
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
            await vfs.write(path=canvas_path, content=new_canvas, user_id=user_id)
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
        """Append a system log entry to a tracked todo's log.md.

        Called by code (not agent) for audit trail. Agent writes to canvas.md.
        """
        doc = await todos_collection.find_one({"_id": ObjectId(todo_id), "user_id": user_id})
        if not doc or not doc.get("vfs_path"):
            return

        vfs = MongoVFS()
        now = datetime.now(UTC)
        await vfs.append(
            path=f"{doc['vfs_path']}/log.md",
            content=f"\n## {now.isoformat()} [{event_type}]\n- {details}\n",
            user_id=user_id,
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

        vfs = MongoVFS()
        lines = [
            _format_signal_entry(doc, await _extract_canvas_key_details(vfs, doc, user_id))
            for doc in docs
        ]
        return "ACTIVE TRACKED TODOS (check if incoming signal relates to any):\n" + "\n".join(
            lines
        )

    @staticmethod
    async def reindex_canvas(todo_id: str, user_id: str) -> bool:
        """Re-index a todo's canvas.md in ChromaDB after agent writes to it."""
        doc = await todos_collection.find_one({"_id": ObjectId(todo_id), "user_id": user_id})
        if not doc or not doc.get("vfs_path"):
            return False

        vfs = MongoVFS()
        canvas_content = await vfs.read(path=f"{doc['vfs_path']}/canvas.md", user_id=user_id)
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


tracked_todo_service = TrackedTodoService()
