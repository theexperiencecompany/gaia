"""
Composio Schema Models

Pydantic models for Composio tool responses and trigger payloads.
Reference: node_modules/@composio/core/generated/<toolkit>.ts
"""

from .asana import AsanaTaskCreatedPayload
from .base import ComposioResponse
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
from .google_docs import (
    GoogleDocsDocumentDeletedPayload,
    GoogleDocsDocumentUpdatedPayload,
    GoogleDocsPageAddedPayload,
)
from .google_sheets import (
    GoogleSheetsNewRowPayload,
    GoogleSheetsNewSheetAddedPayload,
)
from .linear import (
    LinearCommentAddedPayload,
    LinearIssueCreatedPayload,
    LinearIssueUpdatedPayload,
)
from .linear_tools import (
    LinearGetAllTeamsData,
    LinearGetAllTeamsInput,
    LinearMember,
    LinearTeam,
)
from .notion import (
    NotionPageContentUpdatedPayload,
    NotionPageCreatedPayload,
    NotionPagePropertiesUpdatedPayload,
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
from .todoist import TodoistNewTaskCreatedPayload

__all__ = [
    "ComposioResponse",
    # Asana
    "AsanaTaskCreatedPayload",
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
    "GoogleDocsDocumentDeletedPayload",
    "GoogleDocsDocumentUpdatedPayload",
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
    "LinearIssueUpdatedPayload",
    "LinearCommentAddedPayload",
    "LinearGetAllTeamsInput",
    "LinearGetAllTeamsData",
    "LinearMember",
    "LinearTeam",
    # Notion
    "NotionPageCreatedPayload",
    "NotionPagePropertiesUpdatedPayload",
    "NotionPageContentUpdatedPayload",
    "NotionFetchDataInput",
    "NotionFetchDataData",
    "NotionItem",
    # Slack
    "SlackChannelCreatedPayload",
    "SlackReceiveMessagePayload",
    "SlackListAllChannelsInput",
    "SlackListAllChannelsData",
    "SlackChannel",
    # Todoist
    "TodoistNewTaskCreatedPayload",
]
