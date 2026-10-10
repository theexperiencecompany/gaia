"""Factory for provider-specific sub-agents.

Subagents are standalone graphs with their own checkpointers, invoked via the
tool-calling pattern like executor_agent. Passive memory learning is NOT wired
here — it runs once per comms turn, over the conversation the user actually
had (see app/agents/core/nodes/memory_node.py).
"""

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models import LanguageModelLike
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.state import CompiledStateGraph

from app.agents.core.graph_builder.checkpointer_manager import get_checkpointer_manager
from app.agents.core.nodes.pre_model_hooks import worker_pre_model_hooks
from app.agents.middleware import (
    SubagentStackOptions,
    create_subagent_middleware,
)
from app.agents.tools.coding import grep, query_json, read
from app.agents.tools.coding.bash_tool import build_bash_tool
from app.agents.tools.core.registry import ToolRegistry, get_tool_registry
from app.agents.tools.core.retrieval import partition_startup_tools
from app.agents.tools.core.store import get_tools_store
from app.agents.tools.core.tool_runtime_config import (
    build_create_agent_tool_kwargs,
    build_provider_parent_tool_runtime_config,
)
from app.agents.tools.execute.execute_tool import build_execute_tool
from app.agents.tools.execute.schema_tool import get_tool_schema
from app.agents.tools.finish_task_tool import finish_task
from app.agents.tools.integration_instructions_tools import update_integration_instructions
from app.agents.tools.memory_tools import search_memory
from app.agents.tools.research_tool import deep_research
from app.agents.tools.todo_tools import create_todo_pre_model_hook, create_todo_tools
from app.agents.tools.webpage_tool import fetch_webpages, web_search_tool
from app.constants.general import FINISH_TASK_NAME
from app.constants.log_tags import LogTag
from app.override.langgraph_bigtool.agent_config import AgentConfig, HookConfig
from app.override.langgraph_bigtool.create_agent import create_agent
from shared.py.wide_events import log


def resolve_declared_tools(
    declared: list[str] | None,
    scoped_tool_dict: Mapping[str, BaseTool],
    *,
    provider: str,
    kind: str,
) -> list[str]:
    """Return the declared tools that actually resolved, warning about any that did not.

    A subagent's auto_bind_tools / extra_initial_tools promise those tools are
    available before its first model call. A missing name is always an upstream
    fault (an unregistered category, a renamed slug), never normal — left silent,
    a Gmail subagent builds with no Gmail tools, reports healthy, and does nothing.
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


def build_scoped_tool_dict(
    tool_registry: ToolRegistry,
    tool_space: str,
    mcp_tools: list[BaseTool] | None,
    include_finish_task: bool,
    authoring_only: bool = False,
) -> tuple[dict[str, BaseTool], list[str]]:
    """Assemble the scoped tool dict + initial tool IDs for a subagent.

    Split out of create_provider_subagent to keep its cognitive complexity
    below SonarQube's threshold. authoring_only builds a pure draft-authoring
    agent (e.g. the workflow assistant): only its tool_space tools, none of
    the always-available execution tools.
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
        # Built against THIS dict like the execute proxy below: bash mints the
        # code-mode token, and a sandbox `from gaia import execute` must be held to
        # the same tool space, or the confinement is one line to escape.
        scoped_bash = build_bash_tool(scoped_tool_dict)
        scoped_tool_dict[scoped_bash.name] = scoped_bash
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
        # The execute proxy runs integration tools retrieve_tools returned as
        # schema docs. Built against THIS dict so it honors the same tool space
        # retrieve_tools binds against — otherwise a subagent runs any tool by name.
        scoped_execute = build_execute_tool(scoped_tool_dict)
        scoped_tool_dict[scoped_execute.name] = scoped_execute
        initial_tool_ids.append(scoped_execute.name)
        scoped_tool_dict[get_tool_schema.name] = get_tool_schema
        initial_tool_ids.append(get_tool_schema.name)

    if include_finish_task:
        scoped_tool_dict[FINISH_TASK_NAME] = finish_task
        initial_tool_ids.append(FINISH_TASK_NAME)

    return scoped_tool_dict, initial_tool_ids


@dataclass
class SubAgentToolConfig:
    """Tool-retrieval and behavior knobs for a spawned provider subagent."""

    tool_space: str = "general"
    use_direct_tools: bool = False
    disable_retrieve_tools: bool = False
    # Startup tools: internal names bind into the initial set; integration
    # names preload as schema docs in the run's context (see
    # ``preloaded_startup_docs``, injected at handoff) and run via execute.
    auto_bind_tools: list[str] | None = None
    extra_initial_tools: list[str] | None = None
    include_finish_task: bool = True
    mcp_tools: list[BaseTool] | None = None
    source_label: str | None = None
    authoring_only: bool = False


