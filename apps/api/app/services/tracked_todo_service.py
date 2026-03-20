"""
Tracked todo service — VFS lifecycle for GAIA's working memory todos.

A tracked todo is a regular todo with:
- vfs_path set to /users/{user_id}/todos/{todo_id}/
- 'gaia-tracked' label
- canvas.md (agent-written brain) indexed in ChromaDB
- log.md (system-written audit trail)
"""

import re
from datetime import datetime, timezone

from bson import ObjectId

from shared.py.wide_events import log

from app.db.mongodb.collections import todos_collection
from app.models.todo_models import Priority, TodoModel, TodoResponse
from app.services.todos.todo_service import TodoService
from app.services.vfs.mongo_vfs import MongoVFS
from app.utils.canvas_vector_utils import (
    mark_canvas_completed,
    search_canvas_context,
    store_canvas_embedding,
    update_canvas_embedding,
)
from app.utils.redis_utils import RedisPoolManager


CANVAS_TEMPLATE = """# {title}

## Key Details
<!-- email addresses, thread IDs, calendar IDs, issue IDs — everything needed to take action -->

## Current State
<!-- what's true RIGHT NOW — updated after every action -->

## Timeline
<!-- chronological list of actions taken and results -->

## Context
<!-- accumulated context from signals, related information, decisions made -->

## Learnings
<!-- written on completion: what worked, what didn't, key decisions, timing insights, optimizations for next time -->
"""

GAIA_TRACKED_LABEL = "gaia-tracked"


