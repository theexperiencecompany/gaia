"""
Mem0 LangChain Tools for memory management.

These tools allow agents to store, search, and retrieve memories,
enabling them to maintain context and learn from past interactions.
"""

from typing import Annotated, Dict, Optional

from app.decorators import with_doc
from app.services.memory_service import memory_service
from app.templates.docstrings.memory_tool_docs import (
    ADD_MEMORY,
    SEARCH_MEMORY,
)
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool


@tool
@with_doc(ADD_MEMORY)
async def add_memory(
    config: RunnableConfig,
    content: Annotated[str, "Memory content to store"],
    metadata: Annotated[Optional[Dict], "Additional metadata for the memory"] = None,
) -> str:
    if not config:
        return "Error: Configuration required but not provided"

    metadata = metadata or {}
    user_id = config.get("metadata", {}).get("user_id")

    if not user_id:
        return "Error: User ID is required but not found in configuration"

    memory = await memory_service.store_memory(
        message=content, user_id=user_id, metadata=metadata, async_mode=True
    )

    if not memory:
        return "Failed to store memory"

    # For async mode, return event_id and status from metadata
    mem_metadata = memory.metadata or {}
    event_id = mem_metadata.get("event_id")
    status = mem_metadata.get("status", "unknown")

    if event_id:
        return f"Memory queued for processing (Event ID: {event_id}, Status: {status})"

    # Fallback for sync mode
    return f"Memory stored successfully with ID: {memory.id}"


@tool
@with_doc(SEARCH_MEMORY)
async def search_memory(
    config: RunnableConfig,
    query: Annotated[str, "Query string to search for"],
    limit: Annotated[int, "Maximum number of results to return"] = 5,
) -> str:
    if not config:
        return "Error: Configuration required but not provided"

    user_id = config.get("metadata", {}).get("user_id")

    if not user_id:
        return "Error: User ID is required but not found in configuration"

    results = await memory_service.search_memories(
        query=query, user_id=user_id, limit=limit
    )

    if not results.memories:
        return "No matching memories found"

    # Format the results
    formatted_results = "Found the following memories:\n\n"
    for i, memory in enumerate(results.memories, 1):
        score = (
            f" (score: {memory.relevance_score:.2f})" if memory.relevance_score else ""
        )
        formatted_results += f"{i}. {memory.content}{score}\n\n"

    return formatted_results


tools = [add_memory, search_memory]
