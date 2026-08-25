"""Workflow tools for the executor and the workflow assistant.

`search_triggers` and `list_workflows` are shared with the executor. The
`get_my_integrations`, `search_integrations`, and `search_integration_tools`
discovery tools are workflow-assistant only: they let it ground a draft in what
THIS user actually has (built-in + their own custom integrations, with
connection status), what they could add (the public marketplace), and in real
tool capabilities, instead of having the whole catalog injected up front.
"""

import asyncio
from typing import Annotated, Any

from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import tool
from langgraph.config import get_stream_writer

from app.constants.integrations import (
    MAX_INTEGRATION_SEARCH_RESULTS,
    MAX_INTEGRATION_TOOLS_FOR_LLM,
    MAX_MY_INTEGRATIONS_RESULTS,
)
from app.constants.log_tags import LogTag
from app.decorators import with_rate_limiting
from app.helpers.integration_helpers import build_search_matcher
from app.schemas.integrations.responses import IntegrationTool, MyIntegrationItem
from app.services.integrations.community_service import list_community_integrations
from app.services.integrations.my_integrations import (
    get_my_integrations as fetch_my_integrations,
)
from app.services.tools.tools_service import get_integration_tool_list
from app.services.workflow.service import WorkflowService
from app.services.workflow.trigger_search import TriggerSearchService
from app.utils.workflow_utils import (
    error_response,
    get_user_id,
    success_response,
)
from shared.py.wide_events import log


def _resolve_integration(
    items: list[MyIntegrationItem], identifier: str
) -> MyIntegrationItem | None:
    """Find one of the user's integrations by id or name (case-insensitive)."""
    key = identifier.lower().strip()
    for item in items:
        if item.id.lower() == key or item.name.lower() == key:
            return item
    return None


@tool
async def search_triggers(
    config: RunnableConfig,
    query: Annotated[str, "Describe when the workflow should trigger"],
    limit: Annotated[int, "Max number of results to return"] = 15,
) -> dict[str, Any]:
    """
    Search for integration triggers matching your description.

    Returns triggers with their configuration schema embedded (config_fields).
    Use this to find appropriate triggers before creating a workflow.
    """
    try:
        log.set(tool={"name": "search_triggers", "action": "search"})
        user_id = get_user_id(config)

        results = await TriggerSearchService.search(
            query=query,
            user_id=user_id,
            limit=limit,
        )

        connected = [t for t in results if t.get("is_connected")]
        not_connected = [t for t in results if not t.get("is_connected")]

        return success_response(
            {
                "triggers": results,
                "connected_count": len(connected),
                "not_connected_count": len(not_connected),
            }
        )

    except Exception as e:
        log.error(f"{LogTag.TOOL} Error searching triggers", error_type=type(e).__name__)
        return error_response("search_failed", str(e))


@tool
@with_rate_limiting("workflow_operations")
async def list_workflows(
    config: RunnableConfig,
    page: Annotated[int, "1-indexed page number"] = 1,
    page_size: Annotated[int, "Workflows per page (1-50)"] = 20,
) -> dict[str, Any]:
    """List the user's workflows, newest first, one page at a time.

    Returns a page of workflow summaries plus `page`, `page_size`, `total`, and
    `has_more`. Use this to find a workflow's id before pausing, resuming, or
    editing it. Increment `page` to see more.
    """
    try:
        page = max(1, page)
        page_size = max(1, min(page_size, 50))
        offset = (page - 1) * page_size

        log.set(tool={"name": "list_workflows", "action": "list", "page": page})
        user_id = get_user_id(config)
        workflows, total = await WorkflowService.list_workflows(
            user_id, limit=page_size, offset=offset
        )

        workflow_summaries = [
            {
                "id": w.id,
                "title": w.title,
                "description": w.description[:100] + "..."
                if len(w.description) > 100
                else w.description,
                "trigger_type": w.trigger_config.type,
                "activated": w.activated,
                "step_count": len(w.steps),
                "total_executions": w.total_executions,
            }
            for w in workflows
        ]

        # Measured against the page window, not the surviving summaries: a
        # malformed document dropped during validation shrinks the page but does
        # not mean the collection has more pages than it does.
        has_more = offset + page_size < total
        payload = {
            "workflows": workflow_summaries,
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": has_more,
        }

        writer = get_stream_writer()
        writer({"workflow_list": {"action": "list", **payload}})

        return success_response(payload)

    except Exception as e:
        log.error(f"{LogTag.TOOL} Error listing workflows", error_type=type(e).__name__)
        return error_response("fetch_failed", str(e))


