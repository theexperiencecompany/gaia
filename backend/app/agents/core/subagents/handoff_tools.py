from typing import Annotated, List, Optional

from app.agents.prompts.github_node_prompts import GITHUB_ORCHESTRATOR_PROMPT
from app.agents.prompts.gmail_node_prompts import GMAIL_ORCHESTRATOR_PROMPT
from app.agents.prompts.hubspot_node_prompts import HUBSPOT_ORCHESTRATOR_PROMPT
from app.agents.prompts.subagent_prompts import (
    AIRTABLE_AGENT_SYSTEM_PROMPT,
    ASANA_AGENT_SYSTEM_PROMPT,
    CALENDAR_AGENT_SYSTEM_PROMPT,
    CLICKUP_AGENT_SYSTEM_PROMPT,
    GOOGLE_MAPS_AGENT_SYSTEM_PROMPT,
    GOOGLE_MEET_AGENT_SYSTEM_PROMPT,
    GOOGLE_SHEETS_AGENT_SYSTEM_PROMPT,
    GOOGLE_TASKS_AGENT_SYSTEM_PROMPT,
    INSTAGRAM_AGENT_SYSTEM_PROMPT,
    LINEAR_AGENT_SYSTEM_PROMPT,
    LINKEDIN_AGENT_SYSTEM_PROMPT,
    MICROSOFT_TEAMS_AGENT_SYSTEM_PROMPT,
    NOTION_AGENT_SYSTEM_PROMPT,
    REDDIT_AGENT_SYSTEM_PROMPT,
    SLACK_AGENT_SYSTEM_PROMPT,
    TODOIST_AGENT_SYSTEM_PROMPT,
    TRELLO_AGENT_SYSTEM_PROMPT,
    TWITTER_AGENT_SYSTEM_PROMPT,
    ZOOM_AGENT_SYSTEM_PROMPT,
)
from app.config.loggers import common_logger as logger
from app.config.oauth_config import get_integration_by_id
from app.services.composio.composio_service import get_composio_service
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
    """Check if integration is connected and return error command if not.

    Returns:
        Command with error message if not connected, None if connected or check failed
    """
    try:
        integration = get_integration_by_id(integration_id)
        if not integration or integration.managed_by != "composio":
            return None

        composio_service = get_composio_service()
        status_map = await composio_service.check_connection_status(
            [integration.provider], user_id
        )

        if status_map.get(integration.provider, False):
            return None

        # Not connected - stream prompt and return error
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


def create_handoff_tool(
    *,
    tool_name: str,
    agent_name: str,
    system_prompt: str,
    description: str | None = None,
    integration_id: Optional[str] = None,
):
    """Create a handoff tool that transfers control to a specialized subagent.

    Args:
        tool_name: Name of the tool
        agent_name: Name of the target agent
        system_prompt: System prompt for the agent
        description: Tool description (optional)
        integration_id: Integration ID to check connection (optional)
    """
    description = description or f"Transfer to {agent_name}"

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
            additional_kwargs={"visible_to": {"main_agent"}},
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


