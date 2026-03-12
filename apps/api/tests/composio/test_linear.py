"""Tests for Linear custom tools registered in linear_tool.py.

Strategy: The tool functions are closures registered via the Composio decorator
inside `register_linear_custom_tools`. To test them without a real Composio
connection we:

1. Capture the callables by mocking the `@composio.tools.custom_tool` decorator
   so it records each decorated function instead of registering it with Composio.
2. Patch `app.utils.linear_utils.graphql_request` at the HTTP boundary so no
   real network calls are made.
3. Call the captured callables directly with Pydantic input models and a fake
   `auth_credentials` dict, then assert on the returned dicts.

If `linear_tool.py` is deleted or the import chain breaks every test will fail
with an ImportError, satisfying the requirement that the tests must import and
call the actual tool code.
"""

from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

# --- import the real production module (tests fail if it is deleted) ---
from app.agents.tools.integrations.linear_tool import register_linear_custom_tools
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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

AUTH = {"access_token": "test_linear_token"}
EXECUTE_REQUEST = MagicMock()  # not used by any of the current tools


def _capture_tools() -> Dict[str, Any]:
    """
    Run `register_linear_custom_tools` with a fake Composio object whose
    `tools.custom_tool` decorator simply stores the decorated functions
    keyed by their __name__, then returns the collected dict.
    """
    captured: Dict[str, Any] = {}

    def fake_custom_tool(toolkit: str):
        def decorator(fn):
            captured[fn.__name__] = fn
            return fn

        return decorator

    mock_composio = MagicMock()
    mock_composio.tools.custom_tool.side_effect = fake_custom_tool

    register_linear_custom_tools(mock_composio)
    return captured


# Capture once for the whole module so patching is cheap.
_TOOLS = _capture_tools()


def _call(tool_name: str, request, side_effects=None, return_values=None):
    """
    Call a captured tool function with graphql_request mocked.

    Either `side_effects` (iterable consumed in call order) or
    `return_values` (iterable consumed in call order) must be provided.
    """
    tool_fn = _TOOLS[tool_name]
    with patch(
        "app.agents.tools.integrations.linear_tool.graphql_request",
        side_effect=side_effects if side_effects is not None else None,
    ) as mock_gql:
        if return_values is not None:
            mock_gql.side_effect = return_values
        return tool_fn(request, EXECUTE_REQUEST, AUTH), mock_gql


# ---------------------------------------------------------------------------
# Fixtures / shared data
# ---------------------------------------------------------------------------

VIEWER_RESPONSE = {
    "viewer": {
        "id": "user-1",
        "name": "Alice",
        "email": "alice@example.com",
        "assignedIssues": {"nodes": []},
    }
}

ISSUE_NODE = {
    "id": "issue-abc",
    "identifier": "ENG-1",
    "title": "Fix the thing",
    "priority": 2,
    "state": {"id": "state-1", "name": "In Progress", "type": "started"},
    "dueDate": None,
    "team": {"id": "team-1", "key": "ENG", "name": "Engineering"},
    "cycle": None,
    "parent": None,
    "assignee": {"id": "user-1", "name": "Alice"},
    "createdAt": "2024-01-01T00:00:00Z",
}


# ===========================================================================
# CUSTOM_RESOLVE_CONTEXT
# ===========================================================================


class TestResolveContext:
    @pytest.mark.composio
    def test_resolve_viewer_only(self):
        """Returns current_user when no name parameters are supplied."""
        result, mock_gql = _call(
            "CUSTOM_RESOLVE_CONTEXT",
            ResolveContextInput(),
            return_values=[VIEWER_RESPONSE],
        )
        assert result["data"]["current_user"]["id"] == "user-1"
        assert result["data"]["current_user"]["name"] == "Alice"
        mock_gql.assert_called_once()

    @pytest.mark.composio
    def test_resolve_team_name(self):
        """Fuzzy-matches team name and returns candidates."""
        teams_response = {
            "teams": {
                "nodes": [
                    {"id": "team-1", "name": "Engineering"},
                    {"id": "team-2", "name": "Product"},
                ]
            }
        }
        result, mock_gql = _call(
            "CUSTOM_RESOLVE_CONTEXT",
            ResolveContextInput(team_name="eng"),
            return_values=[VIEWER_RESPONSE, teams_response],
        )
        assert "teams" in result["data"]
        names = [t["name"] for t in result["data"]["teams"]]
        assert "Engineering" in names

    @pytest.mark.composio
    def test_resolve_user_name(self):
        """Fuzzy-matches user name and returns only active users."""
        users_response = {
            "users": {
                "nodes": [
                    {
                        "id": "user-1",
                        "name": "Alice",
                        "email": "a@e.com",
                        "active": True,
                    },
                    {
                        "id": "user-2",
                        "name": "Bob",
                        "email": "b@e.com",
                        "active": False,
                    },
                ]
            }
        }
        result, _ = _call(
            "CUSTOM_RESOLVE_CONTEXT",
            ResolveContextInput(user_name="alice"),
            return_values=[VIEWER_RESPONSE, users_response],
        )
        users = result["data"]["users"]
        assert any(u["name"] == "Alice" for u in users)
        # Bob is inactive and must not appear
        assert not any(u["name"] == "Bob" for u in users)

    @pytest.mark.composio
    def test_resolve_labels_no_team(self):
        """Fetches all labels when no team_id is given."""
        labels_response = {
            "issueLabels": {
                "nodes": [
                    {"id": "lbl-1", "name": "bug"},
                    {"id": "lbl-2", "name": "feature"},
                ]
            }
        }
        result, mock_gql = _call(
            "CUSTOM_RESOLVE_CONTEXT",
            ResolveContextInput(label_names=["bug"]),
            return_values=[VIEWER_RESPONSE, labels_response],
        )
        assert "labels" in result["data"]

    @pytest.mark.composio
    def test_resolve_state_requires_team_id(self):
        """state_name resolution only runs when team_id is also provided."""
        states_response = {
            "workflowStates": {
                "nodes": [
                    {"id": "s1", "name": "In Progress", "type": "started"},
                ]
            }
        }
        result_with_team, mock_gql = _call(
            "CUSTOM_RESOLVE_CONTEXT",
            ResolveContextInput(state_name="progress", team_id="team-1"),
            return_values=[VIEWER_RESPONSE, states_response],
        )
        assert "states" in result_with_team["data"]

    @pytest.mark.composio
    def test_resolve_graphql_error_propagates(self):
        """graphql_request exceptions bubble up to the caller."""
        with patch(
            "app.agents.tools.integrations.linear_tool.graphql_request",
            side_effect=Exception("Unauthorized"),
        ):
            with pytest.raises(Exception, match="Unauthorized"):
                _TOOLS["CUSTOM_RESOLVE_CONTEXT"](
                    ResolveContextInput(), EXECUTE_REQUEST, AUTH
                )


