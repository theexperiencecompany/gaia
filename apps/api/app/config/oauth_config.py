"""
OAuth Integration Configuration

Single source of truth for all OAuth integration configurations in GAIA.
Defines integrations, scopes, display properties, and subagent configurations.
"""

from functools import cache
from typing import Dict, List, Optional

from app.agents.prompts.subagent_prompts import (
    AIRTABLE_AGENT_SYSTEM_PROMPT,
    ASANA_AGENT_SYSTEM_PROMPT,
    CALENDAR_AGENT_SYSTEM_PROMPT,
    CLICKUP_AGENT_SYSTEM_PROMPT,
    GITHUB_AGENT_SYSTEM_PROMPT,
    GMAIL_AGENT_SYSTEM_PROMPT,
    GOOGLE_MAPS_AGENT_SYSTEM_PROMPT,
    GOOGLE_MEET_AGENT_SYSTEM_PROMPT,
    GOOGLE_SHEETS_AGENT_SYSTEM_PROMPT,
    GOOGLE_TASKS_AGENT_SYSTEM_PROMPT,
    HUBSPOT_AGENT_SYSTEM_PROMPT,
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
from app.langchain.core.subgraphs.github_subgraph import GITHUB_TOOLS
from app.models.oauth_models import (
    ComposioConfig,
    OAuthIntegration,
    OAuthScope,
    ProviderMetadataConfig,
    SubAgentConfig,
    TriggerConfig,
)

# Define all integrations dynamically
OAUTH_INTEGRATIONS: List[OAuthIntegration] = [
    # Individual Google integrations
    OAuthIntegration(
        id="google_calendar",
        name="Google Calendar",
        description="Schedule meetings and manage your calendar events",
        category="productivity",
        provider="google",
        scopes=[
            OAuthScope(
                scope="https://www.googleapis.com/auth/calendar.events",
                description="Create and manage calendar events",
            ),
            OAuthScope(
                scope="https://www.googleapis.com/auth/calendar.readonly",
                description="View calendar events",
            ),
        ],
        is_featured=True,
        short_name="calendar",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_exqcpnLvCzGJ",
            toolkit="GOOGLECALENDAR",
        ),
        subagent_config=SubAgentConfig(
            has_subagent=True,
            agent_name="google_calendar_agent",
            tool_space="google_calendar",
            handoff_tool_name="call_calendar_agent",
            domain="calendar and event management",
            capabilities="creating events, scheduling meetings, managing availability, setting reminders, updating calendar entries, and organizing schedules",
            use_cases="scheduling meetings, managing calendar events, checking availability, or any calendar-related task",
            system_prompt=CALENDAR_AGENT_SYSTEM_PROMPT,
            specific_tools=[
                "GOOGLECALENDAR_FIND_FREE_SLOTS",
                "GOOGLECALENDAR_FREE_BUSY_QUERY",
                "GOOGLECALENDAR_EVENTS_MOVE",
                "GOOGLECALENDAR_REMOVE_ATTENDEE",
                "GOOGLECALENDAR_CALENDAR_LIST_INSERT",
                "GOOGLECALENDAR_CALENDAR_LIST_UPDATE",
                "GOOGLECALENDAR_CALENDARS_DELETE",
                "GOOGLECALENDAR_CALENDARS_UPDATE",
                "GOOGLECALENDAR_CUSTOM_CREATE_EVENT",
                "GOOGLECALENDAR_CUSTOM_LIST_CALENDARS",
                "GOOGLECALENDAR_CUSTOM_FETCH_EVENTS",
                "GOOGLECALENDAR_CUSTOM_FIND_EVENT",
                "GOOGLECALENDAR_CUSTOM_GET_EVENT",
                "GOOGLECALENDAR_CUSTOM_DELETE_EVENT",
                "GOOGLECALENDAR_CUSTOM_PATCH_EVENT",
                "GOOGLECALENDAR_CUSTOM_ADD_RECURRENCE",
            ],
        ),
    ),
    OAuthIntegration(
        id="google_docs",
        name="Google Docs",
        description="Create and edit documents in your workspace",
        category="productivity",
        provider="google",
        scopes=[
            OAuthScope(
                scope="https://www.googleapis.com/auth/documents",
                description="Create and edit documents",
            ),
        ],
        short_name="docs",
        managed_by="self",
    ),
    OAuthIntegration(
        id="gmail",
        name="Gmail",
        description="Manage emails, compose messages, and organize your inbox",
        category="communication",
        provider="gmail",
        scopes=[
            OAuthScope(
                scope="https://www.googleapis.com/auth/gmail.modify",
                description="Read, compose, and send emails",
            )
        ],
        is_featured=True,
        short_name="gmail",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_svLPDmjcTVMX", toolkit="GMAIL"
        ),
        associated_triggers=[
            TriggerConfig(
                slug="GMAIL_NEW_GMAIL_MESSAGE",
                name="New Gmail Message",
                description="Triggered when a new Gmail message arrives",
                config={"labelIds": "INBOX", "user_id": "me", "interval": 1},
            )
        ],
        subagent_config=SubAgentConfig(
            has_subagent=True,
            agent_name="gmail_agent",
            tool_space="gmail",
            handoff_tool_name="call_gmail_agent",
            domain="email",
            capabilities="composing emails, sending messages, reading inbox, organizing with labels, managing drafts, handling attachments, searching emails, and automating email workflows",
            use_cases="any email-related task including sending, reading, organizing, or automating email operations",
            system_prompt=GMAIL_AGENT_SYSTEM_PROMPT,
        ),
    ),
    # Composio integrations
    OAuthIntegration(
        id="notion",
        name="Notion",
        description="Manage pages, databases, and workspace content",
        category="productivity",
        provider="notion",
        scopes=[],
        available=True,
        is_featured=True,
        short_name="notion",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_DR3IWp9-Kezl",
            toolkit="NOTION",
        ),
        subagent_config=SubAgentConfig(
            has_subagent=True,
            agent_name="notion_agent",
            tool_space="notion",
            handoff_tool_name="call_notion_agent",
            domain="workspace and knowledge management",
            capabilities="creating pages, building databases, updating content, organizing workspaces, managing properties, searching content, and structuring knowledge bases",
            use_cases="creating pages, managing databases, organizing knowledge, or any Notion workspace operation",
            system_prompt=NOTION_AGENT_SYSTEM_PROMPT,
        ),
    ),
    OAuthIntegration(
        id="twitter",
        name="Twitter",
        description="Post tweets, read timelines, and manage your account",
        category="social",
        provider="twitter",
        scopes=[],
        available=True,
        short_name="twitter",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_vloH3fnhIeUa",
            toolkit="TWITTER",
        ),
        subagent_config=SubAgentConfig(
            has_subagent=True,
            agent_name="twitter_agent",
            tool_space="twitter",
            handoff_tool_name="call_twitter_agent",
            domain="social media",
            capabilities="posting tweets, creating threads, replying to posts, liking content, retweeting, following users, analyzing engagement metrics, and managing Twitter presence",
            use_cases="posting tweets, engaging with content, managing followers, or analyzing Twitter activity",
            system_prompt=TWITTER_AGENT_SYSTEM_PROMPT,
        ),
        metadata_config=ProviderMetadataConfig(
            user_info_tool="TWITTER_USER_LOOKUP_ME",
            username_field="data.data.username",
        ),
    ),
    OAuthIntegration(
        id="googlesheets",
        name="Google Sheets",
        description="Create, read, and update spreadsheets",
        category="productivity",
        provider="googlesheets",
        scopes=[],
        available=True,
        short_name="sheets",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_18I3fRfWyXDu",
            toolkit="GOOGLESHEETS",
        ),
        subagent_config=SubAgentConfig(
            has_subagent=True,
            agent_name="google_sheets_agent",
            tool_space="googlesheets",
            handoff_tool_name="call_google_sheets_agent",
            domain="spreadsheet management and data analysis",
            capabilities="creating spreadsheets, updating data, managing formulas, organizing sheets, analyzing data, and building collaborative workbooks",
            use_cases="spreadsheet management, data analysis, formula creation, or any Google Sheets operation",
            system_prompt=GOOGLE_SHEETS_AGENT_SYSTEM_PROMPT,
        ),
    ),
    OAuthIntegration(
        id="linkedin",
        name="LinkedIn",
        description="Share posts and engage with your professional network",
        category="social",
        provider="linkedin",
        scopes=[],
        available=True,
        short_name="linkedin",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_GMeJBELf3z_m",
            toolkit="LINKEDIN",
        ),
        subagent_config=SubAgentConfig(
            has_subagent=True,
            agent_name="linkedin_agent",
            tool_space="linkedin",
            handoff_tool_name="call_linkedin_agent",
            domain="professional networking",
            capabilities="creating professional posts, managing connections, networking outreach, updating profile, engaging with content, job searching, and building professional presence",
            use_cases="posting professional content, managing connections, networking, or any LinkedIn career-related activity",
            system_prompt=LINKEDIN_AGENT_SYSTEM_PROMPT,
        ),
    ),
    OAuthIntegration(
        id="github",
        name="GitHub",
        is_featured=True,
        description="Manage repositories, issues, pull requests, and automate your development workflow",
        category="productivity",
        provider="github",
        scopes=[],
        available=True,
        short_name="github",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_y2VK4j0ATiZo",
            toolkit="GITHUB",
        ),
        subagent_config=SubAgentConfig(
            has_subagent=True,
            agent_name="github_agent",
            tool_space="github",
            handoff_tool_name="call_github_agent",
            domain="code repository and development workflow",
            capabilities="managing repositories, creating issues, handling pull requests, managing branches, reviewing code, managing collaborators, and automating development workflows",
            use_cases="repository management, issue tracking, pull requests, code review, or any GitHub development task",
            system_prompt=GITHUB_AGENT_SYSTEM_PROMPT,
            specific_tools=GITHUB_TOOLS,
        ),
        metadata_config=ProviderMetadataConfig(
            user_info_tool="GITHUB_GET_THE_AUTHENTICATED_USER",
            username_field="data.login",
        ),
    ),
    OAuthIntegration(
        id="reddit",
        name="Reddit",
        description="Post content, manage comments, and engage with communities on Reddit",
        category="social",
        provider="reddit",
        scopes=[],
        available=True,
        short_name="reddit",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_7-hfiMVLhcDN",
            toolkit="REDDIT",
        ),
        subagent_config=SubAgentConfig(
            has_subagent=True,
            agent_name="reddit_agent",
            tool_space="reddit",
            handoff_tool_name="call_reddit_agent",
            domain="community engagement and content sharing",
            capabilities="posting content, commenting on posts, managing subreddits, searching communities, voting on content, and engaging with Reddit communities",
            use_cases="posting to Reddit, engaging with communities, managing subreddit content, or analyzing Reddit activity",
            system_prompt=REDDIT_AGENT_SYSTEM_PROMPT,
        ),
    ),
    OAuthIntegration(
        id="airtable",
        name="Airtable",
        description="Create and manage bases, tables, and records with AI-powered automation",
        category="productivity",
        provider="airtable",
        scopes=[],
        available=True,
        short_name="airtable",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_QPtQsXnIYm4C",
            toolkit="AIRTABLE",
        ),
        subagent_config=SubAgentConfig(
            has_subagent=True,
            agent_name="airtable_agent",
            tool_space="airtable",
            handoff_tool_name="call_airtable_agent",
            domain="database and workflow management",
            capabilities="creating bases, managing tables, updating records, organizing data, building automations, and structuring collaborative databases",
            use_cases="managing Airtable bases, organizing data, creating records, or building database workflows",
            system_prompt=AIRTABLE_AGENT_SYSTEM_PROMPT,
        ),
    ),
    OAuthIntegration(
        id="linear",
        name="Linear",
        description="Manage issues, projects, and track development progress with AI assistance",
        category="productivity",
        provider="linear",
        scopes=[],
        available=True,
        short_name="linear",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_mnrcEhhTXPVS",
            toolkit="LINEAR",
        ),
        subagent_config=SubAgentConfig(
            has_subagent=True,
            agent_name="linear_agent",
            tool_space="linear",
            handoff_tool_name="call_linear_agent",
            domain="issue tracking and project management",
            capabilities="creating issues, managing projects, tracking progress, assigning tasks, organizing sprints, and automating development workflows",
            use_cases="issue management, project tracking, sprint planning, or any Linear development workflow task",
            system_prompt=LINEAR_AGENT_SYSTEM_PROMPT,
        ),
    ),
    OAuthIntegration(
        id="slack",
        name="Slack",
        description="Send messages, manage channels, and automate team communication",
        category="communication",
        provider="slack",
        scopes=[],
        available=True,
        is_featured=True,
        short_name="slack",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_acm0K6K_kWxY",
            toolkit="SLACK",
        ),
        subagent_config=SubAgentConfig(
            has_subagent=True,
            agent_name="slack_agent",
            tool_space="slack",
            handoff_tool_name="call_slack_agent",
            domain="team communication and collaboration",
            capabilities="sending messages, managing channels, organizing conversations, sharing files, setting reminders, and automating team communication workflows",
            use_cases="sending Slack messages, managing channels, team communication, or automating workspace workflows",
            system_prompt=SLACK_AGENT_SYSTEM_PROMPT,
        ),
    ),
    OAuthIntegration(
        id="hubspot",
        name="HubSpot",
        description="Manage CRM contacts, deals, and automate sales and marketing workflows",
        category="productivity",
        provider="hubspot",
        scopes=[],
        available=True,
        short_name="hubspot",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_rcnwYp1PRCVr",
            toolkit="HUBSPOT",
        ),
        subagent_config=SubAgentConfig(
            has_subagent=True,
            agent_name="hubspot_agent",
            tool_space="hubspot",
            handoff_tool_name="call_hubspot_agent",
            domain="CRM and sales automation",
            capabilities="managing contacts, tracking deals, organizing pipelines, automating marketing, managing customer relationships, and analyzing sales data",
            use_cases="CRM management, sales tracking, contact organization, or marketing automation tasks",
            system_prompt=HUBSPOT_AGENT_SYSTEM_PROMPT,
        ),
    ),
    OAuthIntegration(
        id="googletasks",
        name="Google Tasks",
        description="Create, manage, and organize your tasks and to-do lists",
        category="productivity",
        provider="googletasks",
        scopes=[],
        available=True,
        short_name="tasks",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_xPSnVjKyHCDb",
            toolkit="GOOGLETASKS",
        ),
        subagent_config=SubAgentConfig(
            has_subagent=True,
            agent_name="google_tasks_agent",
            tool_space="googletasks",
            handoff_tool_name="call_google_tasks_agent",
            domain="task and to-do list management",
            capabilities="creating tasks, organizing to-do lists, managing task lists, setting due dates, marking tasks complete, and organizing personal productivity",
            use_cases="managing tasks, organizing to-do lists, tracking personal productivity, or any Google Tasks operation",
            system_prompt=GOOGLE_TASKS_AGENT_SYSTEM_PROMPT,
        ),
    ),
    OAuthIntegration(
        id="todoist",
        name="Todoist",
        description="Manage tasks, projects, and productivity workflows with advanced task management",
        category="productivity",
        provider="todoist",
        scopes=[],
        available=True,
        short_name="todoist",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_TOjltL3O2kEB",
            toolkit="TODOIST",
        ),
        subagent_config=SubAgentConfig(
            has_subagent=True,
            agent_name="todoist_agent",
            tool_space="todoist",
            handoff_tool_name="call_todoist_agent",
            domain="task and project management",
            capabilities="creating tasks, organizing projects, setting priorities, managing labels, tracking productivity, and building task workflows",
            use_cases="task management, project organization, productivity tracking, or any Todoist operation",
            system_prompt=TODOIST_AGENT_SYSTEM_PROMPT,
        ),
    ),
    OAuthIntegration(
        id="microsoft_teams",
        name="Microsoft Teams",
        description="Collaborate with teams, send messages, manage channels, and automate team workflows",
        category="communication",
        provider="microsoft_teams",
        scopes=[],
        available=True,
        short_name="teams",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_0kzvAbsi2xu3", toolkit="MICROSOFTTEAMS"
        ),
        subagent_config=SubAgentConfig(
            has_subagent=True,
            agent_name="microsoft_teams_agent",
            tool_space="microsoft_teams",
            handoff_tool_name="call_microsoft_teams_agent",
            domain="team collaboration and communication",
            capabilities="sending messages, managing channels, scheduling meetings, managing teams, file sharing, chat operations, call management, and automating team workflows",
            use_cases="team messaging, channel management, meeting coordination, file sharing, or any Microsoft Teams collaboration task",
            system_prompt=MICROSOFT_TEAMS_AGENT_SYSTEM_PROMPT,
        ),
    ),
    OAuthIntegration(
        id="zoom",
        name="Zoom",
        description="Create and manage Zoom meetings, webinars, and video conferencing",
        category="communication",
        provider="zoom",
        scopes=[],
        available=True,
        short_name="zoom",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_fABNBG17lf2A", toolkit="ZOOM"
        ),
        subagent_config=SubAgentConfig(
            has_subagent=True,
            agent_name="zoom_agent",
            tool_space="zoom",
            handoff_tool_name="call_zoom_agent",
            domain="video conferencing and webinar management",
            capabilities="creating meetings, scheduling webinars, managing participants, cloud recording, meeting invitations, attendance tracking, and automating video conferencing workflows",
            use_cases="scheduling meetings, managing webinars, recording conferences, tracking attendance, or any Zoom video conferencing task",
            system_prompt=ZOOM_AGENT_SYSTEM_PROMPT,
        ),
    ),
    OAuthIntegration(
        id="googlemeet",
        name="Google Meet",
        description="Schedule and manage video meetings with Google Meet",
        category="communication",
        provider="googlemeet",
        scopes=[],
        available=True,
        short_name="meet",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_GsHKAmsiGvz1",
            toolkit="GOOGLEMEET",
        ),
        subagent_config=SubAgentConfig(
            has_subagent=True,
            agent_name="google_meet_agent",
            tool_space="googlemeet",
            handoff_tool_name="call_google_meet_agent",
            domain="video conferencing and meeting management",
            capabilities="scheduling meetings, managing video conferences, creating meeting links, and organizing virtual collaboration",
            use_cases="scheduling video meetings, managing Google Meet conferences, or virtual collaboration tasks",
            system_prompt=GOOGLE_MEET_AGENT_SYSTEM_PROMPT,
        ),
    ),
    OAuthIntegration(
        id="google_maps",
        name="Google Maps",
        description="Search locations, get directions, and manage place information",
        category="productivity",
        provider="google_maps",
        scopes=[],
        available=True,
        short_name="maps",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_vy6NqsFlzLuO",
            toolkit="GOOGLE_MAPS",
        ),
        subagent_config=SubAgentConfig(
            has_subagent=True,
            agent_name="google_maps_agent",
            tool_space="google_maps",
            handoff_tool_name="call_google_maps_agent",
            domain="location and navigation services",
            capabilities="searching locations, getting directions, finding places, analyzing geographic data, and managing location information",
            use_cases="location search, getting directions, finding nearby places, or any Google Maps operation",
            system_prompt=GOOGLE_MAPS_AGENT_SYSTEM_PROMPT,
        ),
    ),
    OAuthIntegration(
        id="asana",
        name="Asana",
        description="Manage projects, tasks, and team workflows with comprehensive project management",
        category="productivity",
        provider="asana",
        scopes=[],
        available=True,
        short_name="asana",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_gF2RuhulKw3I",
            toolkit="ASANA",
        ),
        subagent_config=SubAgentConfig(
            has_subagent=True,
            agent_name="asana_agent",
            tool_space="asana",
            handoff_tool_name="call_asana_agent",
            domain="project and task management",
            capabilities="creating tasks, managing projects, organizing workflows, assigning work, tracking progress, and building team collaboration systems",
            use_cases="project management, task organization, team collaboration, or any Asana workflow operation",
            system_prompt=ASANA_AGENT_SYSTEM_PROMPT,
        ),
    ),
    OAuthIntegration(
        id="trello",
        name="Trello",
        description="Organize projects with boards, lists, and cards for visual task management",
        category="productivity",
        provider="trello",
        scopes=[],
        available=True,
        short_name="trello",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_nMjBqOcjLTGW",
            toolkit="TRELLO",
        ),
        subagent_config=SubAgentConfig(
            has_subagent=True,
            agent_name="trello_agent",
            tool_space="trello",
            handoff_tool_name="call_trello_agent",
            domain="visual project management",
            capabilities="creating boards, managing cards, organizing lists, tracking workflows, assigning tasks, and building visual project systems",
            use_cases="board management, card organization, visual task tracking, or any Trello operation",
            system_prompt=TRELLO_AGENT_SYSTEM_PROMPT,
        ),
    ),
    OAuthIntegration(
        id="instagram",
        name="Instagram",
        description="Manage your Instagram account, post content, and engage with your audience",
        category="social",
        provider="instagram",
        scopes=[],
        available=True,
        short_name="instagram",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_JP45uYkUcjVV",
            toolkit="INSTAGRAM",
        ),
        subagent_config=SubAgentConfig(
            has_subagent=True,
            agent_name="instagram_agent",
            tool_space="instagram",
            handoff_tool_name="call_instagram_agent",
            domain="social media content and engagement",
            capabilities="posting content, managing stories, engaging with followers, analyzing insights, and building social media presence",
            use_cases="posting to Instagram, managing content, engaging with audience, or social media management tasks",
            system_prompt=INSTAGRAM_AGENT_SYSTEM_PROMPT,
        ),
    ),
    OAuthIntegration(
        id="clickup",
        name="ClickUp",
        description="Manage tasks, projects, and workflows with comprehensive project management",
        category="productivity",
        provider="clickup",
        scopes=[],
        available=True,
        short_name="clickup",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_cyT9vqo3pcF3",
            toolkit="CLICKUP",
        ),
        subagent_config=SubAgentConfig(
            has_subagent=True,
            agent_name="clickup_agent",
            tool_space="clickup",
            handoff_tool_name="call_clickup_agent",
            domain="comprehensive project management",
            capabilities="managing tasks, organizing projects, tracking time, building workflows, assigning work, and comprehensive productivity management",
            use_cases="task management, project organization, time tracking, or any ClickUp operation",
            system_prompt=CLICKUP_AGENT_SYSTEM_PROMPT,
        ),
    ),
]


