"""Curated matchable fields per trigger — what a subscription condition may test.

Derived from the payload models in ``app/models/composio_schemas/``, which were
verified against Composio's live triggers API. The full payload models stay loose
because external webhooks omit fields; this catalog is the narrower set we are
willing to match on, and it is also what the agent is shown before it writes a
condition, so it builds from known data instead of guessing.

Every verified payload field is either catalogued or listed in ``excluded`` with a
reason. Two reasons recur:

- *nested free-form dict* — the provider ships a blob (``data``, ``task``) whose
  inner shape was not verified upstream. Cataloguing a key inside it would be the
  guessing this module exists to prevent.
- *list of objects* — attendees, attachments and authors are lists of dicts, which
  the operator table has no meaning for.

Dotted names (``document.id``) are supported for one level, and only where the
nested value is itself a typed model — that is the difference between a verified
field and a guess.
"""

from collections.abc import Mapping
from types import MappingProxyType

from app.models.composio_schemas import (
    AsanaTaskCreatedPayload,
    GitHubCommitEventPayload,
    GitHubIssueAddedEventPayload,
    GitHubPullRequestEventPayload,
    GitHubStarAddedEventPayload,
    GmailNewMessagePayload,
    GoogleCalendarEventCreatedPayload,
    GoogleCalendarEventStartingSoonPayload,
    GoogleDocsDocumentDeletedPayload,
    GoogleDocsDocumentUpdatedPayload,
    GoogleDocsPageAddedPayload,
    GoogleSheetsNewRowPayload,
    GoogleSheetsNewSheetAddedPayload,
    LinearCommentAddedPayload,
    LinearIssueCreatedPayload,
    LinearIssueUpdatedPayload,
    NotionPageContentUpdatedPayload,
    NotionPageCreatedPayload,
    NotionPagePropertiesUpdatedPayload,
    SlackChannelCreatedPayload,
    SlackReceiveMessagePayload,
    TodoistNewTaskCreatedPayload,
)
from app.models.trigger_subscription_models import (
    MatchableField,
    MatchableFieldType,
    MatchableTrigger,
)

_NESTED_BLOB = "Free-form nested object; its inner shape is not verified upstream."
_OBJECT_LIST = "List of nested objects; no matching operator applies."

_STRING = MatchableFieldType.STRING
_INTEGER = MatchableFieldType.INTEGER
_NUMBER = MatchableFieldType.NUMBER
_STRING_LIST = MatchableFieldType.STRING_LIST


def _f(name: str, type_: MatchableFieldType, description: str, example: str) -> MatchableField:
    return MatchableField(name=name, type=type_, description=description, example=example)


_GMAIL_NEW_MESSAGE = MatchableTrigger(
    payload_model=GmailNewMessagePayload,
    fields=(
        _f("thread_id", _STRING, "Gmail thread the message belongs to", "18c9f0a1b2c3d4e5"),
        _f("message_id", _STRING, "Stable id of this message", "18c9f0a1b2c3d4e6"),
        _f("sender", _STRING, "Sender email address", "alice@acme.com"),
        _f("to", _STRING, "Recipient email address", "you@example.com"),
        _f("subject", _STRING, "Email subject line", "Re: Invoice 4021"),
        _f("message_text", _STRING, "Plain-text body of the message", "Thanks — approved."),
        _f("label_ids", _STRING_LIST, "Gmail labels applied to the message", "INBOX"),
    ),
    excluded={
        "id": "Raw Gmail message id; match on message_id, which is the stable one.",
        "message_timestamp": "Provider-formatted string; use the event's arrival time instead.",
        "attachment_list": _OBJECT_LIST,
        "payload": _NESTED_BLOB,
        "preview": _NESTED_BLOB,
    },
)

_LINEAR_EVENT_EXCLUSIONS = MappingProxyType({"data": _NESTED_BLOB})