# ===========================================================================
# CUSTOM_GET_MY_TASKS
# ===========================================================================


class TestGetMyTasks:
    @pytest.mark.composio
    def test_returns_issues_for_current_user(self):
        """Happy path: viewer resolved, issues fetched and formatted."""
        issues_response = {
            "issues": {
                "nodes": [ISSUE_NODE],
            }
        }
        result, mock_gql = _call(
            "CUSTOM_GET_MY_TASKS",
            GetMyTasksInput(),
            return_values=[VIEWER_RESPONSE, issues_response],
        )
        assert result["count"] == 1
        assert result["issues"][0]["identifier"] == "ENG-1"
        assert result["filter"] == "all"
        # Viewer query + issues query
        assert mock_gql.call_count == 2

    @pytest.mark.composio
    def test_viewer_id_missing_raises(self):
        """Raises ValueError when viewer response is empty."""
        with patch(
            "app.agents.tools.integrations.linear_tool.graphql_request",
            return_value={"viewer": {}},
        ):
            with pytest.raises(ValueError, match="Could not get current user"):
                _TOOLS["CUSTOM_GET_MY_TASKS"](GetMyTasksInput(), EXECUTE_REQUEST, AUTH)

    @pytest.mark.composio
    def test_filter_high_priority(self):
        """Only P1/P2 issues returned when filter='high_priority'."""
        low_issue = {
            **ISSUE_NODE,
            "id": "issue-low",
            "identifier": "ENG-2",
            "priority": 4,
        }
        issues_response = {"issues": {"nodes": [ISSUE_NODE, low_issue]}}
        result, _ = _call(
            "CUSTOM_GET_MY_TASKS",
            GetMyTasksInput(filter="high_priority"),
            return_values=[VIEWER_RESPONSE, issues_response],
        )
        assert all(i["priority"] in ("urgent", "high") for i in result["issues"])

    @pytest.mark.composio
    def test_filter_overdue(self):
        """Only past-due issues are returned when filter='overdue'."""
        overdue_issue = {
            **ISSUE_NODE,
            "id": "issue-od",
            "identifier": "ENG-3",
            "dueDate": "2000-01-01",
            "priority": 0,
        }
        issues_response = {"issues": {"nodes": [ISSUE_NODE, overdue_issue]}}
        result, _ = _call(
            "CUSTOM_GET_MY_TASKS",
            GetMyTasksInput(filter="overdue"),
            return_values=[VIEWER_RESPONSE, issues_response],
        )
        identifiers = [i["identifier"] for i in result["issues"]]
        assert "ENG-3" in identifiers
        # ENG-1 has no dueDate so it must not appear in overdue
        assert "ENG-1" not in identifiers

    @pytest.mark.composio
    def test_completed_issues_excluded_by_default(self):
        """Completed/canceled issues are filtered out when include_completed=False."""
        completed_issue = {
            **ISSUE_NODE,
            "id": "issue-done",
            "identifier": "ENG-4",
            "state": {"id": "s2", "name": "Done", "type": "completed"},
        }
        issues_response = {"issues": {"nodes": [ISSUE_NODE, completed_issue]}}
        result, _ = _call(
            "CUSTOM_GET_MY_TASKS",
            GetMyTasksInput(include_completed=False),
            return_values=[VIEWER_RESPONSE, issues_response],
        )
        identifiers = [i["identifier"] for i in result["issues"]]
        assert "ENG-4" not in identifiers

    @pytest.mark.composio
    def test_limit_respected(self):
        """Result set is capped at the requested limit."""
        many_issues = [
            {**ISSUE_NODE, "id": f"issue-{i}", "identifier": f"ENG-{i}"}
            for i in range(30)
        ]
        issues_response = {"issues": {"nodes": many_issues}}
        result, _ = _call(
            "CUSTOM_GET_MY_TASKS",
            GetMyTasksInput(limit=5),
            return_values=[VIEWER_RESPONSE, issues_response],
        )
        assert result["count"] <= 5

    @pytest.mark.composio
    def test_assignee_id_passed_to_graphql(self):
        """Viewer ID is forwarded as assigneeId variable to the issues query."""
        issues_response = {"issues": {"nodes": []}}
        _, mock_gql = _call(
            "CUSTOM_GET_MY_TASKS",
            GetMyTasksInput(),
            return_values=[VIEWER_RESPONSE, issues_response],
        )
        # Second call contains the variables dict
        second_call_kwargs = mock_gql.call_args_list[1]
        variables = second_call_kwargs[0][1]  # positional arg index 1
        assert variables["assigneeId"] == "user-1"


# ===========================================================================
# CUSTOM_SEARCH_ISSUES
# ===========================================================================


