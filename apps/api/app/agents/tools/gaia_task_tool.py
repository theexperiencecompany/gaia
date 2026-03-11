"""
GaiaTask agent tools for persistent task registry.

Provides tools for the agent to create, update, complete, and list
persistent tasks that bridge sessions and track multi-step interactions.
"""

from datetime import datetime, timezone
from typing import Annotated, Optional

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.config.loggers import chat_logger as logger
from app.models.gaia_task_models import (
    GaiaTaskCategory,
    GaiaTaskCreate,
    GaiaTaskStatus,
    GaiaTaskUpdate,
)
from app.services.gaia_task_service import GaiaTaskService
from app.utils.chat_utils import get_user_id_from_config


@tool
async def create_gaia_task(
    config: RunnableConfig,
    title: Annotated[str, "Short title for the task (max 200 chars)"],
    waiting_for: Annotated[
        str,
        "What the task is currently waiting for (e.g. 'Aryan's reply with availability')",
    ],
    watched_thread_ids: Annotated[
        Optional[list[str]],
        "Gmail thread IDs to monitor. Get this from the threadId field in send/reply results.",
    ] = None,
    watched_senders: Annotated[
        Optional[list[str]],
        "Recipient email addresses to monitor for replies (lowercase)",
    ] = None,
    category: Annotated[
        Optional[str],
        "Auto-detected if omitted. Override with: meeting_scheduling, email_follow_up, email_thread_tracking, general",
    ] = None,
    description: Annotated[str, "Brief description of the task"] = "",
    expires_in_days: Annotated[
        Optional[int],
        "Days until task auto-expires. None = forever task. Default 14.",
    ] = 14,
) -> str:
    """Create a persistent task to track a multi-step interaction across sessions.
    Use after sending an email that expects a reply, scheduling meetings, or
    starting any interaction requiring 2+ rounds of back-and-forth.

    IMPORTANT: Always include watched_thread_ids (from the email send result's
    threadId field) and/or watched_senders so GAIA can match incoming replies
    to this task automatically.
    """
    user_id = get_user_id_from_config(config)
    if not user_id:
        return "Error: User authentication required"

    try:
        # Extract conversation_id from config
        configurable = config.get("configurable", {})
        conversation_id = configurable.get("thread_id", "")

        # Auto-detect category from title if not provided
        task_category = _infer_category(title, category)

        task_data = GaiaTaskCreate(
            title=title,
            description=description,
            category=task_category,
            created_from_conversation_id=conversation_id,
            watched_thread_ids=watched_thread_ids or [],
            watched_senders=watched_senders or [],
            waiting_for=waiting_for,
            expires_in_days=expires_in_days,
        )

        task = await GaiaTaskService.create_task(user_id, task_data)

        return (
            f"Task created successfully.\n"
            f"- Task ID: {task.id}\n"
            f"- Title: {task.title}\n"
            f"- Category: {task.category.value}\n"
            f"- Task Conversation: {task.task_conversation_id}\n"
            f"- VFS Folder: {task.vfs_folder}\n"
            f"- Waiting for: {task.waiting_for or 'N/A'}\n"
            f"- Expires: {task.expires_at.isoformat() if task.expires_at else 'Never'}"
        )
    except Exception as e:
        logger.error(f"Error creating GaiaTask: {e}")
        return f"Error creating task: {str(e)}"