class TrackedTodoService:
    """Manages VFS lifecycle for tracked (GAIA working memory) todos."""

    async def create_tracked_todo(
        self,
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
        now = datetime.now(timezone.utc)

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

    async def complete_tracked_todo(
        self, todo_id: str, user_id: str, summary: str
    ) -> bool:
        """Complete a tracked todo: archive VFS, remove from ChromaDB index."""
        doc = await todos_collection.find_one(
            {"_id": ObjectId(todo_id), "user_id": user_id}
        )
        if not doc:
            return False

        # Guard against double-completion (VFS already archived)
        if doc.get("completed"):
            return True

        vfs_path = doc.get("vfs_path")
        if not vfs_path:
            return False

        now = datetime.now(timezone.utc)
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

        # Mark as completed in ChromaDB (keep embedding but mark completed)
        await mark_canvas_completed(todo_id)

        log.info(
            "tracked_todo.completed",
            todo_id=todo_id,
            user_id=user_id,
            summary=summary,
        )
        return True

    async def get_active_tracked_summary(self, user_id: str) -> str:
        """Formatted summary of active tracked todos for context injection."""
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

        now = datetime.now(timezone.utc)
        lines = ["ACTIVE TRACKED TODOS:"]

        for doc in docs:
            age_days = (now - doc.get("created_at", now)).days
            last_update = (now - doc.get("updated_at", now)).days
            labels = [lbl for lbl in doc.get("labels", []) if lbl != GAIA_TRACKED_LABEL]
            labels_str = f" [{', '.join(labels)}]" if labels else ""
            due_str = ""
            if doc.get("due_date"):
                days_until = (doc["due_date"] - now).days
                if days_until < 0:
                    due_str = f" OVERDUE({-days_until}d)"
                else:
                    due_str = f" due({days_until}d)"

            todo_id = str(doc["_id"])
            lines.append(
                f'  "{doc["title"]}"{labels_str}{due_str}'
                f" — {age_days}d old, updated {last_update}d ago"
                f" | ID: {todo_id} | VFS: {doc.get('vfs_path', 'none')}"
            )

        return "\n".join(lines)

    async def system_log(
        self, todo_id: str, user_id: str, event_type: str, details: str
    ) -> None:
        """Append a system log entry to a tracked todo's log.md.

        Called by code (not agent) for audit trail. Agent writes to canvas.md.
        """
        doc = await todos_collection.find_one(
            {"_id": ObjectId(todo_id), "user_id": user_id}
        )
        if not doc or not doc.get("vfs_path"):
            return

        vfs = MongoVFS()
        now = datetime.now(timezone.utc)
        await vfs.append(
            path=f"{doc['vfs_path']}/log.md",
            content=f"\n## {now.isoformat()} [{event_type}]\n- {details}\n",
            user_id=user_id,
        )

    async def get_signal_matching_context(self, user_id: str) -> str:
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
        lines = []

        for doc in docs:
            todo_id = str(doc["_id"])
            title = doc.get("title", "")
            labels = [lbl for lbl in doc.get("labels", []) if lbl != GAIA_TRACKED_LABEL]
            vfs_path = doc.get("vfs_path", "")

            # Try to extract Key Details section from canvas for IDs
            key_details = ""
            if vfs_path:
                try:
                    canvas = await vfs.read(
                        path=f"{vfs_path}/canvas.md", user_id=user_id
                    )
                    if canvas:
                        # Extract Key Details section
                        match = re.search(
                            r"## Key Details\n(.*?)(?=\n## |\Z)",
                            canvas,
                            re.DOTALL,
                        )
                        if match:
                            key_details = match.group(1).strip()
                except Exception as e:
                    log.warning("tracked_todo.canvas_read_failed", todo_id=str(doc["_id"]), error=str(e))

            labels_str = f" [{', '.join(labels)}]" if labels else ""
            entry = f'- "{title}"{labels_str} (ID: {todo_id}, vfs: {vfs_path})'
            if key_details:
                # Indent key details under the todo
                detail_lines = key_details.split("\n")
                for dl in detail_lines[:5]:  # Max 5 detail lines per todo
                    entry += f"\n    {dl.strip()}"

            lines.append(entry)

        return "ACTIVE TRACKED TODOS (check if incoming signal relates to any):\n" + "\n".join(lines)

    async def reindex_canvas(self, todo_id: str, user_id: str) -> bool:
        """Re-index a todo's canvas.md in ChromaDB after agent writes to it."""
        doc = await todos_collection.find_one(
            {"_id": ObjectId(todo_id), "user_id": user_id}
        )
        if not doc or not doc.get("vfs_path"):
            return False

        vfs = MongoVFS()
        canvas_content = await vfs.read(
            path=f"{doc['vfs_path']}/canvas.md", user_id=user_id
        )
        if not canvas_content:
            return False

        return await update_canvas_embedding(
            todo_id=todo_id,
            canvas_content=canvas_content,
            user_id=user_id,
            title=doc.get("title", ""),
            labels=doc.get("labels"),
        )

    async def schedule_execution(self, todo_id: str, scheduled_at: datetime) -> bool:
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

    async def reschedule_execution(
        self, todo_id: str, new_scheduled_at: datetime
    ) -> bool:
        """Cancel any existing ARQ job for this todo and enqueue a new one.

        Note: ARQ does not support cancelling deferred jobs by argument.
        We enqueue a new job; the task itself uses a Redis lock to prevent
        double-execution. This is safe — at most one execution fires per lock window.
        """
        return await self.schedule_execution(todo_id, new_scheduled_at)

    async def archive_tracked_todo(
        self, todo_id: str, user_id: str, reason: str
    ) -> bool:
        """Archive a tracked todo by marking it completed with a system-generated summary.

        Used by maintenance sweep when a todo expires cleanly (no action needed).
        Logs the archival reason to log.md before completing.
        """
        try:
            await self.system_log(
                todo_id, user_id, "auto_archived", f"Archived by maintenance sweep: {reason}"
            )
            return await self.complete_tracked_todo(
                todo_id, user_id, summary=f"Auto-archived: {reason}"
            )
        except Exception as e:
            log.warning("tracked_todo.archive_failed", todo_id=todo_id, error=str(e))
            return False

    async def find_similar_past_work(
        self, query: str, user_id: str, top_k: int = 3
    ) -> list[dict]:
        """Search completed tracked todo canvases for similar past work.

        Returns a list of matches with todo_id, title, score, and snippet.
        Only returns completed todos.
        """
        all_results = await search_canvas_context(
            query=query, user_id=user_id, top_k=top_k * 2, include_completed=True
        )

        completed_results = [r for r in all_results if r.get("completed")]
        return completed_results[:top_k]


tracked_todo_service = TrackedTodoService()
