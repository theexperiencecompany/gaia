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
from app.agents.tools.research_tool import deep_research
from app.agents.tools.webpage_tool import fetch_webpages, web_search_tool
from app.config.oauth_config import OAUTH_INTEGRATIONS, get_integration_by_id
from app.db.chroma.public_integrations_store import search_public_integrations
from app.services.composio.composio_service import get_composio_service
from app.services.integrations.integration_service import (
    get_user_available_tool_namespaces,
)
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import InjectedStore
from langgraph.store.base import BaseStore, SearchItem
from shared.py.wide_events import log

WEBPAGE_TOOLS = [web_search_tool.name, fetch_webpages.name, deep_research.name]


def _get_integration_for_space(tool_space: str):
    for integration in OAUTH_INTEGRATIONS:
        if (
            integration.subagent_config
            and integration.subagent_config.tool_space == tool_space
        ):
            return integration
    return None


async def _maybe_hydrate_missing_tools(
    *,
    tool_registry,
    tool_space: str,
    results: list[Any],
    available_tool_names: set[str],
) -> tuple[set[str], int]:
    if tool_space in {"general", "subagents"}:
        return available_tool_names, 0

    integration = _get_integration_for_space(tool_space)
    if not integration or not integration.composio_config:
        return available_tool_names, 0

    missing: set[str] = set()
    for result in results:
        if not isinstance(result, list) or not result:
            continue
        if isinstance(result[0], dict):
            continue
        for item in result:
            if not hasattr(item, "namespace"):
                continue
            if item.namespace != (tool_space,):
                continue
            tool_key = str(item.key)
            if tool_key.startswith("subagent:"):
                continue
            if tool_key not in available_tool_names:
                missing.add(tool_key)

    if not missing:
        return available_tool_names, 0

    missing_list = list(missing)[:10]
    try:
        composio_service = get_composio_service()
        tools = await composio_service.get_tools_by_name(missing_list)
    except Exception as e:
        log.warning(f"Lazy hydration failed for {tool_space}: {e}")
        return available_tool_names, 0

    if not tools:
        return available_tool_names, 0

    category_name = None
    category = None
    for name, cat in tool_registry._categories.items():
        if cat.space == tool_space:
            category_name = name
            category = cat
            break

    if category is None:
        try:
            await tool_registry.register_provider_tools(
                toolkit_name=integration.composio_config.toolkit,
                space_name=tool_space,
                specific_tools=missing_list,
            )
        except Exception as e:
            log.warning(f"Lazy hydration registry load failed for {tool_space}: {e}")
            return available_tool_names, 0
    else:
        category.add_tools(tools)
        if category_name:
            await tool_registry._index_category_tools(category_name)

    refreshed = set(tool_registry.get_tool_names())
    return refreshed, len(tools)


# ---------------------------------------------------------------------------
# retrieve_tools docstring (doubles as LLM-facing tool description)
# ---------------------------------------------------------------------------
# The base docstring covers discovery and binding modes. The subagent section
# is appended only when include_subagents=True so that provider/spawned
# subagents never see delegation guidance they can't act on.

