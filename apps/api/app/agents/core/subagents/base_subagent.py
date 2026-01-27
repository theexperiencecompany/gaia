"""
Base sub-agent factory for creating provider-specific agents.

This module provides the core framework for building specialized sub-agents
that can handle specific tool categories with deep domain expertise.

Subagents are now standalone graphs with their own checkpointers,
invoked via tool-calling pattern similar to executor_agent.
"""

import asyncio

from app.agents.core.graph_builder.checkpointer_manager import get_checkpointer_manager
from app.agents.core.nodes import manage_system_prompts_node, trim_messages_node
from app.agents.core.nodes.filter_messages import filter_messages_node
from app.agents.tools.core.retrieval import get_retrieve_tools_function
from app.agents.tools.core.store import get_tools_store
from app.agents.tools.memory_tools import search_memory
from app.config.loggers import langchain_logger as logger
from app.override.langgraph_bigtool.create_agent import create_agent
from langchain_core.language_models import LanguageModelLike
from langgraph.checkpoint.memory import InMemorySaver


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
    ):
        """
        Creates a specialized sub-agent graph for a specific provider with tool registry.

        Args:
            provider: Provider name (gmail, notion, twitter, linkedin, calendar)
            llm: Language model to use
            tool_space: Tool space to use for retrieval (e.g., "gmail_delegated", "general")

        Returns:
            Compiled LangGraph agent with tool registry, retrieval, and checkpointer
        """
        from app.agents.tools.core.registry import get_tool_registry

        logger.info(
            f"Creating {provider} sub-agent graph using tool space '{tool_space}' with "
            + ("direct tools binding" if use_direct_tools else "retrieve tools")
        )

        store, tool_registry = await asyncio.gather(
            get_tools_store(), get_tool_registry()
        )

        # Build scoped tool_dict containing only tools for this subagent's tool_space
        # This ensures subagents can only access their own integration's tools
        scoped_tool_dict: dict = {}
        initial_tool_ids: list[str] = []

        # Get category by tool_space (handles dynamic category names like mcp_{integration}_{user_id})
        category = tool_registry.get_category_by_space(tool_space)
        if category is not None:
            for t in category.tools:
                scoped_tool_dict[t.name] = t.tool
                initial_tool_ids.append(t.name)

        # Add search_memory to scoped_tool_dict so subagents can access user memories
        scoped_tool_dict[search_memory.name] = search_memory

        common_kwargs = {
            "llm": llm,
            "tool_registry": scoped_tool_dict,  # Use scoped dict instead of global
            "agent_name": name,
            "pre_model_hooks": [
                filter_messages_node,
                manage_system_prompts_node,
                trim_messages_node,
            ],
        }

        if use_direct_tools:
            # Direct binding: tools are already extracted above
            common_kwargs.update(
                {
                    "initial_tool_ids": initial_tool_ids,
                    "disable_retrieve_tools": disable_retrieve_tools,
                }
            )
        else:
            # Use retrieve_tools with scoped tool_space (no subagent nesting)
            # No initial_tool_ids needed - subagent will retrieve tools dynamically
            common_kwargs.update(
                {
                    "retrieve_tools_coroutine": get_retrieve_tools_function(
                        tool_space=tool_space,
                        include_subagents=False,
                    ),
                    "initial_tool_ids": [search_memory.name],
                }
            )

        builder = create_agent(**common_kwargs)  # type: ignore[arg-type]

        try:
            checkpointer_manager = await get_checkpointer_manager()
            checkpointer = checkpointer_manager.get_checkpointer()
            logger.debug(f"Using PostgreSQL checkpointer for {provider} sub-agent")
        except Exception as e:
            logger.warning(
                f"PostgreSQL checkpointer unavailable for {provider} sub-agent: {e}. Using InMemorySaver."
            )
            checkpointer = InMemorySaver()

        subagent_graph = builder.compile(
            store=store, name=name, checkpointer=checkpointer
        )

        logger.info(
            f"Successfully created {provider} sub-agent graph with checkpointer"
        )
        return subagent_graph
