"""Docstrings for Linear custom tools."""

CUSTOM_RESOLVE_CONTEXT = """
LINEAR — RESOLVE CONTEXT

Resolves fuzzy/partial names to Linear entity IDs efficiently.
Use this tool FIRST when you need to convert user-provided names to IDs.

Args:
    team_name (str): Partial team name (e.g., 'eng' for 'Engineering')
    user_name (str): Partial user name to match
    label_names (List[str]): Partial label names to match
    project_name (str): Partial project name to match
    state_name (str): Partial state name (requires team_id)
    team_id (str): Team ID for state resolution

Returns:
    {
        "current_user": {"id": "...", "name": "...", "email": "..."},
        "teams": [{"id": "...", "name": "...", "key": "..."}],
        "users": [...],
        "labels": [...],
        "projects": [...],
        "states": [...]
    }
"""

CUSTOM_GET_MY_TASKS = """
LINEAR — GET MY TASKS

Gets the current user's assigned issues with smart filtering.

USE THIS TOOL when user asks:
• "What are my tasks?"
• "What should I work on?"
• "Show my high priority issues"
• "What's overdue?"

Args:
    filter (str): 'all', 'today', 'this_week', 'overdue', 'high_priority'
    include_completed (bool): Include completed issues (default: False)
    limit (int): Maximum issues to return (default: 20)

Returns:
    {
        "filter": "high_priority",
        "count": 5,
        "issues": [{"identifier": "ENG-123", "title": "...", ...}]
    }
"""

CUSTOM_SEARCH_ISSUES = """
LINEAR — SEARCH ISSUES

Searches issues using natural language queries across titles, descriptions, and comments.

Args:
    query (str): Search query (natural language)
    team_id (str): Optional team filter
    state_filter (str): Optional - 'backlog', 'unstarted', 'started', 'completed', 'canceled'
    assignee_id (str): Optional assignee filter
    priority_filter (str): Optional - 'urgent', 'high', 'medium', 'low', 'none'
    created_after (str): Optional date filter (ISO format)
    limit (int): Maximum results (default: 20)

Returns:
    {
        "query": "authentication",
        "count": 3,
        "issues": [{"identifier": "ENG-123", "title": "...", ...}]
    }
"""

CUSTOM_GET_ISSUE_FULL_CONTEXT = """
LINEAR — GET ISSUE FULL CONTEXT

Gets complete issue details including comments, relations, and history in one call.

Args:
    issue_id (str): Issue UUID
    issue_identifier (str): Issue identifier (e.g., 'ENG-123')

Returns:
    {
        "issue": {
            "identifier": "ENG-123",
            "title": "...",
            "description": "...",
            "state": "In Progress",
            "priority": "high",
            "sub_issues": [...],
            "relations": [...],
            "comments": [...],
            "activity": [...]
        }
    }
"""

CUSTOM_CREATE_ISSUE = """
LINEAR — CREATE ISSUE

Creates a new issue with full field support, optionally with sub-issues.
Use RESOLVE_CONTEXT first to convert names to IDs.

Required Args:
    team_id (str): Team UUID. Get via RESOLVE_CONTEXT(team_name="...")
    title (str): Issue title

Optional Args:
    description (str): Detailed description (markdown supported)
    assignee_id (str): Assignee UUID. Get via RESOLVE_CONTEXT(user_name="...")
    priority (int): 0=none, 1=urgent, 2=high, 3=medium, 4=low
    state_id (str): Workflow state UUID. Get via RESOLVE_CONTEXT(state_name="...", team_id="...")
    label_ids (List[str]): Label UUIDs. Get via RESOLVE_CONTEXT(label_names=[...])
    project_id (str): Project UUID. Get via RESOLVE_CONTEXT(project_name="...")
    cycle_id (str): Sprint UUID. Get via GET_ACTIVE_SPRINT
    due_date (str): Due date (YYYY-MM-DD or ISO8601)
    estimate (int): Estimate points (1, 2, 3, 5, 8 etc.)
    parent_id (str): Parent issue UUID to create as sub-issue
    sub_issues (List): Sub-issues to create under this issue:
        - title (str): Required
        - description (str): Optional
        - assignee_id (str): Optional
        - priority (int): Optional

Returns:
    {
        "issue": {
            "id": "...",
            "identifier": "ENG-456",
            "title": "...",
            "url": "https://linear.app/..."
        },
        "sub_issues": [
            {"id": "...", "identifier": "ENG-457", "title": "..."}
        ]
    }

Workflow:
    1. RESOLVE_CONTEXT(team_name="eng", user_name="john", label_names=["bug"])
    2. CREATE_ISSUE(team_id=..., title=..., assignee_id=..., label_ids=[...])
"""

