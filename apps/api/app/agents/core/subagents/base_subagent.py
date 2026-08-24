"""Factory for provider-specific sub-agents.

Subagents are standalone graphs with their own checkpointers, invoked via the
tool-calling pattern like executor_agent. Each runs memory_node as an
end_graph_hook to learn user memories (IDs, preferences, contacts) per user.
"""

import asyncio
from collections.abc import Mapping

from langchain_core.language_models import LanguageModelLike
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.state import CompiledStateGraph

from app.agents.core.graph_builder.checkpointer_manager import get_checkpointer_manager
from app.agents.core.nodes import memory_node
from app.agents.core.nodes.pre_model_hooks import worker_pre_model_hooks
from app.agents.core.subagents.spawn_agent import get_spawn_graph
from app.agents.middleware import SubagentMiddleware, create_subagent_middleware
from app.agents.tools.coding import bash, grep, query_json, read
from app.agents.tools.core.registry import ToolRegistry, get_tool_registry
from app.agents.tools.core.store import get_tools_store
from app.agents.tools.core.tool_runtime_config import (
    build_child_tool_runtime_config,
    build_create_agent_tool_kwargs,
    build_provider_parent_tool_runtime_config,
)
from app.agents.tools.finish_task_tool import finish_task
from app.agents.tools.integration_instructions_tools import update_integration_instructions
from app.agents.tools.memory_tools import search_memory
from app.agents.tools.research_tool import deep_research
from app.agents.tools.todo_tools import create_todo_pre_model_hook, create_todo_tools
from app.agents.tools.webpage_tool import fetch_webpages, web_search_tool
from app.constants.general import FINISH_TASK_NAME
from app.constants.log_tags import LogTag
from app.override.langgraph_bigtool.create_agent import create_agent
from shared.py.wide_events import log


def resolve_declared_tools(
    declared: list[str] | None,
    scoped_tool_dict: Mapping[str, BaseTool],
    *,
    provider: str,
    kind: str,
) -> list[str]:
    """The declared tools that actually resolved, warning about any that did not.

    A subagent's ``auto_bind_tools`` / ``extra_initial_tools`` are a promise that
    those tools are bound before its first model call. Filtering out names the
    registry never produced is correct — binding a non-existent tool would fail
    the build — but a name that goes missing is always an upstream fault (a
    provider category that never registered, a renamed slug), never a normal
    outcome. Left silent, a Gmail subagent builds with none of its Gmail tools,
    reports healthy, and can do nothing.

    Declaring nothing is normal and says nothing.
    """
    if not declared:
        return []
    resolved = [name for name in declared if name in scoped_tool_dict]
    missing = [name for name in declared if name not in scoped_tool_dict]
    if missing:
        log.warning(
            f"{LogTag.AGENT} Subagent declared tools that do not exist in its resolved "
            "tool set; they will NOT be bound",
            provider=provider,
            declaration=kind,
            missing_tools=missing,
            resolved_tools=resolved,
        )
    return resolved


def _build_scoped_tool_dict(
    tool_registry: ToolRegistry,
    tool_space: str,
    mcp_tools: list[BaseTool] | None,
    include_finish_task: bool,
    authoring_only: bool = False,
) -> tuple[dict[str, BaseTool], list[str]]:
    """Assemble the scoped tool dict + initial tool IDs for a subagent.

    Split out of `create_provider_subagent` to keep that function's cognitive
    complexity below SonarQube's threshold.

    ``authoring_only`` builds a pure draft-authoring agent (e.g. the workflow
    assistant): only its tool_space tools, none of the always-available
    execution tools (coding/FS, web, research, memory), so it cannot try to
    *do* the work instead of describe it.
    """
    scoped_tool_dict: dict[str, BaseTool] = {}
    initial_tool_ids: list[str] = []

    if mcp_tools is not None:
        # Live MCP tools passed in by provider_subagents — source of truth is
        # MCPClient, not the global registry. Used for per-user MCP integrations.
        for tool in mcp_tools:
            scoped_tool_dict[tool.name] = tool
            initial_tool_ids.append(tool.name)
    else:
        # Fallback path for non-MCP subagents (Composio, shared/_system MCPs):
        # look up the registry category that matches this tool_space.
        category = tool_registry.get_category_by_space(tool_space)
        if category is not None:
            for t in category.tools:
                scoped_tool_dict[t.name] = t.tool
                initial_tool_ids.append(t.name)

    if not authoring_only:
        # Always-available tools (memory, coding/FS, search). This branch uses the
        # JuiceFS-backed coding tools (`read` / `bash`); the legacy `vfs_tools`
        # module was removed when subagents moved to the E2B sandbox.
        scoped_tool_dict[search_memory.name] = search_memory
        scoped_tool_dict[read.name] = read
        scoped_tool_dict[bash.name] = bash
        # Resolvable for every subagent (retrieve-on-demand); gmail additionally
        # binds these two into its initial set below, since it always offloads
        # large inboxes and must mine them sandbox-free.
        scoped_tool_dict[query_json.name] = query_json
        scoped_tool_dict[grep.name] = grep
        scoped_tool_dict[web_search_tool.name] = web_search_tool
        scoped_tool_dict[fetch_webpages.name] = fetch_webpages
        scoped_tool_dict[deep_research.name] = deep_research
        # Always-on so a subagent can persist a user's durable preference for its
        # own integration the moment it hears one (its instructions are already in
        # context, so it can rewrite the full block without a separate read).
        scoped_tool_dict[update_integration_instructions.name] = update_integration_instructions

    if include_finish_task:
        scoped_tool_dict[FINISH_TASK_NAME] = finish_task
        initial_tool_ids.append(FINISH_TASK_NAME)

    return scoped_tool_dict, initial_tool_ids


