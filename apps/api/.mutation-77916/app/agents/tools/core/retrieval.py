"""  # pragma: no mutate
Tool Retrieval Functions for Agent Tool Discovery & Binding.  # pragma: no mutate

This module provides the retrieve_tools function factory that supports:  # pragma: no mutate
- Semantic search for tool discovery (query mode)  # pragma: no mutate
- Exact tool binding (exact_tool_names mode)  # pragma: no mutate
- Namespace filtering for user's connected integrations  # pragma: no mutate
- Subagent filtering based on user's connected integrations  # pragma: no mutate
"""  # pragma: no mutate

import asyncio  # pragma: no mutate
from collections.abc import Awaitable, Callable  # pragma: no mutate
import json
from typing import (  # pragma: no mutate
    Annotated,  # pragma: no mutate
    Any,  # pragma: no mutate
    TypeAlias,  # pragma: no mutate
    TypedDict,  # pragma: no mutate
    Union,  # pragma: no mutate
    cast,  # pragma: no mutate
)  # pragma: no mutate

from langchain_core.runnables import RunnableConfig  # pragma: no mutate
from langgraph.prebuilt import InjectedStore  # pragma: no mutate
from langgraph.store.base import BaseStore, SearchItem  # pragma: no mutate
from pydantic import Field  # pragma: no mutate

from app.agents.core.subagents.registry import all_subagents, get_subagent_by_id  # pragma: no mutate
from app.agents.tools.core.registry import (  # pragma: no mutate
    DESKTOP_TOOL_CATEGORY,  # pragma: no mutate
    DESKTOP_TOOL_SPACE,  # pragma: no mutate
    ToolRegistry,  # pragma: no mutate
    get_tool_registry,  # pragma: no mutate
)  # pragma: no mutate
from app.agents.tools.research_tool import deep_research  # pragma: no mutate
from app.agents.tools.webpage_tool import fetch_webpages, web_search_tool  # pragma: no mutate
from app.config.oauth_config import OAUTH_INTEGRATIONS  # pragma: no mutate
from app.constants.log_tags import LogTag  # pragma: no mutate
from app.db.chroma.public_integrations_store import search_public_integrations  # pragma: no mutate
from app.models.agent_models import agent_configurable  # pragma: no mutate
from app.models.chat_models import ConversationSource  # pragma: no mutate
from app.override.langgraph_bigtool.utils import RetrieveToolsResult
from app.services.integrations.integration_service import (  # pragma: no mutate
    get_user_available_tool_namespaces,  # pragma: no mutate
)  # pragma: no mutate
from app.services.integrations.user_integrations import get_user_integrations  # pragma: no mutate
from app.services.mcp.mcp_client import get_mcp_client  # pragma: no mutate
from app.services.oauth.oauth_service import get_all_integrations_status  # pragma: no mutate
from app.utils.mcp_utils import canonical_tool_name_map  # pragma: no mutate
from shared.py.wide_events import log  # pragma: no mutate

WEBPAGE_TOOLS = [web_search_tool.name, fetch_webpages.name, deep_research.name]  # pragma: no mutate


async def _user_mcp_tool_names(user_id: str | None) -> set[str]:  # pragma: no mutate
    """Tool names exposed by the user's live MCPClient.  # pragma: no mutate

    The resilience rewrite moved per-user MCP tool storage out of the global  # pragma: no mutate
    ToolRegistry, so `retrieve_tools` can't rely on `get_tool_names()` alone  # pragma: no mutate
    for discovery filtering or binding validation. This helper supplies the  # pragma: no mutate
    missing slice — read straight from the MCPClient that owns the live  # pragma: no mutate
    connectors for `user_id`. Returns an empty set on any failure so the  # pragma: no mutate
    surrounding logic degrades cleanly.  # pragma: no mutate
    """  # pragma: no mutate
    if not user_id:  # pragma: no mutate
        return set()  # pragma: no mutate
    try:  # pragma: no mutate
        mcp_client = await get_mcp_client(user_id=str(user_id))  # pragma: no mutate
        names: set[str] = set()  # pragma: no mutate
        for integration_tools in mcp_client._tools.values():  # pragma: no mutate
            names.update(t.name for t in integration_tools)  # pragma: no mutate
        return names  # pragma: no mutate
    except Exception as e:  # pragma: no mutate
        log.warning(  # pragma: no mutate
            f"{LogTag.TOOL} _user_mcp_tool_names failed",  # pragma: no mutate
            user_id=user_id,  # pragma: no mutate
            error_type=type(e).__name__,  # pragma: no mutate
        )  # pragma: no mutate
        return set()  # pragma: no mutate


def _is_platform_tool_space(tool_space: str) -> bool:  # pragma: no mutate
    """True if `tool_space` belongs to a hardcoded platform integration.  # pragma: no mutate

    Platform integrations (github, gmail, slack, ...) are defined in  # pragma: no mutate
    OAUTH_INTEGRATIONS and have a fixed `subagent_config.tool_space`.  # pragma: no mutate
    Their tool descriptions are not user-owned, so it is safe to search  # pragma: no mutate
    them without checking that the caller's `user_namespaces` lists them.  # pragma: no mutate

    Custom MCPs and user-added integrations have dynamic, user-owned  # pragma: no mutate
    namespaces (e.g. URL-derived). Those MUST stay gated by user_namespaces  # pragma: no mutate
    so one user cannot search another user's MCP tools.  # pragma: no mutate
    """  # pragma: no mutate
    return any(  # pragma: no mutate
        integration.available is True  # pragma: no mutate
        and integration.subagent_config is not None  # pragma: no mutate
        and integration.subagent_config.tool_space == tool_space  # pragma: no mutate
        for integration in OAUTH_INTEGRATIONS  # pragma: no mutate
    )  # pragma: no mutate


# ---------------------------------------------------------------------------
# retrieve_tools docstring (doubles as LLM-facing tool description)
# ---------------------------------------------------------------------------
# The base docstring covers discovery and binding modes. The subagent section
# is appended only when include_subagents=True so that provider/spawned
# subagents never see delegation guidance they can't act on.

