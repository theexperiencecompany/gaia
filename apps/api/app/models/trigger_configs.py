"""
Type-safe trigger configuration models.

This module defines Pydantic models for provider-specific trigger configurations
using a discriminated union pattern for type safety.

To add a new trigger:
1. Create a new config class extending BaseTriggerConfigData
2. Add a literal trigger_name field as the discriminator
3. Add the class to the TriggerConfigData union
"""

from typing import Annotated, List, Literal, Union

from pydantic import BaseModel, Discriminator, Field


class BaseTriggerConfigData(BaseModel):
    """Base class for trigger-specific configuration."""

    pass


# =============================================================================
# CALENDAR TRIGGERS
# =============================================================================


class CalendarEventCreatedConfig(BaseTriggerConfigData):
    """Config for calendar_event_created trigger."""

    trigger_name: Literal["calendar_event_created"] = "calendar_event_created"
    calendar_ids: List[str] = Field(
        default=["primary"],
        description="Calendar IDs to monitor. Use ['all'] for all calendars.",
    )


class CalendarEventStartingSoonConfig(BaseTriggerConfigData):
    """Config for calendar_event_starting_soon trigger."""

    trigger_name: Literal["calendar_event_starting_soon"] = (
        "calendar_event_starting_soon"
    )
    calendar_ids: List[str] = Field(
        default=["primary"],
        description="Calendar IDs to monitor. Use ['all'] for all calendars.",
    )
    minutes_before_start: int = Field(
        default=10,
        ge=1,
        le=1440,
        description="Minutes before event start to trigger",
    )
    include_all_day: bool = Field(
        default=False, description="Whether to include all-day events"
    )


# =============================================================================
# GMAIL TRIGGERS
# =============================================================================


class GmailNewMessageConfig(BaseTriggerConfigData):
    """Config for gmail new message trigger."""

    trigger_name: Literal["gmail_new_message"] = "gmail_new_message"
    # Gmail triggers currently have no additional config


# =============================================================================
# GITHUB TRIGGERS
# =============================================================================


class GitHubCommitEventConfig(BaseTriggerConfigData):
    """Config for github_commit_event trigger."""

    trigger_name: Literal["github_commit_event"] = "github_commit_event"
    repos: List[str] = Field(
        default_factory=list,
        description="List of repositories in owner/repo format",
    )


class GitHubPrEventConfig(BaseTriggerConfigData):
    """Config for github_pr_event trigger."""

    trigger_name: Literal["github_pr_event"] = "github_pr_event"
    repos: List[str] = Field(
        default_factory=list,
        description="List of repositories in owner/repo format",
    )


class GitHubStarAddedConfig(BaseTriggerConfigData):
    """Config for github_star_added trigger."""

    trigger_name: Literal["github_star_added"] = "github_star_added"
    repos: List[str] = Field(
        default_factory=list,
        description="List of repositories in owner/repo format",
    )


class GitHubIssueAddedConfig(BaseTriggerConfigData):
    """Config for github_issue_added trigger."""

    trigger_name: Literal["github_issue_added"] = "github_issue_added"
    repos: List[str] = Field(
        default_factory=list,
        description="List of repositories in owner/repo format",
    )


# =============================================================================
# GOOGLE DOCS TRIGGERS
# =============================================================================


class GoogleDocsNewDocumentConfig(BaseTriggerConfigData):
    """Config for google_docs_new_document trigger."""

    trigger_name: Literal["google_docs_new_document"] = "google_docs_new_document"


class GoogleDocsDocumentDeletedConfig(BaseTriggerConfigData):
    """Config for google_docs_document_deleted trigger."""

    trigger_name: Literal["google_docs_document_deleted"] = (
        "google_docs_document_deleted"
    )


class GoogleDocsDocumentUpdatedConfig(BaseTriggerConfigData):
    """Config for google_docs_document_updated trigger."""

    trigger_name: Literal["google_docs_document_updated"] = (
        "google_docs_document_updated"
    )


# =============================================================================
# GOOGLE SHEETS TRIGGERS
# =============================================================================


class GoogleSheetsNewRowConfig(BaseTriggerConfigData):
    """Config for google_sheets_new_row trigger."""

    trigger_name: Literal["google_sheets_new_row"] = "google_sheets_new_row"
    spreadsheet_ids: List[str] = Field(
        default_factory=list,
        description="List of spreadsheet IDs to monitor",
    )
    sheet_names: List[str] = Field(
        default_factory=list,
        description="List of sheet names to monitor (requires spreadsheet_ids)",
    )


class GoogleSheetsNewSheetConfig(BaseTriggerConfigData):
    """Config for google_sheets_new_sheet trigger."""

    trigger_name: Literal["google_sheets_new_sheet"] = "google_sheets_new_sheet"
    spreadsheet_ids: List[str] = Field(
        default_factory=list,
        description="List of spreadsheet IDs to monitor",
    )


# =============================================================================
# LINEAR TRIGGERS
# =============================================================================


class LinearIssueCreatedConfig(BaseTriggerConfigData):
    """Config for linear_issue_created trigger."""

    trigger_name: Literal["linear_issue_created"] = "linear_issue_created"
    team_id: str = Field(
        default="",
        description="Linear team ID to monitor (optional)",
    )


