"""
OAuth Integration Configuration

Single source of truth for all OAuth integration configurations in GAIA.
Defines integrations, scopes, display properties, and subagent configurations.
"""

from functools import cache
from typing import Dict, List, Optional

from app.agents.prompts.memory_prompts import (
    AGENTMAIL_MEMORY_PROMPT,
    AIRTABLE_MEMORY_PROMPT,
    ASANA_MEMORY_PROMPT,
    BROWSERBASE_MEMORY_PROMPT,
    CALENDAR_MEMORY_PROMPT,
    CLICKUP_MEMORY_PROMPT,
    CONTEXT7_MEMORY_PROMPT,
    DEEPWIKI_MEMORY_PROMPT,
    GITHUB_MEMORY_PROMPT,
    GMAIL_MEMORY_PROMPT,
    GOALS_MEMORY_PROMPT,
    GOOGLE_DOCS_MEMORY_PROMPT,
    GOOGLE_MAPS_MEMORY_PROMPT,
    GOOGLE_MEET_MEMORY_PROMPT,
    GOOGLE_SHEETS_MEMORY_PROMPT,
    GOOGLE_TASKS_MEMORY_PROMPT,
    HACKERNEWS_MEMORY_PROMPT,
    HUBSPOT_MEMORY_PROMPT,
    INSTACART_MEMORY_PROMPT,
    INSTAGRAM_MEMORY_PROMPT,
    LINEAR_MEMORY_PROMPT,
    LINKEDIN_MEMORY_PROMPT,
    MICROSOFT_TEAMS_MEMORY_PROMPT,
    NOTION_MEMORY_PROMPT,
    PERPLEXITY_MEMORY_PROMPT,
    POSTHOG_MEMORY_PROMPT,
    REDDIT_MEMORY_PROMPT,
    REMINDER_MEMORY_PROMPT,
    SLACK_MEMORY_PROMPT,
    TODO_MEMORY_PROMPT,
    TODOIST_MEMORY_PROMPT,
    TRELLO_MEMORY_PROMPT,
    TWITTER_MEMORY_PROMPT,
    YELP_MEMORY_PROMPT,
)
from app.agents.prompts.subagent_prompts import (
    AIRTABLE_AGENT_SYSTEM_PROMPT,
    ASANA_AGENT_SYSTEM_PROMPT,
    CALENDAR_AGENT_SYSTEM_PROMPT,
    CLICKUP_AGENT_SYSTEM_PROMPT,
    CONTEXT7_AGENT_SYSTEM_PROMPT,
    DEEPWIKI_AGENT_SYSTEM_PROMPT,
    GITHUB_AGENT_SYSTEM_PROMPT,
    GMAIL_AGENT_SYSTEM_PROMPT,
    GOALS_AGENT_SYSTEM_PROMPT,
    GOOGLE_DOCS_AGENT_SYSTEM_PROMPT,
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
    PERPLEXITY_AGENT_SYSTEM_PROMPT,
    REDDIT_AGENT_SYSTEM_PROMPT,
    REMINDER_AGENT_SYSTEM_PROMPT,
    SLACK_AGENT_SYSTEM_PROMPT,
    TODO_AGENT_SYSTEM_PROMPT,
    TODOIST_AGENT_SYSTEM_PROMPT,
    TRELLO_AGENT_SYSTEM_PROMPT,
    TWITTER_AGENT_SYSTEM_PROMPT,
)
from app.constants.mcp import INSTACART_MCP_SERVER_URL, YELP_MCP_SERVER_URL
from app.langchain.core.subgraphs.github_subgraph import GITHUB_TOOLS
from app.langchain.core.subgraphs.slack_subgraph import SLACK_TOOLS
from app.models.mcp_config import (
    ComposioConfig,
    MCPConfig,
    OAuthScope,
    ProviderMetadataConfig,
    SubAgentConfig,
    ToolMetadataConfig,
    VariableExtraction,
)
from app.models.oauth_models import OAuthIntegration
from app.models.trigger_config import (
    TriggerConfig,
    TriggerConfigFieldSchema,
    WorkflowTriggerSchema,
)