_RETRIEVE_TOOLS_BASE_DOC = """\
Discover and load tools for execution. Supports two modes: discovery and binding.  # pragma: no mutate

REQUIRED: pass exactly ONE of `query` (to discover by intent) or `exact_tool_names`  # pragma: no mutate
(to bind known names). Calling with NEITHER argument is invalid and returns corrective  # pragma: no mutate
guidance instead of binding anything. If you are looking for a capability, pass  # pragma: no mutate
query="what you want to do".  # pragma: no mutate

—DISCOVERY MODE (query)  # pragma: no mutate
Semantic search that returns tool names matching your intent. Tools are NOT loaded yet.  # pragma: no mutate

Rules:  # pragma: no mutate
- This is semantic vector search over tool names and descriptions. Phrase the query in  # pragma: no mutate
  natural language using the INTEGRATION'S NAME ("github", "gmail", "notion") and the  # pragma: no mutate
  action — NEVER an id, uuid, slug, or internal key. Ids carry no semantic meaning, so  # pragma: no mutate
  they embed to noise and return irrelevant tools. Search "list github pull requests",  # pragma: no mutate
  not the repo/connection id.  # pragma: no mutate
- One well-formed query is enough for most tasks. Do not retry unless results are clearly irrelevant.  # pragma: no mutate
- Do not search repeatedly to be thorough. If the first result looks right, move to binding.  # pragma: no mutate
- Comma-separated intents work: "list pull requests, get repo info"  # pragma: no mutate

—BINDING MODE (exact_tool_names)  # pragma: no mutate
Loads tools by exact name so they can be called. Use this after discovery or when you already know the name.  # pragma: no mutate

Rules:  # pragma: no mutate
- Only bind tools you are about to use in the next 1-2 steps  # pragma: no mutate
- Unknown or invalid names are silently ignored  # pragma: no mutate
- You CANNOT call a tool that has not been bound first  # pragma: no mutate

—STANDARD WORKFLOW  # pragma: no mutate
Step 1: retrieve_tools(query="your intent")         → discover tool names  # pragma: no mutate
Step 2: retrieve_tools(exact_tool_names=["TOOL_A"]) → bind for execution  # pragma: no mutate
Step 3: Call the tool directly  # pragma: no mutate

Shortcut: If you already know the exact tool name, skip Step 1 and go straight to binding.  # pragma: no mutate

IF DISCOVERY RETURNS A SUBAGENT (a name starting with "subagent:"): SKIP Step 2  # pragma: no mutate
entirely. Subagents are NOT bound. Go straight to handoff(subagent_id="gmail",  # pragma: no mutate
task="..."). Do NOT call retrieve_tools again to "bind" it, and never call  # pragma: no mutate
retrieve_tools with an empty exact_tool_names. Trying to bind a subagent is the  # pragma: no mutate
single most common mistake here: there is no bind step for a subagent.  # pragma: no mutate

—EFFICIENCY RULES (follow these strictly)  # pragma: no mutate
- Do not call retrieve_tools more than twice for a single task unless the first discovery returned completely irrelevant results  # pragma: no mutate
- Do not discover the same intent twice with different wording unless the first returned nothing useful  # pragma: no mutate
- Do not bind tools you are not going to call immediately  # pragma: no mutate
- Once a tool is bound and returns results, use those results. Do not search for alternative tools.  # pragma: no mutate

—TOOL NAME FORMAT  # pragma: no mutate
Tools follow ALLCAPS_SNAKE_CASE naming: "GITHUB_LIST_PULL_REQUESTS", "GMAIL_SEND_EMAIL"  # pragma: no mutate
Internal tools follow snake_case: "plan_tasks", "vfs_read"  # pragma: no mutate

—ARGS  # pragma: no mutate
query:  # pragma: no mutate
    Natural language description of what you want to do.  # pragma: no mutate
    Be specific about the action and name the integration in plain words  # pragma: no mutate
    ("github", "gmail", "notion") — NOT an id, uuid, or slug. This is semantic  # pragma: no mutate
    vector search; ids do not embed and will not match.  # pragma: no mutate
    Example: "list pull requests", "send email", "create github issue"  # pragma: no mutate

exact_tool_names:  # pragma: no mutate
    List of exact tool names to load and make executable.  # pragma: no mutate
    Example: ["GITHUB_LIST_PULL_REQUESTS", "GITHUB_GET_PULL_REQUEST"]  # pragma: no mutate

—RETURNS  # pragma: no mutate
response: tool names discovered or validated  # pragma: no mutate
tools_to_bind: tools that are now loaded and ready to call  # pragma: no mutate

—EXAMPLES  # pragma: no mutate

Simple read task:  # pragma: no mutate
  retrieve_tools(query="list pull requests")  # pragma: no mutate
  → ["GITHUB_LIST_PULL_REQUESTS", "GITHUB_LIST_PULL_REQUESTS_FOR_REPO", ...]  # pragma: no mutate
  retrieve_tools(exact_tool_names=["GITHUB_LIST_PULL_REQUESTS"])  # pragma: no mutate
  → GITHUB_LIST_PULL_REQUESTS(sort="updated", direction="desc")  # pragma: no mutate
  → First result is the answer. Stop.  # pragma: no mutate

Multi-tool task:  # pragma: no mutate
  retrieve_tools(query="fetch emails, send reply")  # pragma: no mutate
  → ["GMAIL_FETCH_MESSAGES", "GMAIL_REPLY_TO_THREAD", ...]  # pragma: no mutate
  retrieve_tools(exact_tool_names=["GMAIL_FETCH_MESSAGES", "GMAIL_REPLY_TO_THREAD"])  # pragma: no mutate
  → GMAIL_FETCH_MESSAGES(...) → find the thread  # pragma: no mutate
  → GMAIL_REPLY_TO_THREAD(...) → send reply. Done.  # pragma: no mutate

Write task with verification:  # pragma: no mutate
  retrieve_tools(query="list branches, create pull request")  # pragma: no mutate
  → ["GITHUB_LIST_BRANCHES", "GITHUB_CREATE_PULL_REQUEST", ...]  # pragma: no mutate
  retrieve_tools(exact_tool_names=["GITHUB_LIST_BRANCHES", "GITHUB_CREATE_PULL_REQUEST"])  # pragma: no mutate
  → GITHUB_LIST_BRANCHES(...) → confirm branch name  # pragma: no mutate
  → GITHUB_CREATE_PULL_REQUEST(...) → done.  # pragma: no mutate
"""  # pragma: no mutate

_RETRIEVE_TOOLS_SUBAGENT_SECTION = """  # pragma: no mutate

—SUBAGENT TOOLS  # pragma: no mutate
Discovery may also return subagent tools alongside regular tools.  # pragma: no mutate
- Subagent tool format: "subagent:gmail", "subagent:fb9dfd7e05f8"  # pragma: no mutate
- To USE a subagent, call handoff(subagent_id="gmail", task="...") directly.  # pragma: no mutate
- Do NOT pass subagent names back to retrieve_tools, and do NOT try to "bind" them  # pragma: no mutate
  with exact_tool_names. Subagents are never bound, only handed off to; there is no  # pragma: no mutate
  binding step, handoff works immediately on the subagent id (the part after  # pragma: no mutate
  "subagent:").  # pragma: no mutate
- They cannot be executed directly as tools."""  # pragma: no mutate


class ScoredToolHit(TypedDict):  # pragma: no mutate
    """One ranked discovery hit, threaded from a search result to the final list.  # pragma: no mutate

    ``id`` is either a tool name or a ``subagent:<id> (Name)`` key; ``score`` is  # pragma: no mutate
    the backing store's relevance, absent on stores that don't rank.  # pragma: no mutate
    """  # pragma: no mutate

    id: str  # pragma: no mutate
    score: float | None  # pragma: no mutate


