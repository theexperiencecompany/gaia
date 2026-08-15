"""Linear tools using Composio custom tool infrastructure.

Linear GraphQL calls go through `linear_utils.graphql_request`, which routes
through Composio's proxy via `proxy_request_sync`. The proxy attaches the
user's OAuth token server-side; tools only need `user_id` from
`auth_credentials`.

Note: Errors are raised as exceptions - Composio wraps responses automatically.
"""

import contextlib
from datetime import UTC, date, datetime, timedelta
from typing import Any

from composio import Composio
from composio.types import ExecuteRequestFn
from langgraph.config import get_config

from app.decorators import with_doc
from app.models.common_models import GatherContextInput
from app.models.linear_models import (
    BulkUpdateIssuesInput,
    CreateIssueInput,
    CreateIssueRelationInput,
    CreateSubIssuesInput,
    GetActiveSprintInput,
    GetIssueActivityInput,
    GetIssueFullContextInput,
    GetMyTasksInput,
    GetNotificationsInput,
    GetWorkspaceContextInput,
    ResolveContextInput,
    SearchIssuesInput,
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
from app.utils.json_helpers import (
    bool_bag,
    dict_bag,
    float_bag,
    list_bag,
    text_bag,
    text_opt_bag,
)
from app.utils.linear_utils import (
    MUTATION_CREATE_ISSUE,
    MUTATION_CREATE_RELATION,
    MUTATION_UPDATE_ISSUES,
    QUERY_ACTIVE_CYCLES,
    QUERY_ISSUE_BY_ID,
    QUERY_ISSUE_BY_IDENTIFIER,
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
    history_label_names,
    priority_to_int,
    priority_to_str,
)
from app.utils.timezone import home_timezone_from_config


def _nodes(data: dict[str, object], key: str) -> list[dict[str, object]]:
    """The GraphQL ``key { nodes }`` list, checked (Linear API shape)."""
    return [n for n in list_bag(dict_bag(data, key), "nodes") if isinstance(n, dict)]


def _user_local_today() -> date:
    """Today's date in the user's home zone (from the agent config).

    Due-date filters ("today"/"overdue"/"this week") must use the user's local
    date, not the server's. Falls back to the UTC date outside an agent run.
    """
    try:
        return home_timezone_from_config(get_config()).now().date()
    except Exception:
        return datetime.now(UTC).date()


def register_linear_custom_tools(composio: Composio[Any, Any]) -> list[str]:  # type: ignore[explicit-any]
    """Register Linear tools as Composio custom tools."""

    @composio.tools.custom_tool(toolkit="linear")
    @with_doc(CUSTOM_RESOLVE_CONTEXT_DOC)
    def CUSTOM_RESOLVE_CONTEXT(
        request: ResolveContextInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Resolve fuzzy names to Linear IDs."""
        del execute_request  # unused: framework-mandated custom-tool signature
        result: dict[str, object] = {}

        viewer_data = graphql_request(QUERY_VIEWER, None, auth_credentials)
        viewer = dict_bag(viewer_data, "viewer")
        result["current_user"] = {
            "id": text_opt_bag(viewer, "id"),
            "name": text_opt_bag(viewer, "name"),
            "email": text_opt_bag(viewer, "email"),
        }

        if request.team_name:
            teams_data = graphql_request(QUERY_TEAMS, None, auth_credentials)
            teams = _nodes(teams_data, "teams")
            result["teams"] = fuzzy_match(request.team_name, teams, "name", limit=3)

        if request.user_name:
            users_data = graphql_request(QUERY_USERS, None, auth_credentials)
            users = _nodes(users_data, "users")
            active_users = [u for u in users if bool(u.get("active", True))]
            result["users"] = fuzzy_match(request.user_name, active_users, "name", limit=3)

        if request.label_names:
            if request.team_id:
                labels_data = graphql_request(
                    QUERY_LABELS, {"teamId": request.team_id}, auth_credentials
                )
            else:
                labels_data = graphql_request(QUERY_LABELS_ALL, None, auth_credentials)
            labels = _nodes(labels_data, "issueLabels")
            matched_labels = []
            for label_name in request.label_names[:3]:
                matches = fuzzy_match(label_name, labels, "name", limit=1)
                matched_labels.extend(matches)
            result["labels"] = matched_labels[:4]

        if request.project_name:
            projects_data = graphql_request(QUERY_PROJECTS, None, auth_credentials)
            projects = _nodes(projects_data, "projects")
            result["projects"] = fuzzy_match(request.project_name, projects, "name", limit=3)

        if request.state_name and request.team_id:
            states_data = graphql_request(
                QUERY_STATES, {"teamId": request.team_id}, auth_credentials
            )
            states = _nodes(states_data, "workflowStates")
            result["states"] = fuzzy_match(request.state_name, states, "name", limit=3)

        return {"data": result}

    @composio.tools.custom_tool(toolkit="linear")
    @with_doc(CUSTOM_GET_MY_TASKS_DOC)
    def CUSTOM_GET_MY_TASKS(
        request: GetMyTasksInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Get the current user's assigned issues."""
        del execute_request  # unused: framework-mandated custom-tool signature
        viewer_data = graphql_request(QUERY_VIEWER, None, auth_credentials)
        viewer_id = text_opt_bag(dict_bag(viewer_data, "viewer"), "id")

        if not viewer_id:
            raise ValueError("Could not get current user")

        issues_data = graphql_request(
            QUERY_MY_ISSUES,
            {
                "assigneeId": viewer_id,
                "includeCompleted": not request.include_completed,
                "first": min(request.limit * 2, 100),
            },
            auth_credentials,
        )

        issues = _nodes(issues_data, "issues")
        today = _user_local_today()
        week_end = today + timedelta(days=7)

        filtered = []
        for issue in issues:
            due_str = text_opt_bag(issue, "dueDate")
            due_date = None
            if due_str:
                with contextlib.suppress(ValueError):
                    due_date = datetime.fromisoformat(due_str).date()

            priority = issue.get("priority", 0)
            state_type = text_bag(dict_bag(issue, "state"), "type", "")

            if not request.include_completed and state_type in [
                "completed",
                "canceled",
            ]:
                continue

            if request.filter == "today":
                if due_date == today:
                    filtered.append(issue)
            elif request.filter == "this_week":
                if due_date and today <= due_date <= week_end:
                    filtered.append(issue)
            elif request.filter == "overdue":
                if due_date and due_date < today:
                    filtered.append(issue)
            elif request.filter == "high_priority":
                if priority in [1, 2]:
                    filtered.append(issue)
            else:
                filtered.append(issue)

        def sort_key(issue: dict[str, object]) -> tuple[float, str]:
            p = float_bag(issue, "priority", 99.0)
            due = text_bag(issue, "dueDate", "9999-12-31")
            return (p, due)

        filtered.sort(key=sort_key)
        formatted = [format_issue_summary(i) for i in filtered[: request.limit]]

        return {
            "filter": request.filter,
            "count": len(formatted),
            "issues": formatted,
        }

    @composio.tools.custom_tool(toolkit="linear")
    @with_doc(CUSTOM_SEARCH_ISSUES_DOC)
    def CUSTOM_SEARCH_ISSUES(
        request: SearchIssuesInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Search issues using natural language queries."""
        del execute_request  # unused: framework-mandated custom-tool signature
        issues_data = graphql_request(
            QUERY_SEARCH_ISSUES,
            {"query": request.query, "first": min(request.limit * 2, 100)},
            auth_credentials,
        )

        issues = _nodes(issues_data, "searchIssues")
        filtered = []

        for issue in issues:
            if request.team_id:
                if text_opt_bag(dict_bag(issue, "team"), "id") != request.team_id:
                    continue
            if request.state_filter:
                state_type = text_bag(dict_bag(issue, "state"), "type", "").lower()
                if state_type != request.state_filter:
                    continue
            if request.assignee_id:
                if text_opt_bag(dict_bag(issue, "assignee"), "id") != request.assignee_id:
                    continue
            if request.priority_filter:
                priority = issue.get("priority", 0)
                expected = priority_to_int(request.priority_filter)
                if priority != expected:
                    continue
            if request.created_after:
                created = text_bag(issue, "createdAt")
                if created < request.created_after:
                    continue
            filtered.append(issue)

        formatted = [format_issue_summary(i) for i in filtered[: request.limit]]

        return {
            "query": request.query,
            "count": len(formatted),
            "issues": formatted,
        }

    @composio.tools.custom_tool(toolkit="linear")
    @with_doc(CUSTOM_GET_ISSUE_FULL_CONTEXT_DOC)
    def CUSTOM_GET_ISSUE_FULL_CONTEXT(
        request: GetIssueFullContextInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Get complete issue details in one call."""
        del execute_request  # unused: framework-mandated custom-tool signature
        if not request.issue_id and not request.issue_identifier:
            raise ValueError("Provide either issue_id or issue_identifier")

        issue = None

        if request.issue_id:
            data = graphql_request(QUERY_ISSUE_BY_ID, {"id": request.issue_id}, auth_credentials)
            issue = dict_bag(data, "issue")
        elif request.issue_identifier:
            parts = request.issue_identifier.split("-")
            if len(parts) != 2:
                raise ValueError(f"Invalid identifier format: {request.issue_identifier}")
            try:
                float(parts[1])
            except ValueError as e:
                raise ValueError(f"Invalid issue number in: {request.issue_identifier}") from e

            data = graphql_request(
                QUERY_ISSUE_BY_IDENTIFIER,
                {"identifier": request.issue_identifier},
                auth_credentials,
            )
            issue = dict_bag(data, "issue")

        if not issue:
            raise ValueError(f"Issue not found: {request.issue_id or request.issue_identifier}")

        result: dict[str, object] = {
            "id": text_bag(issue, "id"),
            "identifier": text_bag(issue, "identifier"),
            "title": text_bag(issue, "title"),
            "description": text_bag(issue, "description"),
            "priority": priority_to_str(float_bag(issue, "priority")),
            "state": text_opt_bag(dict_bag(issue, "state"), "name"),
            "dueDate": text_opt_bag(issue, "dueDate"),
            "estimate": float_bag(issue, "estimate"),
            "team": text_opt_bag(dict_bag(issue, "team"), "name"),
            "project": text_opt_bag(dict_bag(issue, "project"), "name"),
            "cycle": text_opt_bag(dict_bag(issue, "cycle"), "name"),
            "assignee": text_opt_bag(dict_bag(issue, "assignee"), "name"),
            "creator": text_opt_bag(dict_bag(issue, "creator"), "name"),
        }

        parent = dict_bag(issue, "parent")
        if parent:
            result["parent"] = {
                "identifier": text_opt_bag(parent, "identifier"),
                "title": text_opt_bag(parent, "title"),
            }

        children = _nodes(issue, "children")
        if children:
            result["sub_issues"] = [
                {
                    "identifier": text_bag(c, "identifier"),
                    "title": text_opt_bag(c, "title"),
                    "state": text_opt_bag(dict_bag(c, "state"), "name"),
                }
                for c in children
            ]

        relations = _nodes(issue, "relations")
        if relations:
            result["relations"] = [
                {
                    "type": text_opt_bag(r, "type"),
                    "issue": {
                        "identifier": text_opt_bag(dict_bag(r, "relatedIssue"), "identifier"),
                        "title": text_opt_bag(dict_bag(r, "relatedIssue"), "title"),
                    },
                }
                for r in relations
            ]

        comments = _nodes(issue, "comments")
        if comments:
            result["comments"] = [
                {
                    "author": text_opt_bag(dict_bag(c, "user"), "name"),
                    "body": text_opt_bag(c, "body"),
                    "createdAt": text_opt_bag(c, "createdAt"),
                }
                for c in comments
            ]

        history = _nodes(issue, "history")
        if history:
            activity: list[dict[str, object]] = []
            result["activity"] = activity
            for h in history:
                entry: dict[str, object] = {
                    "timestamp": text_opt_bag(h, "createdAt"),
                    "actor": text_opt_bag(dict_bag(h, "actor"), "name"),
                }
                if h.get("fromState") or h.get("toState"):
                    entry["change"] = "state"
                    entry["from"] = text_opt_bag(dict_bag(h, "fromState"), "name")
                    entry["to"] = text_opt_bag(dict_bag(h, "toState"), "name")
                elif h.get("fromAssignee") or h.get("toAssignee"):
                    entry["change"] = "assignee"
                    entry["from"] = text_opt_bag(dict_bag(h, "fromAssignee"), "name")
                    entry["to"] = text_opt_bag(dict_bag(h, "toAssignee"), "name")
                elif history_label_names(h.get("addedLabels")):
                    entry["change"] = "labels_added"
                    entry["labels"] = history_label_names(h.get("addedLabels"))
                elif history_label_names(h.get("removedLabels")):
                    entry["change"] = "labels_removed"
                    entry["labels"] = history_label_names(h.get("removedLabels"))
                else:
                    continue
                activity.append(entry)

        attachments = _nodes(issue, "attachments")
        if attachments:
            result["attachments"] = [
                {"title": text_opt_bag(a, "title"), "url": text_opt_bag(a, "url")}
                for a in attachments
            ]

        return {"issue": result}

    @composio.tools.custom_tool(toolkit="linear")
    @with_doc(CUSTOM_CREATE_ISSUE_DOC)
    def CUSTOM_CREATE_ISSUE(
        request: CreateIssueInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Create an issue with full field support and optional sub-issues."""
        del execute_request  # unused: framework-mandated custom-tool signature
        # Build input data
        input_data: dict[str, object] = {
            "teamId": request.team_id,
            "title": request.title,
        }

        if request.description:
            input_data["description"] = request.description
        if request.assignee_id:
            input_data["assigneeId"] = request.assignee_id
        if request.priority is not None:
            input_data["priority"] = request.priority
        if request.state_id:
            input_data["stateId"] = request.state_id
        if request.label_ids:
            input_data["labelIds"] = request.label_ids
        if request.project_id:
            input_data["projectId"] = request.project_id
        if request.cycle_id:
            input_data["cycleId"] = request.cycle_id
        if request.due_date:
            input_data["dueDate"] = request.due_date
        if request.estimate is not None:
            input_data["estimate"] = request.estimate
        if request.parent_id:
            input_data["parentId"] = request.parent_id

        # Create the main issue
        result = graphql_request(MUTATION_CREATE_ISSUE, {"input": input_data}, auth_credentials)
        create_result = dict_bag(result, "issueCreate")
        if not bool_bag(create_result, "success"):
            raise RuntimeError("Failed to create issue")

        created = dict_bag(create_result, "issue")
        response: dict[str, object] = {
            "issue": {
                "id": text_opt_bag(created, "id"),
                "identifier": text_opt_bag(created, "identifier"),
                "title": text_opt_bag(created, "title"),
                "url": text_opt_bag(created, "url"),
            },
        }

        # Create sub-issues if provided
        if request.sub_issues:
            parent_id = text_opt_bag(created, "id")
            created_subs = []
            errors = []

            for sub in request.sub_issues:
                sub_input: dict[str, object] = {
                    "teamId": request.team_id,
                    "title": sub.title,
                    "parentId": parent_id,
                }
                if sub.description:
                    sub_input["description"] = sub.description
                if sub.assignee_id:
                    sub_input["assigneeId"] = sub.assignee_id
                if sub.priority is not None:
                    sub_input["priority"] = sub.priority

                sub_result = graphql_request(
                    MUTATION_CREATE_ISSUE, {"input": sub_input}, auth_credentials
                )
                sub_create = dict_bag(sub_result, "issueCreate")
                if bool_bag(sub_create, "success"):
                    sub_issue = dict_bag(sub_create, "issue")
                    created_subs.append(
                        {
                            "id": text_opt_bag(sub_issue, "id"),
                            "identifier": text_opt_bag(sub_issue, "identifier"),
                            "title": text_opt_bag(sub_issue, "title"),
                        }
                    )
                else:
                    errors.append({"title": sub.title, "error": "Failed to create"})

            response["sub_issues"] = created_subs
            if errors:
                response["sub_issue_errors"] = errors

        return response

    @composio.tools.custom_tool(toolkit="linear")
    @with_doc(CUSTOM_CREATE_SUB_ISSUES_DOC)
    def CUSTOM_CREATE_SUB_ISSUES(
        request: CreateSubIssuesInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Create multiple sub-issues under a parent issue."""
        del execute_request  # unused: framework-mandated custom-tool signature
        parent_id = request.parent_issue_id

        if not parent_id and request.parent_identifier:
            parts = request.parent_identifier.split("-")
            if len(parts) != 2:
                raise ValueError(f"Invalid parent identifier: {request.parent_identifier}")
            team_key = parts[0]
            try:
                number = float(parts[1])
            except ValueError as e:
                raise ValueError(f"Invalid issue number in: {request.parent_identifier}") from e

            data = graphql_request(
                QUERY_ISSUE_BY_IDENTIFIER,
                {"teamKey": team_key, "number": number},
                auth_credentials,
            )
            teams = _nodes(data, "teams")
            if teams and dict_bag(teams[0], "issue"):
                parent_id = text_opt_bag(dict_bag(teams[0], "issue"), "id")

        if not parent_id:
            raise ValueError("Could not resolve parent issue")

        parent_data = graphql_request(QUERY_ISSUE_BY_ID, {"id": parent_id}, auth_credentials)
        parent_issue = dict_bag(parent_data, "issue")
        if not parent_issue:
            raise ValueError("Parent issue not found")

        team_id = text_opt_bag(dict_bag(parent_issue, "team"), "id")
        if not team_id:
            raise ValueError("Could not get parent's team")

        created_issues = []
        errors = []

        for sub_issue in request.sub_issues:
            input_data: dict[str, object] = {
                "teamId": team_id,
                "title": sub_issue.title,
                "parentId": parent_id,
            }
            if sub_issue.description:
                input_data["description"] = sub_issue.description
            if sub_issue.assignee_id:
                input_data["assigneeId"] = sub_issue.assignee_id
            if sub_issue.priority is not None:
                input_data["priority"] = sub_issue.priority

            result = graphql_request(MUTATION_CREATE_ISSUE, {"input": input_data}, auth_credentials)
            create_result = dict_bag(result, "issueCreate")
            if bool_bag(create_result, "success"):
                created = dict_bag(create_result, "issue")
                created_issues.append(
                    {
                        "id": text_opt_bag(created, "id"),
                        "identifier": text_opt_bag(created, "identifier"),
                        "title": text_opt_bag(created, "title"),
                    }
                )
            else:
                errors.append({"title": sub_issue.title, "error": "Failed to create"})

        return {
            "parent": request.parent_identifier or parent_id,
            "created_count": len(created_issues),
            "sub_issues": created_issues,
        }

    @composio.tools.custom_tool(toolkit="linear")
    @with_doc(CUSTOM_CREATE_ISSUE_RELATION_DOC)
    def CUSTOM_CREATE_ISSUE_RELATION(
        request: CreateIssueRelationInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Create a relationship between two issues."""
        del execute_request  # unused: framework-mandated custom-tool signature
        type_mapping = {
            "blocks": "blocks",
            "is_blocked_by": "blocked_by",
            "relates_to": "related",
            "duplicates": "duplicate",
        }
        linear_type = type_mapping.get(request.relation_type, request.relation_type)

        result = graphql_request(
            MUTATION_CREATE_RELATION,
            {
                "issueId": request.issue_id,
                "relatedIssueId": request.related_issue_id,
                "type": linear_type,
            },
            auth_credentials,
        )

        create_result = dict_bag(result, "issueRelationCreate")
        if not bool_bag(create_result, "success"):
            raise RuntimeError("Failed to create relation")

        relation = dict_bag(create_result, "issueRelation")
        return {
            "relation": {
                "id": text_opt_bag(relation, "id"),
                "type": request.relation_type,
                "from_issue": request.issue_id,
                "to_issue": request.related_issue_id,
            },
        }

    @composio.tools.custom_tool(toolkit="linear")
    @with_doc(CUSTOM_GET_ISSUE_ACTIVITY_DOC)
    def CUSTOM_GET_ISSUE_ACTIVITY(
        request: GetIssueActivityInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Get the change history for an issue."""
        del execute_request  # unused: framework-mandated custom-tool signature
        issue_id = request.issue_id

        if not issue_id and request.issue_identifier:
            parts = request.issue_identifier.split("-")
            if len(parts) == 2:
                try:
                    float(parts[1])
                    data = graphql_request(
                        QUERY_ISSUE_BY_IDENTIFIER,
                        {"identifier": request.issue_identifier},
                        auth_credentials,
                    )
                    issue = dict_bag(data, "issue")
                    if issue:
                        issue_id = text_bag(issue, "id")
                except ValueError:
                    pass

        if not issue_id:
            raise ValueError("Could not resolve issue")

        data = graphql_request(
            QUERY_ISSUE_HISTORY,
            {"issueId": issue_id, "first": request.limit},
            auth_credentials,
        )
        history = _nodes(dict_bag(data, "issue"), "history")

        activities = []
        for h in history:
            entry: dict[str, object] = {
                "timestamp": text_opt_bag(h, "createdAt"),
                "actor": text_opt_bag(dict_bag(h, "actor"), "name") if h.get("actor") else "System",
            }
            if h.get("fromState") or h.get("toState"):
                entry["change_type"] = "state"
                entry["from"] = text_opt_bag(dict_bag(h, "fromState"), "name")
                entry["to"] = text_opt_bag(dict_bag(h, "toState"), "name")
            elif h.get("fromAssignee") or h.get("toAssignee"):
                entry["change_type"] = "assignee"
                entry["from"] = (
                    text_opt_bag(dict_bag(h, "fromAssignee"), "name")
                    if h.get("fromAssignee")
                    else None
                )
                entry["to"] = (
                    text_opt_bag(dict_bag(h, "toAssignee"), "name") if h.get("toAssignee") else None
                )
            elif h.get("fromPriority") is not None or h.get("toPriority") is not None:
                entry["change_type"] = "priority"
                entry["from"] = priority_to_str(float_bag(h, "fromPriority"))
                entry["to"] = priority_to_str(float_bag(h, "toPriority"))
            elif history_label_names(h.get("addedLabels")):
                entry["change_type"] = "labels_added"
                entry["labels"] = history_label_names(h.get("addedLabels"))
            elif history_label_names(h.get("removedLabels")):
                entry["change_type"] = "labels_removed"
                entry["labels"] = history_label_names(h.get("removedLabels"))
            else:
                continue
            activities.append(entry)

        return {
            "issue": request.issue_identifier or issue_id,
            "activity_count": len(activities),
            "activities": activities,
        }

    @composio.tools.custom_tool(toolkit="linear")
    @with_doc(CUSTOM_GET_ACTIVE_SPRINT_DOC)
    def CUSTOM_GET_ACTIVE_SPRINT(
        request: GetActiveSprintInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Get the current/active sprint context."""
        del execute_request  # unused: framework-mandated custom-tool signature
        data = graphql_request(QUERY_ACTIVE_CYCLES, None, auth_credentials)
        cycles = _nodes(data, "cycles")

        if request.team_id:
            cycles = [
                c for c in cycles if text_opt_bag(dict_bag(c, "team"), "id") == request.team_id
            ]

        limit = request.issues_per_state_limit
        sprints = []
        for cycle in cycles:
            issues = _nodes(cycle, "issues")
            by_state: dict[str, list[dict[str, object]]] = {
                "backlog": [],
                "unstarted": [],
                "started": [],
                "completed": [],
            }

            for issue in issues:
                state_type = text_bag(dict_bag(issue, "state"), "type", "unstarted").lower()
                if state_type in by_state:
                    by_state[state_type].append(
                        {
                            "identifier": text_opt_bag(issue, "identifier"),
                            "title": text_opt_bag(issue, "title"),
                            "priority": priority_to_str(float_bag(issue, "priority")),
                            "assignee": text_opt_bag(dict_bag(issue, "assignee"), "name")
                            if issue.get("assignee")
                            else None,
                        }
                    )

            sprints.append(
                {
                    "id": text_opt_bag(cycle, "id"),
                    "name": text_opt_bag(cycle, "name"),
                    "number": float_bag(cycle, "number"),
                    "team": text_opt_bag(dict_bag(cycle, "team"), "name"),
                    "team_key": text_opt_bag(dict_bag(cycle, "team"), "key"),
                    "starts_at": text_opt_bag(cycle, "startsAt"),
                    "ends_at": text_opt_bag(cycle, "endsAt"),
                    "progress": round(float_bag(cycle, "progress") * 100, 1),
                    "total_issues": len(issues),
                    "issues_by_state": {k: len(v) for k, v in by_state.items()},
                    "in_progress": by_state["started"][:limit],
                    "todo": by_state["unstarted"][:limit],
                }
            )

        return {"sprint_count": len(sprints), "sprints": sprints}

    @composio.tools.custom_tool(toolkit="linear")
    @with_doc(CUSTOM_BULK_UPDATE_ISSUES_DOC)
    def CUSTOM_BULK_UPDATE_ISSUES(
        request: BulkUpdateIssuesInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Batch update multiple issues at once."""
        del execute_request  # unused: framework-mandated custom-tool signature
        if not request.issue_ids:
            raise ValueError("No issue IDs provided")

        input_data: dict[str, object] = {}
        if request.state_id is not None:
            input_data["stateId"] = request.state_id
        if request.priority is not None:
            input_data["priority"] = request.priority
        if request.assignee_id is not None:
            input_data["assigneeId"] = request.assignee_id if request.assignee_id else None
        if request.cycle_id is not None:
            input_data["cycleId"] = request.cycle_id if request.cycle_id else None
        if request.project_id is not None:
            input_data["projectId"] = request.project_id if request.project_id else None
        if request.labels_to_add:
            input_data["labelIds"] = request.labels_to_add

        if not input_data:
            raise ValueError("No updates specified")

        result = graphql_request(
            MUTATION_UPDATE_ISSUES,
            {"issueIds": request.issue_ids, "input": input_data},
            auth_credentials,
        )
        update_result = dict_bag(result, "issueBatchUpdate")
        if not bool_bag(update_result, "success"):
            raise RuntimeError("Batch update failed")

        updated = list_bag(update_result, "issues")
        return {
            "updated_count": len(updated),
            "updated_issues": [
                {"id": text_opt_bag(i, "id"), "identifier": text_opt_bag(i, "identifier")}
                for i in updated
                if isinstance(i, dict)
            ],
        }

    @composio.tools.custom_tool(toolkit="linear")
    @with_doc(CUSTOM_GET_NOTIFICATIONS_DOC)
    def CUSTOM_GET_NOTIFICATIONS(
        request: GetNotificationsInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Get the current user's notifications."""
        del execute_request  # unused: framework-mandated custom-tool signature
        data = graphql_request(
            QUERY_NOTIFICATIONS,
            {"first": request.limit},
            auth_credentials,
        )
        notifications = _nodes(data, "notifications")

        formatted = []
        for n in notifications:
            is_read = text_opt_bag(n, "readAt") is not None

            # Filter by read status if not including read
            if not request.include_read and is_read:
                continue

            formatted.append(
                {
                    "id": text_opt_bag(n, "id"),
                    "type": text_opt_bag(n, "type"),
                    "created_at": text_opt_bag(n, "createdAt"),
                    "read": is_read,
                    "issue": {
                        "identifier": text_opt_bag(dict_bag(n, "issue"), "identifier"),
                        "title": text_opt_bag(dict_bag(n, "issue"), "title"),
                    }
                    if dict_bag(n, "issue")
                    else None,
                    "actor": text_opt_bag(dict_bag(n, "actor"), "name") if n.get("actor") else None,
                }
            )

        return {"count": len(formatted), "notifications": formatted}

    @composio.tools.custom_tool(toolkit="linear")
    @with_doc(CUSTOM_GET_WORKSPACE_CONTEXT_DOC)
    def CUSTOM_GET_WORKSPACE_CONTEXT(
        request: GetWorkspaceContextInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Get full workspace context for session initialization."""
        del request, execute_request  # unused: framework-mandated custom-tool signature
        viewer_data = graphql_request(QUERY_VIEWER, None, auth_credentials)
        viewer = dict_bag(viewer_data, "viewer")
        assigned_count = len(list_bag(dict_bag(viewer, "assignedIssues"), "nodes"))

        teams_data = graphql_request(QUERY_TEAMS, None, auth_credentials)
        teams = _nodes(teams_data, "teams")

        issues_data = graphql_request(
            QUERY_MY_ISSUES,
            {"assigneeId": text_opt_bag(viewer, "id"), "includeCompleted": True, "first": 50},
            auth_credentials,
        )
        my_issues = _nodes(issues_data, "issues")

        today = _user_local_today()
        overdue = []
        high_priority = []
        sla_at_risk = []

        for issue in my_issues:
            state_type = text_bag(dict_bag(issue, "state"), "type", "")
            if state_type in ["completed", "canceled"]:
                continue

            due_str = text_opt_bag(issue, "dueDate")
            if due_str:
                try:
                    due_date = datetime.fromisoformat(due_str).date()
                    if due_date < today:
                        overdue.append(format_issue_summary(issue))
                except ValueError:
                    pass

            if float_bag(issue, "priority") in [1, 2]:
                high_priority.append(format_issue_summary(issue))

            if text_opt_bag(issue, "slaBreachesAt"):
                sla_at_risk.append(format_issue_summary(issue))

        return {
            "user": {
                "id": text_opt_bag(viewer, "id"),
                "name": text_opt_bag(viewer, "name"),
                "email": text_opt_bag(viewer, "email"),
                "assigned_issue_count": assigned_count,
            },
            "teams": [
                {
                    "id": text_opt_bag(t, "id"),
                    "name": text_opt_bag(t, "name"),
                    "key": text_opt_bag(t, "key"),
                    "active_cycle": text_opt_bag(dict_bag(t, "activeCycle"), "name")
                    if t.get("activeCycle")
                    else None,
                    "cycle_progress": round(
                        float_bag(dict_bag(t, "activeCycle"), "progress") * 100, 1
                    )
                    if t.get("activeCycle")
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
        viewer_data = graphql_request(QUERY_VIEWER, None, auth_credentials)
        viewer = dict_bag(viewer_data, "viewer")

        teams_data = graphql_request(QUERY_TEAMS, None, auth_credentials)
        teams = _nodes(teams_data, "teams")

        issues_data = graphql_request(
            QUERY_MY_ISSUES,
            {"assigneeId": text_opt_bag(viewer, "id"), "includeCompleted": True, "first": 50},
            auth_credentials,
        )
        my_issues = _nodes(issues_data, "issues")

        today = _user_local_today()
        overdue = []
        high_priority = []

        for issue in my_issues:
            state_type = text_bag(dict_bag(issue, "state"), "type", "")
            if state_type in ["completed", "canceled"]:
                continue
            due_str = text_opt_bag(issue, "dueDate")
            if due_str:
                try:
                    due_date = datetime.fromisoformat(due_str).date()
                    if due_date < today:
                        overdue.append(format_issue_summary(issue))
                except ValueError:
                    pass
            if float_bag(issue, "priority") in [1, 2]:
                high_priority.append(format_issue_summary(issue))

        return {
            "user": {
                "id": text_opt_bag(viewer, "id"),
                "name": text_opt_bag(viewer, "name"),
                "email": text_opt_bag(viewer, "email"),
            },
            "teams": [
                {
                    "id": text_opt_bag(t, "id"),
                    "name": text_opt_bag(t, "name"),
                    "key": text_opt_bag(t, "key"),
                }
                for t in teams
            ],
            "urgent_items": {
                "overdue": overdue[:5],
                "high_priority": high_priority[:5],
            },
        }

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