class TestSearchIssues:
    @pytest.mark.composio
    def test_basic_search_returns_issues(self):
        """Happy path: issues matching the query are returned."""
        search_response = {"searchIssues": {"nodes": [ISSUE_NODE]}}
        result, mock_gql = _call(
            "CUSTOM_SEARCH_ISSUES",
            SearchIssuesInput(query="fix bug"),
            return_values=[search_response],
        )
        assert result["query"] == "fix bug"
        assert result["count"] == 1
        assert result["issues"][0]["identifier"] == "ENG-1"
        mock_gql.assert_called_once()

    @pytest.mark.composio
    def test_query_forwarded_to_graphql(self):
        """The query string is passed as a variable to graphql_request."""
        search_response = {"searchIssues": {"nodes": []}}
        _, mock_gql = _call(
            "CUSTOM_SEARCH_ISSUES",
            SearchIssuesInput(query="deploy pipeline"),
            return_values=[search_response],
        )
        variables = mock_gql.call_args[0][1]
        assert variables["query"] == "deploy pipeline"

    @pytest.mark.composio
    def test_team_filter_applied_client_side(self):
        """Issues belonging to a different team are excluded."""
        other_team_issue = {
            **ISSUE_NODE,
            "id": "issue-x",
            "identifier": "PROD-1",
            "team": {"id": "team-99", "key": "PROD", "name": "Product"},
        }
        search_response = {"searchIssues": {"nodes": [ISSUE_NODE, other_team_issue]}}
        result, _ = _call(
            "CUSTOM_SEARCH_ISSUES",
            SearchIssuesInput(query="fix", team_id="team-1"),
            return_values=[search_response],
        )
        identifiers = [i["identifier"] for i in result["issues"]]
        assert "ENG-1" in identifiers
        assert "PROD-1" not in identifiers

    @pytest.mark.composio
    def test_state_filter_applied_client_side(self):
        """Issues not matching the requested state type are excluded."""
        done_issue = {
            **ISSUE_NODE,
            "id": "issue-done",
            "identifier": "ENG-99",
            "state": {"id": "s99", "name": "Done", "type": "completed"},
        }
        search_response = {"searchIssues": {"nodes": [ISSUE_NODE, done_issue]}}
        result, _ = _call(
            "CUSTOM_SEARCH_ISSUES",
            SearchIssuesInput(query="fix", state_filter="started"),
            return_values=[search_response],
        )
        identifiers = [i["identifier"] for i in result["issues"]]
        assert "ENG-1" in identifiers
        assert "ENG-99" not in identifiers

    @pytest.mark.composio
    def test_priority_filter_applied_client_side(self):
        """Issues with a different priority level are excluded."""
        urgent_issue = {
            **ISSUE_NODE,
            "id": "issue-urg",
            "identifier": "ENG-5",
            "priority": 1,
        }
        search_response = {"searchIssues": {"nodes": [ISSUE_NODE, urgent_issue]}}
        result, _ = _call(
            "CUSTOM_SEARCH_ISSUES",
            SearchIssuesInput(query="fix", priority_filter="high"),
            return_values=[search_response],
        )
        identifiers = [i["identifier"] for i in result["issues"]]
        # ISSUE_NODE priority=2 (high) → included; urgent_issue priority=1 → excluded
        assert "ENG-1" in identifiers
        assert "ENG-5" not in identifiers

    @pytest.mark.composio
    def test_created_after_filter(self):
        """Issues created before the cutoff are excluded."""
        old_issue = {
            **ISSUE_NODE,
            "id": "issue-old",
            "identifier": "ENG-6",
            "createdAt": "2020-01-01T00:00:00Z",
        }
        new_issue = {
            **ISSUE_NODE,
            "id": "issue-new",
            "identifier": "ENG-7",
            "createdAt": "2024-06-01T00:00:00Z",
        }
        search_response = {"searchIssues": {"nodes": [old_issue, new_issue]}}
        result, _ = _call(
            "CUSTOM_SEARCH_ISSUES",
            SearchIssuesInput(query="fix", created_after="2023-01-01"),
            return_values=[search_response],
        )
        identifiers = [i["identifier"] for i in result["issues"]]
        assert "ENG-7" in identifiers
        assert "ENG-6" not in identifiers

    @pytest.mark.composio
    def test_empty_result(self):
        """Returns count=0 and empty list when no issues match."""
        search_response = {"searchIssues": {"nodes": []}}
        result, _ = _call(
            "CUSTOM_SEARCH_ISSUES",
            SearchIssuesInput(query="nonexistent xyz"),
            return_values=[search_response],
        )
        assert result["count"] == 0
        assert result["issues"] == []

    @pytest.mark.composio
    def test_graphql_error_propagates(self):
        """HTTP-level errors from graphql_request surface as exceptions."""
        with patch(
            "app.agents.tools.integrations.linear_tool.graphql_request",
            side_effect=Exception("403 Forbidden"),
        ):
            with pytest.raises(Exception, match="403 Forbidden"):
                _TOOLS["CUSTOM_SEARCH_ISSUES"](
                    SearchIssuesInput(query="test"), EXECUTE_REQUEST, AUTH
                )


# ===========================================================================
# CUSTOM_GET_ISSUE_FULL_CONTEXT
# ===========================================================================

FULL_ISSUE = {
    "id": "issue-abc",
    "identifier": "ENG-1",
    "title": "Fix the thing",
    "description": "Some details",
    "priority": 2,
    "state": {"id": "s1", "name": "In Progress", "type": "started"},
    "dueDate": None,
    "estimate": 3,
    "team": {"id": "team-1", "key": "ENG", "name": "Engineering"},
    "project": {"id": "proj-1", "name": "Q1 Goals"},
    "cycle": None,
    "assignee": {"id": "user-1", "name": "Alice", "email": "a@e.com"},
    "creator": {"id": "user-2", "name": "Bob"},
    "parent": None,
    "children": {"nodes": []},
    "relations": {"nodes": []},
    "comments": {"nodes": []},
    "history": {"nodes": []},
    "attachments": {"nodes": []},
}


