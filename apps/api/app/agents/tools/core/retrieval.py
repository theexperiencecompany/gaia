"""
Tool Retrieval Functions for Agent Tool Discovery & Binding.

This module provides the retrieve_tools function factory that supports:
- Semantic search for tool discovery (query mode)
- Exact tool binding (exact_tool_names mode)
- Namespace filtering for user's connected integrations
- Subagent filtering based on user's connected integrations
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import (
    Annotated,
    Any,
    TypedDict,
    Union,
)

from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import InjectedStore
from langgraph.store.base import BaseStore, SearchItem

from app.agents.core.subagents.registry import all_subagents, get_subagent_by_id
from app.agents.tools.core.registry import get_tool_registry
from app.agents.tools.research_tool import deep_research
from app.agents.tools.webpage_tool import fetch_webpages, web_search_tool
from app.config.oauth_config import OAUTH_INTEGRATIONS, get_integration_by_id
from app.db.chroma.public_integrations_store import search_public_integrations
from app.services.integrations.integration_service import (
    get_user_available_tool_namespaces,
)
from app.services.mcp.mcp_client import get_mcp_client
from app.utils.mcp_utils import canonical_tool_name_map
from shared.py.wide_events import log

WEBPAGE_TOOLS = [web_search_tool.name, fetch_webpages.name, deep_research.name]


async def _user_mcp_tool_names(user_id: str | None) -> set[str]:
    """Tool names exposed by the user's live MCPClient.

    The resilience rewrite moved per-user MCP tool storage out of the global
    ToolRegistry, so `retrieve_tools` can't rely on `get_tool_names()` alone
    for discovery filtering or binding validation. This helper supplies the
    missing slice — read straight from the MCPClient that owns the live
    connectors for `user_id`. Returns an empty set on any failure so the
    surrounding logic degrades cleanly.
    """
    if not user_id:
        return set()
    try:
        mcp_client = await get_mcp_client(user_id=str(user_id))
        names: set[str] = set()
        for integration_tools in mcp_client._tools.values():
            names.update(t.name for t in integration_tools)
        return names
    except Exception as e:
        log.warning(f"_user_mcp_tool_names: failed for user {user_id}: {type(e).__name__}: {e}")
        return set()


def _is_platform_tool_space(tool_space: str) -> bool:
    """True if `tool_space` belongs to a hardcoded platform integration.

    Platform integrations (github, gmail, slack, ...) are defined in
    OAUTH_INTEGRATIONS and have a fixed `subagent_config.tool_space`.
    Their tool descriptions are not user-owned, so it is safe to search
    them without checking that the caller's `user_namespaces` lists them.

    Custom MCPs and user-added integrations have dynamic, user-owned
    namespaces (e.g. URL-derived). Those MUST stay gated by user_namespaces
    so one user cannot search another user's MCP tools.
    """
    return any(
        integration.available is True
        and integration.subagent_config is not None
        and integration.subagent_config.tool_space == tool_space
        for integration in OAUTH_INTEGRATIONS
    )


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
    user_id: str | None,
    tool_space: str,
    include_subagents: bool = True,
) -> tuple[set[str], set[str], set[str]]:
    """Get user's available namespaces and connected integrations.

    When include_subagents is False, skips computing subagent-related data
    entirely — no integration queries, no internal subagent resolution.

    Returns:
        Tuple of (user_namespaces, connected_integrations, internal_subagents)
    """
    # Seed namespaces:
    # - "general" is always available (core tools).
    # - tool_space is seeded ONLY when it belongs to a platform integration
    #   (hardcoded in OAUTH_INTEGRATIONS). For custom MCPs / user-owned
    #   integrations the namespace is user-scoped, so it must come from
    #   user_namespaces and not be implicitly granted by the seed —
    #   otherwise one user could search another user's MCP tools.
    user_namespaces: set[str] = {"general"}
    if _is_platform_tool_space(tool_space):
        user_namespaces.add(tool_space)

    connected_integrations: set[str] = set()
    internal_subagents: set[str] = set()

    # Only compute subagent data when subagents are included
    if include_subagents:
        internal_subagents = {sa.id for sa in all_subagents() if sa.managed_by == "internal"}

    if not user_id:
        return user_namespaces, connected_integrations, internal_subagents

    try:
        # Union (not assign) so platform seeds survive cache contents.
        # Custom MCP namespaces only enter via the cache lookup, which is
        # the user-scoped source of truth.
        user_namespaces |= set(await get_user_available_tool_namespaces(user_id))

        if include_subagents:
            raw_connected = user_namespaces - {"general", "subagents"}

            # raw_connected contains tool namespaces (e.g. "github_delegated"),
            # not subagent ids. Map each namespace back to its subagent via
            # config.tool_space, falling back to treating it as a custom/public
            # MCP integration when no OAuth integration matches.
            tool_space_to_subagent_id = {sa.config.tool_space: sa.id for sa in all_subagents()}

            connected_integrations = set()
            for namespace in raw_connected:
                subagent_id = tool_space_to_subagent_id.get(namespace)
                if subagent_id:
                    connected_integrations.add(subagent_id)
                elif get_integration_by_id(namespace) is None:
                    # Custom/public MCP integration — not in OAuth config and
                    # no subagent claims this namespace; surface it directly.
                    connected_integrations.add(namespace)

            log.info(f"User {user_id} connected subagents: {connected_integrations}")

        log.info(f"User {user_id} namespaces: {user_namespaces}")
    except Exception as e:
        log.warning(f"Failed to get user namespaces: {e}")

    return user_namespaces, connected_integrations, internal_subagents


def _build_search_tasks(
    store: BaseStore,
    query: str,
    tool_space: str,
    user_namespaces: set[str],
    include_subagents: bool,
    limit: int,
) -> list[Awaitable[Union[list[SearchItem], list[dict[str, Any]]]]]:
    """Build list of search tasks to execute.

    The `tool_space in user_namespaces` gate is the security boundary that
    keeps a user from searching another user's custom MCP tools. We never
    bypass it here — _get_user_context is responsible for ensuring
    user_namespaces contains tool_space whenever the caller is entitled
    to search it (always for platform integrations, only when the user
    has the integration connected for custom MCPs).
    """
    search_tasks: list[Awaitable[Union[list[SearchItem], list[dict[str, Any]]]]] = []

    # Search in tool_space
    if tool_space in user_namespaces or tool_space == "general":
        log.info(f"Adding search for tool_space: {tool_space}")
        search_tasks.append(store.asearch((tool_space,), query=query, limit=limit))
    else:
        # Caller is in a subagent whose namespace they don't own. This is
        # unusual — usually it means a stale cache or a misrouted handoff.
        # We refuse the search rather than leak another user's tool index.
        log.warning(
            "retrieve_tools refused search: tool_space not in user_namespaces",
            tool_space=tool_space,
            user_namespaces=sorted(user_namespaces),
        )

    # For subagents, also search 'general' namespace with a small limit
    # so core tools (e.g. webpage tools) are still discoverable.
    if tool_space != "general":
        log.info("Adding search for general namespace (limited to 5 for core tools)")
        search_tasks.append(store.asearch(("general",), query=query, limit=5))

    # Search subagents namespace
    if include_subagents:
        log.info("Adding search for subagents namespace")
        search_tasks.append(store.asearch(("subagents",), query=query, limit=15))
        search_tasks.append(search_public_integrations(query=query, limit=15))

    return search_tasks


def _process_public_integration_result(
    result: list[dict[str, Any]],
) -> list[dict[str, str | float | None]]:
    """Process public integration search results."""
    processed = []

    for item in result:
        integration_id = item.get("integration_id")
        if integration_id:
            # Include name for LLM readability
            name = item.get("name")
            subagent_key = (
                f"subagent:{integration_id} ({name})" if name else f"subagent:{integration_id}"
            )
            processed.append(
                {
                    "id": subagent_key,
                    "score": item.get("relevance_score", 0),
                }
            )

    return processed


def _process_chroma_search_result(
    result: list[SearchItem],
    available_tool_names: set[str],
    tool_registry,
    include_subagents: bool,
    tool_space: str = "general",
) -> list[dict[str, str | float | None]]:
    """Process Chroma store search results."""
    processed: list[dict[str, str | float | None]] = []

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
                subagent_key = f"subagent:{tool_key} ({name})" if name else f"subagent:{tool_key}"

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
    results: list[Any],
    available_tool_names: set[str],
    tool_registry,
    include_subagents: bool,
    tool_space: str = "general",
) -> list[dict[str, str | float | None]]:
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
            processed = _process_public_integration_result(result)
        else:
            try:
                preview = [
                    {
                        "key": str(item.key),
                        "namespace": item.namespace if hasattr(item, "namespace") else None,
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
                available_tool_names,
                tool_registry,
                include_subagents,
                tool_space,
            )

        all_results.extend(processed)

    return all_results


def _deduplicate_and_sort(
    results: list[dict[str, str | float | None]],
    limit: int,
) -> list[str]:
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
    discovered_tools: list[str],
    internal_subagents: set[str],
    connected_integrations: set[str],
    include_subagents: bool,
) -> list[str]:
    """Inject available subagents that user has access to."""
    if not include_subagents:
        return discovered_tools

    result = list(discovered_tools)

    # Dedupe by canonical integration id rather than rendered subagent_key
    # ("subagent:gmail" vs "subagent:gmail (Gmail)" must collapse). Seed
    # seen_ids with ids parsed out of any pre-existing entries.
    seen_ids: set[str] = set()
    for entry in discovered_tools:
        if entry.startswith("subagent:"):
            tail = entry[len("subagent:") :]
            canonical_id = tail.split(" ", 1)[0]
            seen_ids.add(canonical_id)

    def _add_subagent(integration_id: str) -> None:
        if integration_id in seen_ids:
            return
        sa = get_subagent_by_id(integration_id)
        name = sa.name if sa else None
        subagent_key = (
            f"subagent:{integration_id} ({name})" if name else f"subagent:{integration_id}"
        )
        result.append(subagent_key)
        seen_ids.add(integration_id)

    # Add internal subagents (always available)
    for integration_id in internal_subagents:
        _add_subagent(integration_id)

    # Add connected integration subagents
    for integration_id in connected_integrations:
        _add_subagent(integration_id)

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
        query: str | None = None,
        exact_tool_names: list[str] | None = None,
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
            log.warning("retrieve_tools called with NO user_id (not in configurable or metadata)")

        # BINDING MODE: Validate and bind exact tool names
        if exact_tool_names:
            available_tool_names_set = set(available_tool_names)

            mcp_tool_names_set = await _user_mcp_tool_names(user_id)
            known_by_canonical = canonical_tool_name_map(
                available_tool_names_set | mcp_tool_names_set
            )

            validated_tool_names: list[str] = []
            unknown_tool_names: list[str] = []
            for tool_name in exact_tool_names:
                if tool_name.startswith("subagent:"):
                    # Subagents are invoked via the `handoff` tool, not bound
                    # here — the docstring tells the LLM this and select_tools
                    # filters subagent:* out before binding. We accept the
                    # key when subagents are enabled so it appears in the
                    # response (purely informational); membership validation
                    # happens at handoff time where it actually matters.
                    if include_subagents:
                        validated_tool_names.append(tool_name)
                    else:
                        unknown_tool_names.append(tool_name)
                elif tool_name in available_tool_names_set or tool_name in mcp_tool_names_set:
                    validated_tool_names.append(tool_name)
                elif canonical := known_by_canonical.get(tool_name.replace("-", "_")):
                    validated_tool_names.append(canonical)
                else:
                    unknown_tool_names.append(tool_name)

            if unknown_tool_names:
                # Surfacing this is important: silently dropping requested tools
                # makes registry-population bugs invisible to operators.
                log.warning(
                    "retrieve_tools binding dropped unknown tools",
                    tool_space=tool_space,
                    unknown=unknown_tool_names,
                    available_count=len(available_tool_names_set),
                )

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

        # MCP tool names don't live in the global registry anymore (resilience
        # rewrite removed the per-user mcp_{iid}_{user_id} categories). Union
        # the registry names with the user's live MCPClient tool names so the
        # discovery-mode filter doesn't drop every PostHog/Notion/etc. hit.
        available_tool_names_set = set(available_tool_names) | await _user_mcp_tool_names(user_id)

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
                tool_space=tool_space,
                user_id=user_id,
                namespaces_searched=sorted(user_namespaces),
                tools_discovered=len(final_tools),
                chroma_hits=chroma_hits,
                public_hits=public_hits,
                per_namespace_hits=per_namespace_hits,
                candidates_after_filter=len(all_results),
                chroma_preview=chroma_preview,
            )
        )
        if chroma_hits == 0 and tool_space != "general":
            log.warning(
                f"retrieve_tools: 0 ChromaDB hits for tool_space='{tool_space}' "
                f"user={user_id} query={query!r}. Check that index_tools_to_store "
                f"actually wrote docs for this namespace."
            )

        return RetrieveToolsResult(
            tools_to_bind=[],
            response=final_tools,
        )

    # Assign the LLM-facing docstring from pre-built constants
    if include_subagents:
        retrieve_tools.__doc__ = _RETRIEVE_TOOLS_BASE_DOC + _RETRIEVE_TOOLS_SUBAGENT_SECTION
    else:
        retrieve_tools.__doc__ = _RETRIEVE_TOOLS_BASE_DOC

    return retrieve_tools
