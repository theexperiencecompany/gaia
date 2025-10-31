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

        # System prompt for MCP agent
        system_prompt = f"""You are a specialized agent for the {server_name} MCP server.

Description: {description}

Your capabilities:
- Execute tools from the {server_name} MCP server
- Access memory tools to remember information across conversations
- Use retrieve_tools to discover available tools from this server

When using retrieve_tools:
1. Use exact tool names if you know them from the system prompt
2. Use semantic queries like "{server_name} [action]" to discover tools
3. Be persistent - try different query variations if needed

Your goal is to help users accomplish tasks using the {server_name} server's capabilities.
Provide clear, helpful responses and explain what you're doing."""

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

        # Get user's MCP servers
        servers = await mcp_service.get_user_servers(user_id)

        if not servers:
            logger.debug(f"No MCP servers configured for user {user_id}")
            return {}

        # Create subagents for enabled servers
        tasks = []
        agent_names = []

        for server in servers:
            if server.enabled:
                tasks.append(
                    MCPSubAgentFactory.create_mcp_subagent(
                        server_name=server.name,
                        description=server.description or "MCP Server",
                        llm=llm,
                    )
                )
                agent_names.append(f"mcp_{server.name}_agent")

        if not tasks:
            return {}

        # Create all subagents in parallel
        subagents = await asyncio.gather(*tasks)

        return dict(zip(agent_names, subagents))