class TestGetIssueFullContext:
    @pytest.mark.composio
    def test_fetch_by_issue_id(self):
        """Fetches issue by UUID and returns structured context."""
        result, mock_gql = _call(
            "CUSTOM_GET_ISSUE_FULL_CONTEXT",
            GetIssueFullContextInput(issue_id="issue-abc"),
            return_values=[{"issue": FULL_ISSUE}],
        )
        assert result["issue"]["identifier"] == "ENG-1"
        assert result["issue"]["priority"] == "high"  # priority_to_str(2)
        assert result["issue"]["project"] == "Q1 Goals"
        mock_gql.assert_called_once()

    @pytest.mark.composio
    def test_fetch_by_identifier(self):
        """Fetches issue by human-readable identifier like 'ENG-1'."""
        result, _ = _call(
            "CUSTOM_GET_ISSUE_FULL_CONTEXT",
            GetIssueFullContextInput(issue_identifier="ENG-1"),
            return_values=[{"issue": FULL_ISSUE}],
        )
        assert result["issue"]["id"] == "issue-abc"

    @pytest.mark.composio
    def test_no_id_raises(self):
        """Raises ValueError when neither issue_id nor issue_identifier is given."""
        with pytest.raises(ValueError, match="Provide either"):
            _TOOLS["CUSTOM_GET_ISSUE_FULL_CONTEXT"](
                GetIssueFullContextInput(), EXECUTE_REQUEST, AUTH
            )

    @pytest.mark.composio
    def test_invalid_identifier_format_raises(self):
        """Raises ValueError for identifiers that are not 'TEAM-NUMBER' format."""
        with patch("app.agents.tools.integrations.linear_tool.graphql_request"):
            with pytest.raises(ValueError, match="Invalid identifier format"):
                _TOOLS["CUSTOM_GET_ISSUE_FULL_CONTEXT"](
                    GetIssueFullContextInput(issue_identifier="BADFORMAT"),
                    EXECUTE_REQUEST,
                    AUTH,
                )

    @pytest.mark.composio
    def test_issue_not_found_raises(self):
        """Raises ValueError when the API returns no issue data."""
        with patch(
            "app.agents.tools.integrations.linear_tool.graphql_request",
            return_value={"issue": None},
        ):
            with pytest.raises(ValueError, match="Issue not found"):
                _TOOLS["CUSTOM_GET_ISSUE_FULL_CONTEXT"](
                    GetIssueFullContextInput(issue_id="missing-id"),
                    EXECUTE_REQUEST,
                    AUTH,
                )

    @pytest.mark.composio
    def test_sub_issues_included(self):
        """Sub-issues appear in the result when the issue has children."""
        issue_with_children = {
            **FULL_ISSUE,
            "children": {
                "nodes": [
                    {
                        "identifier": "ENG-2",
                        "title": "Sub task",
                        "state": {"name": "Todo"},
                    }
                ]
            },
        }
        result, _ = _call(
            "CUSTOM_GET_ISSUE_FULL_CONTEXT",
            GetIssueFullContextInput(issue_id="issue-abc"),
            return_values=[{"issue": issue_with_children}],
        )
        assert "sub_issues" in result["issue"]
        assert result["issue"]["sub_issues"][0]["identifier"] == "ENG-2"

    @pytest.mark.composio
    def test_comments_included(self):
        """Comments appear in the result when the issue has them."""
        issue_with_comments = {
            **FULL_ISSUE,
            "comments": {
                "nodes": [
                    {
                        "id": "c1",
                        "body": "LGTM",
                        "createdAt": "2024-01-02T00:00:00Z",
                        "user": {"id": "user-2", "name": "Bob"},
                    }
                ]
            },
        }
        result, _ = _call(
            "CUSTOM_GET_ISSUE_FULL_CONTEXT",
            GetIssueFullContextInput(issue_id="issue-abc"),
            return_values=[{"issue": issue_with_comments}],
        )
        assert result["issue"]["comments"][0]["body"] == "LGTM"
        assert result["issue"]["comments"][0]["author"] == "Bob"

    @pytest.mark.composio
    def test_activity_state_change(self):
        """History entries with state changes appear as activity."""
        issue_with_history = {
            **FULL_ISSUE,
            "history": {
                "nodes": [
                    {
                        "id": "h1",
                        "createdAt": "2024-01-03T00:00:00Z",
                        "actor": {"id": "user-1", "name": "Alice"},
                        "fromState": {"id": "s0", "name": "Backlog"},
                        "toState": {"id": "s1", "name": "In Progress"},
                        "fromAssignee": None,
                        "toAssignee": None,
                        "addedLabels": {"nodes": []},
                        "removedLabels": {"nodes": []},
                    }
                ]
            },
        }
        result, _ = _call(
            "CUSTOM_GET_ISSUE_FULL_CONTEXT",
            GetIssueFullContextInput(issue_id="issue-abc"),
            return_values=[{"issue": issue_with_history}],
        )
        activity = result["issue"]["activity"]
        assert activity[0]["change"] == "state"
        assert activity[0]["from"] == "Backlog"
        assert activity[0]["to"] == "In Progress"


# ===========================================================================
# CUSTOM_CREATE_ISSUE
# ===========================================================================

CREATE_ISSUE_SUCCESS = {
    "issueCreate": {
        "success": True,
        "issue": {
            "id": "issue-new",
            "identifier": "ENG-10",
            "title": "New Issue",
            "url": "https://linear.app/team/issue/ENG-10",
        },
    }
}


class TestCreateIssue:
    @pytest.mark.composio
    def test_create_minimal_issue(self):
        """Happy path: creates an issue with just team_id and title."""
        result, mock_gql = _call(
            "CUSTOM_CREATE_ISSUE",
            CreateIssueInput(team_id="team-1", title="New Issue"),
            return_values=[CREATE_ISSUE_SUCCESS],
        )
        assert result["issue"]["identifier"] == "ENG-10"
        assert result["issue"]["url"] == "https://linear.app/team/issue/ENG-10"
        mock_gql.assert_called_once()

    @pytest.mark.composio
    def test_input_fields_forwarded_to_graphql(self):
        """Optional fields are included in the mutation variables."""
        _, mock_gql = _call(
            "CUSTOM_CREATE_ISSUE",
            CreateIssueInput(
                team_id="team-1",
                title="Bug fix",
                description="Details here",
                assignee_id="user-2",
                priority=1,
                state_id="state-5",
                due_date="2024-06-01",
                estimate=2,
            ),
            return_values=[CREATE_ISSUE_SUCCESS],
        )
        call_variables = mock_gql.call_args[0][1]
        inp = call_variables["input"]
        assert inp["teamId"] == "team-1"
        assert inp["description"] == "Details here"
        assert inp["assigneeId"] == "user-2"
        assert inp["priority"] == 1
        assert inp["stateId"] == "state-5"
        assert inp["dueDate"] == "2024-06-01"
        assert inp["estimate"] == 2

    @pytest.mark.composio
    def test_create_issue_api_failure_raises(self):
        """Raises RuntimeError when issueCreate.success is False."""
        failure_response = {"issueCreate": {"success": False, "issue": None}}
        with patch(
            "app.agents.tools.integrations.linear_tool.graphql_request",
            return_value=failure_response,
        ):
            with pytest.raises(RuntimeError, match="Failed to create issue"):
                _TOOLS["CUSTOM_CREATE_ISSUE"](
                    CreateIssueInput(team_id="team-1", title="Bad"),
                    EXECUTE_REQUEST,
                    AUTH,
                )

    @pytest.mark.composio
    def test_create_issue_with_sub_issues(self):
        """Sub-issues are created sequentially after the parent."""
        sub_success = {
            "issueCreate": {
                "success": True,
                "issue": {
                    "id": "sub-1",
                    "identifier": "ENG-11",
                    "title": "Sub task",
                },
            }
        }
        result, mock_gql = _call(
            "CUSTOM_CREATE_ISSUE",
            CreateIssueInput(
                team_id="team-1",
                title="Parent Issue",
                sub_issues=[CreateIssueSubItem(title="Sub task")],
            ),
            return_values=[CREATE_ISSUE_SUCCESS, sub_success],
        )
        assert result["issue"]["identifier"] == "ENG-10"
        assert "sub_issues" in result
        assert result["sub_issues"][0]["identifier"] == "ENG-11"
        assert mock_gql.call_count == 2

    @pytest.mark.composio
    def test_sub_issue_failure_recorded_in_errors(self):
        """Failed sub-issue creations appear in sub_issue_errors, not sub_issues."""
        sub_failure = {"issueCreate": {"success": False, "issue": None}}
        result, _ = _call(
            "CUSTOM_CREATE_ISSUE",
            CreateIssueInput(
                team_id="team-1",
                title="Parent",
                sub_issues=[CreateIssueSubItem(title="Failing Sub")],
            ),
            return_values=[CREATE_ISSUE_SUCCESS, sub_failure],
        )
        assert result["sub_issues"] == []
        assert result["sub_issue_errors"][0]["title"] == "Failing Sub"

    @pytest.mark.composio
    def test_graphql_error_propagates(self):
        """Network-level errors bubble out of create_issue."""
        with patch(
            "app.agents.tools.integrations.linear_tool.graphql_request",
            side_effect=Exception("GraphQL errors: Unauthorized"),
        ):
            with pytest.raises(Exception, match="Unauthorized"):
                _TOOLS["CUSTOM_CREATE_ISSUE"](
                    CreateIssueInput(team_id="team-1", title="Test"),
                    EXECUTE_REQUEST,
                    AUTH,
                )


