import asyncio
from contextlib import asynccontextmanager
from typing import Optional

from app.agents.core.graph_builder.checkpointer_manager import (
    get_checkpointer_manager,
)
from app.agents.core.nodes import (
    follow_up_actions_node,
    manage_system_prompts_node,
    trim_messages_node,
)
from app.agents.core.nodes.filter_messages import filter_messages_node
from app.agents.core.subagents.handoff_tools import handoff as handoff_tool
from app.agents.core.subagents.provider_subagents import register_subagent_providers
from app.agents.llm.client import init_llm
from app.agents.tools import memory_tools
from app.agents.tools.core.registry import get_tool_registry
from app.agents.tools.core.retrieval import get_retrieve_tools_function
from app.agents.tools.core.store import get_tools_store
from app.agents.tools.executor_tool import call_executor
from app.config.loggers import app_logger as logger
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider
from app.override.langgraph_bigtool.create_agent import create_agent
from langchain_core.language_models import LanguageModelLike
from langgraph.checkpoint.memory import InMemorySaver


@asynccontextmanager
async def build_executor_graph(
    chat_llm: Optional[LanguageModelLike] = None,
    in_memory_checkpointer: bool = False,
):
    """Construct and compile the executor agent graph with handoff tools."""
    if chat_llm is None:
        chat_llm = init_llm()

    tool_registry, store = await asyncio.gather(
        get_tool_registry(),
        get_tools_store(),
    )

    tool_dict = tool_registry.get_tool_dict()
    tool_dict.update({"handoff": handoff_tool})

    builder = create_agent(
        llm=chat_llm,
        agent_name="executor_agent",
        tool_registry=tool_dict,
        retrieve_tools_coroutine=get_retrieve_tools_function(),
        initial_tool_ids=["handoff"],
        pre_model_hooks=[
            filter_messages_node,
            manage_system_prompts_node,
            trim_messages_node,
        ],
    )

    checkpointer_manager = await get_checkpointer_manager()

    if in_memory_checkpointer or not checkpointer_manager:
        in_memory_checkpointer_instance = InMemorySaver()
        graph = builder.compile(
            checkpointer=in_memory_checkpointer_instance, store=store
        )
        logger.debug("Graph compiled with in-memory checkpointer")
        yield graph
    else:
        postgres_checkpointer = checkpointer_manager.get_checkpointer()
        graph = builder.compile(checkpointer=postgres_checkpointer, store=store)
        logger.debug("Graph compiled with PostgreSQL checkpointer")
        yield graph


@lazy_provider(
    name="executor_agent",
    required_keys=[],
    strategy=MissingKeyStrategy.WARN,
    auto_initialize=False,
)
async def build_executor_agent():
    """Build and return the executor agent with full tool access."""
    logger.debug("Building executor agent with lazy providers")

    async with build_executor_graph() as graph:
        logger.info("Executor agent built successfully")
    return graph


@asynccontextmanager
async def build_comms_graph(
    chat_llm: Optional[LanguageModelLike] = None,
    in_memory_checkpointer: bool = False,
):
    """Build the comms agent graph with only the executor tool."""
    if chat_llm is None:
        chat_llm = init_llm()

    tool_registry = {
        "call_executor": call_executor,
        "add_memory": memory_tools.add_memory,
        "search_memory": memory_tools.search_memory,
    }
    store = await get_tools_store()

    builder = create_agent(
        llm=chat_llm,
        agent_name="comms_agent",
        tool_registry=tool_registry,
        disable_retrieve_tools=True,
        initial_tool_ids=["call_executor", "add_memory", "search_memory"],
        pre_model_hooks=[
            filter_messages_node,
            manage_system_prompts_node,
            trim_messages_node,
        ],
        end_graph_hooks=[
            follow_up_actions_node,
        ],
    )

    checkpointer_manager = await get_checkpointer_manager()

    if in_memory_checkpointer or not checkpointer_manager:
        in_memory_checkpointer_instance = InMemorySaver()
        graph = builder.compile(
            checkpointer=in_memory_checkpointer_instance, store=store
        )
        logger.debug("Comms graph compiled with in-memory checkpointer")
        yield graph
    else:
        postgres_checkpointer = checkpointer_manager.get_checkpointer()
        graph = builder.compile(checkpointer=postgres_checkpointer, store=store)
        logger.debug("Comms graph compiled with PostgreSQL checkpointer")
        yield graph


@lazy_provider(
    name="comms_agent",
    required_keys=[],
    strategy=MissingKeyStrategy.WARN,
    auto_initialize=False,
)
async def build_comms_agent():
    """Build and return the comms agent using lazy providers."""
    logger.debug("Building comms agent with lazy providers")

    async with build_comms_graph() as graph:
        logger.info("Comms agent built successfully")
    return graph


def build_graphs():
    """Build comms and executor agents and register subagent providers."""
    logger.info("Building core agent graphs...")

    register_subagent_providers()
    build_executor_agent()
    build_comms_agent()

    logger.info("Core agent graphs built and registered successfully")