class LinearIssueUpdatedConfig(BaseTriggerConfigData):
    """Config for linear_issue_updated trigger."""

    trigger_name: Literal["linear_issue_updated"] = "linear_issue_updated"
    team_id: str = Field(
        default="",
        description="Linear team ID to monitor (optional)",
    )


class LinearCommentAddedConfig(BaseTriggerConfigData):
    """Config for linear_comment_added trigger."""

    trigger_name: Literal["linear_comment_added"] = "linear_comment_added"
    team_id: str = Field(
        default="",
        description="Linear team ID to monitor (optional)",
    )


# =============================================================================
# NOTION TRIGGERS
# =============================================================================


class NotionNewPageInDbConfig(BaseTriggerConfigData):
    """Config for notion_new_page_in_db trigger."""

    trigger_name: Literal["notion_new_page_in_db"] = "notion_new_page_in_db"
    database_ids: List[str] = Field(
        default_factory=list,
        description="List of Notion database IDs to monitor",
    )


class NotionPageUpdatedConfig(BaseTriggerConfigData):
    """Config for notion_page_updated trigger."""

    trigger_name: Literal["notion_page_updated"] = "notion_page_updated"
    page_ids: List[str] = Field(
        default_factory=list,
        description="List of Notion page IDs to monitor",
    )


class NotionAllPageEventsConfig(BaseTriggerConfigData):
    """Config for notion_all_page_events trigger."""

    trigger_name: Literal["notion_all_page_events"] = "notion_all_page_events"


# =============================================================================
# SLACK TRIGGERS
# =============================================================================


class SlackNewMessageConfig(BaseTriggerConfigData):
    """Config for slack_new_message trigger."""

    trigger_name: Literal["slack_new_message"] = "slack_new_message"
    channel_ids: List[str] = Field(
        default_factory=list,
        description="List of Slack channel IDs to monitor (optional)",
    )
    exclude_bot_messages: bool = Field(
        default=False,
        description="Exclude bot messages from triggering",
    )
    exclude_direct_messages: bool = Field(
        default=False,
        description="Exclude direct messages from triggering",
    )
    exclude_group_messages: bool = Field(
        default=False,
        description="Exclude group messages from triggering",
    )
    exclude_mpim_messages: bool = Field(
        default=False,
        description="Exclude multi-party direct messages from triggering",
    )
    exclude_thread_replies: bool = Field(
        default=False,
        description="Exclude thread replies from triggering",
    )


class SlackChannelCreatedConfig(BaseTriggerConfigData):
    """Config for slack_channel_created trigger."""

    trigger_name: Literal["slack_channel_created"] = "slack_channel_created"


# =============================================================================
# TODOIST TRIGGERS
# =============================================================================


class TodoistNewTaskCreatedConfig(BaseTriggerConfigData):
    """Config for todoist_new_task_created trigger."""

    trigger_name: Literal["todoist_new_task_created"] = "todoist_new_task_created"


# =============================================================================
# ASANA TRIGGERS
# =============================================================================


class AsanaTaskTriggerConfig(BaseTriggerConfigData):
    """Config for asana_task_trigger."""

    trigger_name: Literal["asana_task_trigger"] = "asana_task_trigger"
    project_id: str = Field(
        default="",
        description="ID of the project to trigger on (optional)",
    )
    workspace_id: str = Field(
        default="",
        description="ID of the workspace to trigger on (optional)",
    )


# =============================================================================
# DISCRIMINATED UNION - Add new configs here
# =============================================================================

TriggerConfigData = Annotated[
    Union[
        CalendarEventCreatedConfig,
        CalendarEventStartingSoonConfig,
        GmailNewMessageConfig,
        GitHubCommitEventConfig,
        GitHubPrEventConfig,
        GitHubStarAddedConfig,
        GitHubIssueAddedConfig,
        GoogleDocsNewDocumentConfig,
        GoogleDocsDocumentDeletedConfig,
        GoogleDocsDocumentUpdatedConfig,
        GoogleSheetsNewRowConfig,
        GoogleSheetsNewSheetConfig,
        LinearIssueCreatedConfig,
        LinearIssueUpdatedConfig,
        LinearCommentAddedConfig,
        NotionNewPageInDbConfig,
        NotionPageUpdatedConfig,
        NotionAllPageEventsConfig,
        SlackNewMessageConfig,
        SlackChannelCreatedConfig,
        TodoistNewTaskCreatedConfig,
        AsanaTaskTriggerConfig,
    ],
    Discriminator("trigger_name"),
]

# Type alias for trigger names
TriggerName = Literal[
    "calendar_event_created",
    "calendar_event_starting_soon",
    "gmail_new_message",
    "github_commit_event",
    "github_pr_event",
    "github_star_added",
    "github_issue_added",
    "google_docs_new_document",
    "google_docs_document_deleted",
    "google_docs_document_updated",
    "google_sheets_new_row",
    "google_sheets_new_sheet",
    "linear_issue_created",
    "linear_issue_updated",
    "linear_comment_added",
    "notion_new_page_in_db",
    "notion_page_updated",
    "notion_all_page_events",
    "slack_new_message",
    "slack_channel_created",
    "todoist_new_task_created",
    "asana_task_trigger",
]