class SubAgentFactory:
    """Factory for creating provider-specific sub-agents with specialized tool registries."""

    @staticmethod
    async def create_provider_subagent(
        provider: str,
        name: str,
        llm: LanguageModelLike,
        config: SubAgentToolConfig | None = None,
    ) -> CompiledStateGraph:
        """Create a specialized subagent graph for one provider, wired to the tool registry.

        auto_bind_tools are available before the first model call (internal names
        bind, integration names preload as schema docs). With include_finish_task
        False the subagent ends on a normal AIMessage instead of a finish_task
        signal — used for answer-only subagents like documentation fetchers.
        """
        cfg = config or SubAgentToolConfig()
        tool_space = cfg.tool_space
        use_direct_tools = cfg.use_direct_tools
        log.set(subagent={"name": name, "provider": provider})
        log.info(
            f"{LogTag.AGENT} Creating sub-agent graph",
            provider=provider,
            tool_space=tool_space,
            direct_tools=use_direct_tools,
        )

        store, tool_registry = await asyncio.gather(get_tools_store(), get_tool_registry())

        scoped_tool_dict, initial_tool_ids = build_scoped_tool_dict(
            tool_registry=tool_registry,
            tool_space=tool_space,
            mcp_tools=cfg.mcp_tools,
            include_finish_task=cfg.include_finish_task,
            authoring_only=cfg.authoring_only,
        )

        # Subagents can never spawn sub-subagents — create_subagent_middleware
        # structurally omits the spawn middleware (only the executor spawns).
        middleware = create_subagent_middleware(
            agent_name=name,
            subagent=SubagentStackOptions(llm=llm, tool_space=tool_space),
        )

        # Create todo tools and register them in the scoped tool registry
        todo_tools: list[BaseTool] = (
            []
            if cfg.authoring_only
            else create_todo_tools(source=provider, source_label=cfg.source_label)
        )
        todo_hook = None if cfg.authoring_only else create_todo_pre_model_hook(source=provider)
        todo_tool_names: list[str] = []
        for todo_tool in todo_tools:
            scoped_tool_dict[todo_tool.name] = todo_tool
            todo_tool_names.append(todo_tool.name)

        common_kwargs: dict[str, Any] = {
            "llm": llm,
            "tool_registry": scoped_tool_dict,  # Use scoped dict instead of global
            "agent_config": AgentConfig(agent_name=name, middleware=middleware),
            # No memory hook: extraction runs once per comms turn, and a
            # subagent sees the same thread comms already ingested.
            "hooks_config": HookConfig(
                pre_model_hooks=worker_pre_model_hooks(todo_hook, drains_subagent_inbox=True),
                end_graph_hooks=[],
            ),
        }

        # Any falsy start is identical: the only reader does auto_bind_tool_names or [].
        valid_auto_bind: list[str] | None = None  # pragma: no mutate
        # Config-declared startup tools (auto_bind_tools / extra_initial_tools) bind
        # up front. Integration tools among them never bind — they preload as schema
        # docs and run via execute, so only the internal remainder binds.
        declared_startup = [
            *resolve_declared_tools(
                cfg.auto_bind_tools, scoped_tool_dict, provider=provider, kind="auto_bind"
            ),
            *resolve_declared_tools(
                cfg.extra_initial_tools,
                scoped_tool_dict,
                provider=provider,
                kind="extra_initial",
            ),
        ]
        if declared_startup:
            # Per-user MCP tools live in cfg.mcp_tools, not in any registry the
            # classifier sees — name them explicitly so they classify as preloaded
            # rather than falling through to binding.
            mcp_names = {t.name for t in cfg.mcp_tools} if cfg.mcp_tools else set()
            bind_now, preload_names = partition_startup_tools(
                tool_registry, declared_startup, mcp_names
            )
            valid_auto_bind = bind_now or None
            if preload_names:
                log.info(
                    f"{LogTag.AGENT} Preloading tool schemas instead of binding",
                    tool_count=len(preload_names),
                    provider=provider,
                    tool_names=preload_names,
                )

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
            disable_retrieve_tools=cfg.disable_retrieve_tools,
            include_finish_task=cfg.include_finish_task,
        )
        common_kwargs.update(
            build_create_agent_tool_kwargs(
                parent_tool_runtime,
                tool_space=tool_space,
                # Validate binding against exactly what this graph executes.
                bindable_tool_names=set(scoped_tool_dict.keys()),
            )
        )

        builder = create_agent(**common_kwargs)

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