@tool
async def get_my_integrations(
    config: RunnableConfig,
    query: Annotated[
        str | None,
        "Filter to integrations matching this text (e.g. 'email', 'github'). "
        "Omit to list them all.",
    ] = None,
) -> dict[str, Any]:
    """List the integrations THIS user has: built-in and their own custom ones, each connected or not.

    Call this FIRST to see what the workflow can build on and to decide which
    integrations it depends on (record those in integration_ids, connected or
    not). To find an integration the user does NOT have, use search_integrations.
    """
    try:
        log.set(tool={"name": "get_my_integrations", "action": "list"})
        user_id = get_user_id(config)
        mine = (await fetch_my_integrations(user_id)).integrations

        matches = build_search_matcher(query)

        def _match(item: MyIntegrationItem) -> bool:
            return matches(f"{item.id} {item.name} {item.category} {item.description}".lower())

        matched = [i for i in mine if i.available and _match(i)]
        # Connected first: if the cap ever bites, what gets dropped is an
        # integration the user has not set up, never one they can already use.
        matched.sort(key=lambda i: i.status != "connected")
        capped = matched[:MAX_MY_INTEGRATIONS_RESULTS]
        integrations = [
            {
                "id": i.id,
                "name": i.name,
                "category": i.category,
                "description": i.description,
                "connected": i.status == "connected",
                "source": i.source,
            }
            for i in capped
        ]
        return success_response(
            {
                "integrations": integrations,
                "connected_count": sum(1 for i in integrations if i["connected"]),
                "truncated": len(matched) > len(capped),
                "query": query,
            }
        )

    except Exception as e:
        log.error(
            f"{LogTag.TOOL} Error listing the user's integrations", error_type=type(e).__name__
        )
        return error_response("fetch_failed", str(e))


@tool
async def search_integrations(
    config: RunnableConfig,
    query: Annotated[
        str,
        "What kind of integration to find in the public marketplace "
        "(e.g. 'project management', 'CRM', 'calendar').",
    ],
) -> dict[str, Any]:
    """Search the PUBLIC integration marketplace for something the user could add.

    Use this ONLY when the workflow needs an integration the user does not already
    have (check get_my_integrations first). Returns public integrations the user
    can connect; ones they already have are filtered out. Suggest adding one only
    when the request strictly needs it.
    """
    try:
        log.set(tool={"name": "search_integrations", "action": "search_public"})
        user_id = get_user_id(config)
        owned_ids = {i.id.lower() for i in (await fetch_my_integrations(user_id)).integrations}

        # Over-fetch by the owned count, then cap after filtering: owned integrations
        # ranking above the limit must not crowd out valid unowned matches.
        community = await list_community_integrations(
            search=query, limit=MAX_INTEGRATION_SEARCH_RESULTS + len(owned_ids)
        )
        results = [
            {
                "id": c.integration_id,
                "name": c.name,
                "category": c.category,
                "description": c.description,
                "connected": False,
                "source": "public",
            }
            for c in community.integrations
            if c.integration_id.lower() not in owned_ids
        ][:MAX_INTEGRATION_SEARCH_RESULTS]
        return success_response({"integrations": results, "query": query})

    except Exception as e:
        log.error(f"{LogTag.TOOL} Error searching public integrations", error_type=type(e).__name__)
        return error_response("search_failed", str(e))


