"""Discovery tools the comms agent runs itself, without the executor.

Two questions used to cost a round trip through ``call_executor``: "is there a
Notion integration?" and "is there a ready-made workflow for X?". Both are
read-only catalogue lookups with no side effects.

Neither does work on the user's data, so putting them on the front door does
not breach the "delegate every real ask" rule: they read catalogues. Connecting
an integration is not one of them -- that goes to the executor, whose
``connect_integration`` tool and integration checker are the one card source.
"""

from typing import Annotated, Any, TypedDict

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.config.settings import settings
from app.constants.log_tags import LogTag
from app.db.repositories.workflows import workflow_repository
from app.decorators import with_doc
from app.helpers.integration_helpers import build_search_patterns
from app.models.agent_models import agent_configurable
from app.services.integrations.integration_search import (
    match_my_integrations,
    match_public_integrations,
)
from app.templates.docstrings.discovery_tool_docs import (
    FIND_INTEGRATION,
    SEARCH_PUBLIC_WORKFLOWS,
)
from shared.py.wide_events import log

# Five is what a chat reply can carry without turning into a catalogue dump; the
# model picks one rather than listing everything it found.
MAX_DISCOVERY_RESULTS = 5


class IntegrationMatch(TypedDict):
    """One integration the user could use, and whether they already can."""

    id: str
    name: str
    description: str
    connected: bool
    source: str


class PublicWorkflowMatch(TypedDict):
    """One public workflow template the user could add from the explore page."""

    title: str
    description: str
    source_integration: str | None
    slug: str | None


def _user_id_from(config: RunnableConfig) -> str | None:
    configurable = agent_configurable(config)
    return configurable.get("user_id") if configurable else None


def _one_line(text: str | None) -> str:
    """First sentence-ish line of a catalogue description, never a paragraph."""
    collapsed = " ".join((text or "").split())
    return collapsed[:160]


@tool
@with_doc(FIND_INTEGRATION)
async def find_integration(
    config: RunnableConfig,
    query: Annotated[
        str,
        "What the user is looking for: a product name ('notion', 'slack') or a "
        "capability ('email', 'crm', 'project management').",
    ],
) -> dict[str, Any]:
    """Search GAIA's built-in integrations and the public marketplace."""
    try:
        log.set(tool={"name": "find_integration", "action": "search"})
        user_id = _user_id_from(config)
        if not user_id:
            return {"error": "User ID not found in configuration.", "query": query}

        # The user's own catalogue first: those are the ones that can actually
        # be connected, so a hit there beats a marketplace one.
        matches: list[IntegrationMatch] = [
            {
                "id": item.id,
                "name": item.name,
                "description": _one_line(item.description),
                "connected": item.status == "connected",
                "source": item.source,
            }
            for item in (await match_my_integrations(user_id, query))[:MAX_DISCOVERY_RESULTS]
        ]

        if len(matches) < MAX_DISCOVERY_RESULTS:
            matches.extend(
                {
                    "id": item.integration_id,
                    "name": item.name,
                    "description": _one_line(item.description),
                    "connected": False,
                    "source": "community",
                }
                for item in await match_public_integrations(
                    query,
                    exclude_ids={m["id"] for m in matches},
                    limit=MAX_DISCOVERY_RESULTS - len(matches),
                )
            )

        log.set_ns("tool", result_count=len(matches))
        return {"integrations": matches, "query": query}

    except Exception as e:
        log.error(f"{LogTag.TOOL} Error finding integrations", error_type=type(e).__name__)
        return {"error": f"Could not search integrations: {e!s}", "query": query}


@tool
@with_doc(SEARCH_PUBLIC_WORKFLOWS)
async def search_public_workflows(
    config: RunnableConfig,  # noqa: ARG001 -- tool contract; the catalogue is public
    query: Annotated[
        str,
        "The outcome the user wants a template for, e.g. 'weekly investor "
        "update', 'morning briefing', 'triage my inbox'.",
    ],
) -> dict[str, Any]:
    """Search the featured and community public workflow templates."""
    explore_url = f"{settings.FRONTEND_URL.rstrip('/')}/workflows"
    try:
        log.set(tool={"name": "search_public_workflows", "action": "search"})
        rows = await workflow_repository.find_public_matching(
            build_search_patterns(query), limit=MAX_DISCOVERY_RESULTS
        )
        matches: list[PublicWorkflowMatch] = [
            {
                "title": row.title,
                "description": _one_line(row.description),
                "source_integration": row.source_integration,
                "slug": row.slug,
            }
            for row in rows
        ]
        log.set_ns("tool", result_count=len(matches))
        return {"workflows": matches, "query": query, "explore_url": explore_url}

    except Exception as e:
        log.error(f"{LogTag.TOOL} Error searching public workflows", error_type=type(e).__name__)
        return {
            "error": f"Could not search public workflows: {e!s}",
            "query": query,
            "explore_url": explore_url,
        }
