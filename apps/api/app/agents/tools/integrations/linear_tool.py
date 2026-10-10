"""Linear tools using Composio custom tool infrastructure.

Linear GraphQL calls go through `linear_utils.graphql_request`, which routes
through Composio's proxy via `proxy_request_sync`. The proxy attaches the
user's OAuth token server-side; tools only need `user_id` from
`auth_credentials`.

Note: Errors are raised as exceptions - Composio wraps responses automatically.
"""

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import TypeVar

from composio import Composio
from composio.types import ExecuteRequestFn
from langgraph.config import get_config

from app.decorators import with_doc
from app.models.common_models import GatherContextInput
from app.models.integrations.composio import CustomToolAuthCredentials
from app.models.integrations.linear import (
    LinearCyclesData,
    LinearFirstVariables,
    LinearIssue,
    LinearIssueBatchUpdateData,
    LinearIssueBatchUpdateVariables,
    LinearIssueCreateData,
    LinearIssueCreateInput,
    LinearIssueCreateVariables,
    LinearIssueData,
    LinearIssueHistory,
    LinearIssueHistoryData,
    LinearIssueHistoryVariables,
    LinearIssueIdVariables,
    LinearIssueRelationCreateData,
    LinearIssueRelationCreateVariables,
    LinearIssuesData,
    LinearIssueSummary,
    LinearIssueUpdateInput,
    LinearLabel,
    LinearLabelsData,
    LinearMyIssuesVariables,
    LinearNotificationsData,
    LinearPassthroughNode,
    LinearProjectsData,
    LinearSearchIssuesData,
    LinearSearchIssuesVariables,
    LinearStatesData,
    LinearTeamIdVariables,
    LinearTeamsData,
    LinearUsersData,
    LinearViewerData,
)
from app.models.linear_models import (
    BulkUpdateIssuesInput,
    CreateIssueInput,
    CreateIssueRelationInput,
    CreateIssueSubItem,
    CreateSubIssuesInput,
    GetActiveSprintInput,
    GetIssueActivityInput,
    GetIssueFullContextInput,
    GetMyTasksInput,
    GetNotificationsInput,
    GetWorkspaceContextInput,
    ResolveContextInput,
    SearchIssuesInput,
    SubIssueItem,
)
from app.templates.docstrings.linear_tool_docs import (
    CUSTOM_BULK_UPDATE_ISSUES as CUSTOM_BULK_UPDATE_ISSUES_DOC,
    CUSTOM_CREATE_ISSUE as CUSTOM_CREATE_ISSUE_DOC,
    CUSTOM_CREATE_ISSUE_RELATION as CUSTOM_CREATE_ISSUE_RELATION_DOC,
    CUSTOM_CREATE_SUB_ISSUES as CUSTOM_CREATE_SUB_ISSUES_DOC,
    CUSTOM_GET_ACTIVE_SPRINT as CUSTOM_GET_ACTIVE_SPRINT_DOC,
    CUSTOM_GET_ISSUE_ACTIVITY as CUSTOM_GET_ISSUE_ACTIVITY_DOC,
    CUSTOM_GET_ISSUE_FULL_CONTEXT as CUSTOM_GET_ISSUE_FULL_CONTEXT_DOC,
    CUSTOM_GET_MY_TASKS as CUSTOM_GET_MY_TASKS_DOC,
    CUSTOM_GET_NOTIFICATIONS as CUSTOM_GET_NOTIFICATIONS_DOC,
    CUSTOM_GET_WORKSPACE_CONTEXT as CUSTOM_GET_WORKSPACE_CONTEXT_DOC,
    CUSTOM_RESOLVE_CONTEXT as CUSTOM_RESOLVE_CONTEXT_DOC,
    CUSTOM_SEARCH_ISSUES as CUSTOM_SEARCH_ISSUES_DOC,
)
from app.utils.linear_utils import (
    MUTATION_CREATE_ISSUE,
    MUTATION_CREATE_RELATION,
    MUTATION_UPDATE_ISSUES,
    QUERY_ACTIVE_CYCLES,
    QUERY_ISSUE_BY_ID,
    QUERY_ISSUE_HISTORY,
    QUERY_LABELS,
    QUERY_LABELS_ALL,
    QUERY_MY_ISSUES,
    QUERY_NOTIFICATIONS,
    QUERY_PROJECTS,
    QUERY_SEARCH_ISSUES,
    QUERY_STATES,
    QUERY_TEAMS,
    QUERY_USERS,
    QUERY_VIEWER,
    format_issue_summary,
    fuzzy_match,
    graphql_request,
    priority_to_int,
    priority_to_str,
)
from app.utils.timezone import home_timezone_from_config

