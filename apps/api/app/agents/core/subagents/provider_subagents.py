"""
Provider-specific sub-agent implementations.

This module contains the factory methods for creating specialized sub-agent graphs
for different providers (Gmail, Notion, Twitter, LinkedIn, etc.) with full tool
registry and retrieval capabilities.

Subagents are built on-demand each turn. Per-user MCP tools are read live from
MCPClient (the source of truth) rather than copied into a process-global cache.
"""

from collections.abc import Awaitable, Callable

from langgraph.graph.state import CompiledStateGraph

from app.agents.core.subagents.registry import all_subagents, get_subagent_by_id
from app.agents.llm.client import init_llm
from app.agents.tools.cli.cli_tool import build_cli_tool
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
from app.db.repositories.integrations import integration_repository
from app.db.repositories.user_integrations import user_integration_repository
from app.helpers.namespace_utils import derive_integration_namespace
from app.models.subagent_models import Subagent
from app.services.cli.tools import CliIntegration, resolve_cli_integration
from app.services.mcp.mcp_client import get_mcp_client
from shared.py.wide_events import log

from .base_subagent import SubAgentFactory, SubAgentToolConfig


class SubagentUnavailableError(Exception):
    """Raised when a per-user subagent graph cannot be built.

    Carries a user-facing reason (e.g. the MCP server returned 402) so the
    handoff layer can surface *why* instead of a generic "failed to create"
    message. Without this the real cause is logged but lost to the caller.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def register_composio_subagent_tools(subagent: Subagent, tool_registry: ToolRegistry) -> None:
    """Put a Composio subagent's toolkit in the registry, once per process.

    Both the live handoff and a playbook's validator and replay resolve the
    subagent's tool space from the registry, and the toolkit is only there once
    something has loaded it. A worker that has never handed off to this
    subagent has an empty category for it until this runs, which is how a
    replay three minutes after a worker restart found no GMAIL tool at all.

    ``Subagent`` does not carry composio_config; the OAuth integration does
    (composio is OAuth-only). The OAuthIntegration validator enforces
    composio_config when managed_by="composio", so landing here without one
    means a builtin Subagent declared managed_by="composio" and would silently
    produce a tool-less agent. Fail loudly instead.
    """
    integration = get_integration_by_id(subagent.id)
    if integration is None or integration.composio_config is None:
        raise ValueError(
            f"Composio subagent {subagent.id!r} has no matching OAuth "
            f"integration with composio_config. managed_by='composio' "
            f"must correspond to an OAUTH_INTEGRATIONS entry."
        )
    config = subagent.config
    await tool_registry.register_provider_tools(
        toolkit_name=integration.composio_config.toolkit,
        space_name=config.tool_space,
        specific_tools=config.specific_tools,
        exclude_tools=config.exclude_tools,
    )


async def register_cli_subagent_tools(subagent: Subagent, tool_registry: ToolRegistry) -> None:
    """Put a platform CLI integration's single tool in the registry.

    ``Subagent`` does not carry cli_config; the OAuth integration does. The
    OAuthIntegration validator enforces cli_config when managed_by="cli", so
    landing here without one means an entry declared that transport and never
    described the CLI — which would build a tool-less agent that reports
    healthy. Fail loudly instead, exactly as the Composio path does.
    """
    integration = get_integration_by_id(subagent.id)
    if integration is None or integration.cli_config is None:
        raise ValueError(
            f"CLI subagent {subagent.id!r} has no matching OAuth integration "
            f"with cli_config. managed_by='cli' must correspond to an "
            f"OAUTH_INTEGRATIONS entry."
        )
    await register_cli_tools(
        tool_registry,
        CliIntegration(id=subagent.id, name=integration.name, config=integration.cli_config),
        tool_space=subagent.config.tool_space,
    )


async def register_cli_tools(
    tool_registry: ToolRegistry, integration: CliIntegration, tool_space: str
) -> None:
    """Register, once per process, the one tool that runs this integration's CLI.

    A CLI integration is delegated and integration-gated exactly like a Composio
    toolkit, so it gets the same category shape: keyed by integration id, spaced
    by the subagent's tool_space (which is how ``build_scoped_tool_dict`` finds
    it), delegated so the main executor discovers the subagent rather than the
    raw shell, and require_integration so the tools catalog reports it locked
    until the user connects.

    Unlike the per-user MCP tools, this category is process-global on purpose:
    the tool closes over the integration, never over a user, and resolves the
    sandbox and the credentials from the run's user at call time.

    Risk stays with ``integration_destructive_tools`` — uncurated means the HIL
    classifier judges each command at gate time, which is the only workable
    verdict when one tool name covers ``gh pr list`` and ``gh repo delete``
    alike.
    """
    if integration.id in tool_registry._categories:
        return

    tool = build_cli_tool(integration.id, integration.name, integration.config)
    tool_registry._add_category(
        name=integration.id,
        tools=[tool],
        options=CategoryOptions(
            space=tool_space,
            require_integration=True,
            integration_name=integration.id,
            is_delegated=True,
        ),
        risk=CategoryRisk(destructive_tools=integration_destructive_tools(integration.id)),
    )
    await tool_registry._index_category_tools(integration.id)

    log.set(cli={"integration_id": integration.id, "command": integration.config.command})
    log.info(
        f"{LogTag.AGENT} Registered CLI integration tool",
        integration_id=integration.id,
        command=integration.config.command,
        tool_name=tool.name,
        tool_space=tool_space,
    )


def custom_subagent_name(integration_id: str, *, is_cli: bool) -> str:
    """Graph name for a user-created integration's subagent.

    Defined once because the handoff layer derives the same name for its call
    records: two copies of the convention drift the moment a transport is added
    — which is exactly what CLI would have done.
    """
    return f"custom_{'cli' if is_cli else 'mcp'}_{integration_id}"


async def create_subagent(subagent: Subagent) -> CompiledStateGraph:
    """
    Create a provider subagent graph on-demand.
    Registers provider tools to registry if not already present.

    Note: For auth-required MCP integrations, use create_subagent_for_user instead.

    Args:
        subagent: The Subagent to materialize a graph for

    Returns:
        Compiled subagent graph
    """
    config = subagent.config
    tool_registry = await get_tool_registry()

    # Handle internal integrations (like todos) - tools are already registered
    if subagent.managed_by == "internal":
        # Internal integrations use core tools that are registered at startup
        # No additional setup needed - tools are already in the registry
        log.info(
            f"{LogTag.AGENT} Internal integration using pre-registered tools",
            integration_id=subagent.id,
        )

    # Handle MCP-managed integrations (like DeepWiki)
    elif subagent.managed_by == "mcp" and subagent.mcp_config:
        mcp_config = subagent.mcp_config
        category_name = subagent.id

        # Skip auth-required MCPs here - they need user-specific tokens
        # loaded via create_subagent_for_user() with actual user_id
        if mcp_config.requires_auth:
            raise ValueError(
                f"{subagent.id} requires authentication - use create_subagent_for_user"
            )
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

    elif subagent.managed_by == "composio":
        await register_composio_subagent_tools(subagent, tool_registry)

    # CLI integrations: one tool, registered here rather than per user. Whether
    # THIS user may reach it is settled before the graph is asked for — handoff
    # runs the connection check for every non-MCP, non-internal transport.
    elif subagent.managed_by == "cli":
        await register_cli_subagent_tools(subagent, tool_registry)

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


async def create_subagent_for_user(integration_id: str, user_id: str) -> CompiledStateGraph:
    """Build a per-user subagent graph.

    No memoization — every handoff rebuilds the graph from live MCPClient
    state. The build itself is sub-second; the cost that used to motivate
    caching (MCP connect + Chroma indexing) lives in MCPClient, which keeps
    warm sessions per integration for the worker's lifetime.
    """
    return await _build_user_subagent(integration_id, user_id)


async def _build_user_subagent(integration_id: str, user_id: str) -> CompiledStateGraph:
    """Build a per-user subagent graph for an MCP integration.

    Pulls live tools from MCPClient. Lazy-connects on first use per integration;
    subsequent builds reuse the warm session. No registry-side state is written
    — tool objects only live inside MCPClient.
    """
    subagent = get_subagent_by_id(integration_id)

    # Custom integrations from MongoDB (not in static registry) — IDs can be
    # 'custom_' prefixed or 12-char hex. A CLI-backed one is dispatched on its
    # spec here rather than inside the MCP builder, so that builder keeps owning
    # exactly one transport.
    if not subagent:
        cli_integration = await resolve_cli_integration(integration_id)
        if cli_integration is not None:
            return await _create_custom_cli_subagent(cli_integration, user_id)
        return await _create_custom_mcp_subagent(integration_id, user_id)

    mcp_config = subagent.mcp_config
    if not (subagent.managed_by == "mcp" and mcp_config):
        log.error(
            f"{LogTag.AGENT} Integration is not an MCP integration", integration_id=integration_id
        )
        raise SubagentUnavailableError(f"{integration_id} is not an MCP integration")

    config = subagent.config
    mcp_client = await get_mcp_client(user_id=user_id)

    if subagent.id in mcp_client._tools:
        tools = mcp_client._tools[subagent.id]
        log.info(
            f"{LogTag.AGENT} _build_user_subagent using warm MCPClient tools",
            integration_id=integration_id,
            user_id=user_id,
            tool_count=len(tools),
        )
    else:
        try:
            tools = await mcp_client.connect(subagent.id)
            log.info(
                f"{LogTag.AGENT} _build_user_subagent cold connect succeeded",
                integration_id=integration_id,
                user_id=user_id,
                tool_count=len(tools),
            )
        except Exception as e:
            log.error(
                f"{LogTag.AGENT} _build_user_subagent connect failed",
                integration_id=integration_id,
                user_id=user_id,
                error_type=type(e).__name__,
                error=str(e),
            )
            raise SubagentUnavailableError(str(e)) from e

    if not tools:
        log.error(
            f"{LogTag.AGENT} _build_user_subagent got no tools — cannot create subagent",
            integration_id=integration_id,
            user_id=user_id,
        )
        raise SubagentUnavailableError(f"{integration_id} exposed no usable tools")

    llm = init_llm()

    log.set(subagent={"name": config.agent_name, "provider": subagent.provider})
    log.info(
        f"{LogTag.AGENT} Creating user-specific subagent",
        agent_name=config.agent_name,
        user_id=user_id,
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
            mcp_tools=tools,
            source_label=subagent.name,
        ),
    )

    log.info(
        f"{LogTag.AGENT} User-specific subagent created successfully",
        agent_name=config.agent_name,
        user_id=user_id,
    )
    return graph


async def _create_custom_mcp_subagent(integration_id: str, user_id: str) -> CompiledStateGraph:
    """Build a subagent graph for a custom MCP integration from MongoDB.

    Pulls live tools from MCPClient (lazy-connects on first use). Namespace
    derives from the custom integration's server URL.
    """
    custom_doc = await integration_repository.get(integration_id)
    if not custom_doc:
        log.error(
            f"{LogTag.AGENT} Custom integration not found in MongoDB",
            integration_id=integration_id,
            user_id=user_id,
        )
        raise SubagentUnavailableError(f"Custom integration {integration_id} not found")

    server_url = custom_doc.mcp_config.server_url if custom_doc.mcp_config else ""
    tool_namespace = derive_integration_namespace(integration_id, server_url, is_custom=True)

    mcp_client = await get_mcp_client(user_id=user_id)

    if integration_id in mcp_client._tools:
        tools = mcp_client._tools[integration_id]
    else:
        try:
            tools = await mcp_client.connect(integration_id)
        except Exception as e:
            log.error(
                f"{LogTag.AGENT} Failed to get MCP tools",
                integration_id=integration_id,
                user_id=user_id,
                error_type=type(e).__name__,
                error=str(e),
            )
            raise SubagentUnavailableError(str(e)) from e

    if not tools:
        log.error(
            f"{LogTag.AGENT} No tools available for custom integration",
            integration_id=integration_id,
            user_id=user_id,
        )
        raise SubagentUnavailableError(f"{integration_id} exposed no usable tools")

    llm = init_llm()
    agent_name = custom_subagent_name(integration_id, is_cli=False)

    log.set(subagent={"name": agent_name, "provider": integration_id})

    # Dynamic tool-count override: if actual tool count is small (1-10),
    # bind all tools directly and skip retrieve_tools for lower latency.
    tool_count = len(tools)
    use_direct = 0 < tool_count <= 10

    log.info(
        f"{LogTag.AGENT} Custom MCP tool binding mode resolved",
        integration_id=integration_id,
        tool_count=tool_count,
        direct_binding=use_direct,
    )

    graph = await SubAgentFactory.create_provider_subagent(
        provider=integration_id,
        llm=llm,
        name=agent_name,
        config=SubAgentToolConfig(
            tool_space=tool_namespace,
            use_direct_tools=use_direct,
            disable_retrieve_tools=use_direct,
            mcp_tools=tools,
            source_label=custom_doc.name,
        ),
    )

    log.info(
        f"{LogTag.AGENT} Custom MCP subagent created successfully",
        agent_name=agent_name,
        integration_id=integration_id,
        user_id=user_id,
    )
    return graph


async def _create_custom_cli_subagent(
    integration: CliIntegration, user_id: str
) -> CompiledStateGraph:
    """Build a subagent graph for a user-created CLI integration from MongoDB.

    The connection check lives here because this is the only place it can: a
    platform CLI integration is gated by handoff before its graph is ever asked
    for, but a custom one is resolved straight out of Mongo and never passes
    that check. Skipping it would hand the model a CLI that is installed and
    signed in for nobody, and the failure would surface as vendor auth errors
    rather than "connect this first".

    The integration's id is its namespace: unlike a custom MCP there is no
    server URL to derive one from, and the id is already unique per document.
    """
    if not await user_integration_repository.is_connected(user_id, integration.id):
        log.warning(
            f"{LogTag.AGENT} Custom CLI subagent refused: integration not connected",
            integration_id=integration.id,
            user_id=user_id,
        )
        # Dash-free: this reason is relayed to the model verbatim by handoff.
        raise SubagentUnavailableError(
            f"{integration.name} is not connected. Ask the user to connect it first."
        )

    tool_registry = await get_tool_registry()
    await register_cli_tools(tool_registry, integration, tool_space=integration.id)

    llm = init_llm()
    agent_name = custom_subagent_name(integration.id, is_cli=True)

    log.set(subagent={"name": agent_name, "provider": integration.id})
    log.info(
        f"{LogTag.AGENT} Creating custom CLI subagent",
        agent_name=agent_name,
        integration_id=integration.id,
        command=integration.config.command,
        user_id=user_id,
    )

    graph = await SubAgentFactory.create_provider_subagent(
        provider=integration.id,
        llm=llm,
        name=agent_name,
        config=SubAgentToolConfig(
            tool_space=integration.id,
            # One tool, so retrieval can only ever return that same tool: bind
            # it up front and skip the round trip.
            use_direct_tools=True,
            disable_retrieve_tools=True,
            source_label=integration.name,
        ),
    )

    log.info(
        f"{LogTag.AGENT} Custom CLI subagent created successfully",
        agent_name=agent_name,
        integration_id=integration.id,
        user_id=user_id,
    )
    return graph


def _make_subagent_loader(
    subagent: Subagent,
) -> Callable[[], Awaitable[CompiledStateGraph]]:
    """Bind the subagent into a zero-arg async loader for `providers.register`."""

    async def _loader() -> CompiledStateGraph:
        return await create_subagent(subagent)

    return _loader


def register_subagent_providers(integration_ids: list[str] | None = None) -> int:
    """
    Register lazy providers for all subagents (OAuth-derived + builtins).
    Subagents are created on-demand when first accessed via providers.

    Note: Auth-required MCP subagents are NOT registered here - they are created
    on-the-fly via create_subagent_for_user() when the handoff tool is invoked.

    Args:
        integration_ids: Optional list of specific subagent IDs to register.
                        If None, registers all subagents.

    Returns:
        Number of registered subagent providers.
    """
    registered_count = 0

    for subagent in all_subagents():
        # Skip if not in the requested list (when list is provided)
        if integration_ids is not None and subagent.id not in integration_ids:
            continue

        # Skip auth-required MCP integrations - they are created on-the-fly
        # via create_subagent_for_user() when the handoff tool is invoked
        if (
            subagent.managed_by == "mcp"
            and subagent.mcp_config
            and subagent.mcp_config.requires_auth
        ):
            log.info(
                f"{LogTag.AGENT} Auth-required MCP subagent will be created on-demand via handoff",
                agent_name=subagent.config.agent_name,
            )
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
