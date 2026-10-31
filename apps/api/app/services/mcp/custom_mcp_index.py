"""Index a connected custom MCP into the store's ``subagents`` namespace for discovery."""

from dataclasses import dataclass

from langchain_core.tools import BaseTool
from langgraph.store.base import BaseStore, PutOp

from app.constants.log_tags import LogTag
from app.helpers.namespace_utils import derive_integration_namespace
from shared.py.wide_events import log

SUBAGENTS_NAMESPACE = ("subagents",)


@dataclass(frozen=True)
class CustomMcpIndexRequest:
    """The custom-MCP identity/description cluster indexed for discovery.

    Args:
        integration_id: Unique ID of the custom integration (12-char hex)
        name: Display name of the integration
        description: Description of what the integration does
        server_url: MCP server URL for namespace derivation
        tools: The MCP's tools — their names/summaries are embedded so the
            integration ranks for what it can actually do (e.g. a "get_meetings"
            tool surfaces on a "meetings" query) instead of generic boilerplate.
    """

    integration_id: str
    name: str
    description: str
    server_url: str | None = None
    tools: list[BaseTool] | None = None


async def index_custom_mcp_as_subagent(
    store: BaseStore,
    request: CustomMcpIndexRequest,
) -> None:
    """Index a custom MCP so semantic search finds it as soon as the user connects it."""
    integration_id = request.integration_id
    name = request.name
    description = request.description
    server_url = request.server_url
    tools = request.tools

    parts = [f"{name}."]
    if description:
        parts.append(f"{description}.")
    if tools:
        summaries = []
        for t in tools:
            first_line = (t.description or "").strip().splitlines()
            summary = first_line[0][:120] if first_line else ""
            summaries.append(f"{t.name}: {summary}" if summary else t.name)
        parts.append(f"Available tools: {'; '.join(summaries)}.")
    rich_description = " ".join(parts)

    tool_namespace = derive_integration_namespace(integration_id, server_url, is_custom=True)

    put_op = PutOp(
        namespace=SUBAGENTS_NAMESPACE,
        key=integration_id,
        value={
            "id": integration_id,
            "name": name,
            "description": rich_description,
            "source": "custom",
            "tool_namespace": tool_namespace,
        },
        index=["description"],
    )

    await store.abatch([put_op])
    log.info(
        f"{LogTag.AGENT} Indexed custom MCP as subagent",
        integration_name=name,
        integration_id=integration_id,
        tool_count=len(tools or []),
    )