_CLOSED_STATE_TYPES = ("completed", "canceled")
_URGENT_PRIORITIES = (1, 2)
_SPRINT_STATE_TYPES = ("backlog", "unstarted", "started", "completed")
_UNDATED_SORT_KEY = "9999-12-31"  # pragma: no mutate -- ISO dates sort before any letter-led key
_PassthroughT = TypeVar("_PassthroughT", bound=LinearPassthroughNode)
# Linear's name for each relation_type the tool accepts.
_RELATION_TYPES: dict[str, str] = {
    "blocks": "blocks",
    "is_blocked_by": "blocked_by",
    "relates_to": "related",
    "duplicates": "duplicate",
}


def _user_id(auth_credentials: dict[str, object]) -> str:
    return CustomToolAuthCredentials.parse(auth_credentials).user_id


def _user_local_today() -> date:
    """Today's date in the user's home zone (from the agent config).

    Due-date filters ("today"/"overdue"/"this week") must use the user's local
    date, not the server's. Falls back to the UTC date outside an agent run.
    """
    try:
        return home_timezone_from_config(get_config()).now().date()
    except Exception:
        return datetime.now(UTC).date()


def _parse_due_date(due_date: str | None) -> date | None:
    if not due_date:
        return None
    try:
        return datetime.fromisoformat(due_date).date()
    except ValueError:
        return None


def _validate_identifier(identifier: str) -> None:
    """TEAM-123: a team key, a dash, a number."""
    parts = identifier.split("-")
    if len(parts) != 2:
        raise ValueError(f"Invalid identifier format: {identifier}")
    try:
        float(parts[1])
    except ValueError as e:
        raise ValueError(f"Invalid issue number in: {identifier}") from e


def _fetch_issue(issue_ref: str, user_id: str) -> LinearIssue:
    """The full issue for a UUID or a TEAM-123 identifier (issue(id:) takes both)."""
    return graphql_request(
        QUERY_ISSUE_BY_ID, LinearIssueIdVariables(id=issue_ref), user_id, LinearIssueData
    ).issue


def _sub_issue_input(
    team_id: str, parent_id: str, sub: CreateIssueSubItem | SubIssueItem
) -> LinearIssueCreateInput:
    input_data = LinearIssueCreateInput(team_id=team_id, title=sub.title, parent_id=parent_id)
    if sub.description:
        input_data.description = sub.description
    if sub.assignee_id:
        input_data.assignee_id = sub.assignee_id
    if sub.priority is not None:
        input_data.priority = sub.priority
    return input_data


def _create_issue(input_data: LinearIssueCreateInput, user_id: str) -> dict[str, object] | None:
    """Create one issue; None when Linear reports success: false."""
    payload = graphql_request(
        MUTATION_CREATE_ISSUE,
        LinearIssueCreateVariables(input=input_data),
        user_id,
        LinearIssueCreateData,
    ).issue_create
    if not payload.success or payload.issue is None:
        return None
    return {
        "id": payload.issue.id,
        "identifier": payload.issue.identifier,
        "title": payload.issue.title,
    }


def _history_entry(
    entry: LinearIssueHistory, change_key: str, *, system_actor: str | None
) -> dict[str, object] | None:
    """One activity line for a history entry, or None when it changed nothing we report."""
    actor = entry.actor.name if entry.actor else system_actor
    line: dict[str, object] = {"timestamp": entry.created_at, "actor": actor}
    if entry.from_state or entry.to_state:
        line[change_key] = "state"
        line["from"] = entry.from_state.name if entry.from_state else None
        line["to"] = entry.to_state.name if entry.to_state else None
    elif entry.from_assignee or entry.to_assignee:
        line[change_key] = "assignee"
        line["from"] = entry.from_assignee.name if entry.from_assignee else None
        line["to"] = entry.to_assignee.name if entry.to_assignee else None
    elif entry.from_priority is not None or entry.to_priority is not None:
        line[change_key] = "priority"
        line["from"] = priority_to_str(entry.from_priority or 0)
        line["to"] = priority_to_str(entry.to_priority or 0)
    elif entry.added_labels:
        line[change_key] = "labels_added"
        line["labels"] = [label.name for label in entry.added_labels]
    elif entry.removed_labels:
        line[change_key] = "labels_removed"
        line["labels"] = [label.name for label in entry.removed_labels]
    else:
        return None
    return line


