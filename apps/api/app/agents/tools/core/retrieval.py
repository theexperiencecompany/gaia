"""
Tool Retrieval Functions for Agent Tool Discovery & Binding.

This module provides the retrieve_tools function factory that supports:
- Semantic search for tool discovery (query mode)
- Exact tool binding (exact_tool_names mode)
- Namespace filtering for user's connected integrations
- Subagent filtering based on user's connected integrations
"""

import asyncio
from typing import (
    Annotated,
    Any,
    Awaitable,
    Callable,
    List,
    Optional,
    Set,
    TypedDict,
    Union,
)

from app.agents.tools.core.registry import get_tool_registry
from app.config.loggers import langchain_logger as logger
from app.config.oauth_config import OAUTH_INTEGRATIONS, get_integration_by_id
from app.db.chroma.public_integrations_store import search_public_integrations
from app.services.integrations.integration_service import (
    get_user_available_tool_namespaces,
)
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import InjectedStore
from langgraph.store.base import BaseStore, SearchItem


class RetrieveToolsResult(TypedDict):
    """Result from retrieve_tools function."""

    tools_to_bind: list[str]
    response: list[str]


async def _get_user_context(
    user_id: Optional[str],
    tool_space: str,
) -> tuple[Set[str], Set[str], Set[str]]:
    """Get user's available namespaces and connected integrations.

    Returns:
        Tuple of (user_namespaces, connected_integrations, internal_subagents)
    """
    user_namespaces: Set[str] = {tool_space, "general"}
    connected_integrations: Set[str] = set()

    # Internal subagents are always available (core platform features)
    internal_subagents: Set[str] = {
        integration.id
        for integration in OAUTH_INTEGRATIONS
        if integration.managed_by == "internal"
        and integration.subagent_config
        and integration.subagent_config.has_subagent
    }

    if not user_id:
        return user_namespaces, connected_integrations, internal_subagents

    try:
        user_namespaces = await get_user_available_tool_namespaces(user_id)
        raw_connected = user_namespaces - {"general", "subagents"}

        # Filter to only integrations with subagent configurations
        connected_integrations = {
            integration_id
            for integration_id in raw_connected
            if (
                # Platform integrations with subagent config
                (
                    (integ := get_integration_by_id(integration_id))
                    and integ.subagent_config
                    and integ.subagent_config.has_subagent
                )
                # Custom/public integrations (not in platform config)
                or get_integration_by_id(integration_id) is None
            )
        }

        logger.info(f"User {user_id} namespaces: {user_namespaces}")
        logger.info(f"User {user_id} connected subagents: {connected_integrations}")
    except Exception as e:
        logger.warning(f"Failed to get user namespaces: {e}")

    return user_namespaces, connected_integrations, internal_subagents


async def _log_store_diagnostics(store: BaseStore) -> None:
    """Log diagnostic information about store contents."""
    try:
        logger.info("DIAGNOSTIC: Inspecting store namespaces...")

        # Check subagents namespace
        subagents_items = await store.asearch(("subagents",), query="", limit=5)
        logger.info(f"DIAGNOSTIC: Subagents namespace has {len(subagents_items)} items")

        for item in subagents_items[:3]:
            logger.info(
                f"DIAGNOSTIC: Item - key='{item.key}', "
                f"namespace={getattr(item, 'namespace', 'N/A')}"
            )
    except Exception as e:
        logger.warning(f"DIAGNOSTIC: Failed to inspect store: {e}")


def _build_search_tasks(
    store: BaseStore,
    query: str,
    tool_space: str,
    user_namespaces: Set[str],
    include_subagents: bool,
    limit: int,
) -> List[Awaitable[Union[List[SearchItem], List[dict[str, Any]]]]]:
    """Build list of search tasks to execute."""
    search_tasks: List[Awaitable[Union[List[SearchItem], List[dict[str, Any]]]]] = []

    # Search in tool_space
    if tool_space in user_namespaces or tool_space == "general":
        logger.info(f"Adding search for tool_space: {tool_space}")
        search_tasks.append(store.asearch((tool_space,), query=query, limit=limit))

    # Search subagents namespace
    if include_subagents:
        logger.info("Adding search for subagents namespace")
        search_tasks.append(store.asearch(("subagents",), query=query, limit=15))
        search_tasks.append(search_public_integrations(query=query, limit=15))

    return search_tasks


def _process_public_integration_result(
    result: List[dict[str, Any]],
    task_idx: int,
) -> List[dict[str, float]]:
    """Process public integration search results."""
    processed = []

    for item in result:
        integration_id = item.get("integration_id")
        if integration_id:
            subagent_key = f"subagent:{integration_id}"
            processed.append(
                {
                    "id": subagent_key,
                    "score": item.get("relevance_score", 0),
                }
            )

    return processed


