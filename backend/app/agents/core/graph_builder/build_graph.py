import asyncio
from contextlib import asynccontextmanager
from typing import Optional

from app.agents.core.graph_builder.checkpointer_manager import (
    get_checkpointer_manager,
)
from app.agents.core.nodes import (
    create_delete_system_messages_node,
    follow_up_actions_node,
    trim_messages_node,
)
from app.agents.core.nodes.filter_messages import create_filter_messages_node
from app.agents.core.subagents.provider_subagents import ProviderSubAgents
from app.agents.llm.client import init_llm
from app.agents.tools.core.registry import get_tool_registry
from app.agents.tools.core.retrieval import get_retrieve_tools_function
from app.agents.tools.core.store import get_tools_store
from app.config.loggers import app_logger as logger
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider
from app.override.langgraph_bigtool.create_agent import create_agent
from langchain_core.language_models import LanguageModelLike
from langgraph.checkpoint.memory import InMemorySaver


@asynccontextmanager
async def build_graph(
    chat_llm: Optional[LanguageModelLike] = None,
    in_memory_checkpointer: bool = False,
):
    """Construct and compile the state graph with integrated sub-agent graphs."""
    # Get default LLM if none provided
    if chat_llm is None:
        chat_llm = init_llm()

    tool_registry, store, sub_agents = await asyncio.gather(
        get_tool_registry(),
        get_tools_store(),
        ProviderSubAgents.get_all_subagents(chat_llm),
    )

    # Create main agent with custom tool retrieval logic
    builder = create_agent(
        llm=chat_llm,
        agent_name="main_agent",
        tool_registry=tool_registry.get_tool_dict(),
        retrieve_tools_coroutine=get_retrieve_tools_function(tool_space="general"),
        sub_agents=sub_agents,  # pyright: ignore[reportArgumentType]
        pre_model_hooks=[
            create_filter_messages_node(
                agent_name="main_agent",
            ),
            trim_messages_node,
        ],
        end_graph_hooks=[
            follow_up_actions_node,
            create_delete_system_messages_node(),
        ],
    )

    checkpointer_manager = await get_checkpointer_manager()

    if (
        in_memory_checkpointer or not checkpointer_manager
    ):  # Use in-memory checkpointer for testing or simple use cases
        in_memory_checkpointer_instance = InMemorySaver()
        # Setup the checkpointer
        graph = builder.compile(
            # type: ignore[call-arg]
            checkpointer=in_memory_checkpointer_instance,
            store=store,
        )
        logger.debug("Graph compiled with in-memory checkpointer")
        yield graph
    else:
        postgres_checkpointer = checkpointer_manager.get_checkpointer()
        graph = builder.compile(checkpointer=postgres_checkpointer, store=store)
        logger.debug("Graph compiled with PostgreSQL checkpointer")
        yield graph


@lazy_provider(
    name="default_graph",
    required_keys=[],  # No specific keys required since dependencies are handled by sub-providers
    strategy=MissingKeyStrategy.WARN,
    auto_initialize=False,
)
async def build_default_graph():
    """Build and return the default graph using lazy providers."""
    logger.debug("Building default graph with lazy providers")

    # Build the graph using the existing function
    async with build_graph() as graph:
        logger.info("Default graph built successfully")
        return graph
