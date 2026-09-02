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
from app.agents.core.subagents.provider_subagents import register_subagent_providers
from app.agents.core.subagents.spawn_agent import get_spawn_graph
from app.agents.llm.client import init_llm
from app.agents.middleware import create_comms_middleware, create_executor_middleware
from app.agents.middleware.subagent import SubagentMiddleware
from app.agents.tools import memory_tools
from app.agents.tools.core.registry import get_tool_registry
from app.agents.tools.core.retrieval import get_retrieve_tools_function
from app.agents.tools.core.store import get_tools_store
from app.agents.tools.core.tool_runtime_config import (
    build_executor_child_tool_runtime_config,
)
from app.agents.tools.executor_tool import call_executor, cancel_executor
from app.agents.tools.todo_tools import create_todo_pre_model_hook, create_todo_tools
from app.agents.tools.wait_for_subagents_tool import wait_for_subagents as wait_for_subagents_tool
from app.constants.general import WAIT_FOR_SUBAGENTS_NAME
from app.constants.log_tags import LogTag
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider
from app.override.langgraph_bigtool.agent_config import (
    AgentConfig,
    HookConfig,
    ToolRetrievalConfig,
)
from app.override.langgraph_bigtool.create_agent import create_agent
from shared.py.wide_events import log


@asynccontextmanager
async def build_executor_graph(
    chat_llm: LanguageModelLike | None = None,
    in_memory_checkpointer: bool = False,
) -> AsyncIterator[CompiledAgentGraph]:
    """Construct and compile the executor agent graph with handoff tools."""
    if chat_llm is None:
        chat_llm = init_llm()

    tool_registry, store = await asyncio.gather(
        get_tool_registry(),
        get_tools_store(),
    )

    todo_tools = create_todo_tools(source="executor")

    tool_dict = tool_registry.get_tool_dict()
    tool_dict.update({"handoff": handoff_tool})
    tool_dict.update({t.name: t for t in todo_tools})
    tool_dict.update({WAIT_FOR_SUBAGENTS_NAME: wait_for_subagents_tool})

    todo_hook = create_todo_pre_model_hook(source="executor")

    # Spawned subagents must not see executor-only orchestration tools.
    excluded_subagent_tools = {"handoff", WAIT_FOR_SUBAGENTS_NAME}

    middleware = create_executor_middleware(
        chat_llm=chat_llm,
        subagent_excluded_tools=excluded_subagent_tools,
        subagent_tool_runtime_config=build_executor_child_tool_runtime_config(),
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

    pre_model_hooks = worker_pre_model_hooks(todo_hook)

    builder = create_agent(
        chat_llm,
        tool_dict,
        tools_config=ToolRetrievalConfig(
            retrieve_tools_coroutine=get_retrieve_tools_function(),
            initial_tool_ids=[
                "handoff",
                "plan_tasks",
                "update_tasks",
                "read",
                "bash",
                "deep_research",
                "wait_for_subagents",
                "read_manual",
                "create_tracked_todo",
                "update_tracked_todo",
                "update_tracked_todo_canvas",
                "complete_tracked_todo",
                "search_todo_context",
                "list_tracked_todos",
                "save_learned_skill",
                # Bound statically, not left to retrieve_tools: the <playbook_check>
                # and heal briefs name these directly, so a run whose semantic
                # retrieval happens to miss them would read the instruction, be
                # unable to act on it, and silently never decide. A tool a prompt
                # names by hand has to be reachable by hand.
                "write_playbook",
                "decline_playbook",
                "read_playbook",
                "disable_playbook",
            ],
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

    tool_registry = {
        "call_executor": call_executor,
        "cancel_executor": cancel_executor,
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
