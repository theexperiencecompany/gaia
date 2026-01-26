"""
Tool Retrieval Functions for Agent Tool Discovery & Binding.

This module provides the retrieve_tools function factory that supports:
- Semantic search for tool discovery (query mode)
- Exact tool binding (exact_tool_names mode)
- Namespace filtering for user's connected integrations
- Subagent filtering based on user's connected integrations
"""

import asyncio
from typing import Annotated, Any, Awaitable, Callable, List, Optional, TypedDict, Union

from app.agents.tools.core.registry import get_tool_registry
from app.config.loggers import langchain_logger as logger
from app.config.oauth_config import OAUTH_INTEGRATIONS, get_integration_by_id
from app.db.chroma.public_integrations_store import search_public_integrations
from app.services.integrations.integration_service import (
    get_user_available_tool_namespaces,
)
from app.utils.agent_utils import parse_subagent_id
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import InjectedStore
from langgraph.store.base import BaseStore, SearchItem


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
        search_tasks: List[
            Awaitable[Union[List[SearchItem], List[dict[str, Any]]]]
        ] = []

        # Search in tool_space (general for main agent, or specific space for subagent)
        if tool_space in user_namespaces or tool_space == "general":
            search_tasks.append(store.asearch((tool_space,), query=query, limit=limit))

        # Include subagents search for main agent context
        if include_subagents:
            search_tasks.append(store.asearch(("subagents",), query=query, limit=15))
            # Search public integrations to discover unconnected tools
            # query is guaranteed to be str here due to checks above, but mypy doesn't know
            search_tasks.append(search_public_integrations(query=query or "", limit=15))

        # Execute all searches
        if search_tasks:
            results = await asyncio.gather(*search_tasks, return_exceptions=True)
        else:
            results = []

        all_results = []

        for result in results:
            if isinstance(result, BaseException):
                logger.warning(f"Search error: {result}")
                continue
            # result is now known to be list[SearchItem] or list[dict]
            if not result:
                continue

            # Check first item to determine if this is a list of dicts (public integrations)
            # or list of SearchItems (Chroma store results)
            is_public_search = isinstance(result[0], dict)

            if is_public_search:
                # Handle public integration search results
                public_result: List[dict[str, Any]] = result  # type: ignore[assignment]
                for public_item in public_result:
                    integration_id = public_item.get("integration_id")
                    if integration_id:
                        subagent_key = f"subagent:{integration_id}"
                        all_results.append(
                            {
                                "id": subagent_key,
                                "score": public_item.get("relevance_score", 0),
                            }
                        )
            else:
                # Handle Chroma store SearchItems
                search_result: List[SearchItem] = result  # type: ignore[assignment]
                for search_item in search_result:
                    tool_key = str(search_item.key)

                    # Check if this is a subagent result from the subagents namespace
                    if hasattr(search_item, "namespace") and search_item.namespace == (
                        "subagents",
                    ):
                        subagent_key = tool_key
                        # Ensure it starts with subagent:
                        if not subagent_key.startswith("subagent:"):
                            subagent_key = f"subagent:{subagent_key}"
                        all_results.append(
                            {"id": subagent_key, "score": search_item.score}
                        )
                        continue

                    if tool_key.startswith("subagent:"):
                        integration_id, _ = parse_subagent_id(tool_key)
                        all_results.append({"id": tool_key, "score": search_item.score})
                        continue

                    # Filter out tools from delegated categories ONLY in main agent context
                    # When include_subagents=False, we're inside a subagent and should
                    # NOT filter out delegated tools (the subagent needs its own tools)
                    if include_subagents:
                        tool_category_name = tool_registry.get_category_of_tool(
                            tool_key
                        )
                        if tool_category_name:
                            category = tool_registry.get_category(
                                name=tool_category_name
                            )
                            if category and category.is_delegated:
                                logger.debug(
                                    f"Filtering out {tool_key} - delegated category {tool_category_name}"
                                )
                                continue

                    # Include if it's in available tools
                    if tool_key in available_tool_names:
                        all_results.append({"id": tool_key, "score": search_item.score})

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
            # Add internal subagents (always available - not integrations)
            for integration_id in internal_subagents:
                subagent_key = f"subagent:{integration_id}"
                if subagent_key not in seen:
                    seen.add(subagent_key)
                    unique_results.append({"id": subagent_key, "score": 0.5})

            # Add connected integration subagents
            for integration_id in connected_integrations:
                subagent_key = f"subagent:{integration_id}"
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