# ===========================================================================
# CUSTOM_CREATE_SUB_ISSUES
# ===========================================================================


class TestCreateSubIssues:
    @pytest.mark.composio
    def test_create_sub_issues_by_parent_id(self):
        """Creates sub-issues when parent_issue_id is supplied directly."""
        parent_response = {
            "issue": {
                "id": "parent-1",
                "team": {"id": "team-1"},
            }
        }
        sub_success = {
            "issueCreate": {
                "success": True,
                "issue": {"id": "sub-2", "identifier": "ENG-20", "title": "Sub A"},
            }
        }
        result, _ = _call(
            "CUSTOM_CREATE_SUB_ISSUES",
            CreateSubIssuesInput(
                parent_issue_id="parent-1",
                sub_issues=[SubIssueItem(title="Sub A")],
            ),
            return_values=[parent_response, sub_success],
        )
        assert result["created_count"] == 1
        assert result["sub_issues"][0]["identifier"] == "ENG-20"

    @pytest.mark.composio
    def test_parent_not_found_raises(self):
        """Raises ValueError when parent_issue_id resolves to nothing."""
        with patch(
            "app.agents.tools.integrations.linear_tool.graphql_request",
            return_value={"issue": None},
        ):
            with pytest.raises(ValueError, match="Parent issue not found"):
                _TOOLS["CUSTOM_CREATE_SUB_ISSUES"](
                    CreateSubIssuesInput(
                        parent_issue_id="bad-id",
                        sub_issues=[SubIssueItem(title="Sub")],
                    ),
                    EXECUTE_REQUEST,
                    AUTH,
                )

    @pytest.mark.composio
    def test_no_parent_raises(self):
        """Raises ValueError when neither parent_issue_id nor parent_identifier given."""
        with patch("app.agents.tools.integrations.linear_tool.graphql_request"):
            with pytest.raises(ValueError, match="Could not resolve parent issue"):
                _TOOLS["CUSTOM_CREATE_SUB_ISSUES"](
                    CreateSubIssuesInput(sub_issues=[SubIssueItem(title="Sub")]),
                    EXECUTE_REQUEST,
                    AUTH,
                )

    @pytest.mark.composio
    def test_team_id_missing_from_parent_raises(self):
        """Raises ValueError when parent issue has no team."""
        with patch(
            "app.agents.tools.integrations.linear_tool.graphql_request",
            return_value={"issue": {"id": "p1", "team": {}}},
        ):
            with pytest.raises(ValueError, match="Could not get parent's team"):
                _TOOLS["CUSTOM_CREATE_SUB_ISSUES"](
                    CreateSubIssuesInput(
                        parent_issue_id="p1",
                        sub_issues=[SubIssueItem(title="Sub")],
                    ),
                    EXECUTE_REQUEST,
                    AUTH,
                )


# ===========================================================================
# CUSTOM_CREATE_ISSUE_RELATION
# ===========================================================================


class TestCreateIssueRelation:
    @pytest.mark.composio
    def test_create_blocks_relation(self):
        """Happy path: 'blocks' relation is created between two issues."""
        relation_success = {
            "issueRelationCreate": {
                "success": True,
                "issueRelation": {"id": "rel-1", "type": "blocks"},
            }
        }
        result, _ = _call(
            "CUSTOM_CREATE_ISSUE_RELATION",
            CreateIssueRelationInput(
                issue_id="issue-a",
                related_issue_id="issue-b",
                relation_type="blocks",
            ),
            return_values=[relation_success],
        )
        assert result["relation"]["id"] == "rel-1"
        assert result["relation"]["type"] == "blocks"
        assert result["relation"]["from_issue"] == "issue-a"
        assert result["relation"]["to_issue"] == "issue-b"

    @pytest.mark.composio
    def test_relation_type_mapping(self):
        """Relation type strings are mapped correctly before the API call."""
        relation_success = {
            "issueRelationCreate": {
                "success": True,
                "issueRelation": {"id": "rel-2", "type": "blocked_by"},
            }
        }
        _, mock_gql = _call(
            "CUSTOM_CREATE_ISSUE_RELATION",
            CreateIssueRelationInput(
                issue_id="issue-a",
                related_issue_id="issue-b",
                relation_type="is_blocked_by",
            ),
            return_values=[relation_success],
        )
        variables = mock_gql.call_args[0][1]
        assert variables["type"] == "blocked_by"

    @pytest.mark.composio
    def test_create_relation_failure_raises(self):
        """Raises RuntimeError when the API reports failure."""
        failure = {"issueRelationCreate": {"success": False, "issueRelation": None}}
        with patch(
            "app.agents.tools.integrations.linear_tool.graphql_request",
            return_value=failure,
        ):
            with pytest.raises(RuntimeError, match="Failed to create relation"):
                _TOOLS["CUSTOM_CREATE_ISSUE_RELATION"](
                    CreateIssueRelationInput(
                        issue_id="a",
                        related_issue_id="b",
                        relation_type="relates_to",
                    ),
                    EXECUTE_REQUEST,
                    AUTH,
                )

    @pytest.mark.composio
    def test_relates_to_mapped_to_related(self):
        """'relates_to' input maps to 'related' in the Linear API call."""
        relation_success = {
            "issueRelationCreate": {
                "success": True,
                "issueRelation": {"id": "rel-3", "type": "related"},
            }
        }
        _, mock_gql = _call(
            "CUSTOM_CREATE_ISSUE_RELATION",
            CreateIssueRelationInput(
                issue_id="a", related_issue_id="b", relation_type="relates_to"
            ),
            return_values=[relation_success],
        )
        variables = mock_gql.call_args[0][1]
        assert variables["type"] == "related"


