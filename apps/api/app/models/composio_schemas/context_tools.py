"""
Context gathering tool schemas.

Reference: Custom tool for GAIA context aggregation.

Note: All Composio tool responses are wrapped in ToolExecutionResponse with
`data`, `error`, `successful` keys. These models represent the INNER data structure.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class GatherContextInput(BaseModel):
    """Input for GATHER_CONTEXT tool."""

    providers: list[str] | None = Field(
        None,
        description=(
            "Specific providers to gather context from. "
            "Available: calendar, gmail, linear, slack, notion, github, "
            "google_tasks, todoist, asana, trello, clickup, google_drive. "
            "If None, uses all connected."
        ),
    )
    date: str | None = Field(
        None,
        description=(
            "Target date in YYYY-MM-DD format. "
            "Supports past and future dates. Defaults to today."
        ),
    )
    query: str | None = Field(
        None,
        description="Optional query to focus context (e.g., 'project X', 'urgent items')",
    )
    limit_per_provider: int = Field(
        5,
        description="Maximum items to return per provider",
        ge=1,
        le=50,
    )


class ProviderContextData(BaseModel):
    """Context data from a single provider."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    provider: str
    connected: bool = True
    data: dict[str, Any] | None = None
    error: str | None = None
    items_count: int = 0


class GatherContextData(BaseModel):
    """Data inside ToolExecutionResponse.data for GATHER_CONTEXT."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    date: str  # The target date requested
    providers_queried: list[str] = Field(default_factory=list)
    context: dict[str, ProviderContextData] = Field(default_factory=dict)
    total_items: int = 0


# Provider-specific data models


class CalendarContextData(BaseModel):
    """Calendar context for a specific date."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    events: list[dict[str, Any]] = Field(default_factory=list)
    next_event: dict[str, Any] | None = None
    busy_hours: float = 0.0
    free_slots: list[dict[str, Any]] = Field(default_factory=list)


class GmailContextData(BaseModel):
    """Gmail context."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    unread_count: int = 0
    emails: list[dict[str, Any]] = Field(default_factory=list)
    threads: list[dict[str, Any]] = Field(default_factory=list)
    important_threads: list[dict[str, Any]] = Field(default_factory=list)


class LinearContextData(BaseModel):
    """Linear context."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    assigned_issues: list[dict[str, Any]] = Field(default_factory=list)
    active_cycle: dict[str, Any] | None = None
    recent_activity: list[dict[str, Any]] = Field(default_factory=list)


class SlackContextData(BaseModel):
    """Slack context."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    messages: list[dict[str, Any]] = Field(default_factory=list)
    mentions: list[dict[str, Any]] = Field(default_factory=list)
    channels_with_activity: list[dict[str, Any]] = Field(default_factory=list)
    unread_count: int = 0


class NotionContextData(BaseModel):
    """Notion context."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    recently_edited: list[dict[str, Any]] = Field(default_factory=list)
    relevant_pages: list[dict[str, Any]] = Field(default_factory=list)


class GitHubContextData(BaseModel):
    """GitHub context."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    assigned_issues: list[dict[str, Any]] = Field(default_factory=list)
    assigned_prs: list[dict[str, Any]] = Field(default_factory=list)
    review_requests: list[dict[str, Any]] = Field(default_factory=list)
    notifications: list[dict[str, Any]] = Field(default_factory=list)


# New providers


class GoogleTasksContextData(BaseModel):
    """Google Tasks context."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    tasks: list[dict[str, Any]] = Field(default_factory=list)
    overdue_tasks: list[dict[str, Any]] = Field(default_factory=list)
    task_lists: list[dict[str, Any]] = Field(default_factory=list)


class TodoistContextData(BaseModel):
    """Todoist context."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    tasks: list[dict[str, Any]] = Field(default_factory=list)
    overdue_tasks: list[dict[str, Any]] = Field(default_factory=list)
    projects: list[dict[str, Any]] = Field(default_factory=list)


class AsanaContextData(BaseModel):
    """Asana context."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    tasks: list[dict[str, Any]] = Field(default_factory=list)
    projects: list[dict[str, Any]] = Field(default_factory=list)


class TrelloContextData(BaseModel):
    """Trello context."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    cards: list[dict[str, Any]] = Field(default_factory=list)
    boards: list[dict[str, Any]] = Field(default_factory=list)


class ClickUpContextData(BaseModel):
    """ClickUp context."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    tasks: list[dict[str, Any]] = Field(default_factory=list)
    spaces: list[dict[str, Any]] = Field(default_factory=list)