def _dump_matches(nodes: Sequence[_PassthroughT]) -> list[dict[str, object]]:
    """Matched nodes as CUSTOM_RESOLVE_CONTEXT returns them: Linear's own camelCase keys."""
    # JSON-native fields: python and json dumps are identical
    return [n.model_dump(mode="json", by_alias=True) for n in nodes]  # pragma: no mutate


def _run_resolve_context(request: ResolveContextInput, user_id: str) -> dict[str, object]:
    result: dict[str, object] = {}

    viewer = graphql_request(QUERY_VIEWER, None, user_id, LinearViewerData).viewer
    result["current_user"] = {
        "id": viewer.id,
        "name": viewer.name,
        "email": viewer.email,
    }

    if request.team_name:
        teams = graphql_request(QUERY_TEAMS, None, user_id, LinearTeamsData).teams.nodes
        result["teams"] = _dump_matches(fuzzy_match(request.team_name, teams))

    if request.user_name:
        users = graphql_request(QUERY_USERS, None, user_id, LinearUsersData).users.nodes
        active_users = [u for u in users if u.active]
        result["users"] = _dump_matches(fuzzy_match(request.user_name, active_users))

    if request.label_names:
        if request.team_id:
            labels_data = graphql_request(
                QUERY_LABELS,
                LinearTeamIdVariables(team_id=request.team_id),
                user_id,
                LinearLabelsData,
            )
        else:
            labels_data = graphql_request(QUERY_LABELS_ALL, None, user_id, LinearLabelsData)
        labels = labels_data.issue_labels.nodes
        matched_labels: list[LinearLabel] = []
        for label_name in request.label_names[:3]:
            matched_labels.extend(fuzzy_match(label_name, labels, limit=1))
        result["labels"] = _dump_matches(matched_labels)

    if request.project_name:
        projects = graphql_request(QUERY_PROJECTS, None, user_id, LinearProjectsData).projects.nodes
        result["projects"] = _dump_matches(fuzzy_match(request.project_name, projects))

    if request.state_name and request.team_id:
        states = graphql_request(
            QUERY_STATES,
            LinearTeamIdVariables(team_id=request.team_id),
            user_id,
            LinearStatesData,
        ).workflow_states.nodes
        result["states"] = _dump_matches(fuzzy_match(request.state_name, states))

    return {"data": result}


def _matches_task_filter(
    task_filter: str | None, issue: LinearIssueSummary, today: date, week_end: date
) -> bool:
    """Whether issue belongs in a CUSTOM_GET_MY_TASKS view; unknown filters keep all."""
    due_date = _parse_due_date(issue.due_date)
    if task_filter == "today":
        return due_date == today
    if task_filter == "this_week":
        return bool(due_date and today <= due_date <= week_end)
    if task_filter == "overdue":
        return bool(due_date and due_date < today)
    if task_filter == "high_priority":
        return issue.priority in _URGENT_PRIORITIES
    return True


def _run_get_my_tasks(request: GetMyTasksInput, user_id: str) -> dict[str, object]:
    viewer = graphql_request(QUERY_VIEWER, None, user_id, LinearViewerData).viewer

    issues = graphql_request(
        QUERY_MY_ISSUES,
        LinearMyIssuesVariables(
            assignee_id=viewer.id,
            include_completed=not request.include_completed,
            first=min(request.limit * 2, 100),  # pragma: no mutate -- limit is capped at 50
        ),
        user_id,
        LinearIssuesData,
    ).issues.nodes
    today = _user_local_today()
    week_end = today + timedelta(days=7)

    filtered: list[LinearIssueSummary] = []
    for issue in issues:
        if not request.include_completed and issue.state.type in _CLOSED_STATE_TYPES:
            continue
        if _matches_task_filter(request.filter, issue, today, week_end):
            filtered.append(issue)

    def sort_key(issue: LinearIssueSummary) -> tuple[int, str]:
        return (issue.priority, issue.due_date or _UNDATED_SORT_KEY)

    filtered.sort(key=sort_key)
    formatted = [format_issue_summary(i) for i in filtered[: request.limit]]

    return {
        "filter": request.filter,
        "count": len(formatted),
        "issues": formatted,
    }