# ===========================================================================
# CUSTOM_GET_ISSUE_ACTIVITY
# ===========================================================================


class TestGetIssueActivity:
    @pytest.mark.composio
    def test_activity_by_issue_id(self):
        """Returns formatted activity entries for a known issue_id."""
        history_response = {
            "issue": {
                "history": {
                    "nodes": [
                        {
                            "id": "h1",
                            "createdAt": "2024-02-01T00:00:00Z",
                            "actor": {"id": "user-1", "name": "Alice"},
                            "fromState": {"id": "s0", "name": "Backlog"},
                            "toState": {"id": "s1", "name": "In Progress"},
                            "fromAssignee": None,
                            "toAssignee": None,
                            "fromPriority": None,
                            "toPriority": None,
                            "addedLabels": {"nodes": []},
                            "removedLabels": {"nodes": []},
                        }
                    ]
                }
            }
        }
        result, _ = _call(
            "CUSTOM_GET_ISSUE_ACTIVITY",
            GetIssueActivityInput(issue_id="issue-abc"),
            return_values=[history_response],
        )
        assert result["activity_count"] == 1
        assert result["activities"][0]["change_type"] == "state"
        assert result["activities"][0]["from"] == "Backlog"
        assert result["activities"][0]["to"] == "In Progress"

    @pytest.mark.composio
    def test_no_issue_id_raises(self):
        """Raises ValueError when neither issue_id nor issue_identifier is given."""
        with patch("app.agents.tools.integrations.linear_tool.graphql_request"):
            with pytest.raises(ValueError, match="Could not resolve issue"):
                _TOOLS["CUSTOM_GET_ISSUE_ACTIVITY"](
                    GetIssueActivityInput(), EXECUTE_REQUEST, AUTH
                )

    @pytest.mark.composio
    def test_activity_by_identifier(self):
        """Resolves issue_identifier to an ID before fetching history."""
        identifier_response = {"issue": {"id": "issue-abc", "identifier": "ENG-1"}}
        history_response = {
            "issue": {
                "history": {
                    "nodes": [
                        {
                            "id": "h2",
                            "createdAt": "2024-02-02T00:00:00Z",
                            "actor": None,
                            "fromAssignee": {"id": "u0", "name": "Old Assignee"},
                            "toAssignee": {"id": "u1", "name": "New Assignee"},
                            "fromState": None,
                            "toState": None,
                            "fromPriority": None,
                            "toPriority": None,
                            "addedLabels": {"nodes": []},
                            "removedLabels": {"nodes": []},
                        }
                    ]
                }
            }
        }
        result, _ = _call(
            "CUSTOM_GET_ISSUE_ACTIVITY",
            GetIssueActivityInput(issue_identifier="ENG-1"),
            return_values=[identifier_response, history_response],
        )
        assert result["activity_count"] == 1
        assert result["activities"][0]["change_type"] == "assignee"

    @pytest.mark.composio
    def test_priority_change_activity(self):
        """Priority change history entries are categorised as 'priority'."""
        history_response = {
            "issue": {
                "history": {
                    "nodes": [
                        {
                            "id": "h3",
                            "createdAt": "2024-02-03T00:00:00Z",
                            "actor": {"id": "u1", "name": "Bob"},
                            "fromState": None,
                            "toState": None,
                            "fromAssignee": None,
                            "toAssignee": None,
                            "fromPriority": 4,
                            "toPriority": 1,
                            "addedLabels": {"nodes": []},
                            "removedLabels": {"nodes": []},
                        }
                    ]
                }
            }
        }
        result, _ = _call(
            "CUSTOM_GET_ISSUE_ACTIVITY",
            GetIssueActivityInput(issue_id="issue-abc"),
            return_values=[history_response],
        )
        assert result["activities"][0]["change_type"] == "priority"
        assert result["activities"][0]["from"] == "low"
        assert result["activities"][0]["to"] == "urgent"

    @pytest.mark.composio
    def test_empty_history_returns_zero_count(self):
        """Returns activity_count=0 when the issue has no history entries."""
        result, _ = _call(
            "CUSTOM_GET_ISSUE_ACTIVITY",
            GetIssueActivityInput(issue_id="issue-abc"),
            return_values=[{"issue": {"history": {"nodes": []}}}],
        )
        assert result["activity_count"] == 0
        assert result["activities"] == []


# ===========================================================================
# CUSTOM_GET_ACTIVE_SPRINT
# ===========================================================================

CYCLE_NODE = {
    "id": "cycle-1",
    "name": "Sprint 5",
    "number": 5,
    "startsAt": "2024-01-01T00:00:00Z",
    "endsAt": "2024-01-14T00:00:00Z",
    "progress": 0.6,
    "team": {"id": "team-1", "key": "ENG", "name": "Engineering"},
    "issues": {
        "nodes": [
            {
                "id": "i1",
                "identifier": "ENG-1",
                "title": "Task A",
                "state": {"name": "In Progress", "type": "started"},
                "priority": 2,
                "assignee": {"name": "Alice"},
            },
            {
                "id": "i2",
                "identifier": "ENG-2",
                "title": "Task B",
                "state": {"name": "Todo", "type": "unstarted"},
                "priority": 3,
                "assignee": None,
            },
        ]
    },
}