def _process_chroma_search_result(
    result: List[SearchItem],
    task_idx: int,
    available_tool_names: Set[str],
    tool_registry,
    include_subagents: bool,
) -> List[dict[str, float]]:
    """Process Chroma store search results."""
    processed = []

    for item in result:
        tool_key = str(item.key)

        # Handle subagent results from subagents namespace
        if hasattr(item, "namespace") and item.namespace == ("subagents",):
            subagent_key = (
                tool_key if tool_key.startswith("subagent:") else f"subagent:{tool_key}"
            )
            processed.append({"id": subagent_key, "score": item.score})
            continue

        # Handle keys with subagent: prefix
        if tool_key.startswith("subagent:"):
            processed.append({"id": tool_key, "score": item.score})
            continue

        # Filter delegated tools in main agent context
        if include_subagents:
            tool_category_name = tool_registry.get_category_of_tool(tool_key)
            if tool_category_name:
                category = tool_registry.get_category(name=tool_category_name)
                if category and category.is_delegated:
                    continue

        # Add regular tools
        if tool_key in available_tool_names:
            processed.append({"id": tool_key, "score": item.score})

    return processed


async def _process_search_results(
    results: List[Any],
    available_tool_names: Set[str],
    tool_registry,
    include_subagents: bool,
) -> List[dict[str, float]]:
    """Process all search results and return unified list."""
    all_results = []

    for idx, result in enumerate(results):
        if isinstance(result, BaseException):
            logger.warning(f"Task {idx}: Search error - {result}")
            continue

        if not result:
            continue

        # Determine result type and process accordingly
        is_public_search = isinstance(result[0], dict)

        if is_public_search:
            processed = _process_public_integration_result(result, idx)
        else:
            processed = _process_chroma_search_result(
                result, idx, available_tool_names, tool_registry, include_subagents
            )

        all_results.extend(processed)

    return all_results


def _deduplicate_and_sort(
    results: List[dict[str, float]],
    limit: int,
) -> List[str]:
    """Remove duplicates, sort by score, and return top results."""
    seen = set()
    unique_results = []

    for r in results:
        if r["id"] not in seen:
            seen.add(r["id"])
            unique_results.append(r)

    unique_results.sort(key=lambda x: x["score"] or 0.0, reverse=True)
    return [str(r["id"]) for r in unique_results[:limit]]


def _inject_available_subagents(
    discovered_tools: List[str],
    internal_subagents: Set[str],
    connected_integrations: Set[str],
    include_subagents: bool,
) -> List[str]:
    """Inject available subagents that user has access to."""
    if not include_subagents:
        return discovered_tools

    seen = set(discovered_tools)
    result = list(discovered_tools)

    # Add internal subagents (always available)
    for integration_id in internal_subagents:
        subagent_key = f"subagent:{integration_id}"
        if subagent_key not in seen:
            result.append(subagent_key)
            seen.add(subagent_key)

    # Add connected integration subagents
    for integration_id in connected_integrations:
        subagent_key = f"subagent:{integration_id}"
        if subagent_key not in seen:
            result.append(subagent_key)
            seen.add(subagent_key)

    return result


