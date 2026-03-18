"""
Tracked-todo LangChain tools for the executor agent.

Allows GAIA's executor to create tracked todos with VFS canvas
and search across canvas context via ChromaDB.
"""

from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.services.tracked_todo_service import tracked_todo_service
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
) -> str:
    """
    Create a tracked todo with VFS canvas for persistent working memory.

    Use when work will span multiple conversations, expects external
    responses, or needs future follow-up. The todo gets a VFS directory
    with canvas.md (your brain) and log.md (system audit trail).

    Do NOT use for one-shot actions with no expected follow-up.
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
        priority=priority,
    )

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


tools = [create_tracked_todo, search_todo_context]