class TestGetActiveSprint:
    @pytest.mark.composio
    def test_returns_active_cycles(self):
        """Returns sprint details including progress and issue breakdown."""
        result, mock_gql = _call(
            "CUSTOM_GET_ACTIVE_SPRINT",
            GetActiveSprintInput(),
            return_values=[{"cycles": {"nodes": [CYCLE_NODE]}}],
        )
        assert result["sprint_count"] == 1
        sprint = result["sprints"][0]
        assert sprint["name"] == "Sprint 5"
        assert sprint["progress"] == pytest.approx(60.0)
        assert sprint["team"] == "Engineering"
        mock_gql.assert_called_once()

    @pytest.mark.composio
    def test_team_filter(self):
        """Only cycles matching team_id are returned."""
        other_cycle = {
            **CYCLE_NODE,
            "id": "cycle-2",
            "team": {"id": "team-99", "key": "PROD", "name": "Product"},
        }
        result, _ = _call(
            "CUSTOM_GET_ACTIVE_SPRINT",
            GetActiveSprintInput(team_id="team-1"),
            return_values=[{"cycles": {"nodes": [CYCLE_NODE, other_cycle]}}],
        )
        assert result["sprint_count"] == 1
        assert result["sprints"][0]["team_key"] == "ENG"

    @pytest.mark.composio
    def test_issues_grouped_by_state(self):
        """Issues are split into in_progress / todo buckets."""
        result, _ = _call(
            "CUSTOM_GET_ACTIVE_SPRINT",
            GetActiveSprintInput(),
            return_values=[{"cycles": {"nodes": [CYCLE_NODE]}}],
        )
        sprint = result["sprints"][0]
        assert sprint["issues_by_state"]["started"] == 1
        assert sprint["issues_by_state"]["unstarted"] == 1
        assert any(i["identifier"] == "ENG-1" for i in sprint["in_progress"])
        assert any(i["identifier"] == "ENG-2" for i in sprint["todo"])

    @pytest.mark.composio
    def test_no_active_cycles(self):
        """Returns sprint_count=0 and empty list when no cycles are active."""
        result, _ = _call(
            "CUSTOM_GET_ACTIVE_SPRINT",
            GetActiveSprintInput(),
            return_values=[{"cycles": {"nodes": []}}],
        )
        assert result["sprint_count"] == 0
        assert result["sprints"] == []


# ===========================================================================
# CUSTOM_BULK_UPDATE_ISSUES
# ===========================================================================


class TestBulkUpdateIssues:
    @pytest.mark.composio
    def test_bulk_update_happy_path(self):
        """Happy path: updates multiple issues and returns count."""
        update_success = {
            "issueBatchUpdate": {
                "success": True,
                "issues": [
                    {"id": "i1", "identifier": "ENG-1"},
                    {"id": "i2", "identifier": "ENG-2"},
                ],
            }
        }
        result, _ = _call(
            "CUSTOM_BULK_UPDATE_ISSUES",
            BulkUpdateIssuesInput(
                issue_ids=["i1", "i2"],
                state_id="state-done",
            ),
            return_values=[update_success],
        )
        assert result["updated_count"] == 2
        identifiers = [i["identifier"] for i in result["updated_issues"]]
        assert "ENG-1" in identifiers
        assert "ENG-2" in identifiers

    @pytest.mark.composio
    def test_issue_ids_forwarded_to_graphql(self):
        """Issue IDs and input fields are passed in the mutation variables."""
        update_success = {
            "issueBatchUpdate": {
                "success": True,
                "issues": [{"id": "i1", "identifier": "ENG-1"}],
            }
        }
        _, mock_gql = _call(
            "CUSTOM_BULK_UPDATE_ISSUES",
            BulkUpdateIssuesInput(
                issue_ids=["i1"],
                priority=1,
                assignee_id="user-2",
            ),
            return_values=[update_success],
        )
        variables = mock_gql.call_args[0][1]
        assert variables["issueIds"] == ["i1"]
        assert variables["input"]["priority"] == 1
        assert variables["input"]["assigneeId"] == "user-2"

    @pytest.mark.composio
    def test_empty_issue_ids_raises(self):
        """Raises ValueError when issue_ids list is empty."""
        with patch("app.agents.tools.integrations.linear_tool.graphql_request"):
            with pytest.raises(ValueError, match="No issue IDs provided"):
                _TOOLS["CUSTOM_BULK_UPDATE_ISSUES"](
                    BulkUpdateIssuesInput(issue_ids=[]),
                    EXECUTE_REQUEST,
                    AUTH,
                )

    @pytest.mark.composio
    def test_no_update_fields_raises(self):
        """Raises ValueError when no update fields are provided."""
        with patch("app.agents.tools.integrations.linear_tool.graphql_request"):
            with pytest.raises(ValueError, match="No updates specified"):
                _TOOLS["CUSTOM_BULK_UPDATE_ISSUES"](
                    BulkUpdateIssuesInput(issue_ids=["i1"]),
                    EXECUTE_REQUEST,
                    AUTH,
                )

    @pytest.mark.composio
    def test_api_failure_raises(self):
        """Raises RuntimeError when the batch update API reports failure."""
        failure = {"issueBatchUpdate": {"success": False, "issues": []}}
        with patch(
            "app.agents.tools.integrations.linear_tool.graphql_request",
            return_value=failure,
        ):
            with pytest.raises(RuntimeError, match="Batch update failed"):
                _TOOLS["CUSTOM_BULK_UPDATE_ISSUES"](
                    BulkUpdateIssuesInput(issue_ids=["i1"], state_id="s1"),
                    EXECUTE_REQUEST,
                    AUTH,
                )

    @pytest.mark.composio
    def test_labels_to_add_forwarded(self):
        """labels_to_add is forwarded as labelIds in the mutation."""
        update_success = {
            "issueBatchUpdate": {
                "success": True,
                "issues": [{"id": "i1", "identifier": "ENG-1"}],
            }
        }
        _, mock_gql = _call(
            "CUSTOM_BULK_UPDATE_ISSUES",
            BulkUpdateIssuesInput(issue_ids=["i1"], labels_to_add=["lbl-1", "lbl-2"]),
            return_values=[update_success],
        )
        variables = mock_gql.call_args[0][1]
        assert variables["input"]["labelIds"] == ["lbl-1", "lbl-2"]


# ===========================================================================
# CUSTOM_GET_NOTIFICATIONS
# ===========================================================================

NOTIFICATION_NODE_UNREAD = {
    "id": "notif-1",
    "type": "issueAssignedToYou",
    "createdAt": "2024-03-01T00:00:00Z",
    "readAt": None,
    "issue": {"id": "issue-abc", "identifier": "ENG-1", "title": "Fix the thing"},
    "actor": {"id": "user-2", "name": "Bob"},
}

NOTIFICATION_NODE_READ = {
    **NOTIFICATION_NODE_UNREAD,
    "id": "notif-2",
    "readAt": "2024-03-02T00:00:00Z",
}