def _run_search_issues(request: SearchIssuesInput, user_id: str) -> dict[str, object]:
    issues = graphql_request(
        QUERY_SEARCH_ISSUES,
        LinearSearchIssuesVariables(
            query=request.query,
            first=min(request.limit * 2, 100),  # pragma: no mutate -- limit is capped at 50
        ),
        user_id,
        LinearSearchIssuesData,
    ).search_issues.nodes

    filtered: list[LinearIssueSummary] = []
    for issue in issues:
        if request.team_id and issue.team.id != request.team_id:
            continue
        if request.state_filter and issue.state.type.lower() != request.state_filter:
            continue
        if request.assignee_id:
            if issue.assignee is None or issue.assignee.id != request.assignee_id:
                continue
        if request.priority_filter:
            if issue.priority != priority_to_int(request.priority_filter):
                continue
        if request.created_after and (issue.created_at or "") < request.created_after:
            continue
        filtered.append(issue)

    formatted = [format_issue_summary(i) for i in filtered[: request.limit]]

    return {
        "query": request.query,
        "count": len(formatted),
        "issues": formatted,
    }


def _run_get_issue_full_context(
    request: GetIssueFullContextInput, user_id: str
) -> dict[str, object]:
    if not request.issue_id and not request.issue_identifier:
        raise ValueError("Provide either issue_id or issue_identifier")

    if request.issue_id:
        issue = _fetch_issue(request.issue_id, user_id)
    else:
        _validate_identifier(
            request.issue_identifier or "",  # pragma: no mutate -- guard above rules out ""
        )
        issue = _fetch_issue(
            request.issue_identifier or "",  # pragma: no mutate -- guard above rules out ""
            user_id,
        )

    result: dict[str, object] = {
        "id": issue.id,
        "identifier": issue.identifier,
        "title": issue.title,
        "description": issue.description,
        "priority": priority_to_str(issue.priority),
        "state": issue.state.name,
        "dueDate": issue.due_date,
        "estimate": issue.estimate,
        "team": issue.team.name,
        "project": issue.project.name if issue.project else None,
        "cycle": issue.cycle.name if issue.cycle else None,
        "assignee": issue.assignee.name if issue.assignee else None,
        "creator": issue.creator.name if issue.creator else None,
    }

    if issue.parent:
        result["parent"] = {
            "identifier": issue.parent.identifier,
            "title": issue.parent.title,
        }

    if issue.children.nodes:
        result["sub_issues"] = [
            {"identifier": c.identifier, "title": c.title, "state": c.state.name}
            for c in issue.children.nodes
        ]

    if issue.relations.nodes:
        result["relations"] = [
            {
                "type": r.type,
                "issue": {
                    "identifier": r.related_issue.identifier,
                    "title": r.related_issue.title,
                },
            }
            for r in issue.relations.nodes
        ]

    if issue.comments.nodes:
        result["comments"] = [
            {
                "author": c.user.name if c.user else None,
                "body": c.body,
                "createdAt": c.created_at,
            }
            for c in issue.comments.nodes
        ]

    if issue.history.nodes:
        result["activity"] = [
            entry
            for h in issue.history.nodes
            if (entry := _history_entry(h, "change", system_actor=None)) is not None
        ]

    if issue.attachments.nodes:
        result["attachments"] = [{"title": a.title, "url": a.url} for a in issue.attachments.nodes]

    return {"issue": result}


def _issue_create_input(request: CreateIssueInput) -> LinearIssueCreateInput:
    """The GraphQL create input, carrying only the fields the request actually set."""
    input_data = LinearIssueCreateInput(team_id=request.team_id, title=request.title)

    if request.description:
        input_data.description = request.description
    if request.assignee_id:
        input_data.assignee_id = request.assignee_id
    if request.priority is not None:
        input_data.priority = request.priority
    if request.state_id:
        input_data.state_id = request.state_id
    if request.label_ids:
        input_data.label_ids = request.label_ids
    if request.project_id:
        input_data.project_id = request.project_id
    if request.cycle_id:
        input_data.cycle_id = request.cycle_id
    if request.due_date:
        input_data.due_date = request.due_date
    if request.estimate is not None:
        input_data.estimate = request.estimate
    if request.parent_id:
        input_data.parent_id = request.parent_id
    return input_data