def _linear(payload_model: type, action_example: str) -> MatchableTrigger:
    """Linear's three triggers share one envelope; only the payload model differs."""
    return MatchableTrigger(
        payload_model=payload_model,
        fields=(
            _f("action", _STRING, "What happened to the resource", action_example),
            _f("type", _STRING, "Linear resource type", "Issue"),
            _f(
                "url", _STRING, "Link to the resource in Linear", "https://linear.app/x/issue/ENG-1"
            ),
        ),
        excluded=dict(_LINEAR_EVENT_EXCLUSIONS),
    )


def _notion(payload_model: type, page_description: str) -> MatchableTrigger:
    """Notion's three triggers share one envelope; only the page semantics differ."""
    return MatchableTrigger(
        payload_model=payload_model,
        fields=(
            _f("page_id", _STRING, page_description, "1f2e3d4c5b6a7890"),
            _f("event_id", _STRING, "Unique id of this webhook event", "evt_01H8X"),
            _f("event_type", _STRING, "Notion webhook event type", "page.created"),
            _f("timestamp", _STRING, "ISO 8601 event timestamp", "2026-08-27T10:15:00Z"),
            _f("workspace_id", _STRING, "Workspace the event came from", "ws_9f8e7d"),
            _f("workspace_name", _STRING, "Workspace name", "Acme HQ"),
        ),
        excluded={"data": _NESTED_BLOB, "authors": _OBJECT_LIST},
    )


def _google_doc(payload_model: type, document_description: str) -> MatchableTrigger:
    """Docs triggers carry a typed ``GoogleDocsDocument``, so one level of dotting
    stays verified rather than guessed."""
    return MatchableTrigger(
        payload_model=payload_model,
        fields=(
            _f("document.id", _STRING, document_description, "1AbCdEfGhIjKlMnOpQ"),
            _f("document.name", _STRING, "Document title", "Q3 Planning"),
            _f(
                "document.mimeType",
                _STRING,
                "MIME type of the document",
                "application/vnd.google-apps.document",
            ),
            _f("document.createdTime", _STRING, "Creation time, ISO 8601", "2026-08-27T10:15:00Z"),
            _f(
                "document.modifiedTime",
                _STRING,
                "Last modification time, ISO 8601",
                "2026-08-27T11:02:00Z",
            ),
            _f("event_type", _STRING, "Type of document event", "document.updated"),
        ),
        excluded={
            "document.owners": _OBJECT_LIST,
            "document.lastModifyingUser": _NESTED_BLOB,
        },
    )


