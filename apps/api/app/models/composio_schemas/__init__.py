"""
Composio Schema Models

Pydantic models for Composio tool responses and trigger payloads.
Reference: node_modules/@composio/core/generated/<toolkit>.ts
"""

from .base import ComposioResponse
from .context_tools import (
    AsanaContextData,
    CalendarContextData,
    ClickUpContextData,
    GatherContextData,
    GatherContextInput,
    GitHubContextData,
    GmailContextData,
    GoogleTasksContextData,
    LinearContextData,
    NotionContextData,
    ProviderContextData,
    SlackContextData,
    TodoistContextData,
    TrelloContextData,
)
from .github import (
    GitHubCommitEventPayload,
    GitHubIssueAddedEventPayload,
    GitHubPullRequestEventPayload,
    GitHubStarAddedEventPayload,
)
from .github_tools import (
    GitHubListRepositoriesData,
    GitHubListRepositoriesInput,
    GitHubRepository,
)
from .gmail import GmailNewMessagePayload
from .google_calendar import (
    GoogleCalendarEventCreatedPayload,
    GoogleCalendarEventStartingSoonPayload,
)
from .google_docs import GoogleDocsPageAddedPayload
from .google_sheets import (
    GoogleSheetsNewRowPayload,
    GoogleSheetsNewSheetAddedPayload,
)
from .linear import LinearCommentAddedPayload, LinearIssueCreatedPayload
from .linear_tools import (
    LinearGetAllTeamsData,
    LinearGetAllTeamsInput,
    LinearMember,
    LinearTeam,
)
from .notion import (
    NotionAllPageEventsPayload,
    NotionPageAddedPayload,
    NotionPageUpdatedPayload,
)
from .notion_tools import NotionFetchDataData, NotionFetchDataInput, NotionItem
from .sheets_tools import (
    GoogleSheetsGetSheetNamesData,
    GoogleSheetsGetSheetNamesInput,
    GoogleSheetsSearchSpreadsheetsData,
    GoogleSheetsSearchSpreadsheetsInput,
    GoogleSheetsSpreadsheet,
)
from .slack import SlackChannelCreatedPayload, SlackReceiveMessagePayload
from .slack_tools import (
    SlackChannel,
    SlackListAllChannelsData,
    SlackListAllChannelsInput,
)

__all__ = [
    "ComposioResponse",
    # Context Gathering
    "AsanaContextData",
    "CalendarContextData",
    "ClickUpContextData",
    "GatherContextData",
    "GatherContextInput",
    "GitHubContextData",
    "GmailContextData",
    "GoogleTasksContextData",
    "LinearContextData",
    "NotionContextData",
    "ProviderContextData",
    "SlackContextData",
    "TodoistContextData",
    "TrelloContextData",
    # GitHub
    "GitHubCommitEventPayload",
    "GitHubPullRequestEventPayload",
    "GitHubStarAddedEventPayload",
    "GitHubIssueAddedEventPayload",
    "GitHubListRepositoriesData",
    "GitHubListRepositoriesInput",
    "GitHubRepository",
    # Gmail
    "GmailNewMessagePayload",
    # Google Calendar
    "GoogleCalendarEventCreatedPayload",
    "GoogleCalendarEventStartingSoonPayload",
    # Google Docs
    "GoogleDocsPageAddedPayload",
    # Google Sheets
    "GoogleSheetsNewRowPayload",
    "GoogleSheetsNewSheetAddedPayload",
    "GoogleSheetsSearchSpreadsheetsInput",
    "GoogleSheetsSearchSpreadsheetsData",
    "GoogleSheetsGetSheetNamesInput",
    "GoogleSheetsGetSheetNamesData",
    "GoogleSheetsSpreadsheet",
    # Linear
    "LinearIssueCreatedPayload",
    "LinearCommentAddedPayload",
    "LinearGetAllTeamsInput",
    "LinearGetAllTeamsData",
    "LinearMember",
    "LinearTeam",
    # Notion
    "NotionPageAddedPayload",
    "NotionPageUpdatedPayload",
    "NotionAllPageEventsPayload",
    "NotionFetchDataInput",
    "NotionFetchDataData",
    "NotionItem",
    # Slack
    "SlackChannelCreatedPayload",
    "SlackReceiveMessagePayload",
    "SlackListAllChannelsInput",
    "SlackListAllChannelsData",
    "SlackChannel",
]