def _run_create_issue(request: CreateIssueInput, user_id: str) -> dict[str, object]:
    # Create the main issue
    create_result = graphql_request(
        MUTATION_CREATE_ISSUE,
        LinearIssueCreateVariables(input=_issue_create_input(request)),
        user_id,
        LinearIssueCreateData,
    ).issue_create
    if not create_result.success or create_result.issue is None:
        raise RuntimeError("Failed to create issue")

    created = create_result.issue
    response: dict[str, object] = {
        "issue": {
            "id": created.id,
            "identifier": created.identifier,
            "title": created.title,
            "url": created.url,
        },
    }

    # Create sub-issues if provided
    if request.sub_issues:
        created_subs: list[dict[str, object]] = []
        errors: list[dict[str, object]] = []

        for sub in request.sub_issues:
            sub_issue = _create_issue(_sub_issue_input(request.team_id, created.id, sub), user_id)
            if sub_issue is not None:
                created_subs.append(sub_issue)
            else:
                errors.append({"title": sub.title, "error": "Failed to create"})

        response["sub_issues"] = created_subs
        if errors:
            response["sub_issue_errors"] = errors

    return response


def _run_create_sub_issues(request: CreateSubIssuesInput, user_id: str) -> dict[str, object]:
    parent_ref = request.parent_issue_id

    if not parent_ref and request.parent_identifier:
        parts = request.parent_identifier.split("-")
        if len(parts) != 2:
            raise ValueError(f"Invalid parent identifier: {request.parent_identifier}")
        try:
            float(parts[1])
        except ValueError as e:
            raise ValueError(f"Invalid issue number in: {request.parent_identifier}") from e
        parent_ref = request.parent_identifier

    if not parent_ref:
        raise ValueError("Could not resolve parent issue")

    parent_issue = _fetch_issue(parent_ref, user_id)

    created_issues: list[dict[str, object]] = []
    for sub_issue in request.sub_issues:
        created = _create_issue(
            _sub_issue_input(parent_issue.team.id, parent_issue.id, sub_issue), user_id
        )
        if created is not None:
            created_issues.append(created)

    return {
        "parent": request.parent_identifier or parent_ref,
        "created_count": len(created_issues),
        "sub_issues": created_issues,
    }


def _run_create_issue_relation(
    request: CreateIssueRelationInput, user_id: str
) -> dict[str, object]:
    linear_type = _RELATION_TYPES[request.relation_type]

    create_result = graphql_request(
        MUTATION_CREATE_RELATION,
        LinearIssueRelationCreateVariables(
            issue_id=request.issue_id,
            related_issue_id=request.related_issue_id,
            type=linear_type,
        ),
        user_id,
        LinearIssueRelationCreateData,
    ).issue_relation_create
    if not create_result.success or create_result.issue_relation is None:
        raise RuntimeError("Failed to create relation")

    return {
        "relation": {
            "id": create_result.issue_relation.id,
            "type": request.relation_type,
            "from_issue": request.issue_id,
            "to_issue": request.related_issue_id,
        },
    }


def _run_get_issue_activity(request: GetIssueActivityInput, user_id: str) -> dict[str, object]:
    issue_id = request.issue_id

    if not issue_id and request.issue_identifier:
        parts = request.issue_identifier.split("-")
        if len(parts) == 2:
            try:
                float(parts[1])
                issue_id = _fetch_issue(request.issue_identifier, user_id).id
            except ValueError:
                pass

    if not issue_id:
        raise ValueError("Could not resolve issue")

    history = graphql_request(
        QUERY_ISSUE_HISTORY,
        LinearIssueHistoryVariables(issue_id=issue_id, first=request.limit),
        user_id,
        LinearIssueHistoryData,
    ).issue.history.nodes

    activities = [
        entry
        for h in history
        if (entry := _history_entry(h, "change_type", system_actor="System")) is not None
    ]

    return {
        "issue": request.issue_identifier or issue_id,
        "activity_count": len(activities),
        "activities": activities,
    }