class SubAgentFactory:
    """Factory for creating provider-specific sub-agents with specialized tool registries."""

    @staticmethod
    async def create_provider_subagent(
        provider: str,
        name: str,
        llm: LanguageModelLike,
        tool_space: str = "general",
        use_direct_tools: bool = False,
        disable_retrieve_tools: bool = False,
        auto_bind_tools: list[str] | None = None,
        extra_initial_tools: list[str] | None = None,
        include_finish_task: bool = True,
        mcp_tools: list[BaseTool] | None = None,
        source_label: str | None = None,
        authoring_only: bool = False,
    ) -> CompiledStateGraph:
        """
        Creates a specialized sub-agent graph for a specific provider with tool registry.

        Args:
            provider: Provider name (gmail, notion, twitter, linkedin, calendar)
            llm: Language model to use
            tool_space: Tool space to use for retrieval (e.g., "gmail_delegated", "general")
            use_direct_tools: If True, bind all tools directly without retrieve_tools
            disable_retrieve_tools: If True, disable retrieve_tools mechanism entirely
            auto_bind_tools: Tools to auto-bind at startup. Always included
                in `initial` regardless of `use_direct_tools` or
                `disable_retrieve_tools`. Reduces latency for
                frequently-used tools.
            include_finish_task: When True (default), the subagent gets the
                `finish_task` tool to signal completion. When False, it
                terminates with a normal AIMessage that the streaming layer
                captures as the final answer. Use False for answer-only
                subagents (e.g. documentation fetchers) where finish_task adds
                latency without value.
            source_label: Human-readable name for the provider, streamed with
                todo_progress events so the frontend shows the integration's
                name instead of its raw id (provider).

        Returns:
            Compiled LangGraph agent with tool registry, retrieval, and checkpointer
        """
        log.set(subagent={"name": name, "provider": provider})
        log.info(
            f"{LogTag.AGENT} Creating sub-agent graph",
            provider=provider,
            tool_space=tool_space,
            direct_tools=use_direct_tools,
        )

        store, tool_registry = await asyncio.gather(get_tools_store(), get_tool_registry())

        scoped_tool_dict, initial_tool_ids = _build_scoped_tool_dict(
            tool_registry=tool_registry,
            tool_space=tool_space,
            mcp_tools=mcp_tools,
            include_finish_task=include_finish_task,
            authoring_only=authoring_only,
        )

        # Get full tool dict so spawned sub-subagents (via spawn_subagent) inherit
        # all parent tools, not just the provider's scoped tools.
        # The provider agent itself uses scoped_tool_dict for its own tool access,
        # but its SubagentMiddleware needs the full registry so that any child
        # subagent it spawns can access tools like read, bash, web_search, etc.
        full_tool_dict = tool_registry.get_tool_dict()

        # An authoring-only subagent (the workflow assistant) just emits a draft;
        # it must not spawn sub-subagents or plan/run tasks. Strip the spawn
        # middleware and the todo (plan_tasks/update_tasks) tools + hook so it
        # cannot drift into executing the workflow it is supposed to describe.
        middleware = create_subagent_middleware(
            agent_name=name,
            subagent_llm=llm,
            subagent_registry=full_tool_dict,
            subagent_tool_space=tool_space,
            enable_subagent=not authoring_only,
        )

        subagent_mw = next(
            (mw for mw in middleware if isinstance(mw, SubagentMiddleware)),
            None,
        )

        # Create todo tools and register them in the scoped tool registry
        todo_tools: list[BaseTool] = (
            [] if authoring_only else create_todo_tools(source=provider, source_label=source_label)
        )
        todo_hook = None if authoring_only else create_todo_pre_model_hook(source=provider)
        todo_tool_names: list[str] = []
        for todo_tool in todo_tools:
            scoped_tool_dict[todo_tool.name] = todo_tool
            todo_tool_names.append(todo_tool.name)

        if subagent_mw is not None:
            subagent_mw.set_store(store)
            subagent_mw.set_spawn_graph_provider(get_spawn_graph)

        common_kwargs = {
            "llm": llm,
            "tool_registry": scoped_tool_dict,  # Use scoped dict instead of global
            "agent_name": name,
            "middleware": middleware,
            "pre_model_hooks": worker_pre_model_hooks(todo_hook),
            "end_graph_hooks": [memory_node],
        }

        valid_auto_bind: list[str] | None = (
            resolve_declared_tools(
                auto_bind_tools, scoped_tool_dict, provider=provider, kind="auto_bind"
            )
            or None
        )

        # Config-declared extra initial tools (SubAgentConfig.extra_initial_tools):
        # local/general tools this subagent always needs bound up front — for the
        # agent AND the chunk-reader children it spawns. E.g. gmail declares
        # query_json/grep so triage mines an offloaded inbox directly instead of
        # falling back to read-whole-file + bash. Kept per-integration in config
        # (not branched on provider) so it scales to any subagent that offloads.
        extra_initial = resolve_declared_tools(
            extra_initial_tools, scoped_tool_dict, provider=provider, kind="extra_initial"
        )
        if extra_initial:
            valid_auto_bind = [*(valid_auto_bind or []), *extra_initial]

        if valid_auto_bind:
            log.info(
                f"{LogTag.AGENT} Auto-binding tools",
                tool_count=len(valid_auto_bind),
                provider=provider,
                tool_names=valid_auto_bind,
            )

        parent_tool_runtime = build_provider_parent_tool_runtime_config(
            provider_tool_names=initial_tool_ids,
            todo_tool_names=todo_tool_names,
            auto_bind_tool_names=valid_auto_bind,
            use_direct_tools=use_direct_tools,
            disable_retrieve_tools=disable_retrieve_tools,
            include_finish_task=include_finish_task,
        )
        common_kwargs.update(
            build_create_agent_tool_kwargs(
                parent_tool_runtime,
                tool_space=tool_space,
                # Validate binding against exactly what this graph executes.
                bindable_tool_names=set(scoped_tool_dict.keys()),
            )
        )

        child_tool_runtime = build_child_tool_runtime_config(
            parent_tool_runtime,
            use_direct_tools=use_direct_tools,
            disable_retrieve_tools=disable_retrieve_tools,
            extra_initial_tool_names=extra_initial,
        )
        spawn_seed_tools = [
            scoped_tool_dict[name]
            for name in child_tool_runtime.initial_tool_names
            if name in scoped_tool_dict
        ]

        if subagent_mw is not None:
            subagent_mw.set_tools(
                registry=full_tool_dict,
                tools=spawn_seed_tools,
                tool_runtime_config=child_tool_runtime,
            )

        builder = create_agent(**common_kwargs)  # type: ignore[arg-type]  # kwargs assembled as a runtime dict; **-unpacking defeats mypy's kwarg checking

        try:
            checkpointer_manager = await get_checkpointer_manager()
            checkpointer: BaseCheckpointSaver = checkpointer_manager.get_checkpointer()
            log.debug(
                f"{LogTag.AGENT} Using PostgreSQL checkpointer for sub-agent", provider=provider
            )
        except Exception as e:
            log.warning(
                f"{LogTag.AGENT} PostgreSQL checkpointer unavailable for sub-agent; using InMemorySaver",
                provider=provider,
                error_type=type(e).__name__,
                error=str(e),
            )
            checkpointer = InMemorySaver()

        subagent_graph = builder.compile(store=store, name=name, checkpointer=checkpointer)

        log.info(
            f"{LogTag.AGENT} Successfully created sub-agent graph with checkpointer",
            provider=provider,
        )
        return subagent_graph
