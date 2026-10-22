"""One bounded background agent graph over a fixed tool set, as replays and scout learns run it.

Every tool is bound up front (no retrieval), there is no summarization model, and only
metadata is set by hand, since LangGraph does not derive it from configurable.
"""

from collections.abc import Mapping, Sequence
from typing import cast

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AnyMessage, BaseMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool

from app.agents.middleware.factory import (
    AccountingOptions,
    ContextOptions,
    create_middleware_stack,
)
from app.models.agent_models import AgentConfigurable
from app.override.langgraph_bigtool.agent_config import AgentConfig, ToolRetrievalConfig
from app.override.langgraph_bigtool.create_agent import create_agent
from app.override.langgraph_bigtool.utils import State


async def run_tool_graph(
    model: BaseChatModel,
    tools: Mapping[str, BaseTool],
    messages: Sequence[BaseMessage],
    *,
    agent_name: str,
    configurable: AgentConfigurable,
    accounting: AccountingOptions,
) -> list[AnyMessage]:
    """Run the graph to its end on messages and return the whole message history.

    accounting carries the run's step limit, and whether its model calls are metered.
    """
    graph = create_agent(
        model,
        tools,
        tools_config=ToolRetrievalConfig(disable_retrieve_tools=True, initial_tool_ids=list(tools)),
        agent_config=AgentConfig(
            agent_name=agent_name,
            middleware=create_middleware_stack(
                agent_name=agent_name,
                accounting=accounting,
                context=ContextOptions(summarize=False),
            ),
        ),
    ).compile()
    state: State = cast(
        State,
        await graph.ainvoke(
            cast(State, {"messages": list(messages), "todos": []}),
            config=cast(
                RunnableConfig,
                {
                    "configurable": configurable,
                    "metadata": {"user_id": configurable.get("user_id")},
                    "recursion_limit": accounting.recursion_limit,
                },
            ),
        ),
    )
    history: list[AnyMessage] = state["messages"]
    return history