def _run_get_active_sprint(request: GetActiveSprintInput, user_id: str) -> dict[str, object]:
    cycles = graphql_request(QUERY_ACTIVE_CYCLES, None, user_id, LinearCyclesData).cycles.nodes

    if request.team_id:
        cycles = [c for c in cycles if c.team.id == request.team_id]

    limit = request.issues_per_state_limit
    sprints: list[dict[str, object]] = []
    for cycle in cycles:
        issues = cycle.issues.nodes
        counts = dict.fromkeys(_SPRINT_STATE_TYPES, 0)
        in_progress: list[dict[str, object]] = []
        todo: list[dict[str, object]] = []

        for issue in issues:
            state_type = issue.state.type.lower() if issue.state.type else "unstarted"
            if state_type not in counts:
                continue
            counts[state_type] += 1
            line: dict[str, object] = {
                "identifier": issue.identifier,
                "title": issue.title,
                "priority": priority_to_str(issue.priority),
                "assignee": issue.assignee.name if issue.assignee else None,
            }
            if state_type == "started":
                in_progress.append(line)
            elif state_type == "unstarted":
                todo.append(line)

        sprints.append(
            {
                "id": cycle.id,
                "name": cycle.name,
                "number": cycle.number,
                "team": cycle.team.name,
                "team_key": cycle.team.key,
                "starts_at": cycle.starts_at,
                "ends_at": cycle.ends_at,
                "progress": round(cycle.progress * 100, 1),
                "total_issues": len(issues),
                "issues_by_state": counts,
                "in_progress": in_progress[:limit],
                "todo": todo[:limit],
            }
        )

    return {"sprint_count": len(sprints), "sprints": sprints}


def _run_bulk_update_issues(request: BulkUpdateIssuesInput, user_id: str) -> dict[str, object]:
    if not request.issue_ids:
        raise ValueError("No issue IDs provided")

    input_data = LinearIssueUpdateInput()
    if request.state_id is not None:
        input_data.state_id = request.state_id
    if request.priority is not None:
        input_data.priority = request.priority
    if request.assignee_id is not None:
        input_data.assignee_id = request.assignee_id or None
    if request.cycle_id is not None:
        input_data.cycle_id = request.cycle_id or None
    if request.project_id is not None:
        input_data.project_id = request.project_id or None
    if request.labels_to_add:
        input_data.label_ids = request.labels_to_add

    if not input_data.model_fields_set:
        raise ValueError("No updates specified")

    update_result = graphql_request(
        MUTATION_UPDATE_ISSUES,
        LinearIssueBatchUpdateVariables(issue_ids=request.issue_ids, input=input_data),
        user_id,
        LinearIssueBatchUpdateData,
    ).issue_batch_update
    if not update_result.success:
        raise RuntimeError("Batch update failed")

    return {
        "updated_count": len(update_result.issues),
        "updated_issues": [{"id": i.id, "identifier": i.identifier} for i in update_result.issues],
    }


def _run_get_notifications(request: GetNotificationsInput, user_id: str) -> dict[str, object]:
    notifications = graphql_request(
        QUERY_NOTIFICATIONS,
        LinearFirstVariables(first=request.limit),
        user_id,
        LinearNotificationsData,
    ).notifications.nodes

    formatted: list[dict[str, object]] = []
    for n in notifications:
        is_read = n.read_at is not None

        # Filter by read status if not including read
        if not request.include_read and is_read:
            continue

        formatted.append(
            {
                "id": n.id,
                "type": n.type,
                "created_at": n.created_at,
                "read": is_read,
                "issue": {"identifier": n.issue.identifier, "title": n.issue.title}
                if n.issue
                else None,
                "actor": n.actor.name if n.actor else None,
            }
        )

    return {"count": len(formatted), "notifications": formatted}


def _run_get_workspace_context(user_id: str) -> dict[str, object]:
    viewer = graphql_request(QUERY_VIEWER, None, user_id, LinearViewerData).viewer
    assigned_count = len(viewer.assigned_issues.nodes)

    teams = graphql_request(QUERY_TEAMS, None, user_id, LinearTeamsData).teams.nodes

    my_issues = graphql_request(
        QUERY_MY_ISSUES,
        LinearMyIssuesVariables(assignee_id=viewer.id, include_completed=True, first=50),
        user_id,
        LinearIssuesData,
    ).issues.nodes

    today = _user_local_today()
    overdue: list[dict[str, object]] = []
    high_priority: list[dict[str, object]] = []
    sla_at_risk: list[dict[str, object]] = []

    for issue in my_issues:
        if issue.state.type in _CLOSED_STATE_TYPES:
            continue

        due_date = _parse_due_date(issue.due_date)
        if due_date and due_date < today:
            overdue.append(format_issue_summary(issue))

        if issue.priority in _URGENT_PRIORITIES:
            high_priority.append(format_issue_summary(issue))

        if issue.sla_breaches_at:
            sla_at_risk.append(format_issue_summary(issue))

    return {
        "user": {
            "id": viewer.id,
            "name": viewer.name,
            "email": viewer.email,
            "assigned_issue_count": assigned_count,
        },
        "teams": [
            {
                "id": t.id,
                "name": t.name,
                "key": t.key,
                "active_cycle": t.active_cycle.name if t.active_cycle else None,
                "cycle_progress": round(t.active_cycle.progress * 100, 1)
                if t.active_cycle
                else None,
            }
            for t in teams
        ],
        "urgent_items": {
            "overdue": overdue[:5],
            "high_priority": high_priority[:5],
            "sla_at_risk": sla_at_risk[:3],
        },
    }


