"""Linear tool Pydantic models for input validation."""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class ResolveContextInput(BaseModel):
    """Input for resolving fuzzy names to Linear IDs."""

    team_name: Optional[str] = Field(
        default=None,
        description="Partial team name to fuzzy match (e.g., 'eng' for 'Engineering')",
    )
    user_name: Optional[str] = Field(
        default=None,
        description="Partial user name to fuzzy match",
    )
    label_names: Optional[List[str]] = Field(
        default=None,
        description="Partial label names to fuzzy match",
    )
    project_name: Optional[str] = Field(
        default=None,
        description="Partial project name to fuzzy match",
    )
    state_name: Optional[str] = Field(
        default=None,
        description="Partial state name to match (requires team context)",
    )
    team_id: Optional[str] = Field(
        default=None,
        description="Team ID for state resolution (if state_name provided)",
    )


class GetMyTasksInput(BaseModel):
    """Input for getting current user's assigned issues."""

    filter: Optional[
        Literal["all", "today", "this_week", "overdue", "high_priority"]
    ] = Field(
        default="all",
        description="Filter for issues: 'all', 'today' (due today), 'this_week', 'overdue', 'high_priority' (P1/P2)",
    )
    include_completed: bool = Field(
        default=False,
        description="Whether to include completed issues",
    )
    limit: int = Field(
        default=20,
        le=50,
        description="Maximum number of issues to return",
    )


class SearchIssuesInput(BaseModel):
    """Input for searching issues with natural language."""

    query: str = Field(
        ...,
        description="Search query (searches title, description, and comments)",
    )
    team_id: Optional[str] = Field(
        default=None,
        description="Filter by team ID",
    )
    state_filter: Optional[
        Literal["backlog", "unstarted", "started", "completed", "canceled"]
    ] = Field(
        default=None,
        description="Filter by state type",
    )
    assignee_id: Optional[str] = Field(
        default=None,
        description="Filter by assignee user ID",
    )
    priority_filter: Optional[Literal["urgent", "high", "medium", "low", "none"]] = (
        Field(
            default=None,
            description="Filter by priority level",
        )
    )
    created_after: Optional[str] = Field(
        default=None,
        description="Filter to issues created after this date (ISO format: YYYY-MM-DD)",
    )
    limit: int = Field(
        default=20,
        le=50,
        description="Maximum number of issues to return",
    )


class GetIssueFullContextInput(BaseModel):
    """Input for getting complete issue context."""

    issue_id: Optional[str] = Field(
        default=None,
        description="Issue UUID",
    )
    issue_identifier: Optional[str] = Field(
        default=None,
        description="Issue identifier (e.g., 'ENG-123')",
    )


class CreateIssueSubItem(BaseModel):
    """Sub-issue to create along with parent issue."""

    title: str = Field(
        ...,
        description="Title of the sub-issue",
    )
    description: Optional[str] = Field(
        default=None,
        description="Description (markdown supported)",
    )
    assignee_id: Optional[str] = Field(
        default=None,
        description="Assignee user ID",
    )
    priority: Optional[int] = Field(
        default=None,
        ge=0,
        le=4,
        description="Priority: 0=none, 1=urgent, 2=high, 3=medium, 4=low",
    )


class CreateIssueInput(BaseModel):
    """Input for creating an issue with full field support."""

    # Required fields
    team_id: str = Field(
        ...,
        description="UUID of the team. Use RESOLVE_CONTEXT to get team_id from team name.",
    )
    title: str = Field(
        ...,
        description="Title of the issue",
    )

    # Optional fields
    description: Optional[str] = Field(
        default=None,
        description="Detailed description (markdown supported)",
    )
    assignee_id: Optional[str] = Field(
        default=None,
        description="UUID of assignee. Use RESOLVE_CONTEXT to get user_id from name.",
    )
    priority: Optional[int] = Field(
        default=0,
        ge=0,
        le=4,
        description="Priority: 0=none, 1=urgent, 2=high, 3=medium, 4=low",
    )
    state_id: Optional[str] = Field(
        default=None,
        description="UUID of workflow state. Use RESOLVE_CONTEXT with team_id to get state_id.",
    )
    label_ids: Optional[List[str]] = Field(
        default=None,
        description="List of label UUIDs. Use RESOLVE_CONTEXT to get label_ids from names.",
    )
    project_id: Optional[str] = Field(
        default=None,
        description="UUID of project. Use RESOLVE_CONTEXT to get project_id from name.",
    )
    cycle_id: Optional[str] = Field(
        default=None,
        description="UUID of cycle/sprint. Use GET_ACTIVE_SPRINT to get cycle_id.",
    )
    due_date: Optional[str] = Field(
        default=None,
        description="Due date in ISO format: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ",
    )
    estimate: Optional[int] = Field(
        default=None,
        ge=0,
        description="Estimate points (team-specific scale: 1, 2, 3, 5, 8 etc.)",
    )
    parent_id: Optional[str] = Field(
        default=None,
        description="UUID of parent issue to create this as a sub-issue",
    )

    # Sub-issues to create
    sub_issues: Optional[List[CreateIssueSubItem]] = Field(
        default=None,
        description="Sub-issues to create under this issue (max 10)",
        max_length=10,
    )


