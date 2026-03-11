"""
GaiaTask service for persistent task registry.

Handles CRUD operations, trigger matching, task activation,
VFS initialization, and Redis caching for GaiaTasks.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

from app.config.loggers import general_logger as logger
from app.db.mongodb.collections import gaia_tasks_collection
from app.db.redis import delete_cache, get_cache, set_cache
from app.models.chat_models import SystemPurpose
from app.models.gaia_task_models import (
    GaiaTask,
    GaiaTaskCreate,
    GaiaTaskStatus,
    GaiaTaskUpdate,
)

ACTIVE_TASKS_CACHE_PREFIX = "gaia_tasks:active"
ACTIVE_TASKS_CACHE_TTL = 60


class GaiaTaskService:
    @staticmethod
    async def create_task(user_id: str, task_data: GaiaTaskCreate) -> GaiaTask:
        task_id = f"gt_{uuid4().hex[:12]}"
        task_conversation_id = str(uuid4())
        vfs_folder = f"/gaia/tasks/{task_id}"

        # Create dedicated conversation for this task
        from app.services.conversation_service import create_system_conversation

        await create_system_conversation(
            user_id=user_id,
            description=f"Task: {task_data.title}",
            system_purpose=SystemPurpose.TASK_EXECUTION,
            conversation_id=task_conversation_id,
        )

        # Calculate expiration
        expires_at = None
        if task_data.expires_in_days is not None:
            expires_at = datetime.now(timezone.utc) + timedelta(
                days=task_data.expires_in_days
            )

        now = datetime.now(timezone.utc)

        task = GaiaTask(
            id=task_id,
            user_id=user_id,
            title=task_data.title,
            description=task_data.description,
            category=task_data.category,
            status=GaiaTaskStatus.ACTIVE,
            task_conversation_id=task_conversation_id,
            created_from_conversation_id=task_data.created_from_conversation_id,
            vfs_folder=vfs_folder,
            watched_thread_ids=task_data.watched_thread_ids,
            watched_senders=[s.lower() for s in task_data.watched_senders],
            waiting_for=task_data.waiting_for,
            created_at=now,
            updated_at=now,
            expires_at=expires_at,
        )

        # Initialize VFS folder
        await GaiaTaskService._init_vfs_folder(user_id, task)

        # Insert into MongoDB
        task_dict = task.model_dump()
        task_dict["_id"] = task_id
        await gaia_tasks_collection.insert_one(task_dict)

        # Create indexes (idempotent)
        await GaiaTaskService._ensure_indexes()

        # Invalidate cache
        await GaiaTaskService._invalidate_cache(user_id)

        logger.info(f"Created GaiaTask {task_id} for user {user_id}: {task_data.title}")
        return task

    @staticmethod
    async def _init_vfs_folder(user_id: str, task: GaiaTask) -> None:
        from app.services.vfs import get_vfs

        vfs = await get_vfs()

        initial_context = (
            f"# Task: {task.title}\n\n"
            f"## Description\n{task.description}\n\n"
            f"## Current State\n"
            f"Status: {task.status.value}\n"
            f"Category: {task.category.value}\n"
            f"Waiting for: {task.waiting_for or 'N/A'}\n"
            f"Created: {task.created_at.isoformat()}\n\n"
            f"## Key Information\n"
            f"(Agent will update this section as the task progresses)\n"
        )

        initial_progress = (
            f"# Progress Log: {task.title}\n\n"
            f"- [{task.created_at.isoformat()}] Task created."
            f" {task.waiting_for or ''}\n"
        )

        await vfs.write(
            path=f"{task.vfs_folder}/context.md",
            content=initial_context,
            user_id=user_id,
        )
        await vfs.write(
            path=f"{task.vfs_folder}/progress.md",
            content=initial_progress,
            user_id=user_id,
        )

    @staticmethod
    async def _ensure_indexes() -> None:
        try:
            await gaia_tasks_collection.create_index([("user_id", 1), ("status", 1)])
            await gaia_tasks_collection.create_index(
                [("user_id", 1), ("watched_thread_ids", 1)]
            )
            await gaia_tasks_collection.create_index(
                [("user_id", 1), ("watched_senders", 1)]
            )
            await gaia_tasks_collection.create_index("expires_at", expireAfterSeconds=0)
        except Exception as e:
            logger.debug(f"Index creation (may already exist): {e}")

    @staticmethod
    async def get_task(task_id: str, user_id: str) -> Optional[GaiaTask]:
        doc = await gaia_tasks_collection.find_one({"_id": task_id, "user_id": user_id})
        if not doc:
            return None
        doc["id"] = doc.pop("_id")
        return GaiaTask(**doc)

    @staticmethod
    async def update_task(
        task_id: str, user_id: str, updates: GaiaTaskUpdate
    ) -> Optional[GaiaTask]:
        update_dict = updates.model_dump(exclude_none=True)
        if not update_dict:
            return await GaiaTaskService.get_task(task_id, user_id)

        update_dict["updated_at"] = datetime.now(timezone.utc)

        result = await gaia_tasks_collection.find_one_and_update(
            {"_id": task_id, "user_id": user_id},
            {"$set": update_dict},
            return_document=True,
        )

        if result:
            await GaiaTaskService._invalidate_cache(user_id)
            result["id"] = result.pop("_id")
            return GaiaTask(**result)
        return None

    @staticmethod
    async def complete_task(task_id: str, user_id: str) -> bool:
        result = await gaia_tasks_collection.update_one(
            {"_id": task_id, "user_id": user_id},
            {
                "$set": {
                    "status": GaiaTaskStatus.COMPLETED,
                    "updated_at": datetime.now(timezone.utc),
                    "expires_at": datetime.now(timezone.utc) + timedelta(days=7),
                }
            },
        )
        if result.modified_count > 0:
            await GaiaTaskService._invalidate_cache(user_id)
            return True
        return False

    @staticmethod
    async def cancel_task(task_id: str, user_id: str) -> bool:
        result = await gaia_tasks_collection.update_one(
            {"_id": task_id, "user_id": user_id},
            {
                "$set": {
                    "status": GaiaTaskStatus.CANCELLED,
                    "updated_at": datetime.now(timezone.utc),
                    "expires_at": datetime.now(timezone.utc) + timedelta(days=7),
                }
            },
        )
        if result.modified_count > 0:
            await GaiaTaskService._invalidate_cache(user_id)
            return True
        return False

    @staticmethod
    async def list_active_tasks(user_id: str) -> list[GaiaTask]:
        cache_key = f"{ACTIVE_TASKS_CACHE_PREFIX}:{user_id}"
        cached = await get_cache(cache_key)
        if cached is not None:
            return [GaiaTask(**t) for t in cached]

        active_statuses = [
            GaiaTaskStatus.ACTIVE,
            GaiaTaskStatus.WAITING_FOR_REPLY,
            GaiaTaskStatus.WAITING_FOR_USER,
        ]

        cursor = (
            gaia_tasks_collection.find(
                {"user_id": user_id, "status": {"$in": active_statuses}}
            )
            .sort("updated_at", -1)
            .limit(10)
        )

        tasks = []
        async for doc in cursor:
            doc["id"] = doc.pop("_id")
            tasks.append(GaiaTask(**doc))

        await set_cache(
            cache_key,
            [t.model_dump(mode="json") for t in tasks],
            ttl=ACTIVE_TASKS_CACHE_TTL,
        )
        return tasks

    @staticmethod
    async def find_matching_tasks(
        user_id: str,
        thread_id: Optional[str],
        sender_email: Optional[str],
    ) -> list[GaiaTask]:
        active_statuses = [
            GaiaTaskStatus.ACTIVE,
            GaiaTaskStatus.WAITING_FOR_REPLY,
        ]

        or_conditions = []
        if thread_id:
            or_conditions.append({"watched_thread_ids": thread_id})
        if sender_email:
            or_conditions.append({"watched_senders": sender_email.lower()})

        if not or_conditions:
            return []

        query = {
            "user_id": user_id,
            "status": {"$in": active_statuses},
            "$or": or_conditions,
        }

        tasks = []
        async for doc in gaia_tasks_collection.find(query):
            doc["id"] = doc.pop("_id")
            tasks.append(GaiaTask(**doc))
        return tasks

    @staticmethod
    async def add_watched_thread(task_id: str, user_id: str, thread_id: str) -> bool:
        result = await gaia_tasks_collection.update_one(
            {"_id": task_id, "user_id": user_id},
            {
                "$addToSet": {"watched_thread_ids": thread_id},
                "$set": {"updated_at": datetime.now(timezone.utc)},
            },
        )
        if result.modified_count > 0:
            await GaiaTaskService._invalidate_cache(user_id)
            return True
        return False

    @staticmethod
    async def activate_task(
        task: GaiaTask,
        user_id: str,
        trigger_event: dict,
    ) -> str:
        from app.agents.core.agent import call_agent_silent
        from app.models.message_models import MessageRequestWithHistory
        from app.services.model_service import get_user_selected_model
        from app.services.user_service import get_user_by_id
        from app.services.vfs import get_vfs

        try:
            vfs = await get_vfs()
            context_content = await vfs.read(
                path=f"{task.vfs_folder}/context.md",
                user_id=user_id,
            )
            context_content = context_content or "(No prior context)"
        except Exception as e:
            logger.warning(f"Failed to read task context: {e}")
            context_content = "(Failed to load context)"

        trigger_summary = _format_trigger_event(trigger_event)

        activation_msg = (
            f"[Task Activation] A new event occurred for your task '{task.title}'.\n\n"
            f"## Trigger Event\n{trigger_summary}\n\n"
            f"## Current Task State\n{context_content}\n\n"
            f"Review this update. Update {task.vfs_folder}/context.md with the new state. "
            f"Append a progress entry to {task.vfs_folder}/progress.md. "
            f"If the task goal is achieved, call complete_gaia_task."
        )

        request = MessageRequestWithHistory(
            message=activation_msg,
            messages=[],
            fileIds=[],
            fileData=[],
        )

        try:
            user_data = await get_user_by_id(user_id)
            if user_data:
                user_data["user_id"] = user_id
            else:
                user_data = {"user_id": user_id}
        except Exception:
            user_data = {"user_id": user_id}

        from zoneinfo import ZoneInfo

        user_tz = ZoneInfo(user_data.get("timezone", "UTC") if user_data else "UTC")
        user_time = datetime.now(user_tz)

        user_model_config = None
        try:
            user_model_config = await get_user_selected_model(user_id)
        except Exception:
            pass

        from langchain_core.callbacks import UsageMetadataCallbackHandler

        complete_message, _ = await call_agent_silent(
            request=request,
            conversation_id=task.task_conversation_id,
            user=user_data,
            user_time=user_time,
            user_model_config=user_model_config,
            trigger_context={"type": "task_activation", "task_id": task.id},
            usage_metadata_callback=UsageMetadataCallbackHandler(),
        )

        # Send WebSocket notification
        try:
            from app.core.websocket_manager import get_websocket_manager

            websocket_manager = get_websocket_manager()
            await websocket_manager.broadcast_to_user(
                user_id,
                {
                    "type": "task.activated",
                    "task_id": task.id,
                    "task_title": task.title,
                    "conversation_id": task.task_conversation_id,
                },
            )
        except Exception as e:
            logger.warning(f"Failed to send task activation WebSocket: {e}")

        logger.info(f"Task {task.id} activated for user {user_id}")
        return complete_message

    @staticmethod
    async def _invalidate_cache(user_id: str) -> None:
        cache_key = f"{ACTIVE_TASKS_CACHE_PREFIX}:{user_id}"
        await delete_cache(cache_key)


def _format_trigger_event(event: dict) -> str:
    parts = []
    if event.get("type"):
        parts.append(f"Type: {event['type']}")
    if event.get("sender"):
        parts.append(f"From: {event['sender']}")
    if event.get("subject"):
        parts.append(f"Subject: {event['subject']}")
    if event.get("summary"):
        parts.append(f"Summary: {event['summary']}")
    if event.get("thread_id"):
        parts.append(f"Thread ID: {event['thread_id']}")
    return "\n".join(parts) if parts else "No details available"