def get_handoff_tools(enabled_providers: List[str]):
    """
    Get handoff tools for enabled provider sub-agent graphs.

    Args:
        enabled_providers: List of enabled provider names

    Returns:
        List of handoff tools for the enabled provider sub-agent graphs
    """
    tools = []

    if "gmail" in enabled_providers:
        tools.append(
            create_handoff_tool(
                tool_name="call_gmail_agent",
                agent_name="gmail_agent",
                description=HANDOFF_DESCRIPTION_TEMPLATE.format(
                    provider_name="Gmail",
                    domain="email",
                    capabilities="composing emails, sending messages, reading inbox, organizing with labels, managing drafts, handling attachments, searching emails, and automating email workflows",
                    use_cases="any email-related task including sending, reading, organizing, or automating email operations",
                ),
                system_prompt=GMAIL_ORCHESTRATOR_PROMPT,
                integration_id="gmail",
            )
        )

    if "notion" in enabled_providers:
        tools.append(
            create_handoff_tool(
                tool_name="call_notion_agent",
                agent_name="notion_agent",
                description=HANDOFF_DESCRIPTION_TEMPLATE.format(
                    provider_name="Notion",
                    domain="workspace and knowledge management",
                    capabilities="creating pages, building databases, updating content, organizing workspaces, managing properties, searching content, and structuring knowledge bases",
                    use_cases="creating pages, managing databases, organizing knowledge, or any Notion workspace operation",
                ),
                system_prompt=NOTION_AGENT_SYSTEM_PROMPT,
                integration_id="notion",
            )
        )

    if "twitter" in enabled_providers:
        tools.append(
            create_handoff_tool(
                tool_name="call_twitter_agent",
                agent_name="twitter_agent",
                description=HANDOFF_DESCRIPTION_TEMPLATE.format(
                    provider_name="Twitter/X",
                    domain="social media",
                    capabilities="posting tweets, creating threads, replying to posts, liking content, retweeting, following users, analyzing engagement metrics, and managing Twitter presence",
                    use_cases="posting tweets, engaging with content, managing followers, or analyzing Twitter activity",
                ),
                system_prompt=TWITTER_AGENT_SYSTEM_PROMPT,
                integration_id="twitter",
            )
        )

    if "linkedin" in enabled_providers:
        tools.append(
            create_handoff_tool(
                tool_name="call_linkedin_agent",
                agent_name="linkedin_agent",
                description=HANDOFF_DESCRIPTION_TEMPLATE.format(
                    provider_name="LinkedIn",
                    domain="professional networking",
                    capabilities="creating professional posts, managing connections, networking outreach, updating profile, engaging with content, job searching, and building professional presence",
                    use_cases="posting professional content, managing connections, networking, or any LinkedIn career-related activity",
                ),
                system_prompt=LINKEDIN_AGENT_SYSTEM_PROMPT,
                integration_id="linkedin",
            )
        )

    if "github" in enabled_providers:
        tools.append(
            create_handoff_tool(
                tool_name="call_github_agent",
                agent_name="github_agent",
                description=HANDOFF_DESCRIPTION_TEMPLATE.format(
                    provider_name="GitHub",
                    domain="code repository and development workflow",
                    capabilities="managing repositories, creating issues, handling pull requests, managing branches, reviewing code, managing collaborators, and automating development workflows",
                    use_cases="repository management, issue tracking, pull requests, code review, or any GitHub development task",
                ),
                system_prompt=GITHUB_ORCHESTRATOR_PROMPT,
                integration_id="github",
            )
        )

    if "reddit" in enabled_providers:
        tools.append(
            create_handoff_tool(
                tool_name="call_reddit_agent",
                agent_name="reddit_agent",
                description=HANDOFF_DESCRIPTION_TEMPLATE.format(
                    provider_name="Reddit",
                    domain="community engagement",
                    capabilities="posting to subreddits, commenting on posts, replying to discussions, searching content, managing karma, engaging with communities, and following reddiquette",
                    use_cases="posting to Reddit, commenting, engaging with communities, or managing Reddit presence",
                ),
                system_prompt=REDDIT_AGENT_SYSTEM_PROMPT,
                integration_id="reddit",
            )
        )

    if "airtable" in enabled_providers:
        tools.append(
            create_handoff_tool(
                tool_name="call_airtable_agent",
                agent_name="airtable_agent",
                description=HANDOFF_DESCRIPTION_TEMPLATE.format(
                    provider_name="Airtable",
                    domain="database and data management",
                    capabilities="creating bases, managing tables, adding records, updating data, creating views, configuring fields, linking records, and automating data workflows",
                    use_cases="database creation, data management, record operations, or any Airtable workflow automation",
                ),
                system_prompt=AIRTABLE_AGENT_SYSTEM_PROMPT,
                integration_id="airtable",
            )
        )

    if "linear" in enabled_providers:
        tools.append(
            create_handoff_tool(
                tool_name="call_linear_agent",
                agent_name="linear_agent",
                description=HANDOFF_DESCRIPTION_TEMPLATE.format(
                    provider_name="Linear",
                    domain="project and issue tracking",
                    capabilities="creating issues, managing projects, organizing cycles, tracking progress, setting priorities, managing labels, updating statuses, and coordinating team workflows",
                    use_cases="issue tracking, project management, sprint planning, or any Linear project coordination task",
                ),
                system_prompt=LINEAR_AGENT_SYSTEM_PROMPT,
                integration_id="linear",
            )
        )

    if "slack" in enabled_providers:
        tools.append(
            create_handoff_tool(
                tool_name="call_slack_agent",
                agent_name="slack_agent",
                description=HANDOFF_DESCRIPTION_TEMPLATE.format(
                    provider_name="Slack",
                    domain="team communication",
                    capabilities="sending messages, creating channels, managing threads, direct messaging, mentioning users, adding reactions, uploading files, and automating team communication",
                    use_cases="sending Slack messages, channel management, team communication, or any Slack collaboration task",
                ),
                system_prompt=SLACK_AGENT_SYSTEM_PROMPT,
                integration_id="slack",
            )
        )

    if "hubspot" in enabled_providers:
        tools.append(
            create_handoff_tool(
                tool_name="call_hubspot_agent",
                agent_name="hubspot_agent",
                description=HANDOFF_DESCRIPTION_TEMPLATE.format(
                    provider_name="HubSpot",
                    domain="CRM and sales/marketing automation",
                    capabilities="managing contacts, tracking deals, organizing companies, logging activities, creating tasks, sending emails, managing pipeline, and automating sales/marketing workflows",
                    use_cases="CRM management, sales tracking, marketing automation, contact management, or any HubSpot operation",
                ),
                system_prompt=HUBSPOT_ORCHESTRATOR_PROMPT,
                integration_id="hubspot",
            )
        )

    if "googletasks" in enabled_providers:
        tools.append(
            create_handoff_tool(
                tool_name="call_google_tasks_agent",
                agent_name="google_tasks_agent",
                description=HANDOFF_DESCRIPTION_TEMPLATE.format(
                    provider_name="Google Tasks",
                    domain="task management",
                    capabilities="creating tasks, organizing task lists, setting due dates, adding notes, managing subtasks, completing tasks, and integrating with Gmail and Calendar",
                    use_cases="task creation, to-do list management, deadline tracking, or any Google Tasks operation",
                ),
                system_prompt=GOOGLE_TASKS_AGENT_SYSTEM_PROMPT,
                integration_id="googletasks",
            )
        )

    if "googlesheets" in enabled_providers:
        tools.append(
            create_handoff_tool(
                tool_name="call_google_sheets_agent",
                agent_name="google_sheets_agent",
                description=HANDOFF_DESCRIPTION_TEMPLATE.format(
                    provider_name="Google Sheets",
                    domain="spreadsheet and data management",
                    capabilities="creating spreadsheets, managing sheets, reading/writing cell data, applying formulas, formatting data, batch operations, and automating spreadsheet workflows",
                    use_cases="spreadsheet creation, data entry, formula management, data analysis, or any Google Sheets operation",
                ),
                system_prompt=GOOGLE_SHEETS_AGENT_SYSTEM_PROMPT,
                integration_id="googlesheets",
            )
        )

    if "todoist" in enabled_providers:
        tools.append(
            create_handoff_tool(
                tool_name="call_todoist_agent",
                agent_name="todoist_agent",
                description=HANDOFF_DESCRIPTION_TEMPLATE.format(
                    provider_name="Todoist",
                    domain="task and project management",
                    capabilities="creating tasks, managing projects, organizing with sections and labels, setting priorities and due dates, tracking completion, and automating productivity workflows",
                    use_cases="task creation, project organization, productivity tracking, to-do management, or any Todoist workflow",
                ),
                system_prompt=TODOIST_AGENT_SYSTEM_PROMPT,
                integration_id="todoist",
            )
        )

    if "microsoft_teams" in enabled_providers:
        tools.append(
            create_handoff_tool(
                tool_name="call_microsoft_teams_agent",
                agent_name="microsoft_teams_agent",
                description=HANDOFF_DESCRIPTION_TEMPLATE.format(
                    provider_name="Microsoft Teams",
                    domain="team collaboration and communication",
                    capabilities="sending messages, managing channels, scheduling meetings, sharing files, organizing team discussions, and automating collaboration workflows",
                    use_cases="team messaging, channel management, meeting scheduling, file sharing, or any Teams collaboration task",
                ),
                system_prompt=MICROSOFT_TEAMS_AGENT_SYSTEM_PROMPT,
                integration_id="microsoft_teams",
            )
        )

    if "googlemeet" in enabled_providers:
        tools.append(
            create_handoff_tool(
                tool_name="call_google_meet_agent",
                agent_name="google_meet_agent",
                description=HANDOFF_DESCRIPTION_TEMPLATE.format(
                    provider_name="Google Meet",
                    domain="video conferencing and meeting management",
                    capabilities="creating meetings, scheduling video calls, generating meeting links, managing participants, and organizing virtual collaboration",
                    use_cases="video meeting creation, scheduling calls, generating meeting links, or any Google Meet operation",
                ),
                system_prompt=GOOGLE_MEET_AGENT_SYSTEM_PROMPT,
                integration_id="googlemeet",
            )
        )

    if "zoom" in enabled_providers:
        tools.append(
            create_handoff_tool(
                tool_name="call_zoom_agent",
                agent_name="zoom_agent",
                description=HANDOFF_DESCRIPTION_TEMPLATE.format(
                    provider_name="Zoom",
                    domain="video conferencing and webinar management",
                    capabilities="creating meetings, managing webinars, scheduling video calls, handling recordings, configuring settings, managing participants, and organizing virtual events",
                    use_cases="video meeting creation, webinar management, call scheduling, recording management, or any Zoom operation",
                ),
                system_prompt=ZOOM_AGENT_SYSTEM_PROMPT,
                integration_id="zoom",
            )
        )

    if "google_maps" in enabled_providers:
        tools.append(
            create_handoff_tool(
                tool_name="call_google_maps_agent",
                agent_name="google_maps_agent",
                description=HANDOFF_DESCRIPTION_TEMPLATE.format(
                    provider_name="Google Maps",
                    domain="location search and navigation",
                    capabilities="searching locations, getting directions, finding nearby places, geocoding addresses, calculating distances, and providing travel information",
                    use_cases="location search, route planning, finding nearby places, address geocoding, or any Google Maps operation",
                ),
                system_prompt=GOOGLE_MAPS_AGENT_SYSTEM_PROMPT,
                integration_id="google_maps",
            )
        )

    if "asana" in enabled_providers:
        tools.append(
            create_handoff_tool(
                tool_name="call_asana_agent",
                agent_name="asana_agent",
                description=HANDOFF_DESCRIPTION_TEMPLATE.format(
                    provider_name="Asana",
                    domain="project and task management",
                    capabilities="creating tasks, managing projects, organizing with sections, assigning team members, setting due dates, tracking progress, adding subtasks, and automating project workflows",
                    use_cases="task management, project organization, team collaboration, sprint planning, or any Asana workflow",
                ),
                system_prompt=ASANA_AGENT_SYSTEM_PROMPT,
                integration_id="asana",
            )
        )

    if "trello" in enabled_providers:
        tools.append(
            create_handoff_tool(
                tool_name="call_trello_agent",
                agent_name="trello_agent",
                description=HANDOFF_DESCRIPTION_TEMPLATE.format(
                    provider_name="Trello",
                    domain="visual project management and organization",
                    capabilities="creating boards, managing cards and lists, organizing with labels and checklists, managing team members, and visual workflow management",
                    use_cases="board creation, card management, visual project organization, or team collaboration",
                ),
                system_prompt=TRELLO_AGENT_SYSTEM_PROMPT,
                integration_id="trello",
            )
        )

    if "clickup" in enabled_providers:
        tools.append(
            create_handoff_tool(
                tool_name="call_clickup_agent",
                agent_name="clickup_agent",
                description=HANDOFF_DESCRIPTION_TEMPLATE.format(
                    provider_name="ClickUp",
                    domain="comprehensive project and task management",
                    capabilities="managing tasks and projects, tracking time, setting goals, organizing workspaces, team collaboration, and workflow automation",
                    use_cases="task management, time tracking, goal setting, workspace organization, or team workflows",
                ),
                system_prompt=CLICKUP_AGENT_SYSTEM_PROMPT,
                integration_id="clickup",
            )
        )

    if "calendar" in enabled_providers:
        tools.append(
            create_handoff_tool(
                tool_name="call_calendar_agent",
                agent_name="calendar_agent",
                description=HANDOFF_DESCRIPTION_TEMPLATE.format(
                    provider_name="Calendar",
                    domain="calendar and event management",
                    capabilities="creating events, scheduling meetings, managing calendars, searching events, editing appointments, handling recurring events, and comprehensive calendar workflows",
                    use_cases="event creation, meeting scheduling, calendar management, or any calendar-related task",
                ),
                system_prompt=CALENDAR_AGENT_SYSTEM_PROMPT,
                integration_id="google_calendar",
            )
        )

    if "instagram" in enabled_providers:
        tools.append(
            create_handoff_tool(
                tool_name="call_instagram_agent",
                agent_name="instagram_agent",
                description=HANDOFF_DESCRIPTION_TEMPLATE.format(
                    provider_name="Instagram",
                    domain="social media management",
                    capabilities="posting photos and videos, managing stories, engaging with followers, analyzing metrics, and automating Instagram workflows",
                    use_cases="posting content, managing stories, engaging with followers, or analyzing Instagram activity",
                ),
                system_prompt=INSTAGRAM_AGENT_SYSTEM_PROMPT,
                integration_id="instagram",
            )
        )

    logger.info(
        f"Created {len(tools)} handoff tools for providers: {enabled_providers}"
    )
    return tools
