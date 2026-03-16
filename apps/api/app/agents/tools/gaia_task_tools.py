"""
GaiaTask LangChain tools for the executor agent.

Allows GAIA's executor to create, update, read, complete, and cancel
persistent multi-step tasks backed by VFS working memory.
"""

from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.models.gaia_task_models import (
    CreateGaiaTaskRequest,
    GaiaTaskStatus,
    UpdateGaiaTaskRequest,
)
from app.services.gaia_task_service import gaia_task_service
from app.services.vfs.mongo_vfs import MongoVFS


@tool
async def create_gaia_task(
    config: RunnableConfig,
    title: Annotated[str, "Short title for the task, e.g. 'Schedule meeting with Rahul'"],
    description: Annotated[str, "What this task is tracking and what outcome is expected"],
    expires_in_days: Annotated[
        int | None,
        "Days until this task expires if not resolved. Default 30. Pass None for permanent tasks.",
    ] = 30,
) -> str:
    """
    Create a persistent GaiaTask to track multi-step work that unfolds across
    time or channels. Use when a request expects a response (e.g. sent an email
    and waiting for reply), involves multiple steps, or needs monitoring over time.

    Do NOT use for one-shot actions with no expected follow-up.
    """
    user_id = config.get("metadata", {}).get("user_id")
    conversation_id = config.get("metadata", {}).get("thread_id")
    if not user_id:
        return "Error: user_id not found in config"

    request = CreateGaiaTaskRequest(
        title=title,
        description=description,
        expires_in_days=expires_in_days,
    )
    task = await gaia_task_service.create_task(
        user_id=user_id,
        request=request,
        conversation_id=conversation_id,
    )
    return (
        f"GaiaTask created: {task.task_id}\n"
        f"Title: {task.title}\n"
        f"VFS: {task.vfs_path}\n"
        f"Expires: {task.expires_at}"
    )


@tool
async def update_gaia_task(
    config: RunnableConfig,
    task_id: Annotated[str, "ID of the GaiaTask to update"],
    notes: Annotated[
        str | None,
        "Progress notes to append to the task log. Describe what just happened.",
    ] = None,
    status: Annotated[
        str | None,
        "New status: 'active' | 'waiting' | 'stalled'. Leave None to keep current.",
    ] = None,
) -> str:
    """
    Update a GaiaTask's status and append notes to its log. Call after taking
    any action related to the task (e.g. sent a follow-up, received a reply,
    made a decision).

    Valid statuses: 'active', 'waiting', 'stalled'. Do NOT use this tool to
    complete or cancel a task — use complete_gaia_task or cancel_gaia_task instead.
    """
    user_id = config.get("metadata", {}).get("user_id")
    if not user_id:
        return "Error: user_id not found in config"

    if status:
        try:
            parsed_status = GaiaTaskStatus(status)
        except ValueError:
            return f"Invalid status '{status}'. Valid transitional values: active, waiting, stalled"
        if parsed_status in (GaiaTaskStatus.COMPLETED, GaiaTaskStatus.CANCELLED, GaiaTaskStatus.EXPIRED):
            return f"Use complete_gaia_task or cancel_gaia_task to set status to '{status}'"
    else:
        parsed_status = None

    request = UpdateGaiaTaskRequest(
        notes=notes,
        status=parsed_status,
    )
    task = await gaia_task_service.update_task(
        task_id=task_id, user_id=user_id, request=request
    )
    if not task:
        return f"Task {task_id} not found"
    return f"Task updated: {task.task_id} — status: {task.status}"


@tool
async def complete_gaia_task(
    config: RunnableConfig,
    task_id: Annotated[str, "ID of the GaiaTask to complete"],
    summary: Annotated[str, "What was achieved — one or two sentences"],
) -> str:
    """
    Mark a GaiaTask as completed. Call when the task's goal has been fully
    achieved. Archives the VFS directory.
    """
    user_id = config.get("metadata", {}).get("user_id")
    if not user_id:
        return "Error: user_id not found in config"

    task = await gaia_task_service.complete_task(
        task_id=task_id, user_id=user_id, summary=summary
    )
    if not task:
        return f"Task {task_id} not found"
    return f"Task completed: {task.task_id} — {summary}"


@tool
async def cancel_gaia_task(
    config: RunnableConfig,
    task_id: Annotated[str, "ID of the GaiaTask to cancel"],
    reason: Annotated[str, "Why the task is being cancelled"],
) -> str:
    """
    Cancel a GaiaTask. Use when the user says to stop tracking something or
    the task is no longer relevant. Archives the VFS directory.
    """
    user_id = config.get("metadata", {}).get("user_id")
    if not user_id:
        return "Error: user_id not found in config"

    task = await gaia_task_service.cancel_task(
        task_id=task_id, user_id=user_id, reason=reason
    )
    if not task:
        return f"Task {task_id} not found"
    return f"Task cancelled: {task.task_id}"


@tool
async def list_gaia_tasks(
    config: RunnableConfig,
) -> str:
    """
    List all active GaiaTasks for the current user. Returns task IDs, titles,
    statuses, and open loop counts. Check this before creating a new task to
    avoid duplicates.
    """
    user_id = config.get("metadata", {}).get("user_id")
    if not user_id:
        return "Error: user_id not found in config"

    tasks = await gaia_task_service.list_active_tasks(user_id)
    if not tasks:
        return "No active tasks."

    lines = []
    for task in tasks:
        lines.append(
            f"- {task.task_id}: \"{task.title}\" [{task.status}]"
            f" — {len(task.active_loop_ids)} open loop(s)"
        )
    return "\n".join(lines)


@tool
async def read_task_vfs(
    config: RunnableConfig,
    task_id: Annotated[str, "ID of the GaiaTask"],
    path: Annotated[
        str,
        "File path within the task directory. Examples: 'progress.md', 'log.md', "
        "'context.json', 'inbox/reply_1.json'. Relative to the task VFS root.",
    ],
) -> str:
    """
    Read a file from a GaiaTask's VFS directory for detailed context.
    Start with 'progress.md' for a summary, 'log.md' for history,
    'context.json' for structured state.
    """
    user_id = config.get("metadata", {}).get("user_id")
    if not user_id:
        return "Error: user_id not found in config"

    task = await gaia_task_service.get_task(task_id=task_id, user_id=user_id)
    if not task:
        return f"Task {task_id} not found"

    vfs = MongoVFS()
    full_path = f"{task.vfs_path}/{path.lstrip('/')}"
    content = await vfs.read(path=full_path, user_id=user_id)
    if content is None:
        return f"File not found: {path}"
    return content


tools = [
    create_gaia_task,
    update_gaia_task,
    complete_gaia_task,
    cancel_gaia_task,
    list_gaia_tasks,
    read_task_vfs,
]
