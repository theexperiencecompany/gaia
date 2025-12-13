"""
Handoff Tools - Single Source of Truth

This module creates handoff tools dynamically from OAuth integration configs.
All metadata comes from oauth_config.py OAUTH_INTEGRATIONS.
"""

from typing import Annotated, Optional

from app.config.loggers import common_logger as logger
from app.config.oauth_config import OAUTH_INTEGRATIONS, get_integration_by_id
from app.services.oauth_service import check_integration_status
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.config import get_stream_writer
from langgraph.graph import MessagesState
from langgraph.prebuilt import InjectedState
from langgraph.types import Command, Send

# Handoff tool description template
HANDOFF_DESCRIPTION_TEMPLATE = (
    "Delegate to the specialized {provider_name} agent for {domain} tasks. "
    "This expert agent handles: {capabilities}. "
    "Use for {use_cases}."
)


async def check_integration_connection(
    integration_id: str,
    user_id: str,
    tool_call_id: str,
    state: MessagesState,
) -> Optional[Command]:
    """Check if integration is connected and return error command if not."""
    try:
        integration = get_integration_by_id(integration_id)
        if not integration:
            return None

        is_connected = await check_integration_status(integration_id, user_id)

        if is_connected:
            return None

        writer = get_stream_writer()
        writer({"progress": f"Checking {integration.name} connection..."})

        integration_data = {
            "integration_id": integration.id,
            "message": f"To use {integration.name} features, please connect your account first.",
        }

        writer({"integration_connection_required": integration_data})

        tool_message = ToolMessage(
            content=f"Integration {integration.name} is not connected. Please connect it first.",
            tool_call_id=tool_call_id,
        )

        return Command(update={"messages": state["messages"] + [tool_message]})

    except Exception as e:
        logger.error(f"Error checking integration status for {integration_id}: {e}")
        return None


def create_handoff_tool(integration_id: str):
    """Create a handoff tool dynamically from OAuth integration configuration.

    Args:
        integration_id: Integration ID from OAUTH_INTEGRATIONS

    Returns:
        Handoff tool function or None if integration has no subagent
    """
    integration = get_integration_by_id(integration_id)
    if not integration or not integration.subagent_config:
        logger.debug(f"Integration {integration_id} has no subagent configuration")
        return None

    if not integration.subagent_config.has_subagent:
        return None

    config = integration.subagent_config
    tool_name = config.handoff_tool_name
    agent_name = config.agent_name
    system_prompt = config.system_prompt or ""

    description = HANDOFF_DESCRIPTION_TEMPLATE.format(
        provider_name=integration.name,
        domain=config.domain,
        capabilities=config.capabilities,
        use_cases=config.use_cases,
    )

    @tool(tool_name, description=description)
    async def handoff_tool(
        task_description: Annotated[
            str,
            "Description of what the next agent should do, including all of the relevant context.",
        ],
        state: Annotated[MessagesState, InjectedState],
        tool_call_id: Annotated[str, InjectedToolCallId],
        config: RunnableConfig,
    ) -> Command:
        # Check integration connection if required
        if integration_id:
            user_id = config.get("metadata", {}).get("user_id")
            if user_id:
                error_command = await check_integration_connection(
                    integration_id, user_id, tool_call_id, state
                )
                if error_command:
                    return error_command

        # Build handoff messages
        task_description_message = HumanMessage(
            content=task_description,
            additional_kwargs={"visible_to": {agent_name}},
        )
        system_prompt_message = SystemMessage(
            content=system_prompt,
            additional_kwargs={"visible_to": {agent_name}},
        )
        tool_message = ToolMessage(
            content=f"Successfully transferred to {agent_name}",
            tool_call_id=tool_call_id,
            additional_kwargs={
                "visible_to": {"main_agent"},
                "is_handoff_toolcall": True,
            },
        )

        agent_input = {
            **state,
            "messages": state["messages"]
            + [tool_message, system_prompt_message, task_description_message],
        }

        return Command(
            goto=[Send(agent_name, agent_input)],
            update={"messages": state["messages"] + [tool_message]},
        )

    return handoff_tool


def get_handoff_tools(enabled_providers: list[str] | None = None):
    """Get handoff tools dynamically from OAuth integration configs.

    Args:
        enabled_providers: Optional list of integration IDs to filter by.
                          If None, returns all integrations with subagents.

    Returns:
        List of handoff tools created from integration configurations
    """
    tools = []

    for integration in OAUTH_INTEGRATIONS:
        if enabled_providers and integration.id not in enabled_providers:
            continue

        if (
            not integration.subagent_config
            or not integration.subagent_config.has_subagent
        ):
            continue

        handoff_tool = create_handoff_tool(integration.id)
        if handoff_tool:
            tools.append(handoff_tool)

    logger.info(f"Created {len(tools)} handoff tools from integration configs")
    return tools