class SubIssueItem(BaseModel):
    """Single sub-issue definition for batch creation."""

    title: str = Field(
        ...,
        description="Title of the sub-issue",
    )
    description: Optional[str] = Field(
        default=None,
        description="Description (markdown supported)",
    )
    assignee_id: Optional[str] = Field(
        default=None,
        description="Assignee user ID",
    )
    priority: Optional[int] = Field(
        default=None,
        ge=0,
        le=4,
        description="Priority: 0=none, 1=urgent, 2=high, 3=medium, 4=low",
    )


class CreateSubIssuesInput(BaseModel):
    """Input for batch creating sub-issues under a parent."""

    parent_issue_id: Optional[str] = Field(
        default=None,
        description="Parent issue UUID",
    )
    parent_identifier: Optional[str] = Field(
        default=None,
        description="Parent issue identifier (e.g., 'ENG-123')",
    )
    sub_issues: List[SubIssueItem] = Field(
        ...,
        description="List of sub-issues to create (max 10)",
        max_length=10,
    )


class CreateIssueRelationInput(BaseModel):
    """Input for creating issue relationships."""

    issue_id: str = Field(
        ...,
        description="Source issue UUID",
    )
    related_issue_id: str = Field(
        ...,
        description="Target issue UUID",
    )
    relation_type: Literal["blocks", "is_blocked_by", "relates_to", "duplicates"] = (
        Field(
            ...,
            description="Type of relationship between issues",
        )
    )


class GetIssueActivityInput(BaseModel):
    """Input for getting issue change history."""

    issue_id: Optional[str] = Field(
        default=None,
        description="Issue UUID",
    )
    issue_identifier: Optional[str] = Field(
        default=None,
        description="Issue identifier (e.g., 'ENG-123')",
    )
    limit: int = Field(
        default=10,
        le=50,
        description="Maximum number of history entries to return",
    )


class GetActiveSprintInput(BaseModel):
    """Input for getting current/active cycle context."""

    team_id: Optional[str] = Field(
        default=None,
        description="Team ID to get active sprint for. If None, returns for all teams.",
    )
    issues_per_state_limit: int = Field(
        default=3,
        le=10,
        description="Maximum issues to return per state category (default: 3, max: 10)",
    )


class BulkUpdateIssuesInput(BaseModel):
    """Input for batch updating multiple issues."""

    issue_ids: List[str] = Field(
        ...,
        description="List of issue UUIDs to update",
    )
    state_id: Optional[str] = Field(
        default=None,
        description="New state ID to set",
    )
    priority: Optional[int] = Field(
        default=None,
        ge=0,
        le=4,
        description="New priority to set",
    )
    assignee_id: Optional[str] = Field(
        default=None,
        description="New assignee user ID",
    )
    cycle_id: Optional[str] = Field(
        default=None,
        description="Cycle ID to add issues to (use empty string to remove from cycle)",
    )
    project_id: Optional[str] = Field(
        default=None,
        description="Project ID to move issues to (use empty string to remove from project)",
    )
    labels_to_add: Optional[List[str]] = Field(
        default=None,
        description="Label IDs to add to issues",
    )
    labels_to_remove: Optional[List[str]] = Field(
        default=None,
        description="Label IDs to remove from issues",
    )


class GetNotificationsInput(BaseModel):
    """Input for getting user notifications."""

    include_read: bool = Field(
        default=False,
        description="Whether to include already-read notifications",
    )
    limit: int = Field(
        default=20,
        le=50,
        description="Maximum number of notifications to return",
    )


class GetWorkspaceContextInput(BaseModel):
    """Input for getting full workspace context (no parameters needed)."""

    pass
