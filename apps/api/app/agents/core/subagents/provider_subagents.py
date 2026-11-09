"""
Provider-specific sub-agent implementations.

This module contains the factory methods for creating specialized sub-agent graphs
for different providers (Gmail, Notion, Twitter, LinkedIn, etc.) with full tool
registry and retrieval capabilities.

Subagents are built on-demand each turn. Per-user MCP integrations have no graph
here: their tools live in the user's MCPClient and run through execute.
"""

from collections.abc import Awaitable, Callable

from langgraph.graph.state import CompiledStateGraph

from app.agents.core.subagents.registry import all_subagents
from app.agents.llm.client import init_llm
from app.agents.tools.core.registry import (
    CategoryOptions,
    CategoryRisk,
    ToolRegistry,
    get_tool_registry,
    integration_destructive_tools,
)
from app.config.oauth_config import get_integration_by_id
from app.constants.log_tags import LogTag
from app.core.lazy_loader import providers
from app.models.subagent_models import Subagent
from app.services.mcp.mcp_client import get_mcp_client
from shared.py.wide_events import log

from .base_subagent import SubAgentFactory, SubAgentToolConfig


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


async def create_subagent(subagent: Subagent) -> CompiledStateGraph:
    """Create a provider subagent graph on-demand, registering its tools if absent."""
    config = subagent.config
    await register_integration_tools(subagent)

    llm = init_llm()

    log.set(subagent={"name": config.agent_name, "provider": subagent.provider})
    log.info(
        f"{LogTag.AGENT} Creating subagent on-demand",
        agent_name=config.agent_name,
        tool_space=config.tool_space,
    )

    graph = await SubAgentFactory.create_provider_subagent(
        provider=subagent.provider,
        llm=llm,
        name=config.agent_name,
        config=SubAgentToolConfig(
            tool_space=config.tool_space,
            use_direct_tools=config.use_direct_tools,
            disable_retrieve_tools=config.disable_retrieve_tools,
            auto_bind_tools=config.auto_bind_tools,
            extra_initial_tools=config.extra_initial_tools,
            include_finish_task=config.include_finish_task,
            source_label=subagent.name,
        ),
    )

    log.info(f"{LogTag.AGENT} Subagent created successfully", agent_name=config.agent_name)
    return graph


def _make_subagent_loader(
    subagent: Subagent,
) -> Callable[[], Awaitable[CompiledStateGraph]]:
    """Bind the subagent into a zero-arg async loader for providers.register."""

    async def _loader() -> CompiledStateGraph:
        return await create_subagent(subagent)

    return _loader


def register_subagent_providers(integration_ids: list[str] | None = None) -> int:
    """Register lazy providers for all subagents (OAuth-derived + builtins).

    Subagents are created on-demand when first accessed via providers.
    Auth-required MCP integrations are not registered: they have no shared
    graph, and activate_integration loads their per-user tools instead.
    """
    registered_count = 0

    for subagent in all_subagents():
        # Skip if not in the requested list (when list is provided)
        if integration_ids is not None and subagent.id not in integration_ids:
            continue

        # An unavailable integration is listed but not dialable; registering it
        # makes startup connect to an endpoint that cannot answer.
        if not subagent.available:
            continue

        if (
            subagent.managed_by == "mcp"
            and subagent.mcp_config
            and subagent.mcp_config.requires_auth
        ):
            continue

        agent_name = subagent.config.agent_name

        # mypy can't solve TypeVar T on the Union loader signature
        # against a concrete async function; cast keeps the loader's
        # actual return type while satisfying the registry overload.
        providers.register(
            name=agent_name,
            loader_func=_make_subagent_loader(subagent),  # type: ignore[arg-type]  # register()'s TypeVar'd loader signature won't unify against a concrete async callable
            required_keys=[],
        )
        registered_count += 1

    log.info(
        f"{LogTag.AGENT} Registered subagent lazy providers", registered_count=registered_count
    )
    return registered_count