_RETRIEVE_TOOLS_BASE_DOC = """\
Discover and load tools for execution. Supports two modes: discovery and binding.

—DISCOVERY MODE (query)
Semantic search that returns tool names matching your intent. Tools are NOT loaded yet.

Rules:
- One well-formed query is enough for most tasks. Do not retry unless results are clearly irrelevant.
- Do not search repeatedly to be thorough. If the first result looks right, move to binding.
- Comma-separated intents work: "list pull requests, get repo info"

—BINDING MODE (exact_tool_names)
Loads tools by exact name so they can be called. Use this after discovery or when you already know the name.

Rules:
- Only bind tools you are about to use in the next 1-2 steps
- Unknown or invalid names are silently ignored
- You CANNOT call a tool that has not been bound first

—STANDARD WORKFLOW
Step 1: retrieve_tools(query="your intent")         → discover tool names
Step 2: retrieve_tools(exact_tool_names=["TOOL_A"]) → bind for execution
Step 3: Call the tool directly

Shortcut: If you already know the exact tool name, skip Step 1 and go straight to binding.

—EFFICIENCY RULES (follow these strictly)
- Do not call retrieve_tools more than twice for a single task unless the first discovery returned completely irrelevant results
- Do not discover the same intent twice with different wording unless the first returned nothing useful
- Do not bind tools you are not going to call immediately
- Once a tool is bound and returns results, use those results. Do not search for alternative tools.

—TOOL NAME FORMAT
Tools follow ALLCAPS_SNAKE_CASE naming: "GITHUB_LIST_PULL_REQUESTS", "GMAIL_SEND_EMAIL"
Internal tools follow snake_case: "plan_tasks", "vfs_read"

—ARGS
query:
    Natural language description of what you want to do.
    Be specific about the action and the provider.
    Example: "list pull requests", "send email", "create github issue"

exact_tool_names:
    List of exact tool names to load and make executable.
    Example: ["GITHUB_LIST_PULL_REQUESTS", "GITHUB_GET_PULL_REQUEST"]

—RETURNS
response: tool names discovered or validated
tools_to_bind: tools that are now loaded and ready to call

—EXAMPLES

Simple read task:
  retrieve_tools(query="list pull requests")
  → ["GITHUB_LIST_PULL_REQUESTS", "GITHUB_LIST_PULL_REQUESTS_FOR_REPO", ...]
  retrieve_tools(exact_tool_names=["GITHUB_LIST_PULL_REQUESTS"])
  → GITHUB_LIST_PULL_REQUESTS(sort="updated", direction="desc")
  → First result is the answer. Stop.

Multi-tool task:
  retrieve_tools(query="fetch emails, send reply")
  → ["GMAIL_FETCH_EMAILS", "GMAIL_REPLY_TO_THREAD", ...]
  retrieve_tools(exact_tool_names=["GMAIL_FETCH_EMAILS", "GMAIL_REPLY_TO_THREAD"])
  → GMAIL_FETCH_EMAILS(...) → find the thread
  → GMAIL_REPLY_TO_THREAD(...) → send reply. Done.

Write task with verification:
  retrieve_tools(query="list branches, create pull request")
  → ["GITHUB_LIST_BRANCHES", "GITHUB_CREATE_PULL_REQUEST", ...]
  retrieve_tools(exact_tool_names=["GITHUB_LIST_BRANCHES", "GITHUB_CREATE_PULL_REQUEST"])
  → GITHUB_LIST_BRANCHES(...) → confirm branch name
  → GITHUB_CREATE_PULL_REQUEST(...) → done.
"""

_RETRIEVE_TOOLS_SUBAGENT_SECTION = """

—SUBAGENT TOOLS
Discovery may also return subagent tools alongside regular tools.
- Subagent tool format: "subagent:gmail", "subagent:fb9dfd7e05f8"
- Subagent tools require delegation via the `handoff` tool
- They cannot be executed directly"""


class RetrieveToolsResult(TypedDict):
    """Result from retrieve_tools function."""

    tools_to_bind: list[str]
    response: list[str]


async def _get_user_context(
    user_id: Optional[str],
    tool_space: str,
    include_subagents: bool = True,
) -> tuple[Set[str], Set[str], Set[str]]:
    """Get user's available namespaces and connected integrations.

    When include_subagents is False, skips computing subagent-related data
    entirely — no integration queries, no internal subagent resolution.

    Returns:
        Tuple of (user_namespaces, connected_integrations, internal_subagents)
    """
    user_namespaces: Set[str] = {tool_space, "general"}
    connected_integrations: Set[str] = set()
    internal_subagents: Set[str] = set()

    # Only compute subagent data when subagents are included
    if include_subagents:
        internal_subagents = {
            integration.id
            for integration in OAUTH_INTEGRATIONS
            if integration.managed_by == "internal"
            and integration.subagent_config
            and integration.subagent_config.has_subagent
        }

    if not user_id:
        return user_namespaces, connected_integrations, internal_subagents

    try:
        user_namespaces = set(await get_user_available_tool_namespaces(user_id))

        if include_subagents:
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

            log.info(f"User {user_id} connected subagents: {connected_integrations}")

        log.info(f"User {user_id} namespaces: {user_namespaces}")
    except Exception as e:
        log.warning(f"Failed to get user namespaces: {e}")

    return user_namespaces, connected_integrations, internal_subagents


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
        log.info(f"Adding search for tool_space: {tool_space}")
        search_tasks.append(store.asearch((tool_space,), query=query, limit=limit))

    # For subagents, also search 'general' namespace with small limit
    # to discover core tools like webpage tools
    if tool_space != "general" and "general" in user_namespaces:
        log.info("Adding search for general namespace (limited to 5 for core tools)")
        search_tasks.append(store.asearch(("general",), query=query, limit=5))

    # Search subagents namespace
    if include_subagents:
        log.info("Adding search for subagents namespace")
        search_tasks.append(store.asearch(("subagents",), query=query, limit=15))
        search_tasks.append(search_public_integrations(query=query, limit=15))

    return search_tasks