# What one entry of the gathered search fan-out yields: Chroma's typed
# ``SearchItem``s from the tool namespaces, or the public-integration store's
# raw dicts. Kept as a union because the two backends genuinely differ; the
# consumer discriminates on the first element and narrows with ``cast``.
SearchTaskResult: TypeAlias = Union[list[SearchItem], list[dict[str, Any]]]  # pragma: no mutate


async def _resolve_connected_subagents(user_id: str) -> dict[str, str | None]:  # pragma: no mutate
    """Map connected integration id -> display name. Platform/internal names come  # pragma: no mutate
    from the in-memory registry; custom MCP names from the cached user-integration  # pragma: no mutate
    list (one read), avoiding an uncached per-MCP lookup on this hot path."""  # pragma: no mutate
    status = await get_all_integrations_status(user_id)  # pragma: no mutate
    connected: dict[str, str | None] = {}  # pragma: no mutate
    custom_connected_ids: list[str] = []  # pragma: no mutate
    for integration_id, is_connected in status.items():  # pragma: no mutate
        if not is_connected:  # pragma: no mutate
            continue  # pragma: no mutate
        platform = get_subagent_by_id(integration_id)  # pragma: no mutate
        if platform:  # pragma: no mutate
            connected[platform.id] = platform.name  # pragma: no mutate
        else:  # pragma: no mutate
            custom_connected_ids.append(integration_id)  # pragma: no mutate

    if custom_connected_ids:  # pragma: no mutate
        user_ints = await get_user_integrations(user_id)  # pragma: no mutate
        names = {r.integration_id: r.integration.name for r in user_ints.integrations}  # pragma: no mutate
        for cid in custom_connected_ids:  # pragma: no mutate
            connected[cid] = names.get(cid)  # pragma: no mutate

    return connected  # pragma: no mutate


async def _get_user_context(  # pragma: no mutate
    user_id: str | None,  # pragma: no mutate
    tool_space: str,  # pragma: no mutate
    include_subagents: bool = True,  # pragma: no mutate
) -> tuple[set[str], dict[str, str | None], set[str]]:  # pragma: no mutate
    """Get user's available namespaces and connected integrations.  # pragma: no mutate

    When include_subagents is False, skips computing subagent-related data  # pragma: no mutate
    entirely — no integration queries, no internal subagent resolution.  # pragma: no mutate

    Returns:  # pragma: no mutate
        Tuple of (user_namespaces, connected_integrations, internal_subagents)  # pragma: no mutate
        where connected_integrations maps canonical integration id -> display name.  # pragma: no mutate
    """  # pragma: no mutate
    # Seed namespaces:
    # - "general" is always available (core tools).
    # - tool_space is seeded ONLY when it belongs to a platform integration
    #   (hardcoded in OAUTH_INTEGRATIONS). For custom MCPs / user-owned
    #   integrations the namespace is user-scoped, so it must come from
    #   user_namespaces and not be implicitly granted by the seed —
    #   otherwise one user could search another user's MCP tools.
    user_namespaces: set[str] = {"general"}  # pragma: no mutate
    if _is_platform_tool_space(tool_space):  # pragma: no mutate
        user_namespaces.add(tool_space)  # pragma: no mutate

    connected_integrations: dict[str, str | None] = {}  # pragma: no mutate
    internal_subagents: set[str] = set()  # pragma: no mutate

    # Only compute subagent data when subagents are included
    if include_subagents:  # pragma: no mutate
        internal_subagents = {sa.id for sa in all_subagents() if sa.managed_by == "internal"}  # pragma: no mutate

    if not user_id:  # pragma: no mutate
        return user_namespaces, connected_integrations, internal_subagents  # pragma: no mutate

    try:  # pragma: no mutate
        # Union (not assign) so platform seeds survive cache contents.
        # Custom MCP namespaces only enter via the cache lookup, which is
        # the user-scoped source of truth — these still gate tool search.
        user_namespaces |= set(await get_user_available_tool_namespaces(user_id))  # pragma: no mutate

        if include_subagents:  # pragma: no mutate
            connected_integrations = await _resolve_connected_subagents(user_id)  # pragma: no mutate
            log.info(  # pragma: no mutate
                f"{LogTag.TOOL} User connected subagents",  # pragma: no mutate
                user_id=user_id,  # pragma: no mutate
                connected_integrations=sorted(set(connected_integrations)),  # pragma: no mutate
            )  # pragma: no mutate

        log.info(  # pragma: no mutate
            f"{LogTag.TOOL} User namespaces resolved", user_id=user_id, namespaces=user_namespaces  # pragma: no mutate
        )  # pragma: no mutate
    except Exception as e:  # pragma: no mutate
        log.warning(f"{LogTag.TOOL} Failed to get user namespaces", error_type=type(e).__name__)  # pragma: no mutate

    return user_namespaces, connected_integrations, internal_subagents  # pragma: no mutate


def _build_search_tasks(  # pragma: no mutate
    store: BaseStore,  # pragma: no mutate
    query: str,  # pragma: no mutate
    tool_space: str,  # pragma: no mutate
    user_namespaces: set[str],  # pragma: no mutate
    include_subagents: bool,  # pragma: no mutate
    limit: int,  # pragma: no mutate
    include_desktop: bool = False,  # pragma: no mutate
) -> list[Awaitable[SearchTaskResult]]:  # pragma: no mutate
    """Build list of search tasks to execute.  # pragma: no mutate

    The `tool_space in user_namespaces` gate is the security boundary that  # pragma: no mutate
    keeps a user from searching another user's custom MCP tools. We never  # pragma: no mutate
    bypass it here — _get_user_context is responsible for ensuring  # pragma: no mutate
    user_namespaces contains tool_space whenever the caller is entitled  # pragma: no mutate
    to search it (always for platform integrations, only when the user  # pragma: no mutate
    has the integration connected for custom MCPs).  # pragma: no mutate
    """  # pragma: no mutate
    search_tasks: list[Awaitable[SearchTaskResult]] = []  # pragma: no mutate

    # Search in tool_space
    if tool_space in user_namespaces or tool_space == "general":  # pragma: no mutate
        log.info(f"{LogTag.TOOL} Adding search for tool space", tool_space=tool_space)  # pragma: no mutate
        search_tasks.append(store.asearch((tool_space,), query=query, limit=limit))  # pragma: no mutate
    else:  # pragma: no mutate
        # Caller is in a subagent whose namespace they don't own. This is
        # unusual — usually it means a stale cache or a misrouted handoff.
        # We refuse the search rather than leak another user's tool index.
        log.warning(  # pragma: no mutate
            f"{LogTag.TOOL} retrieve_tools refused search: tool_space not in user_namespaces",  # pragma: no mutate
            tool_space=tool_space,  # pragma: no mutate
            user_namespaces=sorted(user_namespaces),  # pragma: no mutate
        )  # pragma: no mutate

    # For subagents, also search 'general' namespace with a small limit
    # so core tools (e.g. webpage tools) are still discoverable.
    if tool_space != "general":  # pragma: no mutate
        log.info(f"{LogTag.TOOL} Adding search for general namespace (limited to 5 for core tools)")  # pragma: no mutate
        search_tasks.append(store.asearch(("general",), query=query, limit=5))  # pragma: no mutate

    # Desktop-executed tools are only discoverable for desktop-app sessions
    # (include_desktop is derived from conversation_source upstream).
    if include_desktop:  # pragma: no mutate
        log.info(f"{LogTag.TOOL} Adding search for desktop namespace")  # pragma: no mutate
        search_tasks.append(store.asearch((DESKTOP_TOOL_SPACE,), query=query, limit=10))  # pragma: no mutate

    # Search subagents namespace
    if include_subagents:  # pragma: no mutate
        log.info(f"{LogTag.TOOL} Adding search for subagents namespace")  # pragma: no mutate
        search_tasks.append(store.asearch(("subagents",), query=query, limit=15))  # pragma: no mutate
        search_tasks.append(search_public_integrations(query=query, limit=15))  # pragma: no mutate

    return search_tasks  # pragma: no mutate


