from typing import Annotated, List, Optional

from app.agents.prompts.gmail_node_prompts import GMAIL_ORCHESTRATOR_PROMPT
from app.agents.prompts.subagent_prompts import (
    LINKEDIN_AGENT_SYSTEM_PROMPT,
    NOTION_AGENT_SYSTEM_PROMPT,
    TWITTER_AGENT_SYSTEM_PROMPT,
)
from app.config.loggers import common_logger as logger
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.graph import MessagesState
from langgraph.prebuilt import InjectedState
from langgraph.types import Command, Send

# Handoff tool description template
HANDOFF_DESCRIPTION_TEMPLATE = (
    "Transfer control to the {provider_name} specialist agent for comprehensive {domain}. "
    "Handles all {provider_name} operations including {capabilities}. "
    "Provide detailed task description and conversation summary for optimal results."
)


def create_handoff_tool(
    *,
    tool_name: str,
    agent_name: str,
    system_prompt: str,
    description: str | None = None,
):
    description = description or f"Transfer to {agent_name}"

    @tool(tool_name, description=description)
    def handoff_tool(
        task_description: Annotated[
            str,
            "Description of what the next agent should do, including all of the relevant context.",
        ],
        state: Annotated[MessagesState, InjectedState],
        tool_call_id: Annotated[str, InjectedToolCallId],
    ) -> Command:
        # Combine task description with conversation summary
        full_context = task_description

        task_description_message = HumanMessage(
            content=full_context,
            name=agent_name,
            additional_kwargs={"visible_to": {agent_name}},
        )
        system_prompt_message = SystemMessage(
            content=system_prompt,
            name=agent_name,
            additional_kwargs={"visible_to": {agent_name}},
        )
        tool_message = ToolMessage(
            content=f"Successfully transferred to {agent_name}",
            tool_call_id=tool_call_id,
            name="main_agent",
            additional_kwargs={"visible_to": {"main_agent"}},
        )

        agent_input = {
            **state,
            "messages": state["messages"]
            + [tool_message]
            + [system_prompt_message, task_description_message],
        }

        return Command(
            goto=[Send(agent_name, agent_input)],
            update={"messages": state["messages"] + [tool_message]},
        )

    return handoff_tool


async def get_mcp_handoff_tools(user_id: str) -> List:
    """
    Get handoff tools for user's configured MCP servers.

    Args:
        user_id: User identifier

    Returns:
        List of handoff tools for MCP servers
    """
    from app.services.mcp import get_mcp_service

    try:
        mcp_service = get_mcp_service()
        servers = await mcp_service.get_user_servers(user_id)

        tools = []
        for server in servers:
            if server.enabled:
                agent_name = f"mcp_{server.name}_agent"
                tool_name = f"call_mcp_{server.name}_agent"

                description = (
                    f"Transfer control to the {server.name} MCP server specialist agent. "
                    f"Description: {server.description}. "
                    f"Use this agent to access {server.name} server capabilities. "
                    f"Provide detailed task description and relevant context."
                )

                system_prompt = f"""You are a specialized agent for the {server.name} MCP server.

{server.description}

Use the available tools from this MCP server to accomplish the user's task.
Always explain what you're doing and provide clear, helpful responses."""

                tool = create_handoff_tool(
                    tool_name=tool_name,
                    agent_name=agent_name,
                    description=description,
                    system_prompt=system_prompt,
                )
                tools.append(tool)

        logger.info(f"Created {len(tools)} MCP handoff tools for user {user_id}")
        return tools

    except Exception as e:
        logger.error(f"Failed to create MCP handoff tools for user {user_id}: {e}")
        return []


def get_handoff_tools(enabled_providers: Optional[List[str]] = None):
    """
    Get handoff tools for enabled provider sub-agent graphs.

    Args:
        enabled_providers: List of enabled provider names
                          ('gmail', 'notion', 'twitter', 'linkedin')

    Returns:
        List of handoff tools for the enabled provider sub-agent graphs
    """

    if enabled_providers is None:
        enabled_providers = ["gmail", "notion", "twitter", "linkedin"]

    tools = []

    if "gmail" in enabled_providers:
        tools.append(
            create_handoff_tool(
                tool_name="call_gmail_agent",
                agent_name="gmail_agent",
                description=HANDOFF_DESCRIPTION_TEMPLATE.format(
                    provider_name="Gmail",
                    domain="email management",
                    capabilities="composing, sending, reading, organizing emails, managing labels, drafts, attachments, and advanced email workflows",
                ),
                system_prompt=GMAIL_ORCHESTRATOR_PROMPT,
            )
        )

    if "notion" in enabled_providers:
        tools.append(
            create_handoff_tool(
                tool_name="call_notion_agent",
                agent_name="notion_agent",
                description=HANDOFF_DESCRIPTION_TEMPLATE.format(
                    provider_name="Notion",
                    domain="workspace management",
                    capabilities="creating pages, managing databases, updating content, organizing workspaces, handling properties, and advanced Notion workflows",
                ),
                system_prompt=NOTION_AGENT_SYSTEM_PROMPT,
            )
        )

    if "twitter" in enabled_providers:
        tools.append(
            create_handoff_tool(
                tool_name="call_twitter_agent",
                agent_name="twitter_agent",
                description=HANDOFF_DESCRIPTION_TEMPLATE.format(
                    provider_name="Twitter",
                    domain="social media management",
                    capabilities="posting tweets, managing threads, engaging with content, analyzing metrics, scheduling posts, and advanced Twitter workflows",
                ),
                system_prompt=TWITTER_AGENT_SYSTEM_PROMPT,
            )
        )

    if "linkedin" in enabled_providers:
        tools.append(
            create_handoff_tool(
                tool_name="call_linkedin_agent",
                agent_name="linkedin_agent",
                description=HANDOFF_DESCRIPTION_TEMPLATE.format(
                    provider_name="LinkedIn",
                    domain="professional networking management",
                    capabilities="creating posts, managing connections, networking outreach, profile updates, content engagement, and advanced LinkedIn workflows",
                ),
                system_prompt=LINKEDIN_AGENT_SYSTEM_PROMPT,
            )
        )

    logger.info(
        f"Created {len(tools)} handoff tools for providers: {enabled_providers}"
    )
    return tools