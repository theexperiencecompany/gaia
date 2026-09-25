import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langchain_core.language_models import LanguageModelLike
from langgraph.checkpoint.memory import InMemorySaver

from app.agents.core.graph_builder.checkpointer_manager import (
    get_checkpointer_manager,
)
from app.agents.core.graph_manager import CompiledAgentGraph
from app.agents.core.nodes import (
    follow_up_actions_node,
    memory_node,
)
from app.agents.core.nodes.pre_model_hooks import (
    comms_pre_model_hooks,
    worker_pre_model_hooks,
)
from app.agents.core.subagents.handoff_tools import handoff as handoff_tool
from app.agents.core.subagents.integration_activation import activate_integration
from app.agents.core.subagents.provider_subagents import register_subagent_providers
from app.agents.core.subagents.spawn_agent import get_spawn_graph
from app.agents.llm.client import init_llm
from app.agents.middleware import (
    SubagentStackOptions,
    create_comms_middleware,
    create_executor_middleware,
)
from app.agents.middleware.subagent import SubagentMiddleware, bind_spawner
from app.agents.tools import memory_tools
from app.agents.tools.core.registry import get_tool_registry
from app.agents.tools.core.retrieval import get_retrieve_tools_function
from app.agents.tools.core.store import get_tools_store
from app.agents.tools.core.tool_runtime_config import (
    build_executor_child_tool_runtime_config,
)
from app.agents.tools.discovery_tools import find_integration, search_public_workflows
from app.agents.tools.executor_tool import call_executor, cancel_executor
from app.agents.tools.subagent_control_tool import (
    cancel_subagent,
    list_running_subagents,
    message_subagent,
)
from app.agents.tools.todo_tools import create_todo_pre_model_hook, create_todo_tools
from app.agents.tools.webpage_tool import fetch_webpages, web_search_tool
from app.constants.log_tags import LogTag
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider
from app.override.langgraph_bigtool.agent_config import (
    AgentConfig,
    HookConfig,
    ToolRetrievalConfig,
)
from app.override.langgraph_bigtool.create_agent import create_agent
from shared.py.wide_events import log

#: Tools the executor binds before its first turn, ahead of any retrieve_tools call.
#: "activate_integration" is always bound. `handoff` stays for per-user MCP
#: integrations that cannot be activated in-context — see build_executor_graph.
EXECUTOR_INITIAL_TOOL_IDS = [
    "handoff",
    "execute",
    "get_tool_schema",
    "plan_tasks",
    "update_tasks",
    "read",
    "write",
    "edit",
    "bash",
    "deep_research",
    "list_running_subagents",
    "message_subagent",
    "cancel_subagent",
    "read_manual",
    "create_tracked_todo",
    "update_tracked_todo",
    "update_tracked_todo_canvas",
    "complete_tracked_todo",
    "search_todo_context",
    "list_tracked_todos",
    "list_trigger_fields",
    "subscribe_todo_to_trigger",
    "unsubscribe_todo_from_trigger",
    "save_learned_skill",
    # Bound, not retrieved: fetching it cost two retrieve_tools rounds
    # and two model calls (about 8s) before the browser even started.
    "browser_task",
    # The join that collects its answer must not be retrieved either: a
    # retrieval miss here would strand a started run with nobody to report it.
    "wait_for_browser_task",
    # Same reason: the run pauses on this one, and a retrieval miss
    # would leave it waiting out its guidance timeout for nothing.
    "guide_browser_task",
    # Bound statically, not left to retrieve_tools: prompts name these
    # directly, so a run whose semantic retrieval misses them could read
    # the instruction and silently never act on it.
    "write_playbook",
    "decline_playbook",
    "read_playbook",
    "disable_playbook",
    # Same rule as playbook tools: not in the retrieval index, so
    # retrieve_tools once improvised a nonexistent `gaia bridge approve`.
    # approve_device_pairing stays gated regardless of binding.
    "add_device",
    "approve_device_pairing",
    "list_devices",
    "run_on_device",
]


