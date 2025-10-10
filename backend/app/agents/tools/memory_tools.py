"""
Mem0 LangChain Tools for memory management.

These tools allow agents to store, search, and retrieve memories,
enabling them to maintain context and learn from past interactions.
"""

from typing import Annotated, Dict, Optional

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.templates.docstrings.memory_tool_docs import (
    ADD_MEMORY,
    SEARCH_MEMORY,
    GET_ALL_MEMORY,
)
from app.decorators import with_doc
from app.services.memory_service import memory_service


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
        content=content, user_id=user_id, metadata=metadata
    )

    if not memory:
        return "Failed to store memory"

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


@tool
@with_doc(GET_ALL_MEMORY)
async def get_all_memory(
    config: RunnableConfig,
) -> str:
    if not config:
        return "Error: Configuration required but not provided"

    user_id = config.get("metadata", {}).get("user_id")

    if not user_id:
        return "Error: User ID is required but not found in configuration"

    results = await memory_service.get_all_memories(user_id=user_id)

    if not results.memories:
        return "No memories found"

    # Format the results
    formatted_results = f"All memories (total: {results.total_count}):\n\n"

    for i, memory in enumerate(results.memories, 1):
        formatted_results += f"{i}. {memory.content}\n\n"

    return formatted_results


tools = [add_memory, search_memory, get_all_memory]
