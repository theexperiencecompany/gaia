"""
Base sub-agent factory for creating provider-specific agents.

This module provides the core framework for building specialized sub-agents
that can handle specific tool categories with deep domain expertise.
"""

import asyncio

from app.agents.core.nodes import trim_messages_node
from app.agents.core.nodes.delete_system_messages import (
    create_delete_system_messages_node,
)
from app.agents.core.nodes.filter_messages import create_filter_messages_node
from app.agents.tools.core.retrieval import get_retrieve_tools_function
from app.agents.tools.core.store import get_tools_store
from app.agents.tools.memory_tools import get_all_memory, search_memory
from app.config.loggers import langchain_logger as logger
from app.override.langgraph_bigtool.create_agent import create_agent
from langchain_core.language_models import LanguageModelLike
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore
from langgraph_bigtool.graph import State


class SubAgentFactory:
    """Factory for creating provider-specific sub-agents with specialized tool registries."""

    @staticmethod
    async def create_provider_subagent(
        provider: str,
        name: str,
        prompt: str,
        llm: LanguageModelLike,
        tool_space: str = "general",
        retrieve_tools_limit: int = 10,
        use_direct_tools: bool = False,
        disable_retrieve_tools: bool = False,
    ):
        """
        Creates a specialized sub-agent graph for a specific provider with tool registry.

        Args:
            provider: Provider name (gmail, notion, twitter, linkedin, calendar)
            llm: Language model to use
            tool_space: Tool space to use for retrieval (e.g., "gmail_delegated", "general")
            retrieve_tools_limit: Maximum number of tools to retrieve with each retrieval

        Returns:
            Compiled LangGraph agent with tool registry and retrieval
        """
        from app.agents.tools.core.registry import get_tool_registry

        logger.info(
            f"Creating {provider} sub-agent graph using tool space '{tool_space}' with "
            + (
                "direct tools binding"
                if use_direct_tools
                else f"retrieve tools (limit={retrieve_tools_limit})"
            )
        )

        store, tool_registry = await asyncio.gather(
            get_tools_store(), get_tool_registry()
        )

        def transform_output(
            state: State, config: RunnableConfig, store: BaseStore
        ) -> State:
            messages = state["messages"]
            last_message = messages[-1]

            if isinstance(last_message, AIMessage) and not last_message.tool_calls:
                # If the last message is an AI message without tool calls, set its name
                # to include the agent name for filtering
                # Note: Here we are adding "main_agent" as the agent name
                # because last AI Message should be accessible by main agent
                msg_name = (
                    [] if last_message.name is None else last_message.name.split(",")
                )
                msg_name.append("main_agent")
                last_message.name = ",".join(msg_name)

            return state

        # Build common kwargs for agent creation
        common_kwargs = {
            "llm": llm,
            "tool_registry": tool_registry.get_tool_dict(),
            "agent_name": name,
            "pre_model_hooks": [
                create_filter_messages_node(
                    agent_name=name,
                    allow_memory_system_messages=True,
                ),
                trim_messages_node,
            ],
            "end_graph_hooks": [
                transform_output,
                create_delete_system_messages_node(),
            ],
        }

        if use_direct_tools:
            # Resolve initial tool IDs from the registry for the given tool_space
            initial_tool_ids: list[str] = []
            category = tool_registry.get_category(tool_space)
            if category is not None:
                initial_tool_ids.extend([t.name for t in category.tools])

            # Always include memory tools for subagents
            try:
                initial_tool_ids.extend([get_all_memory.name, search_memory.name])
            except Exception:
                pass

            common_kwargs.update(
                {
                    "initial_tool_ids": initial_tool_ids,
                    "disable_retrieve_tools": disable_retrieve_tools,
                }
            )
        else:
            common_kwargs.update(
                {
                    "retrieve_tools_coroutine": get_retrieve_tools_function(
                        tool_space=tool_space,
                        include_core_tools=False,  # Provider agents don't need core tools
                        additional_tools=[get_all_memory, search_memory],
                        limit=retrieve_tools_limit,
                    )
                }
            )

        builder = create_agent(**common_kwargs)

        subagent_graph = builder.compile(store=store, name=name, checkpointer=False)

        logger.info(f"Successfully created {provider} sub-agent graph")
        return subagent_graph