@tool
async def search_integration_tools(
    config: RunnableConfig,
    integration_id: Annotated[
        str | None,
        "Restrict to one integration's tools (its id or name, e.g. 'gmail'). Strongly recommended.",
    ] = None,
    query: Annotated[
        str | None,
        "Filter tools by what they do (e.g. 'send message', 'create issue'). "
        "Omit to list all of the integration's tools. Required if no "
        "integration_id is given.",
    ] = None,
) -> dict[str, Any]:
    """Inspect an integration's tools to understand what it can DO.

    Use this to confirm an integration can actually perform a step before you put
    it in the workflow, and to size up its capabilities. Do NOT copy these tool
    names into the workflow prompt: describe the action in plain language and let
    the executor pick the right tool at run time. Pass integration_id to list that
    integration's tools (optionally narrowed by query); pass only a query to scan
    across the user's connected integrations. You must provide one of them.
    """
    try:
        log.set(tool={"name": "search_integration_tools", "action": "search"})
        user_id = get_user_id(config)

        has_integration = bool(integration_id and integration_id.strip())
        has_query = bool(query and query.strip())
        if not has_integration and not has_query:
            return error_response(
                "missing_argument",
                "Pass integration_id (an integration to inspect) or query (what the tool should do).",
            )

        mine = (await fetch_my_integrations(user_id)).integrations
        matches = build_search_matcher(query)

        def _tool_matches(integration_tool: IntegrationTool) -> bool:
            return matches(f"{integration_tool.name} {integration_tool.description or ''}".lower())

        if integration_id and integration_id.strip():
            integration = _resolve_integration(mine, integration_id)
            if integration is None:
                return error_response(
                    "not_found",
                    f"No integration matches {integration_id!r}. Use "
                    "search_integrations to find the right id.",
                )
            tool_list = await get_integration_tool_list(integration.id)
            matched = [t for t in tool_list if _tool_matches(t)]
            return success_response(
                {
                    "integration_id": integration.id,
                    "integration_name": integration.name,
                    "connected": integration.status == "connected",
                    "tools": [
                        {"name": t.name, "description": t.description}
                        for t in matched[:MAX_INTEGRATION_TOOLS_FOR_LLM]
                    ],
                    "truncated": len(matched) > MAX_INTEGRATION_TOOLS_FOR_LLM,
                }
            )

        # Query only: scan across the user's connected integrations.
        connected = [i for i in mine if i.status == "connected"]
        tool_lists = await asyncio.gather(
            *(get_integration_tool_list(i.id) for i in connected),
            return_exceptions=True,
        )
        results: list[dict[str, Any]] = []
        for integration, tools_or_error in zip(connected, tool_lists, strict=True):
            if isinstance(tools_or_error, BaseException):
                log.warning(
                    f"{LogTag.TOOL} Could not list tools for integration",
                    integration_id=integration.id,
                    error_type=type(tools_or_error).__name__,
                )
                continue
            for integration_tool in tools_or_error:
                if _tool_matches(integration_tool):
                    results.append(
                        {
                            "name": integration_tool.name,
                            "description": integration_tool.description,
                            "integration_id": integration.id,
                            "integration_name": integration.name,
                        }
                    )

        return success_response(
            {
                "tools": results[:MAX_INTEGRATION_TOOLS_FOR_LLM],
                "truncated": len(results) > MAX_INTEGRATION_TOOLS_FOR_LLM,
                "searched_integrations": [i.id for i in connected],
                "query": query,
            }
        )

    except Exception as e:
        log.error(f"{LogTag.TOOL} Error searching integration tools", error_type=type(e).__name__)
        return error_response("search_failed", str(e))


SUBAGENT_WORKFLOW_TOOLS = [
    search_triggers,
    list_workflows,
    get_my_integrations,
    search_integrations,
    search_integration_tools,
]


__all__ = [
    "SUBAGENT_WORKFLOW_TOOLS",
    "get_my_integrations",
    "list_workflows",
    "search_integration_tools",
    "search_integrations",
    "search_triggers",
]