def _process_public_integration_result(  # pragma: no mutate
    result: list[dict[str, Any]],  # pragma: no mutate
) -> list[ScoredToolHit]:  # pragma: no mutate
    """Process public integration search results."""  # pragma: no mutate
    processed: list[ScoredToolHit] = []  # pragma: no mutate

    for item in result:  # pragma: no mutate
        integration_id = item.get("integration_id")  # pragma: no mutate
        if integration_id:  # pragma: no mutate
            # Include name for LLM readability
            name = item.get("name")  # pragma: no mutate
            subagent_key = (  # pragma: no mutate
                f"subagent:{integration_id} ({name})" if name else f"subagent:{integration_id}"  # pragma: no mutate
            )  # pragma: no mutate
            processed.append(ScoredToolHit(id=subagent_key, score=item.get("relevance_score", 0)))  # pragma: no mutate

    return processed  # pragma: no mutate


def _process_chroma_search_result(  # pragma: no mutate
    result: list[SearchItem],  # pragma: no mutate
    available_tool_names: set[str],  # pragma: no mutate
    tool_registry: ToolRegistry,  # pragma: no mutate
    include_subagents: bool,  # pragma: no mutate
    tool_space: str = "general",  # pragma: no mutate
) -> list[ScoredToolHit]:  # pragma: no mutate
    """Process Chroma store search results."""  # pragma: no mutate
    processed: list[ScoredToolHit] = []  # pragma: no mutate

    for item in result:  # pragma: no mutate
        tool_key = str(item.key)  # pragma: no mutate

        # Handle subagent results from subagents namespace
        if hasattr(item, "namespace") and item.namespace == ("subagents",):  # pragma: no mutate
            if not include_subagents:  # pragma: no mutate
                continue  # pragma: no mutate

            # Get display name from item.value if available (stored during indexing)
            name = None  # pragma: no mutate
            if hasattr(item, "value") and isinstance(item.value, dict):  # pragma: no mutate
                name = item.value.get("name")  # pragma: no mutate

            # Build subagent key with display name for LLM readability
            if tool_key.startswith("subagent:"):  # pragma: no mutate
                subagent_key = f"{tool_key} ({name})" if name else tool_key  # pragma: no mutate
            else:  # pragma: no mutate
                subagent_key = f"subagent:{tool_key} ({name})" if name else f"subagent:{tool_key}"  # pragma: no mutate

            processed.append(ScoredToolHit(id=subagent_key, score=item.score))  # pragma: no mutate
            continue  # pragma: no mutate

        # Handle keys with subagent: prefix — skip if subagents not included
        if tool_key.startswith("subagent:"):  # pragma: no mutate
            if not include_subagents:  # pragma: no mutate
                continue  # pragma: no mutate
            processed.append(ScoredToolHit(id=tool_key, score=item.score))  # pragma: no mutate
            continue  # pragma: no mutate

        # Filter general namespace results for subagents - only allow webpage tools
        if (  # pragma: no mutate
            hasattr(item, "namespace")  # pragma: no mutate
            and item.namespace == ("general",)  # pragma: no mutate
            and tool_space != "general"  # pragma: no mutate
        ):  # pragma: no mutate
            # Only include webpage tools from general namespace for subagents
            if tool_key not in WEBPAGE_TOOLS:  # pragma: no mutate
                continue  # pragma: no mutate

        # Filter delegated tools in main agent context
        if include_subagents:  # pragma: no mutate
            tool_category_name = tool_registry.get_category_of_tool(tool_key)  # pragma: no mutate
            if tool_category_name:  # pragma: no mutate
                category = tool_registry.get_category(name=tool_category_name)  # pragma: no mutate
                if category and category.is_delegated:  # pragma: no mutate
                    continue  # pragma: no mutate

        # Add regular tools
        if tool_key in available_tool_names:  # pragma: no mutate
            processed.append(ScoredToolHit(id=tool_key, score=item.score))  # pragma: no mutate

    return processed  # pragma: no mutate


async def _process_search_results(  # pragma: no mutate
    results: list[SearchTaskResult | BaseException],  # pragma: no mutate
    available_tool_names: set[str],  # pragma: no mutate
    tool_registry: ToolRegistry,  # pragma: no mutate
    include_subagents: bool,  # pragma: no mutate
    tool_space: str = "general",  # pragma: no mutate
) -> list[ScoredToolHit]:  # pragma: no mutate
    """Process all search results and return unified list."""  # pragma: no mutate
    all_results: list[ScoredToolHit] = []  # pragma: no mutate

    for idx, result in enumerate(results):  # pragma: no mutate
        if isinstance(result, BaseException):  # pragma: no mutate
            # Already logged (with type) at the gather site in retrieve_tools.
            continue  # pragma: no mutate

        if not result:  # pragma: no mutate
            continue  # pragma: no mutate

        # Determine result type and process accordingly
        is_public_search = isinstance(result[0], dict)  # pragma: no mutate

        if is_public_search:  # pragma: no mutate
            processed = _process_public_integration_result(cast(list[dict[str, Any]], result))  # pragma: no mutate
        else:  # pragma: no mutate
            items = cast(list[SearchItem], result)  # pragma: no mutate
            try:  # pragma: no mutate
                preview = [  # pragma: no mutate
                    {  # pragma: no mutate
                        "key": str(item.key),  # pragma: no mutate
                        "namespace": item.namespace if hasattr(item, "namespace") else None,  # pragma: no mutate
                        "score": item.score,  # pragma: no mutate
                    }  # pragma: no mutate
                    for item in items[:20]  # pragma: no mutate
                ]  # pragma: no mutate
                log.debug(  # pragma: no mutate
                    f"{LogTag.TOOL} Chroma search raw hits",  # pragma: no mutate
                    task_index=idx,  # pragma: no mutate
                    tool_space=tool_space,  # pragma: no mutate
                    hit_count=len(result),  # pragma: no mutate
                    preview=preview,  # pragma: no mutate
                )  # pragma: no mutate
            except Exception as e:  # pragma: no mutate
                log.debug(  # pragma: no mutate
                    f"{LogTag.TOOL} Chroma search raw hits log failed",  # pragma: no mutate
                    task_index=idx,  # pragma: no mutate
                    error_type=type(e).__name__,  # pragma: no mutate
                )  # pragma: no mutate
            processed = _process_chroma_search_result(  # pragma: no mutate
                items,  # pragma: no mutate
                available_tool_names,  # pragma: no mutate
                tool_registry,  # pragma: no mutate
                include_subagents,  # pragma: no mutate
                tool_space,  # pragma: no mutate
            )  # pragma: no mutate

        all_results.extend(processed)  # pragma: no mutate

    return all_results  # pragma: no mutate