@asynccontextmanager
async def build_executor_graph(
    chat_llm: LanguageModelLike | None = None,
    in_memory_checkpointer: bool = False,
) -> AsyncIterator[CompiledAgentGraph]:
    """Construct and compile the executor agent graph with handoff (per-user MCP only) + activation tools."""
    if chat_llm is None:
        chat_llm = init_llm()

    tool_registry, store = await asyncio.gather(
        get_tool_registry(),
        get_tools_store(),
    )

    todo_tools = create_todo_tools(source="executor")

    tool_dict = tool_registry.get_tool_dict()
    tool_dict.update({t.name: t for t in todo_tools})

    # handoff stays bound for per-user MCP integrations, whose tools never
    # enter the global registry; activate_integration routes those to
    # handoff rather than dead-ending them.
    tool_dict.update({"handoff": handoff_tool})
    tool_dict.update({"activate_integration": activate_integration})
    # Executor-only tools to steer or cancel a specific running subagent by id.
    tool_dict.update(
        {t.name: t for t in (list_running_subagents, message_subagent, cancel_subagent)}
    )
    todo_hook = create_todo_pre_model_hook(source="executor")

    # Spawned subagents must not see executor-only orchestration tools, and
    # activate_integration is executor-level: subagents reach integrations
    # through handoff, never by activating in-context themselves.
    excluded_subagent_tools = {
        "handoff",
        "list_running_subagents",
        "message_subagent",
        "cancel_subagent",
        "activate_integration",
    }

    middleware = create_executor_middleware(
        chat_llm=chat_llm,
        subagent=SubagentStackOptions(
            excluded_tools=excluded_subagent_tools,
            tool_runtime_config=build_executor_child_tool_runtime_config(),
            # The executor binds an integration's tools in its own turn, so a
            # spawn it delegates to must inherit them to do the work.
            inherit_parent_tools=True,
        ),
    )

    # Wire SubagentMiddleware with LLM and full tool registry
    subagent_mw = next(
        (mw for mw in middleware if isinstance(mw, SubagentMiddleware)),
        None,
    )
    if subagent_mw is None:
        log.warning(
            f"{LogTag.AGENT} SubagentMiddleware not found in middleware stack; spawn_subagent will be unavailable"
        )
    else:
        subagent_mw.set_llm(chat_llm)
        subagent_mw.set_tools(registry=tool_dict)
        subagent_mw.set_store(store)
        subagent_mw.set_spawn_graph_provider(get_spawn_graph)

    pre_model_hooks = worker_pre_model_hooks(todo_hook, drains_inbox=True)

    # activate_integration leads; handoff stays for the per-user MCP
    # integrations activation cannot bind in-context (routed there).
    initial_tools = ["activate_integration", *EXECUTOR_INITIAL_TOOL_IDS]

    builder = create_agent(
        chat_llm,
        tool_dict,
        tools_config=ToolRetrievalConfig(
            retrieve_tools_coroutine=get_retrieve_tools_function(),
            initial_tool_ids=initial_tools,
        ),
        hooks_config=HookConfig(
            pre_model_hooks=pre_model_hooks,
            require_finish_to_end=True,
        ),
        agent_config=AgentConfig(agent_name="executor_agent", middleware=middleware),
    )

    checkpointer_manager = await get_checkpointer_manager()

    model_name = getattr(chat_llm, "model_name", None) or getattr(chat_llm, "model", None)

    if in_memory_checkpointer or not checkpointer_manager:
        in_memory_checkpointer_instance = InMemorySaver()
        graph = builder.compile(checkpointer=in_memory_checkpointer_instance, store=store)
        if subagent_mw is not None:
            bind_spawner(graph, subagent_mw)
        # Surface fallback at WARNING — users silently lose conversation memory
        # when Postgres checkpointer is unavailable.
        if not in_memory_checkpointer:
            log.warning(
                "checkpointer_fallback_to_memory",
                graph="comms",
                reason="checkpointer_manager_unavailable",
                model=model_name,
            )
        else:
            log.info("graph_compiled_in_memory", graph="comms", model=model_name)
        log.set(agent={"model": model_name})
        yield graph
    else:
        postgres_checkpointer = checkpointer_manager.get_checkpointer()
        graph = builder.compile(checkpointer=postgres_checkpointer, store=store)
        if subagent_mw is not None:
            bind_spawner(graph, subagent_mw)
        log.info("graph_compiled_postgres", graph="comms", model=model_name)
        log.set(agent={"model": model_name})
        yield graph