def _run_gather_context(user_id: str) -> dict[str, object]:
    viewer = graphql_request(QUERY_VIEWER, None, user_id, LinearViewerData).viewer

    teams = graphql_request(QUERY_TEAMS, None, user_id, LinearTeamsData).teams.nodes

    my_issues = graphql_request(
        QUERY_MY_ISSUES,
        LinearMyIssuesVariables(assignee_id=viewer.id, include_completed=True, first=50),
        user_id,
        LinearIssuesData,
    ).issues.nodes

    today = _user_local_today()
    overdue: list[dict[str, object]] = []
    high_priority: list[dict[str, object]] = []

    for issue in my_issues:
        if issue.state.type in _CLOSED_STATE_TYPES:
            continue
        due_date = _parse_due_date(issue.due_date)
        if due_date and due_date < today:
            overdue.append(format_issue_summary(issue))
        if issue.priority in _URGENT_PRIORITIES:
            high_priority.append(format_issue_summary(issue))

    return {
        "user": {
            "id": viewer.id,
            "name": viewer.name,
            "email": viewer.email,
        },
        "teams": [{"id": t.id, "name": t.name, "key": t.key} for t in teams],
        "urgent_items": {
            "overdue": overdue[:5],
            "high_priority": high_priority[:5],
        },
    }