def _deduplicate_and_sort(  # pragma: no mutate
    results: list[ScoredToolHit],  # pragma: no mutate
    limit: int,  # pragma: no mutate
) -> list[str]:  # pragma: no mutate
    """Remove duplicates, sort by score, and return top results."""  # pragma: no mutate
    seen: set[str] = set()  # pragma: no mutate
    unique_results: list[ScoredToolHit] = []  # pragma: no mutate

    for r in results:  # pragma: no mutate
        if r["id"] not in seen:  # pragma: no mutate
            seen.add(r["id"])  # pragma: no mutate
            unique_results.append(r)  # pragma: no mutate
    unique_results.sort(key=lambda x: x["score"] or 0.0, reverse=True)  # pragma: no mutate
    return [str(r["id"]) for r in unique_results[:limit]]  # pragma: no mutate


def _split_subagent_entry(entry: str) -> tuple[str, str | None]:
    """``subagent:<id> (Name)`` -> (id, name)."""
    tail = entry[len("subagent:") :]
    if " (" in tail and tail.endswith(")"):
        subagent_id, name = tail.split(" (", 1)
        return subagent_id, name[:-1]
    return tail, None


def _render_discovery_response(
    final_tools: list[str],
    tool_registry: ToolRegistry,
    connected_integrations: dict[str, str | None],
    internal_subagents: set[str],
    query: str | None,
    total_candidates: int,
    limit: int,
) -> str:
    """Render discovery hits as JSON in three buckets: bind, handoff, connect.

    Availability is the only axis that changes what the model may do next, so it
    is the top-level split. ``internal_subagents`` is required to tell a built-in
    capability (always usable) from an integration the user has not connected —
    without it every built-in was reported as needing a connection it has none of.
    """
    bindable: list[str] = []
    subagents: list[tuple[str, str | None]] = []
    for entry in final_tools:
        if entry.startswith("subagent:"):
            subagents.append(_split_subagent_entry(entry))
        else:
            bindable.append(entry)

    def _tool_entry(name: str) -> dict[str, Any]:
        category = tool_registry.get_category_of_tool(name)
        meta = tool_registry.get_tool_meta(name)
        entry: dict[str, Any] = {
            "name": name,
            "source": connected_integrations.get(category) or category
            if category in connected_integrations
            else "gaia",
        }
        if meta and meta.destructive:
            entry["needs_approval"] = True
        return entry

    def _subagent_entry(sid: str, name: str | None) -> dict[str, str]:
        return {"id": sid, "name": name} if name else {"id": sid}

    ready = [_subagent_entry(s, n) for s, n in subagents if s in internal_subagents]
    connected = [
        _subagent_entry(s, n)
        for s, n in subagents
        if s in connected_integrations and s not in internal_subagents
    ]
    needs_connecting = [
        _subagent_entry(s, n)
        for s, n in subagents
        if s not in connected_integrations and s not in internal_subagents
    ]

    payload: dict[str, Any] = {
        "tools_to_bind": [_tool_entry(n) for n in bindable],
        "subagents_builtin": ready,
        "subagents_connected": connected,
        "subagents_needing_connection": needs_connecting,
    }
    if total_candidates > limit:
        payload["truncated"] = {"shown": len(final_tools), "total": total_candidates}

    # Keyed off the SEARCH, not off what is listed: built-in subagents are injected
    # unconditionally, so a zero-match search still returns entries. Reporting that
    # as a find is what sent the model into re-querying the same dead index.
    if total_candidates == 0:
        payload["search_matched_nothing"] = True
        payload["next"] = (
            "The search matched NOTHING; anything listed above is a built-in that is "
            "always offered, not a hit. Retry ONCE with a broader query naming the "
            "action ('send email', not a product name). If you already know the exact "
            "tool name, skip search and call retrieve_tools(exact_tool_names=[...]). "
            "Otherwise tell the user the capability is unavailable. Never repeat the "
            "same query."
        )
    else:
        payload["next"] = (
            "Bind with retrieve_tools(exact_tool_names=[...]) then call the tool. "
            'Subagents are NOT bindable — use handoff(subagent_id="<id>", task="..."). '
            "Anything under subagents_needing_connection is unusable until the user "
            "connects it, so ask them first."
        )
    if query:
        payload["query"] = query
    return json.dumps(payload, indent=2)


def _inject_available_subagents(  # pragma: no mutate
    discovered_tools: list[str],  # pragma: no mutate
    internal_subagents: set[str],  # pragma: no mutate
    connected_integrations: dict[str, str | None],  # pragma: no mutate
    include_subagents: bool,  # pragma: no mutate
) -> list[str]:  # pragma: no mutate
    """Inject available subagents that user has access to.  # pragma: no mutate

    Every subagent entry is rendered as ``subagent:<id> (Name)`` whenever a name  # pragma: no mutate
    is known, so the model can tell what ``subagent:<uuid>`` actually is. Names  # pragma: no mutate
    come from the connected-integrations map first, then the in-memory registry.  # pragma: no mutate
    Semantic-search hits often arrive unnamed (a ``subagent:`` key from a tool  # pragma: no mutate
    namespace, or a store that didn't return the value); they get upgraded here  # pragma: no mutate
    and deduped by canonical id so the named and unnamed forms collapse to one.  # pragma: no mutate
    """  # pragma: no mutate
    if not include_subagents:  # pragma: no mutate
        return discovered_tools  # pragma: no mutate

    def _resolve_name(integration_id: str) -> str | None:  # pragma: no mutate
        if connected_integrations.get(integration_id):  # pragma: no mutate
            return connected_integrations[integration_id]  # pragma: no mutate
        sa = get_subagent_by_id(integration_id)  # pragma: no mutate
        return sa.name if sa else None  # pragma: no mutate

    result: list[str] = []  # pragma: no mutate
    seen_ids: set[str] = set()  # pragma: no mutate

    # Pass 1: keep discovered tools in order; upgrade unnamed subagent hits to
    # carry a name when we can resolve one, and dedupe subagents by canonical id.
    for entry in discovered_tools:  # pragma: no mutate
        if not entry.startswith("subagent:"):  # pragma: no mutate
            result.append(entry)  # pragma: no mutate
            continue  # pragma: no mutate
        tail = entry[len("subagent:") :]  # pragma: no mutate
        canonical_id = tail.split(" ", 1)[0]  # pragma: no mutate
        if canonical_id in seen_ids:  # pragma: no mutate
            continue  # pragma: no mutate
        seen_ids.add(canonical_id)  # pragma: no mutate
        already_named = "(" in tail  # pragma: no mutate
        if already_named:  # pragma: no mutate
            result.append(entry)  # pragma: no mutate
        else:  # pragma: no mutate
            name = _resolve_name(canonical_id)  # pragma: no mutate
            result.append(f"subagent:{canonical_id} ({name})" if name else entry)  # pragma: no mutate

    def _add_subagent(integration_id: str, name: str | None) -> None:  # pragma: no mutate
        if integration_id in seen_ids:  # pragma: no mutate
            return  # pragma: no mutate
        subagent_key = (  # pragma: no mutate
            f"subagent:{integration_id} ({name})" if name else f"subagent:{integration_id}"  # pragma: no mutate
        )  # pragma: no mutate
        result.append(subagent_key)  # pragma: no mutate
        seen_ids.add(integration_id)  # pragma: no mutate

    # Add internal subagents (always available) — names come from the registry.
    for integration_id in internal_subagents:  # pragma: no mutate
        sa = get_subagent_by_id(integration_id)  # pragma: no mutate
        _add_subagent(integration_id, sa.name if sa else None)  # pragma: no mutate

    # Add connected integration subagents — names resolved in _get_user_context.
    for integration_id, name in connected_integrations.items():  # pragma: no mutate
        _add_subagent(integration_id, name)  # pragma: no mutate

    return result  # pragma: no mutate