def _process_public_integration_result(
    result: List[dict[str, Any]],
    task_idx: int,
) -> List[dict[str, str | float | None]]:
    """Process public integration search results."""
    processed = []

    for item in result:
        integration_id = item.get("integration_id")
        if integration_id:
            # Include name for LLM readability
            name = item.get("name")
            subagent_key = (
                f"subagent:{integration_id} ({name})"
                if name
                else f"subagent:{integration_id}"
            )
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
    tool_space: str = "general",
) -> List[dict[str, str | float | None]]:
    """Process Chroma store search results."""
    processed: List[dict[str, str | float | None]] = []

    for item in result:
        tool_key = str(item.key)

        # Handle subagent results from subagents namespace
        if hasattr(item, "namespace") and item.namespace == ("subagents",):
            if not include_subagents:
                continue

            # Get display name from item.value if available (stored during indexing)
            name = None
            if hasattr(item, "value") and isinstance(item.value, dict):
                name = item.value.get("name")

            # Build subagent key with display name for LLM readability
            if tool_key.startswith("subagent:"):
                subagent_key = f"{tool_key} ({name})" if name else tool_key
            else:
                subagent_key = (
                    f"subagent:{tool_key} ({name})" if name else f"subagent:{tool_key}"
                )

            processed.append({"id": subagent_key, "score": item.score})
            continue

        # Handle keys with subagent: prefix — skip if subagents not included
        if tool_key.startswith("subagent:"):
            if not include_subagents:
                continue
            processed.append({"id": tool_key, "score": item.score})
            continue

        # Filter general namespace results for subagents - only allow webpage tools
        if (
            hasattr(item, "namespace")
            and item.namespace == ("general",)
            and tool_space != "general"
        ):
            # Only include webpage tools from general namespace for subagents
            if tool_key not in WEBPAGE_TOOLS:
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
    tool_space: str = "general",
) -> List[dict[str, str | float | None]]:
    """Process all search results and return unified list."""
    all_results = []

    for idx, result in enumerate(results):
        if isinstance(result, BaseException):
            log.warning(f"Task {idx}: Search error - {result}")
            continue

        if not result:
            continue

        # Determine result type and process accordingly
        is_public_search = isinstance(result[0], dict)

        if is_public_search:
            processed = _process_public_integration_result(result, idx)
        else:
            try:
                preview = [
                    {
                        "key": str(item.key),
                        "namespace": item.namespace
                        if hasattr(item, "namespace")
                        else None,
                        "score": item.score,
                    }
                    for item in result[:20]
                ]
                log.debug(
                    f"Chroma search raw hits (task={idx}, tool_space={tool_space}): "
                    f"{len(result)} items, preview={preview}"
                )
            except Exception as e:
                log.debug(f"Chroma search raw hits log failed (task={idx}): {e}")
            processed = _process_chroma_search_result(
                result,
                idx,
                available_tool_names,
                tool_registry,
                include_subagents,
                tool_space,
            )

        all_results.extend(processed)

    return all_results


