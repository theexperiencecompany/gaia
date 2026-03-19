"""
Tracked-todo LangChain tools for the executor agent.

Allows GAIA's executor to create tracked todos with VFS canvas
and search across canvas context via ChromaDB.
"""

from datetime import datetime
from typing import Annotated, Optional

from bson import ObjectId
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from shared.py.wide_events import log

from app.db.mongodb.collections import todos_collection
from app.models.todo_models import Priority
from app.services.tracked_todo_service import tracked_todo_service
from app.services.vfs.mongo_vfs import MongoVFS
from app.utils.canvas_vector_utils import search_canvas_context


@tool
async def create_tracked_todo(
    config: RunnableConfig,
    title: Annotated[str, "Short title for the tracked todo"],
    description: Annotated[
        str | None,
        "Optional description of what this todo is tracking",
    ] = None,
    initial_canvas: Annotated[
        str | None,
        "Optional initial canvas content (markdown). If omitted, a template is used.",
    ] = None,
    labels: Annotated[
        list[str] | None,
        "Optional labels for categorization (gaia-tracked is added automatically)",
    ] = None,
    priority: Annotated[
        str,
        "Priority: 'high', 'medium', 'low', or 'none'",
    ] = "none",
    scheduled_at: Annotated[
        Optional[str],
        "ISO datetime string when GAIA should execute this todo (e.g., '2026-03-20T09:00:00Z'). If set, GAIA will automatically run this todo at that time.",
    ] = None,
    recurrence: Annotated[
        Optional[str],
        "How often to repeat. Options: 'daily', 'weekly', 'every_4h', or a cron expression. Requires scheduled_at to also be set.",
    ] = None,
    expires_at: Annotated[
        Optional[str],
        "ISO datetime string when this todo becomes irrelevant. "
        "Use for time-sensitive context like 'check if package arrived' (expires in 3 days) "
        "or 'follow up if no reply' (expires in 2 weeks). "
        "Different from due_date: due_date means 'should be done by'; expires_at means 'no longer matters after'.",
    ] = None,
) -> str:
    """
    Create a tracked todo with VFS canvas for persistent working memory.

    Use when work will span multiple conversations, expects external
    responses, or needs future follow-up. The todo gets a VFS directory
    with canvas.md (your brain) and log.md (system audit trail).

    Do NOT use for one-shot actions with no expected follow-up.

    scheduled_at: ISO datetime string when GAIA should execute this todo (e.g., "2026-03-20T09:00:00Z").
                  If set, GAIA will automatically run this todo at that time.
    recurrence: How often to repeat. Options: 'daily', 'weekly', 'every_4h', or a cron expression.
                Requires scheduled_at to also be set.
    expires_at: ISO datetime string when this todo becomes irrelevant regardless of completion.
                Different from due_date: due_date = deadline (overdue = still needs doing),
                expires_at = relevance window (expired = no longer worth tracking).
    """
    user_id = config.get("metadata", {}).get("user_id")
    if not user_id:
        return "Error: user_id not found in config"

    result = await tracked_todo_service.create_tracked_todo(
        user_id=user_id,
        title=title,
        description=description,
        initial_canvas=initial_canvas,
        labels=labels,
        priority=Priority(priority),
    )

    # Store scheduled_at, recurrence, and expires_at on the todo document
    if scheduled_at or recurrence or expires_at:
        update_fields: dict[str, object] = {}
        if scheduled_at:
            update_fields["scheduled_at"] = datetime.fromisoformat(
                scheduled_at.replace("Z", "+00:00")
            )
        if recurrence:
            update_fields["recurrence"] = recurrence
        if expires_at:
            update_fields["expires_at"] = datetime.fromisoformat(
                expires_at.replace("Z", "+00:00")
            )
        await todos_collection.update_one(
            {"_id": ObjectId(result.id)},
            {"$set": update_fields},
        )

    # Schedule execution if requested
    if scheduled_at:
        try:
            parsed_at = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
            await tracked_todo_service.schedule_execution(result.id, parsed_at)
        except Exception as e:
            # Non-fatal — todo was created, scheduling failed
            log.warning(f"Created todo {result.id} but failed to schedule: {e}")

    return (
        f"Tracked todo created: {result.id}\n"
        f"Title: {result.title}\n"
        f"VFS: {result.vfs_path}\n"
        f"Canvas: {result.vfs_path}/canvas.md\n"
        f"Log: {result.vfs_path}/log.md"
    )


@tool
async def search_todo_context(
    config: RunnableConfig,
    query: Annotated[str, "Search query to find relevant tracked todo context"],
    top_k: Annotated[int, "Max results to return"] = 5,
) -> str:
    """
    Semantic search across all tracked todo canvases for the current user.

    Use to find relevant context from existing tracked todos before
    creating a new one or to recall details from past work.
    """
    user_id = config.get("metadata", {}).get("user_id")
    if not user_id:
        return "Error: user_id not found in config"

    matches = await search_canvas_context(
        query=query,
        user_id=user_id,
        top_k=top_k,
    )

    if not matches:
        return "No matching tracked todo context found."

    lines = []
    for m in matches:
        lines.append(
            f"- [{m['title']}] (todo_id: {m['todo_id']}, score: {m['score']})\n"
            f"  {m['snippet'][:200]}"
        )
    return "\n".join(lines)


@tool
async def update_tracked_todo_canvas(
    config: RunnableConfig,
    todo_id: Annotated[str, "ID of the tracked todo"],
    canvas_content: Annotated[str, "Full markdown content to write to canvas.md"],
) -> str:
    """Write updated canvas.md for a tracked todo and re-index in ChromaDB for search.

    Call after every significant action on a tracked todo. Include full canvas content
    (not just the changed section) — Key Details, Current State, Timeline, Context.
    The system log is updated automatically.
    """
    user_id = config.get("metadata", {}).get("user_id")
    if not user_id:
        return "Error: user_id not found in config"

    vfs = MongoVFS()

    doc = await todos_collection.find_one(
        {"_id": ObjectId(todo_id), "user_id": user_id}
    )
    if not doc:
        return f"Error: tracked todo {todo_id} not found"
    vfs_path = doc.get("vfs_path")
    if not vfs_path:
        return f"Error: todo {todo_id} has no vfs_path"

    await vfs.write(
        path=f"{vfs_path}/canvas.md",
        content=canvas_content,
        user_id=user_id,
    )
    await tracked_todo_service.reindex_canvas(todo_id=todo_id, user_id=user_id)
    await tracked_todo_service.system_log(
        todo_id=todo_id,
        user_id=user_id,
        event_type="CANVAS_UPDATED",
        details="Agent updated canvas",
    )
    return "Canvas updated and re-indexed."


@tool
async def complete_tracked_todo(
    config: RunnableConfig,
    todo_id: Annotated[str, "ID of the tracked todo to complete"],
    summary: Annotated[str, "One or two sentences describing what was achieved"],
) -> str:
    """Complete a tracked todo: archive VFS canvas, remove from search index, mark done.

    Call when the todo's goal is fully achieved. Use the regular todo update for
    partial completion or status changes only.
    """
    user_id = config.get("metadata", {}).get("user_id")
    if not user_id:
        return "Error: user_id not found in config"

    success = await tracked_todo_service.complete_tracked_todo(
        todo_id=todo_id, user_id=user_id, summary=summary
    )
    if not success:
        return f"Error: could not complete tracked todo {todo_id} — not found or missing vfs_path"
    return f"Tracked todo {todo_id} completed and archived."


tools = [create_tracked_todo, search_todo_context, update_tracked_todo_canvas, complete_tracked_todo]
