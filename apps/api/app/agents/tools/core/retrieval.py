"""
Tool Retrieval Functions for Agent Tool Discovery & Binding.

This module provides the retrieve_tools function factory that supports:
- Semantic search for tool discovery (query mode)
- Exact tool binding (exact_tool_names mode)
- Namespace filtering for user's connected integrations
- Subagent filtering based on user's connected integrations
"""

import asyncio
from typing import Annotated, Awaitable, Callable, Optional, TypedDict

from app.agents.tools.core.registry import get_tool_registry
from app.config.loggers import langchain_logger as logger
from app.config.oauth_config import OAUTH_INTEGRATIONS, get_integration_by_id
from app.db.mongodb.collections import integrations_collection
from app.services.integrations.integration_service import (
    get_user_available_tool_namespaces,
)
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import InjectedStore
from langgraph.store.base import BaseStore


def _format_subagent_key(integration_id: str, name: str | None = None) -> str:
    """Format subagent key for tool retrieval.

    Format: 'subagent:{id}' or 'subagent:{id} ({name})' when name differs.
    ID comes first for easy extraction, name provides LLM readability.

    Args:
        integration_id: The integration ID (e.g., 'gmail' or 'fb9dfd7e05f8')
        name: Human-readable name for display (e.g., 'Semantic Scholar')

    Returns:
        Formatted key like 'subagent:gmail' or 'subagent:fb9dfd7e05f8 (Semantic Scholar)'
    """
    if name and name.lower() != integration_id.lower():
        return f"subagent:{integration_id} ({name})"
    return f"subagent:{integration_id}"


async def _get_custom_integration_names(
    integration_ids: set[str],
) -> dict[str, str]:
    """Fetch names for custom integrations from MongoDB.

    Args:
        integration_ids: Set of integration IDs to look up

    Returns:
        Dict mapping integration_id -> name
    """
    if not integration_ids:
        return {}

    # Filter to only non-platform integrations (custom/public)
    custom_ids = {iid for iid in integration_ids if get_integration_by_id(iid) is None}

    if not custom_ids:
        return {}

    # Batch fetch from MongoDB
    cursor = integrations_collection.find(
        {"integration_id": {"$in": list(custom_ids)}},
        {"integration_id": 1, "name": 1},
    )

    result = {}
    async for doc in cursor:
        integration_id = doc["integration_id"]
        result[integration_id] = doc.get("name") or integration_id

    return result