class TestGetNotifications:
    @pytest.mark.composio
    def test_returns_unread_only_by_default(self):
        """Only unread notifications are returned when include_read=False."""
        result, _ = _call(
            "CUSTOM_GET_NOTIFICATIONS",
            GetNotificationsInput(),
            return_values=[
                {
                    "notifications": {
                        "nodes": [NOTIFICATION_NODE_UNREAD, NOTIFICATION_NODE_READ]
                    }
                }
            ],
        )
        assert result["count"] == 1
        assert result["notifications"][0]["id"] == "notif-1"
        assert not result["notifications"][0]["read"]

    @pytest.mark.composio
    def test_include_read_returns_all(self):
        """Both read and unread notifications are returned when include_read=True."""
        result, _ = _call(
            "CUSTOM_GET_NOTIFICATIONS",
            GetNotificationsInput(include_read=True),
            return_values=[
                {
                    "notifications": {
                        "nodes": [NOTIFICATION_NODE_UNREAD, NOTIFICATION_NODE_READ]
                    }
                }
            ],
        )
        assert result["count"] == 2

    @pytest.mark.composio
    def test_notification_fields_present(self):
        """Each notification entry has the expected fields."""
        result, _ = _call(
            "CUSTOM_GET_NOTIFICATIONS",
            GetNotificationsInput(),
            return_values=[{"notifications": {"nodes": [NOTIFICATION_NODE_UNREAD]}}],
        )
        notif = result["notifications"][0]
        assert notif["type"] == "issueAssignedToYou"
        assert notif["actor"] == "Bob"
        assert notif["issue"]["identifier"] == "ENG-1"

    @pytest.mark.composio
    def test_limit_forwarded_to_graphql(self):
        """The limit parameter is passed to the GraphQL variables."""
        _, mock_gql = _call(
            "CUSTOM_GET_NOTIFICATIONS",
            GetNotificationsInput(limit=10),
            return_values=[{"notifications": {"nodes": []}}],
        )
        variables = mock_gql.call_args[0][1]
        assert variables["first"] == 10

    @pytest.mark.composio
    def test_no_notifications_returns_empty(self):
        """Returns count=0 when there are no notifications."""
        result, _ = _call(
            "CUSTOM_GET_NOTIFICATIONS",
            GetNotificationsInput(),
            return_values=[{"notifications": {"nodes": []}}],
        )
        assert result["count"] == 0
        assert result["notifications"] == []


# ===========================================================================
# CUSTOM_GET_WORKSPACE_CONTEXT
# ===========================================================================

VIEWER_WITH_ISSUES = {
    "viewer": {
        "id": "user-1",
        "name": "Alice",
        "email": "alice@example.com",
        "assignedIssues": {"nodes": [{"id": "issue-abc"}]},
    }
}

TEAMS_RESPONSE = {
    "teams": {
        "nodes": [
            {
                "id": "team-1",
                "name": "Engineering",
                "key": "ENG",
                "activeCycle": {"id": "c1", "name": "Sprint 5", "progress": 0.6},
            }
        ]
    }
}

WORKSPACE_ISSUES_RESPONSE = {
    "issues": {
        "nodes": [
            {
                **ISSUE_NODE,
                "priority": 1,
                "dueDate": "2000-01-01",  # overdue
                "slaBreachesAt": "2024-01-10T00:00:00Z",
            }
        ]
    }
}


class TestGetWorkspaceContext:
    @pytest.mark.composio
    def test_returns_user_teams_and_urgent_items(self):
        """Returns viewer info, teams, and categorised urgent items."""
        result, mock_gql = _call(
            "CUSTOM_GET_WORKSPACE_CONTEXT",
            GetWorkspaceContextInput(),
            return_values=[
                VIEWER_WITH_ISSUES,
                TEAMS_RESPONSE,
                WORKSPACE_ISSUES_RESPONSE,
            ],
        )
        assert result["user"]["name"] == "Alice"
        assert result["user"]["assigned_issue_count"] == 1
        assert result["teams"][0]["name"] == "Engineering"
        assert result["teams"][0]["active_cycle"] == "Sprint 5"
        assert result["teams"][0]["cycle_progress"] == 60.0
        assert mock_gql.call_count == 3

    @pytest.mark.composio
    def test_overdue_issues_surfaced(self):
        """Issues with past due dates appear in urgent_items.overdue."""
        result, _ = _call(
            "CUSTOM_GET_WORKSPACE_CONTEXT",
            GetWorkspaceContextInput(),
            return_values=[
                VIEWER_WITH_ISSUES,
                TEAMS_RESPONSE,
                WORKSPACE_ISSUES_RESPONSE,
            ],
        )
        assert len(result["urgent_items"]["overdue"]) >= 1

    @pytest.mark.composio
    def test_high_priority_issues_surfaced(self):
        """P1/P2 issues appear in urgent_items.high_priority."""
        result, _ = _call(
            "CUSTOM_GET_WORKSPACE_CONTEXT",
            GetWorkspaceContextInput(),
            return_values=[
                VIEWER_WITH_ISSUES,
                TEAMS_RESPONSE,
                WORKSPACE_ISSUES_RESPONSE,
            ],
        )
        assert len(result["urgent_items"]["high_priority"]) >= 1

    @pytest.mark.composio
    def test_sla_at_risk_issues_surfaced(self):
        """Issues with slaBreachesAt appear in urgent_items.sla_at_risk."""
        result, _ = _call(
            "CUSTOM_GET_WORKSPACE_CONTEXT",
            GetWorkspaceContextInput(),
            return_values=[
                VIEWER_WITH_ISSUES,
                TEAMS_RESPONSE,
                WORKSPACE_ISSUES_RESPONSE,
            ],
        )
        assert len(result["urgent_items"]["sla_at_risk"]) >= 1

    @pytest.mark.composio
    def test_completed_issues_excluded_from_urgent(self):
        """Completed/canceled issues are not counted as urgent."""
        completed_issue_response = {
            "issues": {
                "nodes": [
                    {
                        **ISSUE_NODE,
                        "priority": 1,
                        "dueDate": "2000-01-01",
                        "slaBreachesAt": None,
                        "state": {"id": "s9", "name": "Done", "type": "completed"},
                    }
                ]
            }
        }
        result, _ = _call(
            "CUSTOM_GET_WORKSPACE_CONTEXT",
            GetWorkspaceContextInput(),
            return_values=[
                VIEWER_WITH_ISSUES,
                TEAMS_RESPONSE,
                completed_issue_response,
            ],
        )
        assert result["urgent_items"]["overdue"] == []
        assert result["urgent_items"]["high_priority"] == []

    @pytest.mark.composio
    def test_graphql_error_propagates(self):
        """Errors from any graphql_request call surface as exceptions."""
        with patch(
            "app.agents.tools.integrations.linear_tool.graphql_request",
            side_effect=Exception("GraphQL errors: token expired"),
        ):
            with pytest.raises(Exception, match="token expired"):
                _TOOLS["CUSTOM_GET_WORKSPACE_CONTEXT"](
                    GetWorkspaceContextInput(), EXECUTE_REQUEST, AUTH
                )