def get_retrieve_tools_function(
    tool_space: str = "general",
    include_subagents: bool = True,
    limit: int = 25,
) -> Callable[..., Awaitable[RetrieveToolsResult]]:
    """Get a retrieve_tools function configured for specific context.

    This unified function handles both tool discovery (semantic search) and tool binding.
    - When `query` is provided: Returns tool names for discovery (not bound)
    - When `exact_tool_names` is provided: Binds and returns validated tool names

    Args:
        tool_space: Namespace to search for tools
        include_subagents: Whether to include subagent results in search
        limit: Maximum number of tool results for semantic search

    Returns:
        Configured retrieve_tools coroutine that returns RetrieveToolsResult
    """

    async def retrieve_tools(
        store: Annotated[BaseStore, InjectedStore],
        config: RunnableConfig,
        query: Optional[str] = None,
        exact_tool_names: Optional[list[str]] = None,
    ) -> RetrieveToolsResult:
        """Discover available tools or load specific tools by exact name.

        This is your primary interface to the tool ecosystem. It supports TWO modes:

        —DISCOVERY MODE (query)
        Use natural language to semantically search for relevant tools.

        IMPORTANT BEHAVIOR:
        - Discovery results are LIMITED and NOT exhaustive
        - Not all relevant tools may be returned in a single query
        - Absence of a tool in results does NOT mean it does not exist
        - You are expected to retry with different wording if needed

        You may:
        - Rephrase queries
        - Try broader or narrower intent
        - Use multiple intents in a single query (comma-separated)

        Examples of valid queries:
        - "send email"
        - "email operations"
        - "send email, delete draft"
        - "create pull request, list branches"

        The query is semantic, not keyword-based. Comma-separated intents
        are treated as a single semantic search and are encouraged when
        exploring related capabilities.

        Discovery mode ONLY returns tool names. Tools are NOT loaded.

        —BINDING MODE (exact_tool_names)
        Load tools by their exact names.
        - Use this ONLY after discovery or when exact names are already known
        - Invalid or unknown tool names are ignored
        - Successfully validated tools become available for execution

        —RECOMMENDED WORKFLOW
        1. Call retrieve_tools(query="your intent") to discover tools
        2. Review returned tool names
        3. Retry discovery with alternate queries if needed
        4. Call retrieve_tools(exact_tool_names=[...]) to bind tools
        5. Execute bound tools

        —TOOL NAME FORMATS
        - Regular tools: "GMAIL_SEND_DRAFT", "CREATE_TODO"
        - Subagent tools: "subagent:gmail", "subagent:fb9dfd7e05f8"

        Note:
        - Subagent tools require delegation via the `handoff` tool
        - Discovery may return subagents alongside regular tools

        —ARGS
        query:
            Natural language description of intent for discovery.
            Results are limited and best-effort.
            Retry with different phrasing if needed.

        exact_tool_names:
            Exact tool names to load and bind for execution.

        —RETURNS
        RetrieveToolsResult with:
        - tools_to_bind: tools that are loaded and executable
        - response: tool names discovered or validated

        —EXAMPLES
        1. Find and reply to email (Gmail)
        Discover:
          retrieve_tools(query="find emails, reply to thread")
          → returns ["GMAIL_FETCH_EMAILS", "GMAIL_REPLY_TO_THREAD", ...]
        Bind & Execute:
          retrieve_tools(exact_tool_names=["GMAIL_FETCH_EMAILS","GMAIL_REPLY_TO_THREAD"])
          → GMAIL_FETCH_EMAILS(...) returns email list
          → GMAIL_REPLY_TO_THREAD(...) sends reply

        2. Search, delete, and recreate tasks with subtasks (Todo)
        Discover:
          retrieve_tools(query="search todos, delete task, create with subtasks")
          → returns ["search_todos", "delete_todo", "create_todo", "add_subtask", ...]
        Bind & Execute:
          retrieve_tools(exact_tool_names=["search_todos","delete_todo","create_todo","add_subtask"])
          → search_todos(...) finds matching tasks
          → delete_todo(...) removes old task
          → create_todo(...) creates new task
          → add_subtask(...) adds subtasks
        """

        if not query and not exact_tool_names:
            raise ValueError(
                "Either 'query' (for discovery) or 'exact_tool_names' (for binding) is required."
            )

        tool_registry = await get_tool_registry()
        available_tool_names = tool_registry.get_tool_names()
        logger.info(f"Registry has {len(available_tool_names)} available tools")

        # Get user_id from config
        user_id = config.get("configurable", {}).get("user_id")
        if not user_id:
            logger.warning("retrieve_tools called with NO user_id")

        # BINDING MODE: Validate and bind exact tool names
        if exact_tool_names:
            validated_tool_names = []
            for tool_name in exact_tool_names:
                # Subagent keys don't need binding - pass through for discovery
                if tool_name.startswith("subagent:"):
                    validated_tool_names.append(tool_name)
                elif tool_name in available_tool_names:
                    validated_tool_names.append(tool_name)
            return RetrieveToolsResult(
                tools_to_bind=validated_tool_names,
                response=validated_tool_names,
            )

        # DISCOVERY MODE: Semantic search for tools
        logger.info(
            f"DISCOVERY: query='{query}', user_id={user_id}, "
            f"include_subagents={include_subagents}, tool_space={tool_space}"
        )

        # Get user context
        (
            user_namespaces,
            connected_integrations,
            internal_subagents,
        ) = await _get_user_context(user_id, tool_space)

        logger.info(f"User namespaces: {user_namespaces}")
        logger.info(f"Internal subagents (always available): {internal_subagents}")

        # Run diagnostics
        await _log_store_diagnostics(store)

        # Build and execute search tasks
        search_tasks = _build_search_tasks(
            store, query or "", tool_space, user_namespaces, include_subagents, limit
        )

        logger.info(f"Executing {len(search_tasks)} search tasks")
        results = await asyncio.gather(*search_tasks, return_exceptions=True)
        logger.info(f"Got {len(results)} search results")

        # Process results
        all_results = await _process_search_results(
            results, set(available_tool_names), tool_registry, include_subagents
        )

        # Deduplicate and sort
        discovered_tools = _deduplicate_and_sort(all_results, limit)

        # Inject available subagents
        final_tools = _inject_available_subagents(
            discovered_tools,
            internal_subagents,
            connected_integrations,
            include_subagents,
        )

        logger.info(f"Final discovered tools ({len(final_tools)}): {final_tools}")
        return RetrieveToolsResult(
            tools_to_bind=[],
            response=final_tools,
        )

    return retrieve_tools
