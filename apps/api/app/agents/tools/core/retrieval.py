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
from app.services.integration_service import get_user_available_tool_namespaces
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import InjectedStore
from langgraph.store.base import BaseStore


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

        DISCOVERY MODE (query):
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

        Discovery mode ONLY returns tool names. Tools are NOT loaded.

        BINDING MODE (exact_tool_names):
        Load tools by their exact names.

        - Use this ONLY after discovery or when exact names are already known
        - Invalid or unknown tool names are ignored
        - Successfully validated tools become available for execution

        RECOMMENDED WORKFLOW:
        1. Call retrieve_tools(query="your intent") to discover tools
        2. Review returned tool names
        3. Retry discovery with alternate queries if needed
        4. Call retrieve_tools(exact_tool_names=[...]) to bind tools
        5. Execute bound tools

        TOOL NAME FORMATS:
        - Regular tools: "GMAIL_SEND_DRAFT", "CREATE_TODO"
        - Subagent tools: "subagent:gmail", "subagent:notion"

        Note:
        - Subagent tools require delegation via the `handoff` tool
        - Discovery only returns subagents for integrations you have connected

        Args:
            query:
                Natural language description of intent for discovery.
                Results are limited and best-effort.
                Retry with different phrasing if needed.

            exact_tool_names:
                Exact tool names to load and bind for execution.

            config:
                Runtime configuration containing user_id for namespace filtering.

        Returns:
            RetrieveToolsResult with:
            - tools_to_bind: tools that are loaded and executable
            - response: tool names discovered or validated
        """
        if not query and not exact_tool_names:
            raise ValueError(
                "Either 'query' (for discovery) or 'exact_tool_names' (for binding) is required."
            )

        tool_registry = await get_tool_registry()
        available_tool_names = tool_registry.get_tool_names()

        # Get user_id from explicit arg OR config
        user_id = user_id
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

        logger.info(
            f"retrieve_tools DISCOVERY: query='{query}', user_id={user_id}, "
            f"include_subagents={include_subagents}, tool_space={tool_space}"
        )

        # BINDING MODE: Validate and bind exact tool names
        if exact_tool_names:
            validated_tool_names = [
                tool_name
                for tool_name in exact_tool_names
                if tool_name in available_tool_names
            ]
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
                connected_integrations = {
                    integration_id
                    for integration_id in raw_connected
                    if (integ := get_integration_by_id(integration_id))
                    and integ.subagent_config
                    and integ.subagent_config.has_subagent
                }

                logger.info(f"User {user_id} namespaces: {user_namespaces}")
                logger.info(f"User {user_id} raw connected: {raw_connected}")
                logger.info(
                    f"User {user_id} connected subagent integrations: {connected_integrations}"
                )
            except Exception as e:
                logger.warning(f"Failed to get user namespaces: {e}")
                # Fall back to general search

        # Build search tasks based on user's namespaces
        search_tasks = []

        # Search in tool_space (or user's connected integrations)
        if tool_space in user_namespaces or tool_space == "general":
            search_tasks.append(store.asearch((tool_space,), query=query, limit=limit))

        # Also search in any other user namespaces (for MCP integrations)
        for ns in user_namespaces:
            if ns not in {"general", "subagents", tool_space}:
                search_tasks.append(store.asearch((ns,), query=query, limit=5))

        # Include subagents search if requested
        # But we'll filter results later based on connected integrations
        if include_subagents:
            search_tasks.append(store.asearch(("subagents",), query=query, limit=10))

        # Execute all searches
        if search_tasks:
            results = await asyncio.gather(*search_tasks, return_exceptions=True)
        else:
            results = []

        all_results = []
        for result in results:
            if isinstance(result, Exception):
                logger.warning(f"Search error: {result}")
                continue
            for item in result:
                tool_key = str(item.key)

                # Filter subagents: only include if user has connected OR it's internal
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
                else:
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

                # Include if it's in available tools or is a connected subagent
                if item.key in available_tool_names or tool_key.startswith("subagent:"):
                    all_results.append({"id": item.key, "score": item.score})

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