# Define all integrations dynamically
OAUTH_INTEGRATIONS: List[OAuthIntegration] = [
    # Individual Google integrations
    OAuthIntegration(
        id="googlecalendar",
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
            toolkit_version="20260107_00",
        ),
        associated_triggers=[
            TriggerConfig(
                slug="GOOGLECALENDAR_GOOGLE_CALENDAR_EVENT_CREATED_TRIGGER",
                name="Event Created",
                description="Polling trigger that fires when a new calendar event is created.",
                auto_activate=True,
                workflow_trigger_schema=WorkflowTriggerSchema(
                    slug="calendar_event_created",
                    composio_slug="GOOGLECALENDAR_GOOGLE_CALENDAR_EVENT_CREATED_TRIGGER",
                    name="New Calendar Event",
                    description="Trigger when new events are created",
                    config_schema={
                        "calendar_id": TriggerConfigFieldSchema(
                            type="string",
                            default="primary",
                            options_endpoint="/calendar/list",
                            description="Calendar to monitor for new events",
                        ),
                    },
                ),
            ),
            TriggerConfig(
                slug="GOOGLECALENDAR_EVENT_STARTING_SOON_TRIGGER",
                name="Event Starting Soon",
                description="Triggers when a calendar event is starting soon",
                auto_activate=False,
                workflow_trigger_schema=WorkflowTriggerSchema(
                    slug="calendar_event_starting_soon",
                    composio_slug="GOOGLECALENDAR_EVENT_STARTING_SOON_TRIGGER",
                    name="Event Starting Soon",
                    description="Trigger before events start",
                    config_schema={
                        "calendar_id": TriggerConfigFieldSchema(
                            type="string",
                            default="primary",
                            options_endpoint="/calendar/list",
                            description="Calendar to monitor for upcoming events",
                        ),
                        "minutes_before_start": TriggerConfigFieldSchema(
                            type="integer",
                            default=10,
                            min=1,
                            max=1440,
                            description="Trigger when event is within this many minutes from starting",
                        ),
                        "include_all_day": TriggerConfigFieldSchema(
                            type="boolean",
                            default=False,
                            description="Whether to include all-day events",
                        ),
                    },
                ),
            ),
        ],
        subagent_config=SubAgentConfig(
            has_subagent=True,
            agent_name="googlecalendar_agent",
            tool_space="googlecalendar",
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
                "GOOGLECALENDAR_CUSTOM_GET_DAY_SUMMARY",
                "GOOGLECALENDAR_CUSTOM_FETCH_EVENTS",
                "GOOGLECALENDAR_CUSTOM_FIND_EVENT",
                "GOOGLECALENDAR_CUSTOM_GET_EVENT",
                "GOOGLECALENDAR_CUSTOM_DELETE_EVENT",
                "GOOGLECALENDAR_CUSTOM_PATCH_EVENT",
                "GOOGLECALENDAR_CUSTOM_ADD_RECURRENCE",
            ],
            memory_prompt=CALENDAR_MEMORY_PROMPT,
        ),
    ),
    OAuthIntegration(
        id="googledocs",
        name="Google Docs",
        description="Create, edit, and share documents in your workspace",
        category="productivity",
        provider="googledocs",
        scopes=[],
        is_featured=True,
        short_name="docs",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_coVAA1WRsbdK",
            toolkit="GOOGLEDOCS",
            toolkit_version="20260107_00",
        ),
        associated_triggers=[
            TriggerConfig(
                slug="GOOGLEDOCS_PAGE_ADDED_TRIGGER",
                name="New Document Created",
                description="Triggers when a new Google Doc is created in your workspace.",
                auto_activate=False,
                workflow_trigger_schema=WorkflowTriggerSchema(
                    slug="google_docs_new_document",
                    composio_slug="GOOGLEDOCS_PAGE_ADDED_TRIGGER",
                    name="New Google Doc Created",
                    description="Trigger when a new document is created",
                    config_schema={},
                ),
            ),
            TriggerConfig(
                slug="GOOGLEDOCS_DOCUMENT_DELETED_TRIGGER",
                name="Document Deleted",
                description="Triggers when a Google Doc is deleted in your workspace.",
                auto_activate=False,
                workflow_trigger_schema=WorkflowTriggerSchema(
                    slug="google_docs_document_deleted",
                    composio_slug="GOOGLEDOCS_DOCUMENT_DELETED_TRIGGER",
                    name="Document Deleted",
                    description="Trigger when a document is deleted",
                    config_schema={},
                ),
            ),
            TriggerConfig(
                slug="GOOGLEDOCS_DOCUMENT_UPDATED_TRIGGER",
                name="Document Updated",
                description="Triggers when a Google Doc is updated in your workspace.",
                auto_activate=False,
                workflow_trigger_schema=WorkflowTriggerSchema(
                    slug="google_docs_document_updated",
                    composio_slug="GOOGLEDOCS_DOCUMENT_UPDATED_TRIGGER",
                    name="Document Updated",
                    description="Trigger when a document is updated",
                    config_schema={},
                ),
            ),
        ],
        subagent_config=SubAgentConfig(
            has_subagent=True,
            agent_name="googledocs_agent",
            tool_space="googledocs",
            handoff_tool_name="call_googledocs_agent",
            domain="document creation, editing, and collaboration",
            capabilities="creating documents, editing content, formatting text, sharing with collaborators, managing document structure, inserting tables and images, and using templates",
            use_cases="creating documents, editing docs, sharing with team members, formatting content, or any Google Docs operation",
            system_prompt=GOOGLE_DOCS_AGENT_SYSTEM_PROMPT,
            memory_prompt=GOOGLE_DOCS_MEMORY_PROMPT,
        ),
    ),
    OAuthIntegration(
        id="todos",
        name="Todos",
        description="Manage tasks, projects, and personal productivity with AI assistance",
        category="productivity",
        provider="todos",
        scopes=[],
        available=True,
        is_featured=False,
        short_name="todos",
        managed_by="internal",
        subagent_config=SubAgentConfig(
            has_subagent=True,
            agent_name="todo_agent",
            tool_space="todos",
            handoff_tool_name="call_todo_agent",
            domain="task and productivity management",
            capabilities="creating todos, managing tasks, organizing projects, tracking priorities, setting due dates, using labels, bulk operations, searching tasks, and providing productivity insights",
            use_cases="managing personal todos, organizing tasks by project, tracking deadlines, bulk task operations, or any productivity-related task",
            system_prompt=TODO_AGENT_SYSTEM_PROMPT,
            memory_prompt=TODO_MEMORY_PROMPT,
        ),
    ),
    # Internal Reminders System (no OAuth required)
    OAuthIntegration(
        id="reminders",
        name="Reminders",
        description="Schedule time-based reminders with AI assistance",
        category="productivity",
        provider="reminders",
        scopes=[],
        available=True,
        is_featured=False,
        short_name="reminders",
        managed_by="internal",
        subagent_config=SubAgentConfig(
            has_subagent=True,
            agent_name="reminder_agent",
            tool_space="reminders",
            handoff_tool_name="call_reminder_agent",
            domain="scheduling and time-based notifications",
            capabilities="creating reminders, scheduling notifications, setting recurring reminders, managing reminder statuses, searching reminders",
            use_cases="scheduling reminders, setting up recurring notifications, managing time-based alerts, or any reminder-related task",
            system_prompt=REMINDER_AGENT_SYSTEM_PROMPT,
            use_direct_tools=True,
            disable_retrieve_tools=True,
            memory_prompt=REMINDER_MEMORY_PROMPT,
        ),
    ),
    # Internal Goals System (no OAuth required)
    OAuthIntegration(
        id="goals",
        name="Goals",
        description="Track long-term goals and roadmaps with AI assistance",
        category="productivity",
        provider="goals",
        scopes=[],
        available=True,
        is_featured=False,
        short_name="goals",
        managed_by="internal",
        subagent_config=SubAgentConfig(
            has_subagent=True,
            agent_name="goals_agent",
            tool_space="goals",
            handoff_tool_name="call_goals_agent",
            domain="long-term goal planning and progress tracking",
            capabilities="creating goals, generating roadmaps, tracking progress, managing goal nodes, searching goals, viewing goal statistics",
            use_cases="setting long-term goals, generating action roadmaps, tracking goal progress, or any goal-related task",
            system_prompt=GOALS_AGENT_SYSTEM_PROMPT,
            use_direct_tools=True,
            disable_retrieve_tools=True,
            memory_prompt=GOALS_MEMORY_PROMPT,
        ),
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
            auth_config_id="ac_svLPDmjcTVMX",
            toolkit="GMAIL",
            toolkit_version="20260107_00",
        ),
        associated_triggers=[
            TriggerConfig(
                slug="GMAIL_NEW_GMAIL_MESSAGE",
                name="New Gmail Message",
                description="Triggered when a new Gmail message arrives",
                config={"labelIds": "INBOX", "user_id": "me", "interval": 1},
                auto_activate=True,
                workflow_trigger_schema=WorkflowTriggerSchema(
                    slug="gmail_new_message",
                    composio_slug="GMAIL_NEW_GMAIL_MESSAGE",
                    name="New Gmail Message",
                    description="Trigger when a new email arrives",
                    config_schema={},
                ),
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
            memory_prompt=GMAIL_MEMORY_PROMPT,
        ),
        metadata_config=ProviderMetadataConfig(
            tools=[
                ToolMetadataConfig(
                    tool="GMAIL_GET_PROFILE",
                    variables=[
                        VariableExtraction(name="email", field_path="emailAddress"),
                    ],
                ),
            ],
        ),
    ),
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
            toolkit_version="20260107_00",
        ),
        associated_triggers=[
            TriggerConfig(
                slug="NOTION_PAGE_ADDED_TO_DATABASE",
                name="New Page in Database",
                description="Triggers when a new page is added to a Notion database.",
                auto_activate=False,
                workflow_trigger_schema=WorkflowTriggerSchema(
                    slug="notion_new_page_in_db",
                    composio_slug="NOTION_PAGE_ADDED_TO_DATABASE",
                    name="New Page in Database",
                    description="Trigger when a page is added to a specific database",
                    config_schema={
                        "database_id": TriggerConfigFieldSchema(
                            type="string",
                            default="",
                            description="The ID of the Notion database to monitor",
                        ),
                    },
                ),
            ),
            TriggerConfig(
                slug="NOTION_PAGE_UPDATED_TRIGGER",
                name="Page Updated",
                description="Triggers when any block within a specified Notion page is updated.",
                auto_activate=False,
                workflow_trigger_schema=WorkflowTriggerSchema(
                    slug="notion_page_updated",
                    composio_slug="NOTION_PAGE_UPDATED_TRIGGER",
                    name="Page Updated",
                    description="Trigger when a specific page is updated",
                    config_schema={
                        "page_id": TriggerConfigFieldSchema(
                            type="string",
                            default="",
                            description="The ID of the Notion page to monitor",
                        ),
                    },
                ),
            ),
            TriggerConfig(
                slug="NOTION_ALL_PAGE_EVENTS_TRIGGER",
                name="All Page Events",
                description="Triggers when any Notion page is created or updated across the workspace.",
                auto_activate=False,
                workflow_trigger_schema=WorkflowTriggerSchema(
                    slug="notion_all_page_events",
                    composio_slug="NOTION_ALL_PAGE_EVENTS_TRIGGER",
                    name="Any Page Event",
                    description="Trigger on any page creation or update",
                    config_schema={},
                ),
            ),
        ],
        subagent_config=SubAgentConfig(
            has_subagent=True,
            agent_name="notion_agent",
            tool_space="notion",
            handoff_tool_name="call_notion_agent",
            domain="workspace and knowledge management",
            capabilities="creating pages, building databases, updating content, organizing workspaces, managing properties, searching content, and structuring knowledge bases",
            use_cases="creating pages, managing databases, organizing knowledge, or any Notion workspace operation",
            system_prompt=NOTION_AGENT_SYSTEM_PROMPT,
            memory_prompt=NOTION_MEMORY_PROMPT,
        ),
        metadata_config=ProviderMetadataConfig(
            tools=[
                ToolMetadataConfig(
                    tool="NOTION_GET_ABOUT_ME",
                    variables=[
                        VariableExtraction(name="user_id", field_path="id"),
                        VariableExtraction(
                            name="workspace_id", field_path="bot.workspace_id"
                        ),
                        VariableExtraction(
                            name="workspace_name", field_path="bot.workspace_name"
                        ),
                    ],
                ),
            ],
        ),
    ),
    OAuthIntegration(
        id="twitter",
        name="Twitter",
        description="Post tweets, read timelines, and manage your account",
        category="social_media",
        provider="twitter",
        scopes=[],
        available=True,
        short_name="twitter",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_vloH3fnhIeUa",
            toolkit="TWITTER",
            toolkit_version="20260130_00",
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
            memory_prompt=TWITTER_MEMORY_PROMPT,
        ),
        metadata_config=ProviderMetadataConfig(
            tools=[
                ToolMetadataConfig(
                    tool="TWITTER_USER_LOOKUP_ME",
                    variables=[
                        VariableExtraction(name="username", field_path="data.username"),
                        VariableExtraction(name="user_id", field_path="data.id"),
                    ],
                ),
            ],
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
            toolkit_version="20260107_00",
        ),
        associated_triggers=[
            TriggerConfig(
                slug="GOOGLESHEETS_NEW_ROWS_TRIGGER",
                name="New Rows in Sheet",
                description="Triggered when new rows are added to a specific Google Sheet.",
                auto_activate=False,
                workflow_trigger_schema=WorkflowTriggerSchema(
                    slug="google_sheets_new_row",
                    composio_slug="GOOGLESHEETS_NEW_ROWS_TRIGGER",
                    name="New Row Added",
                    description="Trigger when a new row is added",
                    config_schema={
                        "spreadsheet_ids": TriggerConfigFieldSchema(
                            type="string",
                            default="",
                            description="Comma-separated spreadsheet IDs to monitor (empty for all)",
                        ),
                        "sheet_names": TriggerConfigFieldSchema(
                            type="string",
                            description="Comma-separated sheet names (empty for all sheets)",
                            default="",
                        ),
                    },
                ),
            ),
            TriggerConfig(
                slug="GOOGLESHEETS_NEW_SHEET_ADDED_TRIGGER",
                name="New Sheet Added",
                description="Triggered when a new sheet/tab is created in a Google Spreadsheet.",
                auto_activate=False,
                workflow_trigger_schema=WorkflowTriggerSchema(
                    slug="google_sheets_new_sheet",
                    composio_slug="GOOGLESHEETS_NEW_SHEET_ADDED_TRIGGER",
                    name="New Spreadsheet",
                    description="Trigger when a new sheet is added",
                    config_schema={
                        "spreadsheet_ids": TriggerConfigFieldSchema(
                            type="string",
                            default="",
                            description="Comma-separated spreadsheet IDs to monitor",
                        ),
                    },
                ),
            ),
        ],
        subagent_config=SubAgentConfig(
            has_subagent=True,
            agent_name="google_sheets_agent",
            tool_space="googlesheets",
            handoff_tool_name="call_google_sheets_agent",
            domain="spreadsheet management and data analysis",
            capabilities="creating spreadsheets, updating data, managing formulas, organizing sheets, analyzing data, and building collaborative workbooks",
            use_cases="spreadsheet management, data analysis, formula creation, or any Google Sheets operation",
            system_prompt=GOOGLE_SHEETS_AGENT_SYSTEM_PROMPT,
            memory_prompt=GOOGLE_SHEETS_MEMORY_PROMPT,
        ),
    ),
    OAuthIntegration(
        id="linkedin",
        name="LinkedIn",
        description="Share posts and engage with your professional network",
        category="social_media",
        provider="linkedin",
        scopes=[],
        available=True,
        short_name="linkedin",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_GMeJBELf3z_m",
            toolkit="LINKEDIN",
            toolkit_version="20260107_00",
        ),
        subagent_config=SubAgentConfig(
            has_subagent=True,
            agent_name="linkedin_agent",
            tool_space="linkedin",
            handoff_tool_name="call_linkedin_agent",
            domain="professional networking",
            capabilities="creating professional posts with images/documents/articles, managing connections, engaging with content through comments and reactions, networking outreach, and building professional presence",
            use_cases="posting professional content with rich media, commenting on posts, reacting to content, sharing articles, or any LinkedIn career-related activity",
            system_prompt=LINKEDIN_AGENT_SYSTEM_PROMPT,
            memory_prompt=LINKEDIN_MEMORY_PROMPT,
        ),
    ),
    OAuthIntegration(
        id="github",
        name="GitHub",
        is_featured=True,
        description="Manage repositories, issues, pull requests, and automate your development workflow",
        category="developer",
        provider="github",
        scopes=[],
        available=True,
        short_name="github",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_y2VK4j0ATiZo",
            toolkit="GITHUB",
            toolkit_version="20260107_00",
        ),
        associated_triggers=[
            TriggerConfig(
                slug="GITHUB_COMMIT_EVENT",
                name="Commit Event",
                description="Triggered when a new commit is pushed to a repository.",
                auto_activate=False,
                workflow_trigger_schema=WorkflowTriggerSchema(
                    slug="github_commit_event",
                    composio_slug="GITHUB_COMMIT_EVENT",
                    name="New Commit",
                    description="Trigger on new commits to a repository",
                    config_schema={
                        "owner": TriggerConfigFieldSchema(
                            type="string",
                            default="",
                            description="Owner of the repository (username or org)",
                        ),
                        "repo": TriggerConfigFieldSchema(
                            type="string",
                            default="",
                            description="Repository name",
                        ),
                    },
                ),
            ),
            TriggerConfig(
                slug="GITHUB_PULL_REQUEST_EVENT",
                name="Pull Request Event",
                description="Triggered when a pull request is opened, closed, or synchronized.",
                auto_activate=False,
                workflow_trigger_schema=WorkflowTriggerSchema(
                    slug="github_pr_event",
                    composio_slug="GITHUB_PULL_REQUEST_EVENT",
                    name="Pull Request Updates",
                    description="Trigger on PR open, close, or sync",
                    config_schema={
                        "owner": TriggerConfigFieldSchema(
                            type="string",
                            default="",
                            description="Owner of the repository (username or org)",
                        ),
                        "repo": TriggerConfigFieldSchema(
                            type="string",
                            default="",
                            description="Repository name",
                        ),
                    },
                ),
            ),
            TriggerConfig(
                slug="GITHUB_STAR_ADDED_EVENT",
                name="Star Added",
                description="Triggered when a new star is added to the repository.",
                auto_activate=False,
                workflow_trigger_schema=WorkflowTriggerSchema(
                    slug="github_star_added",
                    composio_slug="GITHUB_STAR_ADDED_EVENT",
                    name="New Repository Star",
                    description="Trigger when someone stars the repository",
                    config_schema={
                        "owner": TriggerConfigFieldSchema(
                            type="string",
                            default="",
                            description="Owner of the repository (username or org)",
                        ),
                        "repo": TriggerConfigFieldSchema(
                            type="string",
                            default="",
                            description="Repository name",
                        ),
                    },
                ),
            ),
            TriggerConfig(
                slug="GITHUB_ISSUE_ADDED_EVENT",
                name="Issue Added",
                description="Triggered when a new issue is added to the repository.",
                auto_activate=False,
                workflow_trigger_schema=WorkflowTriggerSchema(
                    slug="github_issue_added",
                    composio_slug="GITHUB_ISSUE_ADDED_EVENT",
                    name="New Issue Created",
                    description="Trigger when a new issue is created",
                    config_schema={
                        "owner": TriggerConfigFieldSchema(
                            type="string",
                            default="",
                            description="Owner of the repository (username or org)",
                        ),
                        "repo": TriggerConfigFieldSchema(
                            type="string",
                            default="",
                            description="Repository name",
                        ),
                    },
                ),
            ),
        ],
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
            memory_prompt=GITHUB_MEMORY_PROMPT,
        ),
        metadata_config=ProviderMetadataConfig(
            tools=[
                ToolMetadataConfig(
                    tool="GITHUB_GET_THE_AUTHENTICATED_USER",
                    variables=[
                        VariableExtraction(name="username", field_path="login"),
                    ],
                ),
            ],
        ),
    ),
    OAuthIntegration(
        id="reddit",
        name="Reddit",
        description="Post content, manage comments, and engage with communities on Reddit",
        category="social_media",
        provider="reddit",
        scopes=[],
        available=True,
        short_name="reddit",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_7-hfiMVLhcDN",
            toolkit="REDDIT",
            toolkit_version="20260107_00",
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
            memory_prompt=REDDIT_MEMORY_PROMPT,
        ),
    ),
    OAuthIntegration(
        id="airtable",
        name="Airtable",
        description="Create and manage bases, tables, and records with AI-powered automation",
        category="business",
        provider="airtable",
        scopes=[],
        available=True,
        short_name="airtable",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_QPtQsXnIYm4C",
            toolkit="AIRTABLE",
            toolkit_version="20260130_00",
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
            memory_prompt=AIRTABLE_MEMORY_PROMPT,
        ),
    ),
    OAuthIntegration(
        id="linear",
        name="Linear",
        description="Manage issues, projects, and track development progress with AI assistance",
        category="developer",
        provider="linear",
        scopes=[],
        available=True,
        short_name="linear",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_mnrcEhhTXPVS",
            toolkit="LINEAR",
            toolkit_version="20260107_00",
        ),
        associated_triggers=[
            TriggerConfig(
                slug="LINEAR_ISSUE_CREATED_TRIGGER",
                name="Issue Created",
                description="Triggered when a new issue is created in Linear.",
                auto_activate=False,
                workflow_trigger_schema=WorkflowTriggerSchema(
                    slug="linear_issue_created",
                    composio_slug="LINEAR_ISSUE_CREATED_TRIGGER",
                    name="New Linear Issue",
                    description="Trigger when a new issue is created",
                    config_schema={
                        "team_id": TriggerConfigFieldSchema(
                            type="string",
                            default="",
                            description="ID of the team to filter issues by",
                        ),
                    },
                ),
            ),
            TriggerConfig(
                slug="LINEAR_ISSUE_UPDATED_TRIGGER",
                name="Issue Updated",
                description="Triggered when an issue is updated in Linear.",
                auto_activate=False,
                workflow_trigger_schema=WorkflowTriggerSchema(
                    slug="linear_issue_updated",
                    composio_slug="LINEAR_ISSUE_UPDATED_TRIGGER",
                    name="Updated Linear Issue",
                    description="Trigger when an issue is updated",
                    config_schema={
                        "team_id": TriggerConfigFieldSchema(
                            type="string",
                            default="",
                            description="ID of the team to filter issues by",
                        ),
                    },
                ),
            ),
            TriggerConfig(
                slug="LINEAR_COMMENT_EVENT_TRIGGER",
                name="Comment Received",
                description="Triggered when a new comment is posted on an issue.",
                auto_activate=False,
                workflow_trigger_schema=WorkflowTriggerSchema(
                    slug="linear_comment_added",
                    composio_slug="LINEAR_COMMENT_EVENT_TRIGGER",
                    name="New Comment",
                    description="Trigger when a comment is added",
                    config_schema={
                        "team_id": TriggerConfigFieldSchema(
                            type="string",
                            default="",
                            description="ID of the team to filter comments by",
                        ),
                    },
                ),
            ),
        ],
        subagent_config=SubAgentConfig(
            has_subagent=True,
            agent_name="linear_agent",
            tool_space="linear",
            handoff_tool_name="call_linear_agent",
            domain="issue tracking and project management",
            capabilities="creating issues, managing projects, tracking progress, assigning tasks, organizing sprints, and automating development workflows",
            use_cases="issue management, project tracking, sprint planning, or any Linear development workflow task",
            system_prompt=LINEAR_AGENT_SYSTEM_PROMPT,
            memory_prompt=LINEAR_MEMORY_PROMPT,
        ),
        metadata_config=ProviderMetadataConfig(
            tools=[
                ToolMetadataConfig(
                    tool="LINEAR_GET_CURRENT_USER",
                    variables=[
                        VariableExtraction(name="user_id", field_path="user.id"),
                        VariableExtraction(
                            name="username", field_path="user.displayName"
                        ),
                        VariableExtraction(name="email", field_path="user.email"),
                    ],
                ),
            ],
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
            toolkit_version="20260204_00",
        ),
        associated_triggers=[
            TriggerConfig(
                slug="SLACK_RECEIVE_MESSAGE",
                name="New Message",
                description="Triggered when messages are posted in Slack",
                auto_activate=False,
                workflow_trigger_schema=WorkflowTriggerSchema(
                    slug="slack_new_message",
                    composio_slug="SLACK_RECEIVE_MESSAGE",
                    name="New Slack Message",
                    description="Trigger on new Slack messages with optional filtering",
                    config_schema={
                        "channel_ids": TriggerConfigFieldSchema(
                            type="string",
                            description="Channel IDs to monitor (leave empty for all channels)",
                            default="",
                        ),
                        "exclude_bot_messages": TriggerConfigFieldSchema(
                            type="boolean",
                            description="Exclude messages from bots",
                            default=False,
                        ),
                        "exclude_direct_messages": TriggerConfigFieldSchema(
                            type="boolean",
                            description="Exclude 1:1 direct messages",
                            default=False,
                        ),
                        "exclude_group_messages": TriggerConfigFieldSchema(
                            type="boolean",
                            description="Exclude private group messages",
                            default=False,
                        ),
                        "exclude_mpim_messages": TriggerConfigFieldSchema(
                            type="boolean",
                            description="Exclude multi-person direct messages",
                            default=False,
                        ),
                        "exclude_thread_replies": TriggerConfigFieldSchema(
                            type="boolean",
                            description="Exclude replies in threads",
                            default=False,
                        ),
                    },
                ),
            ),
            TriggerConfig(
                slug="SLACK_CHANNEL_CREATED",
                name="Channel Created",
                description="Triggered when a new channel is created",
                auto_activate=False,
                workflow_trigger_schema=WorkflowTriggerSchema(
                    slug="slack_channel_created",
                    composio_slug="SLACK_CHANNEL_CREATED",
                    name="New Slack Channel",
                    description="Trigger when a channel is created",
                    config_schema={},
                ),
            ),
        ],
        subagent_config=SubAgentConfig(
            has_subagent=True,
            agent_name="slack_agent",
            tool_space="slack",
            handoff_tool_name="call_slack_agent",
            domain="team communication and collaboration",
            capabilities="sending messages, managing channels, organizing conversations, sharing files, setting reminders, and automating team communication workflows",
            use_cases="sending Slack messages, managing channels, team communication, or automating workspace workflows",
            system_prompt=SLACK_AGENT_SYSTEM_PROMPT,
            specific_tools=SLACK_TOOLS,
            memory_prompt=SLACK_MEMORY_PROMPT,
        ),
        metadata_config=ProviderMetadataConfig(
            tools=[
                ToolMetadataConfig(
                    tool="SLACK_TEST_AUTH",
                    variables=[
                        VariableExtraction(name="user_id", field_path="user_id"),
                        VariableExtraction(name="username", field_path="user"),
                        VariableExtraction(name="team_id", field_path="team_id"),
                        VariableExtraction(name="team_name", field_path="team"),
                    ],
                ),
            ],
        ),
    ),
    OAuthIntegration(
        id="hubspot",
        name="HubSpot",
        description="Manage CRM contacts, deals, and automate sales and marketing workflows",
        category="business",
        provider="hubspot",
        scopes=[],
        available=True,
        short_name="hubspot",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_rcnwYp1PRCVr",
            toolkit="HUBSPOT",
            toolkit_version="20260107_00",
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
            memory_prompt=HUBSPOT_MEMORY_PROMPT,
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
            toolkit_version="20260107_00",
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
            memory_prompt=GOOGLE_TASKS_MEMORY_PROMPT,
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
            toolkit_version="20260107_00",
        ),
        associated_triggers=[
            TriggerConfig(
                slug="TODOIST_NEW_TASK_CREATED",
                name="New Task Created",
                description="Trigger when a new task is added to Todoist.",
                auto_activate=False,
                workflow_trigger_schema=WorkflowTriggerSchema(
                    slug="todoist_new_task_created",
                    composio_slug="TODOIST_NEW_TASK_CREATED",
                    name="New Task Created",
                    description="Trigger when a new task is added to Todoist.",
                    config_schema={},
                ),
            ),
        ],
        subagent_config=SubAgentConfig(
            has_subagent=True,
            agent_name="todoist_agent",
            tool_space="todoist",
            handoff_tool_name="call_todoist_agent",
            domain="task and project management",
            capabilities="creating tasks, organizing projects, setting priorities, managing labels, tracking productivity, and building task workflows",
            use_cases="task management, project organization, productivity tracking, or any Todoist operation",
            system_prompt=TODOIST_AGENT_SYSTEM_PROMPT,
            memory_prompt=TODOIST_MEMORY_PROMPT,
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
            auth_config_id="ac_0kzvAbsi2xu3",
            toolkit="MICROSOFT_TEAMS",
            toolkit_version="20260107_00",
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
            memory_prompt=MICROSOFT_TEAMS_MEMORY_PROMPT,
        ),
    ),
    # OAuthIntegration(
    #     id="zoom",
    #     name="Zoom",
    #     description="Create and manage Zoom meetings, webinars, and video conferencing",
    #     category="communication",
    #     provider="zoom",
    #     scopes=[],
    #     available=True,
    #     short_name="zoom",
    #     managed_by="composio",
    #     composio_config=ComposioConfig(
    #         auth_config_id="ac_fABNBG17lf2A",
    #         toolkit="ZOOM",
    #         toolkit_version="20260130_00",
    #     ),
    #     subagent_config=SubAgentConfig(
    #         has_subagent=True,
    #         agent_name="zoom_agent",
    #         tool_space="zoom",
    #         handoff_tool_name="call_zoom_agent",
    #         domain="video conferencing and webinar management",
    #         capabilities="creating meetings, scheduling webinars, managing participants, cloud recording, meeting invitations, attendance tracking, and automating video conferencing workflows",
    #         use_cases="scheduling meetings, managing webinars, recording conferences, tracking attendance, or any Zoom video conferencing task",
    #         system_prompt=ZOOM_AGENT_SYSTEM_PROMPT,
    #     ),
    # ),
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
            toolkit_version="20260107_00",
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
            memory_prompt=GOOGLE_MEET_MEMORY_PROMPT,
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
            toolkit_version="20260107_00",
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
            memory_prompt=GOOGLE_MAPS_MEMORY_PROMPT,
        ),
    ),
    OAuthIntegration(
        id="asana",
        name="Asana",
        description="Manage projects, tasks, and team workflows with comprehensive project management",
        category="business",
        provider="asana",
        scopes=[],
        available=True,
        short_name="asana",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_gF2RuhulKw3I",
            toolkit="ASANA",
            toolkit_version="20260107_00",
        ),
        associated_triggers=[
            TriggerConfig(
                slug="ASANA_TASK_TRIGGER",
                name="Task Trigger",
                description="Triggered when a task involves the user.",
                auto_activate=False,
                workflow_trigger_schema=WorkflowTriggerSchema(
                    slug="asana_task_trigger",
                    composio_slug="ASANA_TASK_TRIGGER",
                    name="Task Trigger",
                    description="Triggered when a task involves the user.",
                    config_schema={
                        "project_id": TriggerConfigFieldSchema(
                            type="string",
                            description="ID of the project to trigger on.",
                            default="",
                        ),
                        "workspace_id": TriggerConfigFieldSchema(
                            type="string",
                            description="ID of the workspace to trigger on.",
                            default="",
                        ),
                    },
                ),
            ),
        ],
        subagent_config=SubAgentConfig(
            has_subagent=True,
            agent_name="asana_agent",
            tool_space="asana",
            handoff_tool_name="call_asana_agent",
            domain="project and task management",
            capabilities="creating tasks, managing projects, organizing workflows, assigning work, tracking progress, and building team collaboration systems",
            use_cases="project management, task organization, team collaboration, or any Asana workflow operation",
            system_prompt=ASANA_AGENT_SYSTEM_PROMPT,
            memory_prompt=ASANA_MEMORY_PROMPT,
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
            toolkit_version="20260107_00",
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
            memory_prompt=TRELLO_MEMORY_PROMPT,
        ),
    ),
    OAuthIntegration(
        id="instagram",
        name="Instagram",
        description="Manage your Instagram account, post content, and engage with your audience",
        category="social_media",
        provider="instagram",
        scopes=[],
        available=True,
        short_name="instagram",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_JP45uYkUcjVV",
            toolkit="INSTAGRAM",
            toolkit_version="20260107_00",
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
            memory_prompt=INSTAGRAM_MEMORY_PROMPT,
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
            toolkit_version="20260107_00",
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
            memory_prompt=CLICKUP_MEMORY_PROMPT,
        ),
    ),
    # MCP Integrations (no authentication required)
    OAuthIntegration(
        id="deepwiki",
        name="DeepWiki",
        description="AI-powered documentation for any GitHub repository. Ask questions and explore codebases.",
        category="developer",
        provider="deepwiki",
        scopes=[],
        available=True,
        short_name="deepwiki",
        managed_by="mcp",
        mcp_config=MCPConfig(
            server_url="https://mcp.deepwiki.com/mcp",
        ),
        subagent_config=SubAgentConfig(
            has_subagent=True,
            agent_name="deepwiki_agent",
            tool_space="deepwiki",
            handoff_tool_name="call_deepwiki_agent",
            domain="GitHub repository documentation and code understanding",
            capabilities="reading wiki structure, viewing documentation contents, asking questions about any GitHub repository",
            use_cases="exploring codebases, understanding repositories, asking questions about GitHub projects",
            system_prompt=DEEPWIKI_AGENT_SYSTEM_PROMPT,
            use_direct_tools=True,
            disable_retrieve_tools=True,
            memory_prompt=DEEPWIKI_MEMORY_PROMPT,
        ),
    ),
    # HackerNews MCP (unauthenticated, Composio hosted)
    OAuthIntegration(
        id="hackernews",
        name="Hacker News",
        description="Browse and search Hacker News stories, comments, and discussions.",
        category="news",
        provider="hackernews",
        scopes=[],
        available=True,
        short_name="hn",
        managed_by="mcp",
        mcp_config=MCPConfig(
            server_url="https://backend.composio.dev/v3/mcp/0f5b8d43-4e16-4919-8788-b462f1089b91/mcp",
        ),
        subagent_config=SubAgentConfig(
            has_subagent=True,
            agent_name="hackernews_agent",
            tool_space="hackernews",
            handoff_tool_name="call_hackernews_agent",
            domain="tech news and discussions",
            capabilities="browsing Hacker News, searching stories, reading comments and discussions",
            use_cases="checking top stories, searching for tech news, reading discussions",
            system_prompt="You are a Hacker News assistant. Help users browse and search tech news, stories, and discussions.",
            use_direct_tools=True,
            memory_prompt=HACKERNEWS_MEMORY_PROMPT,
        ),
    ),
    # Instacart MCP (unauthenticated, Composio hosted)
    OAuthIntegration(
        id="instacart",
        name="Instacart",
        description="Search and browse grocery products, recipes, and shopping options.",
        category="lifestyle",
        provider="instacart",
        scopes=[],
        available=True,
        short_name="instacart",
        managed_by="mcp",
        mcp_config=MCPConfig(
            server_url=INSTACART_MCP_SERVER_URL,
        ),
        subagent_config=SubAgentConfig(
            has_subagent=True,
            agent_name="instacart_agent",
            tool_space="instacart",
            handoff_tool_name="call_instacart_agent",
            domain="grocery shopping and recipes",
            capabilities="searching grocery products, finding recipes, browsing shopping options",
            use_cases="finding groceries, searching recipes, planning meals",
            system_prompt="You are an Instacart assistant. Help users search for groceries, find recipes, and plan their shopping.",
            use_direct_tools=True,
            memory_prompt=INSTACART_MEMORY_PROMPT,
        ),
    ),
    # Yelp MCP (unauthenticated, Composio hosted)
    OAuthIntegration(
        id="yelp",
        name="Yelp",
        description="Search for local businesses, restaurants, and read reviews.",
        category="lifestyle",
        provider="yelp",
        scopes=[],
        available=True,
        short_name="yelp",
        managed_by="mcp",
        mcp_config=MCPConfig(
            server_url=YELP_MCP_SERVER_URL,
        ),
        subagent_config=SubAgentConfig(
            has_subagent=True,
            agent_name="yelp_agent",
            tool_space="yelp",
            handoff_tool_name="call_yelp_agent",
            domain="local business search and reviews",
            capabilities="searching local businesses, finding restaurants, reading reviews, getting business information",
            use_cases="finding restaurants, searching local services, reading reviews",
            system_prompt="You are a Yelp assistant. Help users find local businesses, restaurants, and services with reviews and ratings.",
            use_direct_tools=True,
            memory_prompt=YELP_MEMORY_PROMPT,
        ),
    ),
    # Context7 MCP (Smithery-hosted, OAuth via MCP spec discovery)
    OAuthIntegration(
        id="context7",
        name="Context7",
        description="Fetch up-to-date, version-specific documentation and code examples for any library or framework.",
        category="developer",
        provider="context7",
        scopes=[],
        available=True,
        is_featured=False,
        short_name="context7",
        managed_by="mcp",
        mcp_config=MCPConfig(
            server_url="https://server.smithery.ai/@upstash/context7-mcp",
            requires_auth=True,
        ),
        subagent_config=SubAgentConfig(
            has_subagent=True,
            agent_name="context7_agent",
            tool_space="context7",
            handoff_tool_name="call_context7_agent",
            domain="library documentation and code examples",
            capabilities="resolving library identifiers, fetching up-to-date documentation, providing version-specific code examples, eliminating hallucinated APIs",
            use_cases="getting accurate documentation, finding code examples, checking API references, learning about libraries",
            system_prompt=CONTEXT7_AGENT_SYSTEM_PROMPT,
            memory_prompt=CONTEXT7_MEMORY_PROMPT,
        ),
    ),
    # Perplexity MCP (Smithery-hosted, OAuth via MCP spec discovery)
    OAuthIntegration(
        id="perplexity",
        name="Perplexity",
        description="AI-powered web search with detailed, contextually relevant results and citations.",
        category="productivity",
        provider="perplexity",
        scopes=[],
        available=True,
        is_featured=True,
        short_name="perplexity",
        managed_by="mcp",
        mcp_config=MCPConfig(
            server_url="https://server.smithery.ai/@arjunkmrm/perplexity-search",
            requires_auth=True,
        ),
        subagent_config=SubAgentConfig(
            has_subagent=True,
            agent_name="perplexity_agent",
            tool_space="perplexity",
            handoff_tool_name="call_perplexity_agent",
            domain="AI-powered web search",
            capabilities="performing comprehensive web searches, providing contextually relevant results with citations, filtering by recency",
            use_cases="web searches, research, finding current information, fact-checking, getting cited answers",
            system_prompt=PERPLEXITY_AGENT_SYSTEM_PROMPT,
            use_direct_tools=True,
            memory_prompt=PERPLEXITY_MEMORY_PROMPT,
        ),
    ),
    # AgentMail MCP (OAuth via MCP spec discovery)
    OAuthIntegration(
        id="agentmail",
        name="AgentMail",
        description="AgentMail is the email inbox API for AI agents. It gives agents their own email inboxes, like Gmail does for humans.",
        category="communication",
        provider="agentmail",
        scopes=[],
        available=True,
        is_featured=True,
        short_name="agentmail",
        managed_by="mcp",
        mcp_config=MCPConfig(
            server_url="https://mcp.agentmail.to",
            requires_auth=True,
        ),
        subagent_config=SubAgentConfig(
            has_subagent=True,
            agent_name="agentmail_agent",
            tool_space="agentmail",
            handoff_tool_name="call_agentmail_agent",
            domain="email management and automation",
            capabilities="sending emails, receiving emails, managing inboxes, email automation, programmatic email handling",
            use_cases="sending automated emails, managing email workflows, email integration, inbox management",
            system_prompt="You are an AgentMail assistant. Help users send, receive, and manage emails programmatically through the AgentMail API.",
            use_direct_tools=True,
            memory_prompt=AGENTMAIL_MEMORY_PROMPT,
        ),
    ),
    # Browserbase MCP (OAuth via MCP spec discovery)
    OAuthIntegration(
        id="browserbase",
        name="Browserbase",
        description="Cloud-based headless browser automation for web scraping, testing, and interaction - navigate pages, fill forms, click elements, and extract data at scale.",
        category="developer",
        provider="browserbase",
        scopes=[],
        available=True,
        is_featured=True,
        short_name="browserbase",
        managed_by="mcp",
        mcp_config=MCPConfig(
            server_url="https://mcp.browserbase.com",
            requires_auth=True,
        ),
        subagent_config=SubAgentConfig(
            has_subagent=True,
            agent_name="browserbase_agent",
            tool_space="browserbase",
            handoff_tool_name="call_browserbase_agent",
            domain="browser automation and web scraping",
            capabilities="navigating web pages, filling forms, clicking elements, extracting data, taking screenshots, running browser automation at scale",
            use_cases="web scraping, browser testing, form automation, data extraction, web interaction",
            system_prompt="You are a Browserbase assistant. Help users automate browser interactions, scrape web content, fill forms, and extract data from websites.",
            use_direct_tools=True,
            memory_prompt=BROWSERBASE_MEMORY_PROMPT,
        ),
    ),
    # PostHog MCP (OAuth via MCP spec discovery)
    OAuthIntegration(
        id="posthog",
        name="PostHog",
        description="Product analytics and experimentation platform - track events, analyze user funnels, run A/B tests, manage feature flags, and query session recordings.",
        category="business",
        provider="posthog",
        scopes=[],
        available=True,
        is_featured=True,
        short_name="posthog",
        managed_by="mcp",
        mcp_config=MCPConfig(
            server_url="https://mcp.posthog.com/mcp",
            requires_auth=True,
        ),
        subagent_config=SubAgentConfig(
            has_subagent=True,
            agent_name="posthog_agent",
            tool_space="posthog",
            handoff_tool_name="call_posthog_agent",
            domain="product analytics and experimentation",
            capabilities="tracking events, analyzing funnels, running A/B tests, managing feature flags, querying session recordings, creating dashboards",
            use_cases="product analytics, user behavior analysis, A/B testing, feature flag management, session replay analysis",
            system_prompt="You are a PostHog assistant. Help users analyze product data, set up experiments, manage feature flags, and understand user behavior.",
            use_direct_tools=True,
            memory_prompt=POSTHOG_MEMORY_PROMPT,
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


@cache
def get_subagent_integrations() -> List[OAuthIntegration]:
    """Get all platform integrations that have subagent configurations.

    Returns:
        List of OAuthIntegration objects with has_subagent=True
    """
    return [
        integration
        for integration in OAUTH_INTEGRATIONS
        if integration.subagent_config and integration.subagent_config.has_subagent
    ]


def get_memory_extraction_prompt(integration_id: str) -> Optional[str]:
    """Get the memory extraction prompt for a specific integration.

    This is the single source of truth for memory prompts.

    Args:
        integration_id: The integration ID (e.g., 'slack', 'github')

    Returns:
        The memory extraction prompt for this integration, or None if not found
    """
    integration = get_integration_by_id(integration_id)
    if not integration or not integration.subagent_config:
        return None
    return integration.subagent_config.memory_prompt


@cache
def get_toolkit_to_integration_map() -> Dict[str, str]:
    """Get mapping of Composio toolkit names to integration IDs.

    This is the single source of truth for tool prefix -> integration category mapping.
    Used by workflow context extractor to infer categories from tool names.

    Returns:
        Dict mapping toolkit name (e.g., 'GMAIL', 'GOOGLECALENDAR') to integration ID
        (e.g., 'gmail', 'googlecalendar')
    """
    mapping = {}
    for integration in OAUTH_INTEGRATIONS:
        # From composio_config.toolkit (e.g., 'GMAIL' -> 'gmail')
        if integration.composio_config and integration.composio_config.toolkit:
            mapping[integration.composio_config.toolkit] = integration.id

        # Also add uppercase ID for internal integrations (e.g., 'TODO' -> 'todos')
        # and for agent name patterns
        mapping[integration.id.upper()] = integration.id

    return mapping
