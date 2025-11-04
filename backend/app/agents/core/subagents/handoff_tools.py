from typing import Annotated, List, Optional

from app.agents.prompts.gmail_node_prompts import GMAIL_ORCHESTRATOR_PROMPT
from app.agents.prompts.subagent_prompts import (
    AIRTABLE_AGENT_SYSTEM_PROMPT,
    GITHUB_AGENT_SYSTEM_PROMPT,
    GOOGLE_SHEETS_AGENT_SYSTEM_PROMPT,
    GOOGLE_TASKS_AGENT_SYSTEM_PROMPT,
    HUBSPOT_AGENT_SYSTEM_PROMPT,
    LINEAR_AGENT_SYSTEM_PROMPT,
    LINKEDIN_AGENT_SYSTEM_PROMPT,
    NOTION_AGENT_SYSTEM_PROMPT,
    REDDIT_AGENT_SYSTEM_PROMPT,
    SLACK_AGENT_SYSTEM_PROMPT,
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
    "Delegate to the specialized {provider_name} agent for {domain} tasks. "
    "This expert agent handles: {capabilities}. "
    "Use for {use_cases}."
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
            + [tool_message]
            + [system_prompt_message, task_description_message],
        }

        return Command(
            goto=[Send(agent_name, agent_input)],
            update={"messages": state["messages"] + [tool_message]},
        )

    return handoff_tool


def get_handoff_tools(enabled_providers: Optional[List[str]] = None):
    """
    Get handoff tools for enabled provider sub-agent graphs.

    Args:
        enabled_providers: List of enabled provider names

    Returns:
        List of handoff tools for the enabled provider sub-agent graphs
    """

    if enabled_providers is None:
        enabled_providers = [
            "gmail",
            "notion",
            "twitter",
            "linkedin",
            "github",
            "reddit",
            "airtable",
            "linear",
            "slack",
            "hubspot",
            "google_tasks",
            "google_sheets",
        ]

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
                system_prompt=GITHUB_AGENT_SYSTEM_PROMPT,
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
                system_prompt=HUBSPOT_AGENT_SYSTEM_PROMPT,
            )
        )

    if "google_tasks" in enabled_providers:
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
            )
        )

    if "google_sheets" in enabled_providers:
        tools.append(
            create_handoff_tool(
                tool_name="call_google_sheets_agent",
                agent_name="google_sheets_agent",
                description=HANDOFF_DESCRIPTION_TEMPLATE.format(
                    provider_name="Google Sheets",
                    domain="spreadsheet and data automation",
                    capabilities="creating spreadsheets, reading data, updating cells, managing sheets, applying formulas, formatting data, working with ranges, and automating spreadsheet workflows",
                    use_cases="spreadsheet creation, data entry, formula management, data analysis, or any Google Sheets operation",
                ),
                system_prompt=GOOGLE_SHEETS_AGENT_SYSTEM_PROMPT,
            )
        )

    # if "calendar" in enabled_providers:
    #     tools.append(
    #         create_handoff_tool(
    #             tool_name="call_calendar_agent",
    #             agent_name="calendar_agent",
    #             description=HANDOFF_DESCRIPTION_TEMPLATE.format(
    #                 provider_name="Calendar",
    #                 domain="calendar and event management",
    #                 capabilities="creating events, scheduling meetings, managing calendars, searching events, editing appointments, handling recurring events, and comprehensive calendar workflows",
    #             ),
    #             system_prompt=CALENDAR_AGENT_SYSTEM_PROMPT,
    #         )
    #     )

    logger.info(
        f"Created {len(tools)} handoff tools for providers: {enabled_providers}"
    )
    return tools