@cache
def get_integration_by_id(integration_id: str) -> Optional[OAuthIntegration]:
    """Get an integration by its ID."""
    return next((i for i in OAUTH_INTEGRATIONS if i.id == integration_id), None)


@cache
def get_integration_scopes(integration_id: str) -> List[str]:
    """Get the OAuth scopes for a specific integration."""
    integration = get_integration_by_id(integration_id)
    if not integration:
        return []
    return [scope.scope for scope in integration.scopes]


@cache
def get_short_name_mapping() -> Dict[str, str]:
    """Get mapping of short names to integration IDs."""
    return {i.short_name: i.id for i in OAUTH_INTEGRATIONS if i.short_name}


@cache
def get_composio_social_configs() -> Dict[str, ComposioConfig]:
    """Get COMPOSIO_SOCIAL_CONFIGS from integrations managed by Composio."""
    configs = {}
    for integration in OAUTH_INTEGRATIONS:
        if integration.managed_by == "composio" and integration.composio_config:
            configs[integration.provider] = integration.composio_config
    return configs


@cache
def get_integration_by_config(auth_config_id: str) -> Optional[OAuthIntegration]:
    """Get an integration by its Composio auth config ID."""
    return next(
        (
            i
            for i in OAUTH_INTEGRATIONS
            if i.composio_config and i.composio_config.auth_config_id == auth_config_id
        ),
        None,
    )