@tool
async def update_gaia_task(
    config: RunnableConfig,
    task_id: Annotated[str, "The task ID (e.g., gt_abc123)"],
    status: Annotated[
        Optional[str],
        "New status: active, waiting_for_reply, waiting_for_user, completed, cancelled",
    ] = None,
    waiting_for: Annotated[
        Optional[str], "Updated description of what the task is waiting for"
    ] = None,
    last_update: Annotated[
        Optional[str],
        "Summary of what just happened (also appended to progress.md)",
    ] = None,
    add_thread_id: Annotated[
        Optional[str], "A Gmail thread ID to add to the watch list"
    ] = None,
) -> str:
    """Update a task's state after taking action or receiving new information.
    Also writes a progress entry to the task's VFS progress.md."""
    user_id = get_user_id_from_config(config)
    if not user_id:
        return "Error: User authentication required"

    try:
        task_status = None
        if status:
            try:
                task_status = GaiaTaskStatus(status)
            except ValueError:
                return f"Error: Invalid status '{status}'"

        updates = GaiaTaskUpdate(
            status=task_status,
            waiting_for=waiting_for,
            last_update=last_update,
        )

        task = await GaiaTaskService.update_task(task_id, user_id, updates)
        if not task:
            return f"Error: Task {task_id} not found"

        # Add watched thread if provided
        if add_thread_id:
            await GaiaTaskService.add_watched_thread(task_id, user_id, add_thread_id)

        # Append to progress.md if last_update provided
        if last_update:
            try:
                from app.services.vfs import get_vfs

                vfs = await get_vfs()
                progress_entry = (
                    f"- [{datetime.now(timezone.utc).isoformat()}] {last_update}\n"
                )
                await vfs.append(
                    path=f"{task.vfs_folder}/progress.md",
                    content=progress_entry,
                    user_id=user_id,
                )
            except Exception as e:
                logger.warning(f"Failed to append to progress.md: {e}")

        return (
            f"Task {task_id} updated.\n"
            f"- Status: {task.status.value}\n"
            f"- Waiting for: {task.waiting_for or 'N/A'}\n"
            f"- Last update: {task.last_update or 'N/A'}"
        )
    except Exception as e:
        logger.error(f"Error updating GaiaTask: {e}")
        return f"Error updating task: {str(e)}"


@tool
async def complete_gaia_task(
    config: RunnableConfig,
    task_id: Annotated[str, "The task ID to mark as completed"],
) -> str:
    """Mark a task as completed when its goal has been achieved.
    Writes a final summary to context.md."""
    user_id = get_user_id_from_config(config)
    if not user_id:
        return "Error: User authentication required"

    try:
        success = await GaiaTaskService.complete_task(task_id, user_id)
        if not success:
            return f"Error: Task {task_id} not found or already completed"

        # Append completion to progress.md
        try:
            from app.services.vfs import get_vfs

            task = await GaiaTaskService.get_task(task_id, user_id)
            if task:
                vfs = await get_vfs()
                progress_entry = (
                    f"- [{datetime.now(timezone.utc).isoformat()}] Task completed.\n"
                )
                await vfs.append(
                    path=f"{task.vfs_folder}/progress.md",
                    content=progress_entry,
                    user_id=user_id,
                )
        except Exception as e:
            logger.warning(f"Failed to update progress.md on completion: {e}")

        return f"Task {task_id} marked as completed. It will be cleaned up in 7 days."
    except Exception as e:
        logger.error(f"Error completing GaiaTask: {e}")
        return f"Error completing task: {str(e)}"


@tool
async def list_gaia_tasks(
    config: RunnableConfig,
) -> str:
    """List all active tasks with their IDs, status, and waiting_for."""
    user_id = get_user_id_from_config(config)
    if not user_id:
        return "Error: User authentication required"

    try:
        tasks = await GaiaTaskService.list_active_tasks(user_id)
        if not tasks:
            return "No active tasks."

        lines = [f"Active Tasks ({len(tasks)}):"]
        for t in tasks:
            lines.append(
                f'- [{t.category.value}] "{t.title}" | '
                f"status: {t.status.value} | "
                f"waiting for: {t.waiting_for or 'N/A'} | "
                f"task_id: {t.id} | "
                f"conv: {t.task_conversation_id}"
            )
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"Error listing GaiaTasks: {e}")
        return f"Error listing tasks: {str(e)}"


def _infer_category(title: str, explicit_category: Optional[str]) -> GaiaTaskCategory:
    """Auto-detect task category from title if not explicitly provided."""
    if explicit_category:
        try:
            return GaiaTaskCategory(explicit_category)
        except ValueError:
            pass

    title_lower = title.lower()
    if any(kw in title_lower for kw in ("meeting", "schedule", "calendar", "invite")):
        return GaiaTaskCategory.MEETING_SCHEDULING
    if any(
        kw in title_lower for kw in ("follow up", "follow-up", "followup", "check in")
    ):
        return GaiaTaskCategory.EMAIL_FOLLOW_UP
    if any(kw in title_lower for kw in ("track", "monitor", "watch", "thread")):
        return GaiaTaskCategory.EMAIL_THREAD_TRACKING
    if any(kw in title_lower for kw in ("inbox", "triage", "email management")):
        return GaiaTaskCategory.INBOX_MANAGEMENT
    return GaiaTaskCategory.GENERAL


tools = [create_gaia_task, update_gaia_task, complete_gaia_task, list_gaia_tasks]
