"""
GaiaTask service — CRUD operations and VFS lifecycle for GAIA's
internal working memory.
"""

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from shared.py.wide_events import log

from app.db.mongodb.collections import gaia_tasks_collection
from app.models.gaia_task_models import (
    CreateGaiaTaskRequest,
    GaiaTask,
    GaiaTaskStatus,
    UpdateGaiaTaskRequest,
)
from app.services.vfs.mongo_vfs import MongoVFS


class GaiaTaskService:
    """Manages GaiaTasks: creation, updates, completion, and VFS lifecycle."""

    async def create_task(
        self,
        user_id: str,
        request: CreateGaiaTaskRequest,
        conversation_id: str | None = None,
    ) -> GaiaTask:
        expires_at = None
        if request.expires_in_days:
            expires_at = datetime.now(timezone.utc) + timedelta(
                days=request.expires_in_days
            )

        task = GaiaTask(
            user_id=user_id,
            title=request.title,
            description=request.description,
            primary_conversation_id=conversation_id or request.primary_conversation_id,
            expires_at=expires_at,
        )
        task.vfs_path = f"/users/{user_id}/tasks/{task.task_id}"

        await self._initialize_task_vfs(user_id, task)
        await gaia_tasks_collection.insert_one(task.model_dump())

        log.info(
            "gaia_task.created",
            task_id=task.task_id,
            user_id=user_id,
            title=task.title,
        )
        return task

    async def _initialize_task_vfs(self, user_id: str, task: GaiaTask) -> None:
        """Create the three seed files in the task's VFS directory."""
        vfs = MongoVFS()
        base = task.vfs_path
        now = task.created_at.isoformat()

        await vfs.write(
            path=f"{base}/progress.md",
            content=(
                f"# {task.title}\n\n"
                f"**Status:** {task.status}\n"
                f"**Created:** {now}\n\n"
                f"## What's been done\n\n_Nothing yet._\n\n"
                f"## What's next\n\n_{task.description}_\n"
            ),
            user_id=user_id,
        )

        await vfs.write(
            path=f"{base}/log.md",
            content=(
                f"# Task Log: {task.title}\n\n"
                f"## {now}\n"
                f"- Task created: {task.description}\n"
            ),
            user_id=user_id,
        )

        context: dict[str, Any] = {
            "task_id": task.task_id,
            "title": task.title,
            "status": task.status,
            "created_at": now,
            "active_loop_ids": [],
            "owned_workflow_ids": [],
            "primary_conversation_id": task.primary_conversation_id,
        }
        await vfs.write(
            path=f"{base}/context.json",
            content=json.dumps(context, indent=2),
            user_id=user_id,
        )

    async def get_task(self, task_id: str, user_id: str) -> GaiaTask | None:
        doc = await gaia_tasks_collection.find_one(
            {"task_id": task_id, "user_id": user_id}
        )
        if not doc:
            return None
        doc.pop("_id", None)
        return GaiaTask(**doc)

    async def list_active_tasks(self, user_id: str) -> list[GaiaTask]:
        """Return all non-terminal tasks for a user (max 50)."""
        cursor = gaia_tasks_collection.find(
            {
                "user_id": user_id,
                "status": {
                    "$in": [
                        GaiaTaskStatus.ACTIVE,
                        GaiaTaskStatus.WAITING,
                        GaiaTaskStatus.STALLED,
                        GaiaTaskStatus.ESCALATING,
                    ]
                },
            }
        )
        docs = await cursor.to_list(length=50)
        for doc in docs:
            doc.pop("_id", None)
        return [GaiaTask(**doc) for doc in docs]

    async def get_active_tasks_summary(self, user_id: str) -> str:
        """Formatted one-liner per task for context injection."""
        tasks = await self.list_active_tasks(user_id)
        if not tasks:
            return ""

        now = datetime.now(timezone.utc)
        lines = ["ACTIVE TASKS:"]
        for task in tasks:
            age_days = (now - task.created_at).days
            loop_count = len(task.active_loop_ids)
            lines.append(
                f'  "{task.title}" — {task.status}, '
                f"{age_days}d old, {loop_count} open loop(s)"
            )
        return "\n".join(lines)

    async def update_task(
        self, task_id: str, user_id: str, request: UpdateGaiaTaskRequest
    ) -> GaiaTask | None:
        update: dict[str, Any] = {"updated_at": datetime.now(timezone.utc)}

        if request.status is not None:
            update["status"] = request.status
        if request.active_loop_ids is not None:
            update["active_loop_ids"] = request.active_loop_ids
        if request.owned_workflow_ids is not None:
            update["owned_workflow_ids"] = request.owned_workflow_ids

        result = await gaia_tasks_collection.update_one(
            {"task_id": task_id, "user_id": user_id},
            {"$set": update},
        )

        if result.matched_count == 0:
            return None

        if request.notes:
            task = await self.get_task(task_id, user_id)
            if task:
                vfs = MongoVFS()
                timestamp = datetime.now(timezone.utc).isoformat()
                await vfs.append(
                    path=f"{task.vfs_path}/log.md",
                    content=f"\n## {timestamp}\n- {request.notes}\n",
                    user_id=user_id,
                )

        return await self.get_task(task_id, user_id)

    async def complete_task(
        self, task_id: str, user_id: str, summary: str
    ) -> GaiaTask | None:
        task = await self.get_task(task_id, user_id)
        if not task:
            return None
        assert task.vfs_path is not None, f"Task {task_id} has no vfs_path"

        now = datetime.now(timezone.utc)
        archive_path = task.vfs_path.replace("/tasks/", "/tasks/archive/")
        await gaia_tasks_collection.update_one(
            {"task_id": task_id, "user_id": user_id},
            {
                "$set": {
                    "status": GaiaTaskStatus.COMPLETED,
                    "completed_at": now,
                    "updated_at": now,
                    "vfs_path": archive_path,
                }
            },
        )

        vfs = MongoVFS()
        await vfs.append(
            path=f"{task.vfs_path}/log.md",
            content=f"\n## {now.isoformat()}\n- Task completed: {summary}\n",
            user_id=user_id,
        )
        await vfs.move(source=task.vfs_path, dest=archive_path, user_id=user_id)

        log.info("gaia_task.completed", task_id=task_id, user_id=user_id, summary=summary)
        return await self.get_task(task_id, user_id)

    async def cancel_task(
        self, task_id: str, user_id: str, reason: str
    ) -> GaiaTask | None:
        task = await self.get_task(task_id, user_id)
        if not task:
            return None
        assert task.vfs_path is not None, f"Task {task_id} has no vfs_path"

        now = datetime.now(timezone.utc)
        archive_path = task.vfs_path.replace("/tasks/", "/tasks/archive/")
        await gaia_tasks_collection.update_one(
            {"task_id": task_id, "user_id": user_id},
            {"$set": {"status": GaiaTaskStatus.CANCELLED, "updated_at": now, "vfs_path": archive_path}},
        )

        vfs = MongoVFS()
        await vfs.append(
            path=f"{task.vfs_path}/log.md",
            content=f"\n## {now.isoformat()}\n- Task cancelled: {reason}\n",
            user_id=user_id,
        )
        await vfs.move(source=task.vfs_path, dest=archive_path, user_id=user_id)

        log.info("gaia_task.cancelled", task_id=task_id, user_id=user_id, reason=reason)
        return await self.get_task(task_id, user_id)


gaia_task_service = GaiaTaskService()
