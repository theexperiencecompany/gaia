"""Load a platform integration's tools into the process-wide tool registry.

activate_integration calls this to make an integration's tools retrievable and
execute-routable. Per-user (auth-required) MCP integrations never come here:
their tools live in the user's MCPClient.
"""

from app.agents.tools.core.registry import (
    CategoryOptions,
    CategoryRisk,
    ToolRegistry,
    get_tool_registry,
    integration_destructive_tools,
)
from app.config.oauth_config import get_integration_by_id
from app.constants.log_tags import LogTag
from app.models.subagent_models import Subagent
from app.services.mcp.mcp_client import get_mcp_client
from shared.py.wide_events import log


async def register_composio_subagent_tools(subagent: Subagent, tool_registry: ToolRegistry) -> str:
    """Put a Composio subagent's toolkit in the registry once per process; return its name.

    The tool space is empty until this runs. Landing here without composio_config
    means managed_by="composio" was misdeclared, so fail loudly rather than
    produce a tool-less agent.
    """
    integration = get_integration_by_id(subagent.id)
    if integration is None or integration.composio_config is None:
        raise ValueError(
            f"Composio subagent {subagent.id!r} has no matching OAuth "
            f"integration with composio_config. managed_by='composio' "
            f"must correspond to an OAUTH_INTEGRATIONS entry."
        )
    config = subagent.config
    toolkit_name = integration.composio_config.toolkit
    await tool_registry.register_provider_tools(
        toolkit_name=toolkit_name,
        space_name=config.tool_space,
        specific_tools=config.specific_tools,
        exclude_tools=config.exclude_tools,
    )
    return toolkit_name


async def register_integration_tools(subagent: Subagent) -> str | None:
    """Load an integration's tools into the global registry, and name their category.

    The single place an integration's tools become bindable. Returns the registry
    category holding them, or None for integrations with no category of their own.
    Auth-required MCP integrations raise here: their tools are per-user, inside
    MCPClient, and never enter the global registry.
    """
    config = subagent.config
    tool_registry = await get_tool_registry()

    if subagent.managed_by == "mcp" and subagent.mcp_config:
        if subagent.mcp_config.requires_auth:
            raise ValueError(
                f"{subagent.id} requires authentication; its tools live in the user's MCPClient"
            )
        category_name = subagent.id
        if category_name not in tool_registry._categories:
            mcp_client = await get_mcp_client(user_id="_system")
            tools = await mcp_client.connect(subagent.id)
            if tools:
                tool_registry._add_category(
                    name=category_name,
                    tools=tools,
                    options=CategoryOptions(
                        space=config.tool_space,
                        integration_name=subagent.id,
                    ),
                    risk=CategoryRisk(destructive_tools=integration_destructive_tools(subagent.id)),
                )
                await tool_registry._index_category_tools(category_name)
                log.info(
                    f"{LogTag.AGENT} Registered MCP tools",
                    tool_count=len(tools),
                    integration_id=subagent.id,
                )
        return category_name

    if subagent.managed_by == "composio":
        return await register_composio_subagent_tools(subagent, tool_registry)

    return None