CUSTOM_CREATE_SUB_ISSUES = """

LINEAR — CREATE SUB-ISSUES (Batch)

Creates multiple sub-issues under a parent issue in one call.
Sub-issues inherit the team from the parent automatically.

Args:
    parent_issue_id (str): Parent issue UUID
    parent_identifier (str): Parent issue identifier (e.g., 'ENG-123')
    sub_issues (List): List of sub-issues to create (max 10):
        - title (str): Required. Sub-issue title.
        - description (str): Optional description
        - assignee_id (str): Optional assignee
        - priority (int): Optional (0=none, 1=urgent, 2=high, 3=medium, 4=low)

Returns:
    {
        "parent": "ENG-123",
        "created_count": 3,
        "sub_issues": [
            {"id": "...", "identifier": "ENG-124", "title": "..."},
            {"id": "...", "identifier": "ENG-125", "title": "..."},
            ...
        ]
    }
"""


CUSTOM_CREATE_ISSUE_RELATION = """
LINEAR — CREATE ISSUE RELATION

Creates a relationship between two issues.

Relation types:
- 'blocks': This issue blocks the related issue
- 'is_blocked_by': This issue is blocked by the related issue
- 'relates_to': Issues are related
- 'duplicates': This issue duplicates the related issue

Args:
    issue_id (str): Source issue UUID
    related_issue_id (str): Target issue UUID
    relation_type (str): 'blocks', 'is_blocked_by', 'relates_to', 'duplicates'

Returns:
    {
        "relation": {"id": "...", "type": "blocks", "from_issue": "...", "to_issue": "..."}
    }
"""

CUSTOM_GET_ISSUE_ACTIVITY = """
LINEAR — GET ISSUE ACTIVITY

Gets the change history for an issue including state changes, assignments, labels.

Args:
    issue_id (str): Issue UUID
    issue_identifier (str): Issue identifier (e.g., 'ENG-123')
    limit (int): Maximum history entries (default: 10)

Returns:
    {
        "issue": "ENG-123",
        "activity_count": 5,
        "activities": [
            {"timestamp": "...", "actor": "John", "change_type": "state", "from": "Todo", "to": "In Progress"}
        ]
    }
"""

CUSTOM_GET_ACTIVE_SPRINT = """
LINEAR — GET ACTIVE SPRINT

Gets current/active cycle (sprint) context with progress and issues.
Returns summary counts and limited issue samples per state.

Args:
    team_id (str): Optional team filter. If None, returns for all teams.
    issues_per_state_limit (int): Max issues per state category (default: 3, max: 10)

Returns:
    {
        "sprint_count": 2,
        "sprints": [
            {
                "name": "Sprint 24",
                "team": "Engineering",
                "progress": 65.5,
                "total_issues": 12,
                "issues_by_state": {"started": 4, "completed": 6, ...},
                "in_progress": [... limited ...],
                "todo": [... limited ...]
            }
        ]
    }
"""


CUSTOM_BULK_UPDATE_ISSUES = """
LINEAR — BULK UPDATE ISSUES

Batch updates multiple issues at once. Efficient for moving issues between cycles or projects.

Args:
    issue_ids (List[str]): List of issue UUIDs to update
    state_id (str): New state ID
    priority (int): New priority (0-4)
    assignee_id (str): New assignee
    cycle_id (str): Cycle to add to (empty string to remove)
    project_id (str): Project to move to (empty string to remove)
    labels_to_add (List[str]): Label IDs to add
    labels_to_remove (List[str]): Label IDs to remove

Returns:
    {
        "updated_count": 5,
        "updated_issues": [{"id": "...", "identifier": "ENG-123"}]
    }
"""

CUSTOM_GET_NOTIFICATIONS = """
LINEAR — GET NOTIFICATIONS

Gets the current user's notifications/inbox.

Args:
    include_read (bool): Include read notifications (default: False)
    limit (int): Maximum notifications (default: 20)

Returns:
    {
        "count": 3,
        "notifications": [
            {"type": "issueAssigned", "issue": {"identifier": "ENG-123", "title": "..."}, "actor": "John"}
        ]
    }
"""

CUSTOM_GET_WORKSPACE_CONTEXT = """
LINEAR — GET WORKSPACE CONTEXT

Gets full workspace context for session initialization.
Use at the start of a conversation to understand the workspace.

Returns:
    {
        "user": {"id": "...", "name": "...", "assigned_issue_count": 12},
        "teams": [{"name": "Engineering", "key": "ENG", "active_cycle": "Sprint 24", "cycle_progress": 65.5}],
        "urgent_items": {
            "overdue": [...],
            "high_priority": [...],
            "sla_at_risk": [...]
        }
    }
"""