def _deduplicate_and_sort(
    results: List[dict[str, str | float | None]],
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
        # Get display name for LLM readability
        integ = get_integration_by_id(integration_id)
        name = integ.name if integ else None
        subagent_key = (
            f"subagent:{integration_id} ({name})"
            if name
            else f"subagent:{integration_id}"
        )
        if subagent_key not in seen:
            result.append(subagent_key)
            seen.add(subagent_key)

    # Add connected integration subagents
    for integration_id in connected_integrations:
        # Get display name for LLM readability
        integ = get_integration_by_id(integration_id)
        name = integ.name if integ else None
        subagent_key = (
            f"subagent:{integration_id} ({name})"
            if name
            else f"subagent:{integration_id}"
        )
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
        log.info(
            "retrieve_tools called",
            query=query,
            exact_tool_names=exact_tool_names,
            tool_space=tool_space,
            include_subagents=include_subagents,
            user_id=config.get("configurable", {}).get("user_id")
            or config.get("metadata", {}).get("user_id"),
        )
        if not query and not exact_tool_names:
            raise ValueError(
                "Either 'query' (for discovery) or 'exact_tool_names' (for binding) is required."
            )

        tool_registry = await get_tool_registry()
        available_tool_names = tool_registry.get_tool_names()
        log.info(f"Registry has {len(available_tool_names)} available tools")

        # Get user_id from config (try configurable first, then metadata as fallback)
        user_id = config.get("configurable", {}).get("user_id")
        if not user_id:
            # Fallback to metadata
            user_id = config.get("metadata", {}).get("user_id")
            if user_id and "configurable" in config:
                # Update configurable with user_id for consistency
                config["configurable"]["user_id"] = user_id

        if not user_id:
            log.warning(
                "retrieve_tools called with NO user_id (not in configurable or metadata)"
            )

        # BINDING MODE: Validate and bind exact tool names
        if exact_tool_names:
            validated_tool_names = []
            for tool_name in exact_tool_names:
                if tool_name.startswith("subagent:"):
                    # Only pass through subagent keys when subagents are enabled
                    if include_subagents:
                        validated_tool_names.append(tool_name)
                elif tool_name in available_tool_names:
                    validated_tool_names.append(tool_name)
            log.set(
                tool_retrieval=dict(
                    mode="binding",
                    tools_requested=len(exact_tool_names),
                    tools_bound=len(validated_tool_names),
                    tools_filtered=len(exact_tool_names) - len(validated_tool_names),
                )
            )

            return RetrieveToolsResult(
                tools_to_bind=validated_tool_names,
                response=validated_tool_names,
            )

        # Get user context (skips subagent computation when include_subagents=False)
        (
            user_namespaces,
            connected_integrations,
            internal_subagents,
        ) = await _get_user_context(user_id, tool_space, include_subagents)

        # Build and execute search tasks
        search_tasks = _build_search_tasks(
            store, query or "", tool_space, user_namespaces, include_subagents, limit
        )

        results = await asyncio.gather(*search_tasks, return_exceptions=True)

        available_tool_names_set = set(available_tool_names)
        available_tool_names_set, hydrated_count = await _maybe_hydrate_missing_tools(
            tool_registry=tool_registry,
            tool_space=tool_space,
            results=results,
            available_tool_names=available_tool_names_set,
        )

        chroma_hits = 0
        public_hits = 0
        per_namespace_hits: dict[str, int] = {}
        for result in results:
            if not isinstance(result, list) or not result:
                continue
            if isinstance(result[0], dict):
                public_hits += len(result)
                continue
            chroma_hits += len(result)
            for item in result:
                if not hasattr(item, "namespace"):
                    continue
                ns = "::".join(item.namespace) if item.namespace else "default"
                per_namespace_hits[ns] = per_namespace_hits.get(ns, 0) + 1

        chroma_preview: list[str] = []
        for result in results:
            if isinstance(result, list) and result and not isinstance(result[0], dict):
                for item in result:
                    if isinstance(item, dict):
                        namespace = item.get("namespace")
                        tool_key = item.get("key")
                    else:
                        namespace = getattr(item, "namespace", None)
                        tool_key = getattr(item, "key", None)
                    if tool_key is None:
                        continue
                    chroma_preview.append(f"{namespace}::{tool_key}")
                    if len(chroma_preview) >= 10:
                        break
            if len(chroma_preview) >= 10:
                break

        # Process results
        all_results = await _process_search_results(
            results,
            available_tool_names_set,
            tool_registry,
            include_subagents,
            tool_space,
        )

        # Deduplicate and sort
        discovered_tools = _deduplicate_and_sort(all_results, limit)

        # Inject available subagents (no-op when include_subagents=False)
        if include_subagents:
            final_tools = _inject_available_subagents(
                discovered_tools,
                internal_subagents,
                connected_integrations,
                include_subagents,
            )
        else:
            final_tools = discovered_tools

        log.set(
            tool_retrieval=dict(
                mode="discovery",
                query=query,
                namespaces_searched=list(user_namespaces),
                tools_discovered=len(final_tools),
                chroma_hits=chroma_hits,
                public_hits=public_hits,
                candidates_after_filter=len(all_results),
            )
        )

        return RetrieveToolsResult(
            tools_to_bind=final_tools,
            response=final_tools,
        )

    # Assign the LLM-facing docstring from pre-built constants
    if include_subagents:
        retrieve_tools.__doc__ = (
            _RETRIEVE_TOOLS_BASE_DOC + _RETRIEVE_TOOLS_SUBAGENT_SECTION
        )
    else:
        retrieve_tools.__doc__ = _RETRIEVE_TOOLS_BASE_DOC

    return retrieve_tools