class RetrieveToolsResult(TypedDict):
    """Result from retrieve_tools function."""

    tools_to_bind: list[str]
    response: list[str]


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
        query: Optional[str] = None,
        exact_tool_names: Optional[list[str]] = None,
        config: Optional[RunnableConfig] = None,
        user_id: Optional[str] = None,
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

        # Get user_id from explicit arg OR config
        if not user_id and config:
            user_id = config.get("configurable", {}).get("user_id")
            # Deep debugging for missing user_id
            if not user_id:
                logger.info(f"retrieve_tools config keys: {list(config.keys())}")
                logger.info(
                    f"retrieve_tools configurable: {config.get('configurable', {})}"
                )

        if not user_id:
            logger.warning("retrieve_tools called with NO user_id (arg or config)")

        # BINDING MODE: Validate and bind exact tool names
        if exact_tool_names:
            validated_tool_names = []
            for tool_name in exact_tool_names:
                # Subagent keys (e.g., "subagent:gmail", "subagent:fb9dfd7e05f8")
                # are not in the tool registry - they're used with the handoff tool
                # and don't need binding. Pass them through for discovery response.
                if tool_name.startswith("subagent:"):
                    validated_tool_names.append(tool_name)
                elif tool_name in available_tool_names:
                    validated_tool_names.append(tool_name)
            return RetrieveToolsResult(
                tools_to_bind=validated_tool_names,
                response=validated_tool_names,
            )

        # DISCOVERY MODE: Semantic search for tools
        # Get user's connected integration namespaces for filtering
        user_namespaces: set[str] = {tool_space, "general"}
        connected_integrations: set[str] = set()

        # Internal subagents (like todos) are ALWAYS available - they're core platform features
        # NOT integrations that need connecting. Only external integrations require UI connection.
        internal_subagents: set[str] = {
            integration.id
            for integration in OAUTH_INTEGRATIONS
            if integration.managed_by == "internal"
            and integration.subagent_config
            and integration.subagent_config.has_subagent
        }

        logger.info(
            f"retrieve_tools DISCOVERY: query='{query}', user_id={user_id}, "
            f"include_subagents={include_subagents}, tool_space={tool_space}"
        )
        logger.info(f"Internal subagents (always available): {internal_subagents}")

        if user_id:
            try:
                user_namespaces = await get_user_available_tool_namespaces(user_id)
                # Extract connected integrations (excluding general and subagents)
                raw_connected = user_namespaces - {"general", "subagents"}

                # Filter to only integrations that have subagent configurations
                # OR are custom/public integrations (which are always subagent-capable)
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
                        # Custom/public integrations: anything not in platform config
                        # is a custom integration (from MongoDB) and is subagent-capable
                        or get_integration_by_id(integration_id) is None
                    )
                }

                logger.info(f"User {user_id} namespaces: {user_namespaces}")
                logger.info(f"User {user_id} raw connected: {raw_connected}")
                logger.info(
                    f"User {user_id} connected subagent integrations: {connected_integrations}"
                )
            except Exception as e:
                logger.warning(f"Failed to get user namespaces: {e}")
                # Fall back to general search

        # Build search tasks - only search general + subagents
        # Individual integration tools are accessed via handoff to subagents
        search_tasks = []

        # Search in tool_space (general for main agent, or specific space for subagent)
        if tool_space in user_namespaces or tool_space == "general":
            search_tasks.append(store.asearch((tool_space,), query=query, limit=limit))

        # Include subagents search for main agent context
        if include_subagents:
            search_tasks.append(store.asearch(("subagents",), query=query, limit=15))

        # Execute all searches
        if search_tasks:
            results = await asyncio.gather(*search_tasks, return_exceptions=True)
        else:
            results = []

        all_results = []
        subagent_names: dict[str, str] = {}  # integration_id -> name

        for result in results:
            if isinstance(result, BaseException):
                logger.warning(f"Search error: {result}")
                continue
            # result is now known to be list[SearchItem]
            for item in result:
                tool_key = str(item.key)

                # Check if this is a subagent result from the subagents namespace
                # (key won't have 'subagent:' prefix, it's just the integration_id)
                if hasattr(item, "namespace") and item.namespace == ("subagents",):
                    integration_id = tool_key
                    # Check if user has access
                    if (
                        integration_id not in connected_integrations
                        and integration_id not in internal_subagents
                    ):
                        logger.debug(
                            f"Filtering out subagent {integration_id} - user not connected"
                        )
                        continue
                    # Extract name from search result value
                    if hasattr(item, "value") and isinstance(item.value, dict):
                        subagent_names[integration_id] = item.value.get(
                            "name", integration_id
                        )
                    # Format as subagent key with name
                    formatted_key = _format_subagent_key(
                        integration_id, subagent_names.get(integration_id)
                    )
                    all_results.append({"id": formatted_key, "score": item.score})
                    continue

                # Filter subagents with prefix (legacy format)
                if tool_key.startswith("subagent:"):
                    integration_id = tool_key.replace("subagent:", "")
                    # Internal subagents (todos) always pass, others need connection
                    if (
                        integration_id not in connected_integrations
                        and integration_id not in internal_subagents
                    ):
                        logger.debug(
                            f"Filtering out {tool_key} - user not connected to {integration_id}"
                        )
                        continue
                    # Extract name from search result value for display
                    if hasattr(item, "value") and isinstance(item.value, dict):
                        subagent_names[integration_id] = item.value.get(
                            "name", integration_id
                        )
                    all_results.append({"id": tool_key, "score": item.score})
                    continue

                # Filter out tools from delegated categories ONLY in main agent context
                # When include_subagents=False, we're inside a subagent and should
                # NOT filter out delegated tools (the subagent needs its own tools)
                if include_subagents:
                    tool_category_name = tool_registry.get_category_of_tool(tool_key)
                    if tool_category_name:
                        category = tool_registry.get_category(name=tool_category_name)
                        if category and category.is_delegated:
                            logger.debug(
                                f"Filtering out {tool_key} - delegated category {tool_category_name}"
                            )
                            continue

                # Include if it's in available tools
                if tool_key in available_tool_names:
                    all_results.append({"id": tool_key, "score": item.score})

        # Remove duplicates and sort by score
        seen = set()
        unique_results = []
        for r in all_results:
            if r["id"] not in seen:
                seen.add(r["id"])
                unique_results.append(r)

        # Always inject available subagents that user has access to
        # This ensures subagents appear regardless of semantic match quality
        if include_subagents:
            # Fetch names for custom integrations that weren't in search results
            custom_integration_names = await _get_custom_integration_names(
                connected_integrations
            )
            # Merge with names from search results
            subagent_names.update(custom_integration_names)

            # Add internal subagents (always available - not integrations)
            for integration_id in internal_subagents:
                # Get name from platform integration
                integ = get_integration_by_id(integration_id)
                name = integ.name if integ else integration_id
                subagent_key = _format_subagent_key(integration_id, name)
                if subagent_key not in seen:
                    seen.add(subagent_key)
                    unique_results.append({"id": subagent_key, "score": 0.5})

            # Add connected integration subagents
            for integration_id in connected_integrations:
                # Get name from platform or custom integration
                integ = get_integration_by_id(integration_id)
                if integ:
                    name = integ.name
                else:
                    name = subagent_names.get(integration_id, integration_id)
                subagent_key = _format_subagent_key(integration_id, name)
                if subagent_key not in seen:
                    seen.add(subagent_key)
                    unique_results.append({"id": subagent_key, "score": 0.5})

        unique_results.sort(key=lambda x: x["score"] or 0.0, reverse=True)

        discovered_tools: list[str] = [str(r["id"]) for r in unique_results[:limit]]
        return RetrieveToolsResult(
            tools_to_bind=[],
            response=discovered_tools,
        )

    return retrieve_tools
