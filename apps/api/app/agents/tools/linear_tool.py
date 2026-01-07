"""Linear tools using Composio custom tool infrastructure.

These tools provide Linear functionality using the access_token from Composio's
auth_credentials. Uses Linear GraphQL API for all operations.

Note: Errors are raised as exceptions - Composio wraps responses automatically.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List

from app.decorators import with_doc
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
)
from app.templates.docstrings.linear_tool_docs import (
    CUSTOM_CREATE_ISSUE as CUSTOM_CREATE_ISSUE_DOC,
)
from app.templates.docstrings.linear_tool_docs import (
    CUSTOM_CREATE_ISSUE_RELATION as CUSTOM_CREATE_ISSUE_RELATION_DOC,
)
from app.templates.docstrings.linear_tool_docs import (
    CUSTOM_CREATE_SUB_ISSUES as CUSTOM_CREATE_SUB_ISSUES_DOC,
)
from app.templates.docstrings.linear_tool_docs import (
    CUSTOM_GET_ACTIVE_SPRINT as CUSTOM_GET_ACTIVE_SPRINT_DOC,
)
from app.templates.docstrings.linear_tool_docs import (
    CUSTOM_GET_ISSUE_ACTIVITY as CUSTOM_GET_ISSUE_ACTIVITY_DOC,
)
from app.templates.docstrings.linear_tool_docs import (
    CUSTOM_GET_ISSUE_FULL_CONTEXT as CUSTOM_GET_ISSUE_FULL_CONTEXT_DOC,
)
from app.templates.docstrings.linear_tool_docs import (
    CUSTOM_GET_MY_TASKS as CUSTOM_GET_MY_TASKS_DOC,
)
from app.templates.docstrings.linear_tool_docs import (
    CUSTOM_GET_NOTIFICATIONS as CUSTOM_GET_NOTIFICATIONS_DOC,
)
from app.templates.docstrings.linear_tool_docs import (
    CUSTOM_GET_WORKSPACE_CONTEXT as CUSTOM_GET_WORKSPACE_CONTEXT_DOC,
)
from app.templates.docstrings.linear_tool_docs import (
    CUSTOM_RESOLVE_CONTEXT as CUSTOM_RESOLVE_CONTEXT_DOC,
)
from app.templates.docstrings.linear_tool_docs import (
    CUSTOM_SEARCH_ISSUES as CUSTOM_SEARCH_ISSUES_DOC,
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
    priority_to_int,
    priority_to_str,
)
from composio import Composio


def register_linear_custom_tools(composio: Composio) -> List[str]:
    """Register Linear tools as Composio custom tools."""

    @composio.tools.custom_tool(toolkit="linear")
    @with_doc(CUSTOM_RESOLVE_CONTEXT_DOC)
    def CUSTOM_RESOLVE_CONTEXT(
        request: ResolveContextInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Resolve fuzzy names to Linear IDs."""
        result: Dict[str, Any] = {}

        viewer_data = graphql_request(QUERY_VIEWER, None, auth_credentials)
        viewer = viewer_data.get("viewer", {})
        result["current_user"] = {
            "id": viewer.get("id"),
            "name": viewer.get("name"),
            "email": viewer.get("email"),
        }

        if request.team_name:
            teams_data = graphql_request(QUERY_TEAMS, None, auth_credentials)
            teams = teams_data.get("teams", {}).get("nodes", [])
            result["teams"] = fuzzy_match(request.team_name, teams, "name", limit=3)

        if request.user_name:
            users_data = graphql_request(QUERY_USERS, None, auth_credentials)
            users = users_data.get("users", {}).get("nodes", [])
            active_users = [u for u in users if u.get("active", True)]
            result["users"] = fuzzy_match(
                request.user_name, active_users, "name", limit=3
            )

        if request.label_names:
            if request.team_id:
                labels_data = graphql_request(
                    QUERY_LABELS, {"teamId": request.team_id}, auth_credentials
                )
            else:
                labels_data = graphql_request(QUERY_LABELS_ALL, None, auth_credentials)
            labels = labels_data.get("issueLabels", {}).get("nodes", [])
            matched_labels = []
            for label_name in request.label_names[:3]:
                matches = fuzzy_match(label_name, labels, "name", limit=1)
                matched_labels.extend(matches)
            result["labels"] = matched_labels[:4]

        if request.project_name:
            projects_data = graphql_request(QUERY_PROJECTS, None, auth_credentials)
            projects = projects_data.get("projects", {}).get("nodes", [])
            result["projects"] = fuzzy_match(
                request.project_name, projects, "name", limit=3
            )

        if request.state_name and request.team_id:
            states_data = graphql_request(
                QUERY_STATES, {"teamId": request.team_id}, auth_credentials
            )
            states = states_data.get("workflowStates", {}).get("nodes", [])
            result["states"] = fuzzy_match(request.state_name, states, "name", limit=3)

        return {"data": result}

    @composio.tools.custom_tool(toolkit="linear")
    @with_doc(CUSTOM_GET_MY_TASKS_DOC)
    def CUSTOM_GET_MY_TASKS(
        request: GetMyTasksInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Get the current user's assigned issues."""
        viewer_data = graphql_request(QUERY_VIEWER, None, auth_credentials)
        viewer_id = viewer_data.get("viewer", {}).get("id")

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

        issues = issues_data.get("issues", {}).get("nodes", [])
        today = datetime.now().date()
        week_end = today + timedelta(days=7)

        filtered = []
        for issue in issues:
            due_str = issue.get("dueDate")
            due_date = None
            if due_str:
                try:
                    due_date = datetime.fromisoformat(
                        due_str.replace("Z", "+00:00")
                    ).date()
                except ValueError:
                    pass

            priority = issue.get("priority", 0)
            state_type = issue.get("state", {}).get("type", "")

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

        def sort_key(issue: Dict) -> tuple:
            p = issue.get("priority", 99)
            due = issue.get("dueDate") or "9999-12-31"
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
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Search issues using natural language queries."""
        issues_data = graphql_request(
            QUERY_SEARCH_ISSUES,
            {"query": request.query, "first": min(request.limit * 2, 100)},
            auth_credentials,
        )

        issues = issues_data.get("searchIssues", {}).get("nodes", [])
        filtered = []

        for issue in issues:
            if request.team_id:
                if issue.get("team", {}).get("id") != request.team_id:
                    continue
            if request.state_filter:
                state_type = issue.get("state", {}).get("type", "").lower()
                if state_type != request.state_filter:
                    continue
            if request.assignee_id:
                if issue.get("assignee", {}).get("id") != request.assignee_id:
                    continue
            if request.priority_filter:
                priority = issue.get("priority", 0)
                expected = priority_to_int(request.priority_filter)
                if priority != expected:
                    continue
            if request.created_after:
                created = issue.get("createdAt", "")
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
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Get complete issue details in one call."""
        if not request.issue_id and not request.issue_identifier:
            raise ValueError("Provide either issue_id or issue_identifier")

        issue = None

        if request.issue_id:
            data = graphql_request(
                QUERY_ISSUE_BY_ID, {"id": request.issue_id}, auth_credentials
            )
            issue = data.get("issue")
        elif request.issue_identifier:
            parts = request.issue_identifier.split("-")
            if len(parts) != 2:
                raise ValueError(
                    f"Invalid identifier format: {request.issue_identifier}"
                )
            try:
                float(parts[1])
            except ValueError as e:
                raise ValueError(
                    f"Invalid issue number in: {request.issue_identifier}"
                ) from e

            data = graphql_request(
                QUERY_ISSUE_BY_IDENTIFIER,
                {"identifier": request.issue_identifier},
                auth_credentials,
            )
            issue = data.get("issue")

        if not issue:
            raise ValueError(
                f"Issue not found: {request.issue_id or request.issue_identifier}"
            )

        result = {
            "id": issue.get("id"),
            "identifier": issue.get("identifier"),
            "title": issue.get("title"),
            "description": issue.get("description"),
            "priority": priority_to_str(issue.get("priority", 0)),
            "state": issue.get("state", {}).get("name"),
            "dueDate": issue.get("dueDate"),
            "estimate": issue.get("estimate"),
            "team": (issue.get("team") or {}).get("name"),
            "project": (issue.get("project") or {}).get("name"),
            "cycle": (issue.get("cycle") or {}).get("name"),
            "assignee": (issue.get("assignee") or {}).get("name"),
            "creator": (issue.get("creator") or {}).get("name"),
        }

        if issue.get("parent"):
            result["parent"] = {
                "identifier": issue["parent"].get("identifier"),
                "title": issue["parent"].get("title"),
            }

        children = (issue.get("children") or {}).get("nodes", [])
        if children:
            result["sub_issues"] = [
                {
                    "identifier": c.get("identifier"),
                    "title": c.get("title"),
                    "state": c.get("state", {}).get("name"),
                }
                for c in children
            ]

        relations = (issue.get("relations") or {}).get("nodes", [])
        if relations:
            result["relations"] = [
                {
                    "type": r.get("type"),
                    "issue": {
                        "identifier": r.get("relatedIssue", {}).get("identifier"),
                        "title": r.get("relatedIssue", {}).get("title"),
                    },
                }
                for r in relations
            ]

        comments = (issue.get("comments") or {}).get("nodes", [])
        if comments:
            result["comments"] = [
                {
                    "author": (c.get("user") or {}).get("name"),
                    "body": c.get("body"),
                    "createdAt": c.get("createdAt"),
                }
                for c in comments
            ]

        history = (issue.get("history") or {}).get("nodes", [])
        if history:
            result["activity"] = []
            for h in history:
                entry = {
                    "timestamp": h.get("createdAt"),
                    "actor": (h.get("actor") or {}).get("name"),
                }
                if h.get("fromState") or h.get("toState"):
                    entry["change"] = "state"
                    entry["from"] = (h.get("fromState") or {}).get("name")
                    entry["to"] = (h.get("toState") or {}).get("name")
                elif h.get("fromAssignee") or h.get("toAssignee"):
                    entry["change"] = "assignee"
                    entry["from"] = (h.get("fromAssignee") or {}).get("name")
                    entry["to"] = (h.get("toAssignee") or {}).get("name")
                elif (h.get("addedLabels") or {}).get("nodes"):
                    entry["change"] = "labels_added"
                    entry["labels"] = [
                        label.get("name") for label in h["addedLabels"]["nodes"]
                    ]
                elif (h.get("removedLabels") or {}).get("nodes"):
                    entry["change"] = "labels_removed"
                    entry["labels"] = [
                        label.get("name") for label in h["removedLabels"]["nodes"]
                    ]
                else:
                    continue
                result["activity"].append(entry)

        attachments = (issue.get("attachments") or {}).get("nodes", [])
        if attachments:
            result["attachments"] = [
                {"title": a.get("title"), "url": a.get("url")} for a in attachments
            ]

        return {"issue": result}

    @composio.tools.custom_tool(toolkit="linear")
    @with_doc(CUSTOM_CREATE_ISSUE_DOC)
    def CUSTOM_CREATE_ISSUE(
        request: CreateIssueInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create an issue with full field support and optional sub-issues."""
        # Build input data
        input_data: Dict[str, Any] = {
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
        result = graphql_request(
            MUTATION_CREATE_ISSUE, {"input": input_data}, auth_credentials
        )
        create_result = result.get("issueCreate", {})
        if not create_result.get("success"):
            raise RuntimeError("Failed to create issue")

        created = create_result.get("issue", {})
        response: Dict[str, Any] = {
            "issue": {
                "id": created.get("id"),
                "identifier": created.get("identifier"),
                "title": created.get("title"),
                "url": created.get("url"),
            },
        }

        # Create sub-issues if provided
        if request.sub_issues:
            parent_id = created.get("id")
            created_subs = []
            errors = []

            for sub in request.sub_issues:
                sub_input: Dict[str, Any] = {
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
                sub_create = sub_result.get("issueCreate", {})
                if sub_create.get("success"):
                    sub_issue = sub_create.get("issue", {})
                    created_subs.append(
                        {
                            "id": sub_issue.get("id"),
                            "identifier": sub_issue.get("identifier"),
                            "title": sub_issue.get("title"),
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
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create multiple sub-issues under a parent issue."""
        parent_id = request.parent_issue_id

        if not parent_id and request.parent_identifier:
            parts = request.parent_identifier.split("-")
            if len(parts) != 2:
                raise ValueError(
                    f"Invalid parent identifier: {request.parent_identifier}"
                )
            team_key = parts[0]
            try:
                number = float(parts[1])
            except ValueError as e:
                raise ValueError(
                    f"Invalid issue number in: {request.parent_identifier}"
                ) from e

            data = graphql_request(
                QUERY_ISSUE_BY_IDENTIFIER,
                {"teamKey": team_key, "number": number},
                auth_credentials,
            )
            teams = data.get("teams", {}).get("nodes", [])
            if teams and teams[0].get("issue"):
                parent_id = teams[0]["issue"].get("id")

        if not parent_id:
            raise ValueError("Could not resolve parent issue")

        parent_data = graphql_request(
            QUERY_ISSUE_BY_ID, {"id": parent_id}, auth_credentials
        )
        parent_issue = parent_data.get("issue")
        if not parent_issue:
            raise ValueError("Parent issue not found")

        team_id = parent_issue.get("team", {}).get("id")
        if not team_id:
            raise ValueError("Could not get parent's team")

        created_issues = []
        errors = []

        for sub_issue in request.sub_issues:
            input_data: Dict[str, Any] = {
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

            result = graphql_request(
                MUTATION_CREATE_ISSUE, {"input": input_data}, auth_credentials
            )
            create_result = result.get("issueCreate", {})
            if create_result.get("success"):
                created = create_result.get("issue", {})
                created_issues.append(
                    {
                        "id": created.get("id"),
                        "identifier": created.get("identifier"),
                        "title": created.get("title"),
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
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create a relationship between two issues."""
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

        create_result = result.get("issueRelationCreate", {})
        if not create_result.get("success"):
            raise RuntimeError("Failed to create relation")

        relation = create_result.get("issueRelation", {})
        return {
            "relation": {
                "id": relation.get("id"),
                "type": request.relation_type,
                "from_issue": request.issue_id,
                "to_issue": request.related_issue_id,
            },
        }

    @composio.tools.custom_tool(toolkit="linear")
    @with_doc(CUSTOM_GET_ISSUE_ACTIVITY_DOC)
    def CUSTOM_GET_ISSUE_ACTIVITY(
        request: GetIssueActivityInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Get the change history for an issue."""
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
                    issue = data.get("issue")
                    if issue:
                        issue_id = issue["id"]
                except ValueError:
                    pass

        if not issue_id:
            raise ValueError("Could not resolve issue")

        data = graphql_request(
            QUERY_ISSUE_HISTORY,
            {"issueId": issue_id, "first": request.limit},
            auth_credentials,
        )
        history = (data.get("issue") or {}).get("history", {}).get("nodes", [])

        activities = []
        for h in history:
            entry = {
                "timestamp": h.get("createdAt"),
                "actor": (h.get("actor") or {}).get("name")
                if h.get("actor")
                else "System",
            }
            if h.get("fromState") or h.get("toState"):
                entry["change_type"] = "state"
                entry["from"] = (h.get("fromState") or {}).get("name")
                entry["to"] = (h.get("toState") or {}).get("name")
            elif h.get("fromAssignee") or h.get("toAssignee"):
                entry["change_type"] = "assignee"
                entry["from"] = (
                    (h.get("fromAssignee") or {}).get("name")
                    if h.get("fromAssignee")
                    else None
                )
                entry["to"] = (
                    (h.get("toAssignee") or {}).get("name")
                    if h.get("toAssignee")
                    else None
                )
            elif h.get("fromPriority") is not None or h.get("toPriority") is not None:
                entry["change_type"] = "priority"
                entry["from"] = priority_to_str(h.get("fromPriority", 0))
                entry["to"] = priority_to_str(h.get("toPriority", 0))
            elif (h.get("addedLabels") or {}).get("nodes"):
                entry["change_type"] = "labels_added"
                entry["labels"] = [
                    label.get("name") for label in h["addedLabels"]["nodes"]
                ]
            elif (h.get("removedLabels") or {}).get("nodes"):
                entry["change_type"] = "labels_removed"
                entry["labels"] = [
                    label.get("name") for label in h["removedLabels"]["nodes"]
                ]
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
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Get the current/active sprint context."""
        data = graphql_request(QUERY_ACTIVE_CYCLES, None, auth_credentials)
        cycles = data.get("cycles", {}).get("nodes", [])

        if request.team_id:
            cycles = [
                c for c in cycles if c.get("team", {}).get("id") == request.team_id
            ]

        limit = request.issues_per_state_limit
        sprints = []
        for cycle in cycles:
            issues = cycle.get("issues", {}).get("nodes", [])
            by_state: Dict[str, List[Dict]] = {
                "backlog": [],
                "unstarted": [],
                "started": [],
                "completed": [],
            }

            for issue in issues:
                state_type = issue.get("state", {}).get("type", "unstarted").lower()
                if state_type in by_state:
                    by_state[state_type].append(
                        {
                            "identifier": issue.get("identifier"),
                            "title": issue.get("title"),
                            "priority": priority_to_str(issue.get("priority", 0)),
                            "assignee": issue.get("assignee", {}).get("name")
                            if issue.get("assignee")
                            else None,
                        }
                    )

            sprints.append(
                {
                    "id": cycle.get("id"),
                    "name": cycle.get("name"),
                    "number": cycle.get("number"),
                    "team": cycle.get("team", {}).get("name"),
                    "team_key": cycle.get("team", {}).get("key"),
                    "starts_at": cycle.get("startsAt"),
                    "ends_at": cycle.get("endsAt"),
                    "progress": round(cycle.get("progress", 0) * 100, 1),
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
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Batch update multiple issues at once."""
        if not request.issue_ids:
            raise ValueError("No issue IDs provided")

        input_data: Dict[str, Any] = {}
        if request.state_id is not None:
            input_data["stateId"] = request.state_id
        if request.priority is not None:
            input_data["priority"] = request.priority
        if request.assignee_id is not None:
            input_data["assigneeId"] = (
                request.assignee_id if request.assignee_id else None
            )
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
        update_result = result.get("issueBatchUpdate", {})
        if not update_result.get("success"):
            raise RuntimeError("Batch update failed")

        updated = update_result.get("issues", [])
        return {
            "updated_count": len(updated),
            "updated_issues": [
                {"id": i.get("id"), "identifier": i.get("identifier")} for i in updated
            ],
        }

    @composio.tools.custom_tool(toolkit="linear")
    @with_doc(CUSTOM_GET_NOTIFICATIONS_DOC)
    def CUSTOM_GET_NOTIFICATIONS(
        request: GetNotificationsInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Get the current user's notifications."""
        data = graphql_request(
            QUERY_NOTIFICATIONS,
            {"first": request.limit},
            auth_credentials,
        )
        notifications = data.get("notifications", {}).get("nodes", [])

        formatted = []
        for n in notifications:
            is_read = n.get("readAt") is not None

            # Filter by read status if not including read
            if not request.include_read and is_read:
                continue

            formatted.append(
                {
                    "id": n.get("id"),
                    "type": n.get("type"),
                    "created_at": n.get("createdAt"),
                    "read": is_read,
                    "issue": {
                        "identifier": n.get("issue", {}).get("identifier"),
                        "title": n.get("issue", {}).get("title"),
                    }
                    if n.get("issue")
                    else None,
                    "actor": n.get("actor", {}).get("name") if n.get("actor") else None,
                }
            )

        return {"count": len(formatted), "notifications": formatted}

    @composio.tools.custom_tool(toolkit="linear")
    @with_doc(CUSTOM_GET_WORKSPACE_CONTEXT_DOC)
    def CUSTOM_GET_WORKSPACE_CONTEXT(
        request: GetWorkspaceContextInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Get full workspace context for session initialization."""
        viewer_data = graphql_request(QUERY_VIEWER, None, auth_credentials)
        viewer = viewer_data.get("viewer", {})
        assigned_count = len(viewer.get("assignedIssues", {}).get("nodes", []))

        teams_data = graphql_request(QUERY_TEAMS, None, auth_credentials)
        teams = teams_data.get("teams", {}).get("nodes", [])

        issues_data = graphql_request(
            QUERY_MY_ISSUES,
            {"assigneeId": viewer.get("id"), "includeCompleted": True, "first": 50},
            auth_credentials,
        )
        my_issues = issues_data.get("issues", {}).get("nodes", [])

        today = datetime.now().date()
        overdue = []
        high_priority = []
        sla_at_risk = []

        for issue in my_issues:
            state_type = issue.get("state", {}).get("type", "")
            if state_type in ["completed", "canceled"]:
                continue

            due_str = issue.get("dueDate")
            if due_str:
                try:
                    due_date = datetime.fromisoformat(
                        due_str.replace("Z", "+00:00")
                    ).date()
                    if due_date < today:
                        overdue.append(format_issue_summary(issue))
                except ValueError:
                    pass

            if issue.get("priority") in [1, 2]:
                high_priority.append(format_issue_summary(issue))

            if issue.get("slaBreachesAt"):
                sla_at_risk.append(format_issue_summary(issue))

        return {
            "user": {
                "id": viewer.get("id"),
                "name": viewer.get("name"),
                "email": viewer.get("email"),
                "assigned_issue_count": assigned_count,
            },
            "teams": [
                {
                    "id": t.get("id"),
                    "name": t.get("name"),
                    "key": t.get("key"),
                    "active_cycle": t.get("activeCycle", {}).get("name")
                    if t.get("activeCycle")
                    else None,
                    "cycle_progress": round(
                        t.get("activeCycle", {}).get("progress", 0) * 100, 1
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
    ]