MATCHABLE_TRIGGERS: Mapping[str, MatchableTrigger] = MappingProxyType(
    {
        # Gmail — both triggers deliver the same payload.
        "gmail_new_message": _GMAIL_NEW_MESSAGE,
        "gmail_poll_inbox": _GMAIL_NEW_MESSAGE,
        "calendar_event_created": MatchableTrigger(
            payload_model=GoogleCalendarEventCreatedPayload,
            fields=(
                _f("event_id", _STRING, "Unique id of the event", "7k2m4n6p8q"),
                _f("calendar_id", _STRING, "Calendar the event lives on", "primary"),
                _f("summary", _STRING, "Event title", "Acme kickoff"),
                _f("organizer_email", _STRING, "Organizer's email", "alice@acme.com"),
                _f("organizer_name", _STRING, "Organizer's display name", "Alice Chen"),
                _f("start_time", _STRING, "Start time, ISO 8601", "2026-09-01T15:00:00Z"),
                _f("end_time", _STRING, "End time, ISO 8601", "2026-09-01T16:00:00Z"),
            ),
        ),
        "calendar_event_starting_soon": MatchableTrigger(
            payload_model=GoogleCalendarEventStartingSoonPayload,
            fields=(
                _f("event_id", _STRING, "Unique id of the event", "7k2m4n6p8q"),
                _f("calendar_id", _STRING, "Calendar the event lives on", "primary"),
                _f("summary", _STRING, "Event title", "Acme kickoff"),
                _f("description", _STRING, "Event description", "Agenda in the doc"),
                _f("location", _STRING, "Event location", "Room 4 / Meet"),
                _f("organizer_email", _STRING, "Organizer's email", "alice@acme.com"),
                _f("creator_email", _STRING, "Creator's email", "alice@acme.com"),
                _f("start_time", _STRING, "Start time, ISO 8601", "2026-09-01T15:00:00Z"),
                _f("hangout_link", _STRING, "Google Meet link", "https://meet.google.com/abc-defg"),
                _f(
                    "html_link",
                    _STRING,
                    "Link to the event in Calendar",
                    "https://calendar.google.com/event?eid=x",
                ),
                _f("minutes_until_start", _NUMBER, "Minutes remaining until start", "60"),
                _f(
                    "countdown_window_minutes",
                    _INTEGER,
                    "Reminder window this trigger was registered with",
                    "60",
                ),
            ),
            excluded={
                "attendees": _OBJECT_LIST,
                "start_timestamp": "Epoch duplicate of start_time; match on start_time.",
            },
        ),
        "google_docs_new_document": _google_doc(
            GoogleDocsPageAddedPayload, "Id of the new document"
        ),
        "google_docs_document_updated": _google_doc(
            GoogleDocsDocumentUpdatedPayload, "Id of the updated document"
        ),
        "google_docs_document_deleted": _google_doc(
            GoogleDocsDocumentDeletedPayload, "Id of the deleted document"
        ),
        "google_sheets_new_row": MatchableTrigger(
            payload_model=GoogleSheetsNewRowPayload,
            fields=(
                _f("spreadsheet_id", _STRING, "Spreadsheet the row was added to", "1BxiMVs0XRA5"),
                _f("sheet_name", _STRING, "Sheet tab name", "Responses"),
                _f("row_number", _INTEGER, "1-indexed row number", "42"),
                _f("row_data", _STRING_LIST, "Cell values of the new row", "alice@acme.com"),
                _f(
                    "detected_at",
                    _STRING,
                    "When the row was detected, ISO 8601",
                    "2026-08-27T10:15:00Z",
                ),
            ),
        ),
        "google_sheets_new_sheet": MatchableTrigger(
            payload_model=GoogleSheetsNewSheetAddedPayload,
            fields=(
                _f("spreadsheet_id", _STRING, "Spreadsheet the sheet was added to", "1BxiMVs0XRA5"),
                _f("sheet_name", _STRING, "New sheet tab name", "Q4"),
                _f(
                    "detected_at", _STRING, "When it was detected, ISO 8601", "2026-08-27T10:15:00Z"
                ),
            ),
        ),
        "github_commit_event": MatchableTrigger(
            payload_model=GitHubCommitEventPayload,
            fields=(
                _f("id", _STRING, "Commit SHA", "9f8e7d6c5b4a"),
                _f("author", _STRING, "GitHub username of the author", "octocat"),
                _f("message", _STRING, "Commit message", "fix: handle empty payload"),
                _f("url", _STRING, "Link to the commit", "https://github.com/o/r/commit/9f8e"),
                _f("timestamp", _STRING, "Commit timestamp, ISO 8601", "2026-08-27T10:15:00Z"),
            ),
        ),
        "github_pr_event": MatchableTrigger(
            payload_model=GitHubPullRequestEventPayload,
            fields=(
                _f("action", _STRING, "What happened to the PR", "opened"),
                _f("number", _INTEGER, "PR number", "1096"),
                _f("title", _STRING, "PR title", "fix(triggers): sync schemas"),
                _f("description", _STRING, "PR description", "Closes #1090"),
                _f("createdBy", _STRING, "Username who opened the PR", "octocat"),
                _f("createdAt", _STRING, "When the PR was created", "2026-08-27T10:15:00Z"),
                _f("url", _STRING, "Link to the PR", "https://github.com/o/r/pull/1096"),
            ),
        ),
        "github_issue_added": MatchableTrigger(
            payload_model=GitHubIssueAddedEventPayload,
            fields=(
                _f("action", _STRING, "What happened to the issue", "opened"),
                _f("issue_id", _INTEGER, "Unique issue id", "2841003911"),
                _f("number", _INTEGER, "Issue number", "1090"),
                _f("title", _STRING, "Issue title", "Trigger drops events"),
                _f("description", _STRING, "Issue description", "Steps to reproduce..."),
                _f("createdBy", _STRING, "Username who opened the issue", "octocat"),
                _f("createdAt", _STRING, "When the issue was created", "2026-08-27T10:15:00Z"),
                _f("url", _STRING, "Link to the issue", "https://github.com/o/r/issues/1090"),
            ),
        ),
        "github_star_added": MatchableTrigger(
            payload_model=GitHubStarAddedEventPayload,
            fields=(
                _f("action", _STRING, "What happened to the star", "created"),
                _f("repository_id", _INTEGER, "Unique repository id", "861234567"),
                _f("repository_name", _STRING, "Repository name", "theexperiencecompany/gaia"),
                _f("repository_url", _STRING, "Link to the repository", "https://github.com/o/r"),
                _f("starred_by", _STRING, "Username who starred", "octocat"),
                _f("starred_at", _STRING, "When the star was added", "2026-08-27T10:15:00Z"),
            ),
        ),
        "linear_issue_created": _linear(LinearIssueCreatedPayload, "create"),
        "linear_issue_updated": _linear(LinearIssueUpdatedPayload, "update"),
        "linear_comment_added": _linear(LinearCommentAddedPayload, "create"),
        "notion_new_page_in_db": _notion(NotionPageCreatedPayload, "Id of the new page"),
        "notion_page_updated": _notion(
            NotionPagePropertiesUpdatedPayload, "Id of the page whose properties changed"
        ),
        "notion_page_content_updated": _notion(
            NotionPageContentUpdatedPayload, "Id of the page whose content changed"
        ),
        "slack_new_message": MatchableTrigger(
            payload_model=SlackReceiveMessagePayload,
            fields=(
                _f("channel", _STRING, "Channel id the message was posted in", "C01ABCDEF"),
                _f("channel_type", _STRING, "Kind of channel", "channel"),
                _f("user", _STRING, "Slack user id who sent it", "U01ABCDEF"),
                _f("text", _STRING, "Message text", "shipped it"),
                _f("team_id", _STRING, "Slack workspace id", "T01ABCDEF"),
                _f("ts", _STRING, "Message timestamp id", "1756291200.000100"),
            ),
            excluded={
                "bot_id": "Present only for bot posts; too sparse to match on reliably.",
                "attachments": _OBJECT_LIST,
                "files": _OBJECT_LIST,
            },
        ),
        "slack_channel_created": MatchableTrigger(
            payload_model=SlackChannelCreatedPayload,
            fields=(
                _f("id", _STRING, "New channel id", "C01ABCDEF"),
                _f("name", _STRING, "New channel name", "proj-acme"),
                _f("creator", _STRING, "Slack user id who created it", "U01ABCDEF"),
                _f("created", _INTEGER, "Creation time, unix seconds", "1756291200"),
            ),
        ),
        "todoist_new_task_created": MatchableTrigger(
            payload_model=TodoistNewTaskCreatedPayload,
            fields=(_f("event_type", _STRING, "Type of Todoist event", "item:added"),),
            excluded={"task": _NESTED_BLOB},
        ),
        "asana_task_trigger": MatchableTrigger(
            payload_model=AsanaTaskCreatedPayload,
            fields=(
                _f("task_gid", _STRING, "Gid of the created task", "1201234567890"),
                _f("project_gid", _STRING, "Gid of the project it was added to", "1209876543210"),
                _f("user_gid", _STRING, "Gid of the user who created it", "1205555555555"),
                _f("created_at", _STRING, "Event timestamp, ISO 8601", "2026-08-27T10:15:00Z"),
            ),
        ),
    }
)


def get_matchable_trigger(trigger_name: str) -> MatchableTrigger | None:
    """The catalog entry for ``trigger_name``, or None when it is not subscribable."""
    return MATCHABLE_TRIGGERS.get(trigger_name)