def _register_lookup_and_create_tools(composio: Composio) -> None:
    """Register the resolve/read/search/create Linear custom tools."""

    @composio.tools.custom_tool(toolkit="linear")
    @with_doc(CUSTOM_RESOLVE_CONTEXT_DOC)
    def CUSTOM_RESOLVE_CONTEXT(
        request: ResolveContextInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Resolve fuzzy names to Linear IDs."""
        del execute_request  # unused: framework-mandated custom-tool signature
        return _run_resolve_context(request, _user_id(auth_credentials))

    @composio.tools.custom_tool(toolkit="linear")
    @with_doc(CUSTOM_GET_MY_TASKS_DOC)
    def CUSTOM_GET_MY_TASKS(
        request: GetMyTasksInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Get the current user's assigned issues."""
        del execute_request  # unused: framework-mandated custom-tool signature
        return _run_get_my_tasks(request, _user_id(auth_credentials))

    @composio.tools.custom_tool(toolkit="linear")
    @with_doc(CUSTOM_SEARCH_ISSUES_DOC)
    def CUSTOM_SEARCH_ISSUES(
        request: SearchIssuesInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Search issues using natural language queries."""
        del execute_request  # unused: framework-mandated custom-tool signature
        return _run_search_issues(request, _user_id(auth_credentials))

    @composio.tools.custom_tool(toolkit="linear")
    @with_doc(CUSTOM_GET_ISSUE_FULL_CONTEXT_DOC)
    def CUSTOM_GET_ISSUE_FULL_CONTEXT(
        request: GetIssueFullContextInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Get complete issue details in one call."""
        del execute_request  # unused: framework-mandated custom-tool signature
        return _run_get_issue_full_context(request, _user_id(auth_credentials))

    @composio.tools.custom_tool(toolkit="linear")
    @with_doc(CUSTOM_CREATE_ISSUE_DOC)
    def CUSTOM_CREATE_ISSUE(
        request: CreateIssueInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Create an issue with full field support and optional sub-issues."""
        del execute_request  # unused: framework-mandated custom-tool signature
        return _run_create_issue(request, _user_id(auth_credentials))

    @composio.tools.custom_tool(toolkit="linear")
    @with_doc(CUSTOM_CREATE_SUB_ISSUES_DOC)
    def CUSTOM_CREATE_SUB_ISSUES(
        request: CreateSubIssuesInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Create multiple sub-issues under a parent issue."""
        del execute_request  # unused: framework-mandated custom-tool signature
        return _run_create_sub_issues(request, _user_id(auth_credentials))

    @composio.tools.custom_tool(toolkit="linear")
    @with_doc(CUSTOM_CREATE_ISSUE_RELATION_DOC)
    def CUSTOM_CREATE_ISSUE_RELATION(
        request: CreateIssueRelationInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Create a relationship between two issues."""
        del execute_request  # unused: framework-mandated custom-tool signature
        return _run_create_issue_relation(request, _user_id(auth_credentials))


def _register_activity_and_workspace_tools(composio: Composio) -> None:
    """Register the activity/sprint/bulk-update/workspace Linear custom tools."""

    @composio.tools.custom_tool(toolkit="linear")
    @with_doc(CUSTOM_GET_ISSUE_ACTIVITY_DOC)
    def CUSTOM_GET_ISSUE_ACTIVITY(
        request: GetIssueActivityInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Get the change history for an issue."""
        del execute_request  # unused: framework-mandated custom-tool signature
        return _run_get_issue_activity(request, _user_id(auth_credentials))

    @composio.tools.custom_tool(toolkit="linear")
    @with_doc(CUSTOM_GET_ACTIVE_SPRINT_DOC)
    def CUSTOM_GET_ACTIVE_SPRINT(
        request: GetActiveSprintInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Get the current/active sprint context."""
        del execute_request  # unused: framework-mandated custom-tool signature
        return _run_get_active_sprint(request, _user_id(auth_credentials))

    @composio.tools.custom_tool(toolkit="linear")
    @with_doc(CUSTOM_BULK_UPDATE_ISSUES_DOC)
    def CUSTOM_BULK_UPDATE_ISSUES(
        request: BulkUpdateIssuesInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Batch update multiple issues at once."""
        del execute_request  # unused: framework-mandated custom-tool signature
        return _run_bulk_update_issues(request, _user_id(auth_credentials))

    @composio.tools.custom_tool(toolkit="linear")
    @with_doc(CUSTOM_GET_NOTIFICATIONS_DOC)
    def CUSTOM_GET_NOTIFICATIONS(
        request: GetNotificationsInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Get the current user's notifications."""
        del execute_request  # unused: framework-mandated custom-tool signature
        return _run_get_notifications(request, _user_id(auth_credentials))

    @composio.tools.custom_tool(toolkit="linear")
    @with_doc(CUSTOM_GET_WORKSPACE_CONTEXT_DOC)
    def CUSTOM_GET_WORKSPACE_CONTEXT(
        request: GetWorkspaceContextInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Get full workspace context for session initialization."""
        del request, execute_request  # unused: framework-mandated custom-tool signature
        return _run_get_workspace_context(_user_id(auth_credentials))

    @composio.tools.custom_tool(toolkit="linear")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Get Linear workspace context snapshot: current user, teams, and urgent items.

        Zero required parameters. Returns full workspace state for session initialization.
        """
        del request, execute_request  # unused: framework-mandated custom-tool signature
        return _run_gather_context(_user_id(auth_credentials))


def register_linear_custom_tools(composio: Composio) -> list[str]:
    """Register Linear tools as Composio custom tools."""
    _register_lookup_and_create_tools(composio)
    _register_activity_and_workspace_tools(composio)
    return [
        "LINEAR_CUSTOM_RESOLVE_CONTEXT",
        "LINEAR_CUSTOM_GET_MY_TASKS",
        "LINEAR_CUSTOM_SEARCH_ISSUES",
        "LINEAR_CUSTOM_GET_ISSUE_FULL_CONTEXT",
        "LINEAR_CUSTOM_CREATE_ISSUE",
        "LINEAR_CUSTOM_CREATE_SUB_ISSUES",
        "LINEAR_CUSTOM_CREATE_ISSUE_RELATION",
        "LINEAR_CUSTOM_GET_ISSUE_ACTIVITY",
        "LINEAR_CUSTOM_GET_ACTIVE_SPRINT",
        "LINEAR_CUSTOM_BULK_UPDATE_ISSUES",
        "LINEAR_CUSTOM_GET_NOTIFICATIONS",
        "LINEAR_CUSTOM_GET_WORKSPACE_CONTEXT",
        "LINEAR_CUSTOM_GATHER_CONTEXT",
    ]
