"""
MCP Sub-agent Factory

Creates specialized sub-agents for each MCP server with tool registry and retrieval.
"""

import asyncio
from typing import Any, Dict

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


class MCPSubAgentFactory:
    """Factory for creating MCP server-specific sub-agents."""

    @staticmethod
    async def create_mcp_subagent(
        server_name: str,
        description: str,
        llm: LanguageModelLike,
    ) -> Any:
        """
        Create a specialized sub-agent for an MCP server.

        Args:
            server_name: Name of the MCP server
            description: Description of the MCP server capabilities
            llm: Language model to use

        Returns:
            Compiled LangGraph agent for the MCP server
        """
        from app.agents.tools.core.registry import get_tool_registry

        agent_name = f"mcp_{server_name}_agent"
        tool_space = f"mcp_{server_name}"

        logger.info(
            f"Creating MCP sub-agent for server '{server_name}' using tool space '{tool_space}'"
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
                msg_name = (
                    [] if last_message.name is None else last_message.name.split(",")
                )
                msg_name.append("main_agent")
                last_message.name = ",".join(msg_name)

            return state

        # Create agent with tool registry and retrieval filtering
        builder = create_agent(
            llm=llm,
            tool_registry=tool_registry.get_tool_dict(),
            agent_name=agent_name,
            retrieve_tools_coroutine=get_retrieve_tools_function(
                tool_space=tool_space,
                include_core_tools=False,
                additional_tools=[get_all_memory, search_memory],
                limit=15,  # MCP servers might have many tools
            ),
            pre_model_hooks=[
                create_filter_messages_node(
                    agent_name=agent_name,
                    allow_memory_system_messages=True,
                ),
                trim_messages_node,
            ],
            end_graph_hooks=[
                transform_output,
                create_delete_system_messages_node(),
            ],
        )

        subagent_graph = builder.compile(
            store=store, name=agent_name, checkpointer=False
        )

        logger.info(f"Successfully created MCP sub-agent for server '{server_name}'")
        return subagent_graph

    @staticmethod
    async def create_all_mcp_subagents(
        llm: LanguageModelLike, user_id: str
    ) -> Dict[str, Any]:
        """
        Create sub-agents for all configured MCP servers for a user.

        Args:
            llm: Language model to use
            user_id: User identifier

        Returns:
            Dictionary mapping agent names to compiled sub-agent graphs
        """
        from app.services.mcp import get_mcp_service

        mcp_service = get_mcp_service()

        # Get user's MCP servers from MongoDB
        servers = await mcp_service.get_user_servers(user_id)

        if not servers:
            logger.debug(f"No MCP servers configured for user {user_id}")
            return {}

        # Create subagents for enabled servers
        tasks = []
        agent_names = []

        for server in servers:
            if server.get("enabled", True):
                server_name = server.get("server_name")
                if not server_name:
                    logger.warning(
                        f"Skipping server with missing server_name: {server}"
                    )
                    continue

                display_name = server.get("display_name", server_name)
                description = server.get("description", f"{display_name} MCP Server")

                tasks.append(
                    MCPSubAgentFactory.create_mcp_subagent(
                        server_name=server_name,
                        description=description,
                        llm=llm,
                    )
                )
                agent_names.append(f"mcp_{server_name}_agent")

        if not tasks:
            return {}

        # Create all subagents in parallel
        subagents = await asyncio.gather(*tasks)

        return dict(zip(agent_names, subagents))