def get_retrieve_tools_function(  # pragma: no mutate
    tool_space: str = "general",  # pragma: no mutate
    include_subagents: bool = True,  # pragma: no mutate
    limit: int = 25,  # pragma: no mutate
    bindable_tool_names: set[str] | None = None,  # pragma: no mutate
) -> Callable[..., Awaitable[RetrieveToolsResult]]:  # pragma: no mutate
    """Get a retrieve_tools function configured for specific context.  # pragma: no mutate

    The ``...`` in the return type is deliberate (Type Safety items 11/14): the  # pragma: no mutate
    result is handed to ``create_agent(retrieve_tools_coroutine=...)``, which  # pragma: no mutate
    wraps it in a ``StructuredTool``. LangGraph then calls it by keyword with  # pragma: no mutate
    ``store``/``config`` injected and the rest supplied by the model, so pinning  # pragma: no mutate
    a parameter list here would describe a call shape that never happens.  # pragma: no mutate

    This unified function handles both tool discovery (semantic search) and tool binding.  # pragma: no mutate
    - When `query` is provided: Returns tool names for discovery (not bound)  # pragma: no mutate
    - When `exact_tool_names` is provided: Binds and returns validated tool names  # pragma: no mutate

    Args:  # pragma: no mutate
        tool_space: Namespace to search for tools  # pragma: no mutate
        include_subagents: Whether to include subagent results in search  # pragma: no mutate
        limit: Maximum number of tool results for semantic search  # pragma: no mutate
        bindable_tool_names: The set of tool names this agent's graph can actually  # pragma: no mutate
            bind and execute. When set (scoped agents like provider subagents),  # pragma: no mutate
            binding validates against it instead of the global registry, so a tool  # pragma: no mutate
            the graph can't execute is never reported as a successful bind. None ->  # pragma: no mutate
            validate against the global registry (main executor/comms carry it).  # pragma: no mutate

    Returns:  # pragma: no mutate
        Configured retrieve_tools coroutine that returns RetrieveToolsResult  # pragma: no mutate
    """  # pragma: no mutate

    async def retrieve_tools(  # pragma: no mutate
        store: Annotated[BaseStore, InjectedStore],  # pragma: no mutate
        config: RunnableConfig,  # pragma: no mutate
        query: str | None = None,  # pragma: no mutate
        # Non-nullable array on purpose. A `list[str] | None` annotation emits an
        # `anyOf: [{array}, {null}]` JSON schema, and MiniMax M3 cannot populate an
        # array wrapped in that nullable union: it sends `exact_tool_names: []`
        # however many names it intends to bind. A plain array schema fixes it, and
        # "no exact tools" is an empty list, not null, so nothing is lost.
        exact_tool_names: list[str] = Field(default_factory=list),  # pragma: no mutate
    ) -> RetrieveToolsResult:  # pragma: no mutate
        log.info(  # pragma: no mutate
            f"{LogTag.TOOL} retrieve_tools called",  # pragma: no mutate
            query=query,  # pragma: no mutate
            exact_tool_names=exact_tool_names,  # pragma: no mutate
            tool_space=tool_space,  # pragma: no mutate
            include_subagents=include_subagents,  # pragma: no mutate
            user_id=agent_configurable(config).get("user_id")  # pragma: no mutate
            or config.get("metadata", {}).get("user_id"),  # pragma: no mutate
        )  # pragma: no mutate
        if not query and not exact_tool_names:  # pragma: no mutate
            # A no-usable-argument call (commonly retrieve_tools(exact_tool_names=[]),
            # an empty list) must NOT crash the run — that aborts the whole executor
            # turn over a recoverable model slip. Return a corrective hint so the
            # caller self-corrects on its next step instead.
            return RetrieveToolsResult(  # pragma: no mutate
                tools_to_bind=[],  # pragma: no mutate
                response=[  # pragma: no mutate
                    (  # pragma: no mutate
                        "retrieve_tools received no usable argument (an empty "  # pragma: no mutate
                        "exact_tool_names counts as none). Next step: pass "  # pragma: no mutate
                        "query='what you want to do' to discover, or "  # pragma: no mutate
                        "exact_tool_names=['TOOL_NAME'] to bind a known tool. To use a "  # pragma: no mutate
                        "subagent (a 'subagent:' result), do NOT call retrieve_tools "  # pragma: no mutate
                        "again; call handoff(subagent_id='gmail', task='...') directly."  # pragma: no mutate
                    )  # pragma: no mutate
                ],  # pragma: no mutate
            )  # pragma: no mutate

        tool_registry = await get_tool_registry()  # pragma: no mutate
        available_tool_names = tool_registry.get_tool_names()  # pragma: no mutate
        log.info(  # pragma: no mutate
            f"{LogTag.TOOL} Registry available tools",  # pragma: no mutate
            available_tool_count=len(available_tool_names),  # pragma: no mutate
        )  # pragma: no mutate

        # Desktop tools only surface for desktop-app conversations, and only
        # in the main agent context (subagents keep their own tool space).
        conversation_source = ConversationSource.coerce(  # pragma: no mutate
            agent_configurable(config).get("conversation_source")  # pragma: no mutate
        )  # pragma: no mutate
        desktop_enabled = (  # pragma: no mutate
            conversation_source is ConversationSource.DESKTOP and tool_space == "general"  # pragma: no mutate
        )  # pragma: no mutate

        # Get user_id from config (try configurable first, then metadata as fallback)
        user_id = agent_configurable(config).get("user_id")  # pragma: no mutate
        if not user_id:  # pragma: no mutate
            # Fallback to metadata
            user_id = config.get("metadata", {}).get("user_id")  # pragma: no mutate
            if user_id and "configurable" in config:  # pragma: no mutate
                # Update configurable with user_id for consistency
                config["configurable"]["user_id"] = user_id  # pragma: no mutate

        if not user_id:  # pragma: no mutate
            log.warning(  # pragma: no mutate
                f"{LogTag.TOOL} retrieve_tools called with NO user_id (not in configurable or metadata)"  # pragma: no mutate
            )  # pragma: no mutate

        # BINDING MODE: Validate and bind exact tool names
        if exact_tool_names:  # pragma: no mutate
            global_tool_names_set = set(available_tool_names)  # pragma: no mutate
            # Validate against the agent's scoped set, not the global registry —
            # else an out-of-scope tool reports a fake bind the graph then rejects,
            # looping the model bind->reject.
            bindable_set = (  # pragma: no mutate
                bindable_tool_names if bindable_tool_names is not None else global_tool_names_set  # pragma: no mutate
            )  # pragma: no mutate

            mcp_tool_names_set = await _user_mcp_tool_names(user_id)  # pragma: no mutate
            known_by_canonical = canonical_tool_name_map(bindable_set | mcp_tool_names_set)  # pragma: no mutate

            validated_tool_names: list[str] = []  # pragma: no mutate
            unknown_tool_names: list[str] = []  # pragma: no mutate
            out_of_scope_tool_names: list[str] = []  # pragma: no mutate
            requested_subagents: list[str] = []  # pragma: no mutate
            # requested name -> canonical name, for the aliases we silently resolved
            renamed_tools: dict[str, str] = {}
            for tool_name in exact_tool_names:  # pragma: no mutate
                if tool_name.startswith("subagent:"):  # pragma: no mutate
                    # Subagents are handed off to, never bound. When subagents are
                    # available here we surface corrective guidance in the response
                    # instead of echoing the name back as if it bound — that made a
                    # model slip look like a successful bind and relied on downstream
                    # filtering. When subagents aren't available, it's just unknown.
                    if include_subagents:  # pragma: no mutate
                        requested_subagents.append(tool_name)  # pragma: no mutate
                    else:  # pragma: no mutate
                        unknown_tool_names.append(tool_name)  # pragma: no mutate
                elif (  # pragma: no mutate
                    not desktop_enabled  # pragma: no mutate
                    and tool_registry.get_category_of_tool(tool_name) == DESKTOP_TOOL_CATEGORY  # pragma: no mutate
                ):  # pragma: no mutate
                    # Desktop tools must not bind outside desktop sessions —
                    # the tools also re-check the source at execution time.
                    unknown_tool_names.append(tool_name)  # pragma: no mutate
                elif tool_name in bindable_set or tool_name in mcp_tool_names_set:  # pragma: no mutate
                    validated_tool_names.append(tool_name)  # pragma: no mutate
                elif canonical := known_by_canonical.get(tool_name.replace("-", "_")):  # pragma: no mutate
                    validated_tool_names.append(canonical)  # pragma: no mutate
                    if canonical != tool_name:
                        renamed_tools[tool_name] = canonical
                elif tool_name in global_tool_names_set:  # pragma: no mutate
                    # Known globally, but not in this agent's scope.
                    out_of_scope_tool_names.append(tool_name)  # pragma: no mutate
                else:  # pragma: no mutate
                    unknown_tool_names.append(tool_name)  # pragma: no mutate

            if unknown_tool_names:  # pragma: no mutate
                # Surfacing this is important: silently dropping requested tools
                # makes registry-population bugs invisible to operators.
                log.warning(  # pragma: no mutate
                    f"{LogTag.TOOL} retrieve_tools binding dropped unknown tools",  # pragma: no mutate
                    tool_space=tool_space,  # pragma: no mutate
                    unknown=unknown_tool_names,  # pragma: no mutate
                    available_count=len(bindable_set),  # pragma: no mutate
                )  # pragma: no mutate
            if out_of_scope_tool_names:  # pragma: no mutate
                log.warning(  # pragma: no mutate
                    "retrieve_tools binding rejected out-of-scope tools",  # pragma: no mutate
                    tool_space=tool_space,  # pragma: no mutate
                    out_of_scope=out_of_scope_tool_names,  # pragma: no mutate
                )  # pragma: no mutate

            log.set(  # pragma: no mutate
                tool_retrieval=dict(  # pragma: no mutate
                    mode="binding",  # pragma: no mutate
                    tools_requested=len(exact_tool_names),  # pragma: no mutate
                    tools_bound=len(validated_tool_names),  # pragma: no mutate
                    tools_filtered=len(exact_tool_names) - len(validated_tool_names),  # pragma: no mutate
                )  # pragma: no mutate
            )  # pragma: no mutate

            # Bind valid tools regardless; add corrective guidance for subagent /
            # out-of-scope names so the model takes the right path.
            response = list(validated_tool_names)  # pragma: no mutate
            if requested_subagents:  # pragma: no mutate
                response.append(  # pragma: no mutate
                    "Subagents are not bound with retrieve_tools. Call "  # pragma: no mutate
                    "handoff(subagent_id='<id>', task='...') directly, using the "  # pragma: no mutate
                    "part after 'subagent:'."  # pragma: no mutate
                )  # pragma: no mutate
            if out_of_scope_tool_names:  # pragma: no mutate
                response.append(  # pragma: no mutate
                    "These tools are not available inside this subagent and cannot be "  # pragma: no mutate
                    f"bound here: {', '.join(out_of_scope_tool_names)}. They belong to the "  # pragma: no mutate
                    "main executor, not this subagent — do not retry binding them; finish "  # pragma: no mutate
                    "your task here and let the executor handle them."  # pragma: no mutate
                )  # pragma: no mutate

            bind_lines: list[str] = []
            if validated_tool_names:
                bind_lines.append(f"Bound {len(validated_tool_names)} tools — call them directly:")
                bind_lines.extend(f"  - {name}" for name in validated_tool_names)
            if renamed_tools:
                bind_lines.append(
                    "Resolved to their canonical names — use these from now on: "
                    + ", ".join(f"{req} -> {canon}" for req, canon in renamed_tools.items())
                )
            if unknown_tool_names:
                bind_lines.append(
                    f"Not found, nothing bound: {', '.join(unknown_tool_names)}. "
                    "Do not retry these names; run retrieve_tools(query=...) to find "
                    "what actually exists."
                )
            bind_lines.extend(line for line in response if line not in validated_tool_names)

            return RetrieveToolsResult(  # pragma: no mutate
                tools_to_bind=validated_tool_names,  # pragma: no mutate
                response=response,  # pragma: no mutate
                response_text="\n".join(bind_lines),
            )  # pragma: no mutate

        # Get user context (skips subagent computation when include_subagents=False)
        (  # pragma: no mutate
            user_namespaces,  # pragma: no mutate
            connected_integrations,  # pragma: no mutate
            internal_subagents,  # pragma: no mutate
        ) = await _get_user_context(user_id, tool_space, include_subagents)  # pragma: no mutate

        # Build and execute search tasks
        search_tasks = _build_search_tasks(  # pragma: no mutate
            store,  # pragma: no mutate
            query or "",  # pragma: no mutate
            tool_space,  # pragma: no mutate
            user_namespaces,  # pragma: no mutate
            include_subagents,  # pragma: no mutate
            limit,  # pragma: no mutate
            include_desktop=desktop_enabled,  # pragma: no mutate
        )  # pragma: no mutate

        results = await asyncio.gather(*search_tasks, return_exceptions=True)  # pragma: no mutate

        # Surface search failures instead of treating them as empty namespaces.
        # A partial outage degrades to the namespaces that answered; a total
        # outage must raise so the select_tools retry policy (and ultimately
        # the caller) sees a failure, not a silent "no tools found".
        failures = [r for r in results if isinstance(r, BaseException)]  # pragma: no mutate
        for failure in failures:  # pragma: no mutate
            log.error(  # pragma: no mutate
                f"{LogTag.TOOL} retrieve_tools search task failed",  # pragma: no mutate
                error=str(failure),  # pragma: no mutate
                error_type=type(failure).__name__,  # pragma: no mutate
            )  # pragma: no mutate
        if failures and len(failures) == len(results):  # pragma: no mutate
            raise failures[0]  # pragma: no mutate

        # MCP tool names don't live in the global registry anymore (resilience
        # rewrite removed the per-user mcp_{iid}_{user_id} categories). Union
        # the registry names with the user's live MCPClient tool names so the
        # discovery-mode filter doesn't drop every PostHog/Notion/etc. hit.
        available_tool_names_set = set(available_tool_names) | await _user_mcp_tool_names(user_id)  # pragma: no mutate

        chroma_hits = 0  # pragma: no mutate
        public_hits = 0  # pragma: no mutate
        per_namespace_hits: dict[str, int] = {}  # pragma: no mutate
        for result in results:  # pragma: no mutate
            if not isinstance(result, list) or not result:  # pragma: no mutate
                continue  # pragma: no mutate
            if isinstance(result[0], dict):  # pragma: no mutate
                public_hits += len(result)  # pragma: no mutate
                continue  # pragma: no mutate
            chroma_hits += len(result)  # pragma: no mutate
            for item in result:  # pragma: no mutate
                if not hasattr(item, "namespace"):  # pragma: no mutate
                    continue  # pragma: no mutate
                ns = "::".join(item.namespace) if item.namespace else "default"  # pragma: no mutate
                per_namespace_hits[ns] = per_namespace_hits.get(ns, 0) + 1  # pragma: no mutate

        chroma_preview: list[str] = []  # pragma: no mutate
        for result in results:  # pragma: no mutate
            if isinstance(result, list) and result and not isinstance(result[0], dict):  # pragma: no mutate
                for item in result:  # pragma: no mutate
                    if isinstance(item, dict):  # pragma: no mutate
                        namespace = item.get("namespace")  # pragma: no mutate
                        tool_key = item.get("key")  # pragma: no mutate
                    else:  # pragma: no mutate
                        namespace = getattr(item, "namespace", None)  # pragma: no mutate
                        tool_key = getattr(item, "key", None)  # pragma: no mutate
                    if tool_key is None:  # pragma: no mutate
                        continue  # pragma: no mutate
                    chroma_preview.append(f"{namespace}::{tool_key}")  # pragma: no mutate
                    if len(chroma_preview) >= 10:  # pragma: no mutate
                        break  # pragma: no mutate
            if len(chroma_preview) >= 10:  # pragma: no mutate
                break  # pragma: no mutate

        # Process results
        all_results = await _process_search_results(  # pragma: no mutate
            results,  # pragma: no mutate
            available_tool_names_set,  # pragma: no mutate
            tool_registry,  # pragma: no mutate
            include_subagents,  # pragma: no mutate
            tool_space,  # pragma: no mutate
        )  # pragma: no mutate

        # Deduplicate and sort
        discovered_tools = _deduplicate_and_sort(all_results, limit)  # pragma: no mutate

        # Inject available subagents (no-op when include_subagents=False)
        if include_subagents:  # pragma: no mutate
            final_tools = _inject_available_subagents(  # pragma: no mutate
                discovered_tools,  # pragma: no mutate
                internal_subagents,  # pragma: no mutate
                connected_integrations,  # pragma: no mutate
                include_subagents,  # pragma: no mutate
            )  # pragma: no mutate
        else:  # pragma: no mutate
            final_tools = discovered_tools  # pragma: no mutate

        log.set(  # pragma: no mutate
            tool_retrieval=dict(  # pragma: no mutate
                mode="discovery",  # pragma: no mutate
                query=query,  # pragma: no mutate
                tool_space=tool_space,  # pragma: no mutate
                user_id=user_id,  # pragma: no mutate
                namespaces_searched=sorted(user_namespaces),  # pragma: no mutate
                tools_discovered=len(final_tools),  # pragma: no mutate
                chroma_hits=chroma_hits,  # pragma: no mutate
                public_hits=public_hits,  # pragma: no mutate
                per_namespace_hits=per_namespace_hits,  # pragma: no mutate
                candidates_after_filter=len(all_results),  # pragma: no mutate
                chroma_preview=chroma_preview,  # pragma: no mutate
            )  # pragma: no mutate
        )  # pragma: no mutate
        if chroma_hits == 0:
            log.warning(  # pragma: no mutate
                f"{LogTag.TOOL} retrieve_tools: 0 ChromaDB hits — check that index_tools_to_store actually wrote docs for this namespace",  # pragma: no mutate
                tool_space=tool_space,  # pragma: no mutate
                user_id=user_id,  # pragma: no mutate
            )  # pragma: no mutate

        return RetrieveToolsResult(  # pragma: no mutate
            tools_to_bind=[],  # pragma: no mutate
            response=final_tools,  # pragma: no mutate
            response_text=_render_discovery_response(
                final_tools,
                tool_registry,
                connected_integrations,
                internal_subagents,
                query,
                len(all_results),
                limit,
            ),
        )  # pragma: no mutate

    # Assign the LLM-facing docstring from pre-built constants
    if include_subagents:  # pragma: no mutate
        retrieve_tools.__doc__ = _RETRIEVE_TOOLS_BASE_DOC + _RETRIEVE_TOOLS_SUBAGENT_SECTION  # pragma: no mutate
    else:  # pragma: no mutate
        retrieve_tools.__doc__ = _RETRIEVE_TOOLS_BASE_DOC  # pragma: no mutate

    return retrieve_tools  # pragma: no mutate