@lazy_provider(
    name="executor_agent",
    required_keys=[],
    strategy=MissingKeyStrategy.WARN,
    auto_initialize=False,
)
async def build_executor_agent() -> CompiledAgentGraph:
    """Build and return the executor agent with full tool access."""
    log.debug(f"{LogTag.AGENT} Building executor agent with lazy providers")

    async with build_executor_graph() as graph:
        log.info(f"{LogTag.AGENT} Executor agent built successfully")
    return graph


@asynccontextmanager
async def build_comms_graph(
    chat_llm: LanguageModelLike | None = None,
    in_memory_checkpointer: bool = False,
) -> AsyncIterator[CompiledAgentGraph]:
    """Build the comms agent graph with only the executor tool."""
    if chat_llm is None:
        chat_llm = init_llm()

    # The discovery pair are read-only catalogue lookups, so they do not breach
    # "delegate every real ask". Connecting an integration is a real ask and
    # goes to the executor.
    tool_registry = {
        "call_executor": call_executor,
        "cancel_executor": cancel_executor,
        "find_integration": find_integration,
        "search_public_workflows": search_public_workflows,
        web_search_tool.name: web_search_tool,
        fetch_webpages.name: fetch_webpages,
        **{memory_tool.name: memory_tool for memory_tool in memory_tools.tools},
    }
    store = await get_tools_store()

    middleware = create_comms_middleware(chat_llm=chat_llm)

    pre_model_hooks = comms_pre_model_hooks()

    builder = create_agent(
        chat_llm,
        tool_registry,
        tools_config=ToolRetrievalConfig(
            disable_retrieve_tools=True,
            initial_tool_ids=[
                "call_executor",
                "cancel_executor",
                "find_integration",
                "search_public_workflows",
                web_search_tool.name,
                fetch_webpages.name,
                *[memory_tool.name for memory_tool in memory_tools.tools],
            ],
        ),
        hooks_config=HookConfig(
            pre_model_hooks=pre_model_hooks,
            end_graph_hooks=[
                follow_up_actions_node,
                # Learn durable user memories from every comms turn (passive
                # ingestion). Without this, only facts the agent explicitly saves
                # via add_memory persist — conversational disclosures are lost.
                memory_node,
            ],
        ),
        agent_config=AgentConfig(agent_name="comms_agent", middleware=middleware),
    )

    checkpointer_manager = await get_checkpointer_manager()

    model_name = getattr(chat_llm, "model_name", None) or getattr(chat_llm, "model", None)

    if in_memory_checkpointer or not checkpointer_manager:
        in_memory_checkpointer_instance = InMemorySaver()
        graph = builder.compile(checkpointer=in_memory_checkpointer_instance, store=store)
        log.debug(f"{LogTag.AGENT} Comms graph compiled with in-memory checkpointer")
        log.set(agent={"model": model_name})
        yield graph
    else:
        postgres_checkpointer = checkpointer_manager.get_checkpointer()
        graph = builder.compile(checkpointer=postgres_checkpointer, store=store)
        log.debug(f"{LogTag.AGENT} Comms graph compiled with PostgreSQL checkpointer")
        log.set(agent={"model": model_name})
        yield graph


@lazy_provider(
    name="comms_agent",
    required_keys=[],
    strategy=MissingKeyStrategy.WARN,
    auto_initialize=False,
)
async def build_comms_agent() -> CompiledAgentGraph:
    """Build and return the comms agent using lazy providers."""
    log.debug(f"{LogTag.AGENT} Building comms agent with lazy providers")

    async with build_comms_graph() as graph:
        log.info(f"{LogTag.AGENT} Comms agent built successfully")
    return graph


def build_graphs() -> None:
    """Build comms and executor agents and register subagent providers."""
    log.info(f"{LogTag.AGENT} Building core agent graphs...")

    register_subagent_providers()
    build_executor_agent()
    build_comms_agent()

    log.info(f"{LogTag.AGENT} Core agent graphs built and registered successfully")
