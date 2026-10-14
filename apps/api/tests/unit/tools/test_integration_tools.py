"""Unit tests for the Linear custom tools (linear_tool.py).

Strategy: register_linear_custom_tools decorates inner functions with
@composio.tools.custom_tool(); a capturing Composio mock records them so
they can be called directly. The only seam faked is the Composio proxy under
linear_utils.graphql_request, so every response runs through the real
GraphQL envelope parsing and the typed Linear models, fed with fixtures shaped
like Linear's schema (every field the operation selects).
"""

from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

from pydantic import ValidationError
import pytest

from app.agents.tools.integrations.linear_tool import register_linear_custom_tools
from app.models.common_models import GatherContextInput
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
)

LINEAR_MODULE = "app.agents.tools.integrations.linear_tool"
PROXY = "app.utils.linear_utils.proxy_request_sync"
USER_ID = "user-123"
AUTH_CREDS: dict[str, Any] = {"user_id": USER_ID, "version": "v1"}
EXECUTE_REQUEST = MagicMock()


def _capture_tools() -> dict[str, Any]:
    composio = MagicMock()
    captured: dict[str, Any] = {}

    def capturing_custom_tool(**_kwargs: Any) -> Any:
        def wrapper(fn: Any) -> Any:
            captured[fn.__name__] = fn
            return fn

        return wrapper

    composio.tools.custom_tool = capturing_custom_tool
    register_linear_custom_tools(composio)
    return captured


@pytest.fixture
def tools() -> dict[str, Any]:
    return _capture_tools()


@pytest.fixture
def proxy() -> Iterator[MagicMock]:
    with patch(PROXY) as mock:
        yield mock


def _answers(proxy: MagicMock, *datas: dict[str, Any]) -> None:
    """Answer successive GraphQL calls with {"data": ...} in order."""
    proxy.side_effect = [{"data": d} for d in datas]


def _bodies(proxy: MagicMock) -> list[dict[str, Any]]:
    return [c.args[0].body for c in proxy.call_args_list]


def _operations(proxy: MagicMock) -> list[tuple[str, str]]:
    """(user the call is attributed to, GraphQL document) for every proxied call, in order."""
    return [(c.args[0].user_id, c.args[0].body["query"]) for c in proxy.call_args_list]


VIEWER = {
    "viewer": {
        "id": "u1",
        "name": "Alice",
        "email": "a@b.com",
        "assignedIssues": {"nodes": [{"id": "x"}]},
    }
}
TEAM = {"id": "t1", "key": "ENG", "name": "Eng"}


def _summary(issue_id: str, **overrides: Any) -> dict[str, Any]:
    """Build an issue as QUERY_MY_ISSUES / QUERY_SEARCH_ISSUES select it."""
    node: dict[str, Any] = {
        "id": issue_id,
        "identifier": f"ENG-{issue_id}",
        "title": f"Task {issue_id}",
        "priority": 3,
        "state": {"id": "s1", "name": "In Progress", "type": "started"},
        "dueDate": None,
        "team": TEAM,
        "cycle": None,
        "parent": None,
        "assignee": None,
    }
    node.update(overrides)
    return node


def _full_issue(**overrides: Any) -> dict[str, Any]:
    """Build an issue as QUERY_ISSUE_BY_ID selects it."""
    node: dict[str, Any] = {
        "id": "i1",
        "identifier": "ENG-1",
        "title": "Bug",
        "description": "desc",
        "priority": 1,
        "state": {"id": "s1", "name": "In Progress", "type": "started"},
        "dueDate": None,
        "estimate": 3,
        "team": TEAM,
        "cycle": None,
        "project": {"id": "p1", "name": "GAIA"},
        "assignee": {"id": "u1", "name": "Alice", "email": "a@b.com"},
        "creator": {"id": "u2", "name": "Bob"},
        "parent": None,
        "children": {"nodes": []},
        "relations": {"nodes": []},
        "comments": {"nodes": []},
        "history": {"nodes": []},
        "attachments": {"nodes": []},
    }
    node.update(overrides)
    return node


def _history(**overrides: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": "h1",
        "createdAt": "2024-01-01",
        "actor": {"id": "u1", "name": "Alice"},
        "fromState": None,
        "toState": None,
        "fromAssignee": None,
        "toAssignee": None,
        "fromPriority": None,
        "toPriority": None,
        "addedLabels": None,
        "removedLabels": None,
    }
    entry.update(overrides)
    return entry


# =============================================================================
# CUSTOM_RESOLVE_CONTEXT
# =============================================================================


class TestLinearResolveContext:
    def test_resolve_context_basic(self, tools, proxy) -> None:
        _answers(proxy, VIEWER)

        result = tools["CUSTOM_RESOLVE_CONTEXT"](ResolveContextInput(), EXECUTE_REQUEST, AUTH_CREDS)

        assert result == {
            "data": {"current_user": {"id": "u1", "name": "Alice", "email": "a@b.com"}}
        }
        assert _operations(proxy) == [(USER_ID, QUERY_VIEWER)]

    def test_resolve_context_with_team_name(self, tools, proxy) -> None:
        eng = {**TEAM, "activeCycle": {"id": "c1", "name": "Sprint 5", "progress": 0.5}}
        design = {"id": "t2", "key": "DES", "name": "Design", "activeCycle": None}
        _answers(proxy, VIEWER, {"teams": {"nodes": [design, eng]}})

        result = tools["CUSTOM_RESOLVE_CONTEXT"](
            ResolveContextInput(team_name="eng"), EXECUTE_REQUEST, AUTH_CREDS
        )

        assert result["data"]["teams"] == [
            {
                "id": "t1",
                "name": "Eng",
                "key": "ENG",
                "activeCycle": {"id": "c1", "name": "Sprint 5", "progress": 0.5},
            },
            # "eng" is within SequenceMatcher's 0.4 threshold of "design".
            {"id": "t2", "name": "Design", "key": "DES", "activeCycle": None},
        ]
        assert _operations(proxy) == [(USER_ID, QUERY_VIEWER), (USER_ID, QUERY_TEAMS)]

    def test_resolve_context_with_user_name(self, tools, proxy) -> None:
        _answers(
            proxy,
            VIEWER,
            {
                "users": {
                    "nodes": [
                        {"id": "u2", "name": "Bob", "email": "b@b.com", "active": True},
                        {"id": "u3", "name": "Bobby", "email": "c@b.com", "active": False},
                        {"id": "u4", "name": "Zed", "email": "z@b.com", "active": True},
                    ]
                }
            },
        )

        result = tools["CUSTOM_RESOLVE_CONTEXT"](
            ResolveContextInput(user_name="bob"), EXECUTE_REQUEST, AUTH_CREDS
        )

        assert result["data"]["users"] == [
            {"id": "u2", "name": "Bob", "email": "b@b.com", "active": True}
        ]
        assert _operations(proxy) == [(USER_ID, QUERY_VIEWER), (USER_ID, QUERY_USERS)]

    @pytest.mark.parametrize(
        ("request_fields", "data_key", "extra_fields", "result_key"),
        [
            ({"team_name": "eng"}, "teams", {"key": "ENG"}, "teams"),
            ({"user_name": "eng"}, "users", {"email": "e@b.com", "active": True}, "users"),
            (
                {"project_name": "eng"},
                "projects",
                {"state": "started", "progress": 0.1},
                "projects",
            ),
            (
                {"state_name": "eng", "team_id": "t1"},
                "workflowStates",
                {"type": "started", "position": 1.0},
                "states",
            ),
        ],
    )
    def test_resolve_context_returns_at_most_three_matches_per_lookup(
        self, tools, proxy, request_fields, data_key, extra_fields, result_key
    ) -> None:
        nodes = [{"id": f"n{i}", "name": f"Eng {i}", **extra_fields} for i in range(4)]
        _answers(proxy, VIEWER, {data_key: {"nodes": nodes}})

        result = tools["CUSTOM_RESOLVE_CONTEXT"](
            ResolveContextInput(**request_fields), EXECUTE_REQUEST, AUTH_CREDS
        )

        assert [node["id"] for node in result["data"][result_key]] == ["n0", "n1", "n2"]

    def test_resolve_context_matches_one_label_per_name_for_the_first_three_names(
        self, tools, proxy
    ) -> None:
        labels = [
            {"id": f"l-{name.lower()}", "name": name, "color": "#fff"}
            for name in ("Bug", "Bugfix", "Feature", "Docs", "Perf")
        ]
        _answers(proxy, VIEWER, {"issueLabels": {"nodes": labels}})

        result = tools["CUSTOM_RESOLVE_CONTEXT"](
            ResolveContextInput(label_names=["bug", "feat", "docs", "perf"]),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

        assert [label["id"] for label in result["data"]["labels"]] == [
            "l-bug",
            "l-feature",
            "l-docs",
        ]

    def test_resolve_context_labels_with_team_id(self, tools, proxy) -> None:
        _answers(
            proxy,
            VIEWER,
            {"issueLabels": {"nodes": [{"id": "l1", "name": "Bug", "color": "#f00"}]}},
        )

        result = tools["CUSTOM_RESOLVE_CONTEXT"](
            ResolveContextInput(label_names=["bug"], team_id="t1"), EXECUTE_REQUEST, AUTH_CREDS
        )

        assert result["data"]["labels"] == [{"id": "l1", "name": "Bug", "color": "#f00"}]
        assert _bodies(proxy)[1] == {"query": QUERY_LABELS, "variables": {"teamId": "t1"}}
        assert _operations(proxy)[1] == (USER_ID, QUERY_LABELS)

    def test_resolve_context_labels_without_team_id(self, tools, proxy) -> None:
        _answers(
            proxy,
            VIEWER,
            {
                "issueLabels": {
                    "nodes": [
                        {"id": "l1", "name": "Bug", "color": "#f00"},
                        {"id": "l2", "name": "Feature", "color": "#0f0"},
                    ]
                }
            },
        )

        result = tools["CUSTOM_RESOLVE_CONTEXT"](
            ResolveContextInput(label_names=["bug", "feat"]), EXECUTE_REQUEST, AUTH_CREDS
        )

        assert [label["id"] for label in result["data"]["labels"]] == ["l1", "l2"]
        assert _bodies(proxy)[1] == {"query": QUERY_LABELS_ALL}
        assert _operations(proxy)[1] == (USER_ID, QUERY_LABELS_ALL)

    def test_resolve_context_with_project_name(self, tools, proxy) -> None:
        _answers(
            proxy,
            VIEWER,
            {
                "projects": {
                    "nodes": [
                        {"id": "p1", "name": "GAIA", "state": "started", "progress": 0.2},
                        {"id": "p2", "name": "Zulu", "state": "started", "progress": 0.9},
                    ]
                }
            },
        )

        result = tools["CUSTOM_RESOLVE_CONTEXT"](
            ResolveContextInput(project_name="gaia"), EXECUTE_REQUEST, AUTH_CREDS
        )

        assert result["data"]["projects"] == [
            {"id": "p1", "name": "GAIA", "state": "started", "progress": 0.2}
        ]
        assert _operations(proxy) == [(USER_ID, QUERY_VIEWER), (USER_ID, QUERY_PROJECTS)]

    def test_resolve_context_with_state_and_team(self, tools, proxy) -> None:
        _answers(
            proxy,
            VIEWER,
            {
                "workflowStates": {
                    "nodes": [
                        {"id": "s1", "name": "In Progress", "type": "started", "position": 2.0},
                        {"id": "s2", "name": "Xyz", "type": "backlog", "position": 0.0},
                    ]
                }
            },
        )

        result = tools["CUSTOM_RESOLVE_CONTEXT"](
            ResolveContextInput(state_name="progress", team_id="t1"), EXECUTE_REQUEST, AUTH_CREDS
        )

        assert result["data"]["states"] == [
            {"id": "s1", "name": "In Progress", "type": "started", "position": 2.0}
        ]
        assert _bodies(proxy)[1] == {"query": QUERY_STATES, "variables": {"teamId": "t1"}}
        assert _operations(proxy)[1] == (USER_ID, QUERY_STATES)


# =============================================================================
# CUSTOM_GET_MY_TASKS
# =============================================================================


class TestLinearGetMyTasks:
    def _run(self, tools, proxy, request: GetMyTasksInput, *nodes: dict[str, Any]) -> Any:
        _answers(proxy, VIEWER, {"issues": {"nodes": list(nodes)}})
        with patch(f"{LINEAR_MODULE}._user_local_today", return_value=datetime.now().date()):
            return tools["CUSTOM_GET_MY_TASKS"](request, EXECUTE_REQUEST, AUTH_CREDS)

    def test_get_my_tasks_all_filter(self, tools, proxy) -> None:
        result = self._run(
            tools,
            proxy,
            GetMyTasksInput(filter="all", limit=10),
            _summary("2", priority=3),
            _summary("1", priority=1, assignee={"id": "u1", "name": "Alice"}),
        )

        assert result["filter"] == "all"
        assert result["count"] == 2
        assert result["issues"][0] == {
            "id": "1",
            "identifier": "ENG-1",
            "title": "Task 1",
            "state": "In Progress",
            "priority": "urgent",
            "assignee": "Alice",
            "dueDate": None,
            "team": "ENG",
            "cycle": None,
            "parent": None,
        }
        assert _bodies(proxy)[1]["variables"] == {
            "assigneeId": "u1",
            "includeCompleted": True,
            "first": 20,
        }
        assert _operations(proxy) == [(USER_ID, QUERY_VIEWER), (USER_ID, QUERY_MY_ISSUES)]

    def test_get_my_tasks_sorts_by_priority_then_due_date_with_undated_last(
        self, tools, proxy
    ) -> None:
        result = self._run(
            tools,
            proxy,
            GetMyTasksInput(filter="all"),
            _summary("undated", priority=2),
            _summary("february", priority=2, dueDate="2024-02-01"),
            _summary("january", priority=2, dueDate="2024-01-01"),
            _summary("urgent", priority=1),
        )

        assert [i["id"] for i in result["issues"]] == ["urgent", "january", "february", "undated"]

    def test_get_my_tasks_no_viewer(self, tools, proxy) -> None:
        """Linear's schema makes viewer non-null: a body without it is a provider fault."""
        _answers(proxy, {})

        with pytest.raises(ValidationError):
            tools["CUSTOM_GET_MY_TASKS"](GetMyTasksInput(), EXECUTE_REQUEST, AUTH_CREDS)

    def test_get_my_tasks_high_priority_filter(self, tools, proxy) -> None:
        result = self._run(
            tools,
            proxy,
            GetMyTasksInput(filter="high_priority"),
            _summary("1", priority=1),
            _summary("2", priority=4),
        )
        assert [i["id"] for i in result["issues"]] == ["1"]

    def test_get_my_tasks_overdue_filter(self, tools, proxy) -> None:
        yesterday = (datetime.now().date() - timedelta(days=1)).isoformat()
        today = datetime.now().date().isoformat()
        result = self._run(
            tools,
            proxy,
            GetMyTasksInput(filter="overdue"),
            _summary("1", dueDate=yesterday),
            _summary("2"),
            _summary("3", dueDate=today),
        )
        assert [i["id"] for i in result["issues"]] == ["1"]

    def test_get_my_tasks_excludes_completed(self, tools, proxy) -> None:
        result = self._run(
            tools,
            proxy,
            GetMyTasksInput(filter="all", include_completed=False),
            _summary("1", state={"id": "s9", "name": "Done", "type": "completed"}),
            _summary("2"),
        )
        assert [i["id"] for i in result["issues"]] == ["2"]

    def test_get_my_tasks_today_filter(self, tools, proxy) -> None:
        today = datetime.now().date().isoformat()
        result = self._run(
            tools,
            proxy,
            GetMyTasksInput(filter="today"),
            _summary("1", dueDate=today),
            _summary("2"),
        )
        assert [i["id"] for i in result["issues"]] == ["1"]

    def test_get_my_tasks_this_week_filter(self, tools, proxy) -> None:
        def in_days(days: int) -> str:
            return (datetime.now().date() + timedelta(days=days)).isoformat()

        result = self._run(
            tools,
            proxy,
            GetMyTasksInput(filter="this_week"),
            _summary("1", dueDate=in_days(1)),
            _summary("2", dueDate=in_days(30)),
            _summary("today", dueDate=in_days(0)),
            _summary("week_end", dueDate=in_days(7)),
            _summary("past_week_end", dueDate=in_days(8)),
        )
        assert [i["id"] for i in result["issues"]] == ["today", "1", "week_end"]


# =============================================================================
# CUSTOM_SEARCH_ISSUES
# =============================================================================


def _search_node(issue_id: str, **overrides: Any) -> dict[str, Any]:
    return _summary(issue_id, **{"createdAt": "2024-01-01", **overrides})


class TestLinearSearchIssues:
    def _run(self, tools, proxy, request: SearchIssuesInput, *nodes: dict[str, Any]) -> Any:
        _answers(proxy, {"searchIssues": {"nodes": list(nodes)}})
        return tools["CUSTOM_SEARCH_ISSUES"](request, EXECUTE_REQUEST, AUTH_CREDS)

    def test_search_issues_basic(self, tools, proxy) -> None:
        result = self._run(tools, proxy, SearchIssuesInput(query="bug"), _search_node("1"))

        assert result["query"] == "bug"
        assert result["count"] == 1
        assert _bodies(proxy)[0]["variables"] == {"query": "bug", "first": 40}
        assert _operations(proxy) == [(USER_ID, QUERY_SEARCH_ISSUES)]

    # Each filter test lists a rejected issue before a kept one: a rejection must skip, not stop.
    def test_search_issues_with_team_filter(self, tools, proxy) -> None:
        other = {"id": "t2", "key": "DES", "name": "Design"}
        result = self._run(
            tools,
            proxy,
            SearchIssuesInput(query="test", team_id="t1"),
            _search_node("2", team=other),
            _search_node("1"),
        )
        assert [i["id"] for i in result["issues"]] == ["1"]

    def test_search_issues_with_state_filter(self, tools, proxy) -> None:
        result = self._run(
            tools,
            proxy,
            SearchIssuesInput(query="test", state_filter="completed"),
            _search_node("2"),
            _search_node("1", state={"id": "s9", "name": "Done", "type": "completed"}),
        )
        assert [i["id"] for i in result["issues"]] == ["1"]

    def test_search_issues_with_assignee_filter(self, tools, proxy) -> None:
        result = self._run(
            tools,
            proxy,
            SearchIssuesInput(query="test", assignee_id="u1"),
            _search_node("2", assignee={"id": "u2", "name": "Bob"}),
            _search_node("3"),
            _search_node("1", assignee={"id": "u1", "name": "Alice"}),
        )
        assert [i["id"] for i in result["issues"]] == ["1"]

    def test_search_issues_with_priority_filter(self, tools, proxy) -> None:
        result = self._run(
            tools,
            proxy,
            SearchIssuesInput(query="test", priority_filter="urgent"),
            _search_node("2", priority=3),
            _search_node("1", priority=1),
        )
        assert [i["id"] for i in result["issues"]] == ["1"]

    def test_search_issues_with_created_after(self, tools, proxy) -> None:
        result = self._run(
            tools,
            proxy,
            SearchIssuesInput(query="test", created_after="2024-03-01"),
            _search_node("2", createdAt="2024-01-01"),
            _search_node("undated", createdAt=None),
            _search_node("1", createdAt="2024-06-01"),
            _search_node("same_day", createdAt="2024-03-01"),
        )
        assert [i["id"] for i in result["issues"]] == ["1", "same_day"]


# =============================================================================
# CUSTOM_GET_ISSUE_FULL_CONTEXT
# =============================================================================


class TestLinearGetIssueFullContext:
    def test_get_issue_by_id(self, tools, proxy) -> None:
        _answers(proxy, {"issue": _full_issue()})

        result = tools["CUSTOM_GET_ISSUE_FULL_CONTEXT"](
            GetIssueFullContextInput(issue_id="i1"), EXECUTE_REQUEST, AUTH_CREDS
        )

        assert result == {
            "issue": {
                "id": "i1",
                "identifier": "ENG-1",
                "title": "Bug",
                "description": "desc",
                "priority": "urgent",
                "state": "In Progress",
                "dueDate": None,
                "estimate": 3,
                "team": "Eng",
                "project": "GAIA",
                "cycle": None,
                "assignee": "Alice",
                "creator": "Bob",
            }
        }
        assert _bodies(proxy) == [{"query": QUERY_ISSUE_BY_ID, "variables": {"id": "i1"}}]
        assert _operations(proxy) == [(USER_ID, QUERY_ISSUE_BY_ID)]

    def test_get_issue_by_identifier(self, tools, proxy) -> None:
        _answers(proxy, {"issue": _full_issue(identifier="ENG-123")})

        result = tools["CUSTOM_GET_ISSUE_FULL_CONTEXT"](
            GetIssueFullContextInput(issue_identifier="ENG-123"), EXECUTE_REQUEST, AUTH_CREDS
        )

        assert result["issue"]["identifier"] == "ENG-123"
        assert _bodies(proxy)[0]["variables"] == {"id": "ENG-123"}
        assert _operations(proxy) == [(USER_ID, QUERY_ISSUE_BY_ID)]

    def test_get_issue_no_id_or_identifier(self, tools) -> None:
        with pytest.raises(ValueError, match=r"^Provide either issue_id or issue_identifier$"):
            tools["CUSTOM_GET_ISSUE_FULL_CONTEXT"](
                GetIssueFullContextInput(), EXECUTE_REQUEST, AUTH_CREDS
            )

    def test_get_issue_invalid_identifier_format(self, tools, proxy) -> None:
        with pytest.raises(ValueError, match="Invalid identifier format"):
            tools["CUSTOM_GET_ISSUE_FULL_CONTEXT"](
                GetIssueFullContextInput(issue_identifier="BADFORMAT"), EXECUTE_REQUEST, AUTH_CREDS
            )
        proxy.assert_not_called()

    def test_get_issue_invalid_number_in_identifier(self, tools, proxy) -> None:
        with pytest.raises(ValueError, match="Invalid issue number"):
            tools["CUSTOM_GET_ISSUE_FULL_CONTEXT"](
                GetIssueFullContextInput(issue_identifier="ENG-abc"), EXECUTE_REQUEST, AUTH_CREDS
            )
        proxy.assert_not_called()

    def test_get_issue_not_found(self, tools, proxy) -> None:
        """issue(id:) is non-null: Linear answers an unknown id with a GraphQL error."""
        proxy.return_value = {"data": None, "errors": [{"message": "Entity not found: Issue"}]}

        with pytest.raises(Exception, match="GraphQL errors: Entity not found: Issue"):
            tools["CUSTOM_GET_ISSUE_FULL_CONTEXT"](
                GetIssueFullContextInput(issue_id="nonexistent"), EXECUTE_REQUEST, AUTH_CREDS
            )

    def test_get_issue_with_children_and_relations(self, tools, proxy) -> None:
        _answers(
            proxy,
            {
                "issue": _full_issue(
                    parent={"id": "i0", "identifier": "ENG-0", "title": "Grand"},
                    children={
                        "nodes": [
                            {
                                "id": "i2",
                                "identifier": "ENG-2",
                                "title": "Sub",
                                "state": {"name": "Done"},
                            }
                        ]
                    },
                    relations={
                        "nodes": [
                            {
                                "id": "r1",
                                "type": "blocks",
                                "relatedIssue": {"id": "i3", "identifier": "ENG-3", "title": "Dep"},
                            }
                        ]
                    },
                    comments={
                        "nodes": [
                            {
                                "id": "cm1",
                                "body": "comment",
                                "createdAt": "2024-01-01",
                                "user": {"id": "u1", "name": "Alice"},
                            },
                            {"id": "cm2", "body": "bot", "createdAt": "2024-01-02", "user": None},
                        ]
                    },
                    history={
                        "nodes": [
                            _history(
                                fromState={"id": "s0", "name": "Todo", "type": "unstarted"},
                                toState={"id": "s9", "name": "Done", "type": "completed"},
                            ),
                            _history(
                                id="h2", actor=None, removedLabels=[{"id": "l1", "name": "Bug"}]
                            ),
                            _history(id="h3"),
                        ]
                    },
                    attachments={
                        "nodes": [
                            {"id": "a1", "title": "file.pdf", "url": "https://example.com/file.pdf"}
                        ]
                    },
                )
            },
        )

        issue = tools["CUSTOM_GET_ISSUE_FULL_CONTEXT"](
            GetIssueFullContextInput(issue_id="i1"), EXECUTE_REQUEST, AUTH_CREDS
        )["issue"]

        assert issue["parent"] == {"identifier": "ENG-0", "title": "Grand"}
        assert issue["sub_issues"] == [{"identifier": "ENG-2", "title": "Sub", "state": "Done"}]
        assert issue["relations"] == [
            {"type": "blocks", "issue": {"identifier": "ENG-3", "title": "Dep"}}
        ]
        assert issue["comments"] == [
            {"author": "Alice", "body": "comment", "createdAt": "2024-01-01"},
            {"author": None, "body": "bot", "createdAt": "2024-01-02"},
        ]
        assert issue["activity"] == [
            {
                "timestamp": "2024-01-01",
                "actor": "Alice",
                "change": "state",
                "from": "Todo",
                "to": "Done",
            },
            {
                "timestamp": "2024-01-01",
                "actor": None,
                "change": "labels_removed",
                "labels": ["Bug"],
            },
        ]
        assert issue["attachments"] == [
            {"title": "file.pdf", "url": "https://example.com/file.pdf"}
        ]


# =============================================================================
# CUSTOM_CREATE_ISSUE / CUSTOM_CREATE_SUB_ISSUES / CUSTOM_CREATE_ISSUE_RELATION
# =============================================================================


def _created(issue_id: str, title: str) -> dict[str, Any]:
    return {
        "issueCreate": {
            "success": True,
            "issue": {
                "id": issue_id,
                "identifier": f"ENG-{issue_id}",
                "title": title,
                "url": f"https://linear.app/eng-{issue_id}",
            },
        }
    }


class TestLinearCreateIssue:
    def test_create_issue_basic(self, tools, proxy) -> None:
        _answers(proxy, _created("1", "New Bug"))

        result = tools["CUSTOM_CREATE_ISSUE"](
            CreateIssueInput(team_id="t1", title="New Bug"), EXECUTE_REQUEST, AUTH_CREDS
        )

        assert result == {
            "issue": {
                "id": "1",
                "identifier": "ENG-1",
                "title": "New Bug",
                "url": "https://linear.app/eng-1",
            }
        }
        assert _bodies(proxy) == [
            {
                "query": MUTATION_CREATE_ISSUE,
                "variables": {"input": {"teamId": "t1", "title": "New Bug", "priority": 0}},
            }
        ]
        assert _operations(proxy) == [(USER_ID, MUTATION_CREATE_ISSUE)]

    def test_create_issue_failure(self, tools, proxy) -> None:
        _answers(proxy, {"issueCreate": {"success": False, "issue": None}})

        with pytest.raises(RuntimeError, match=r"^Failed to create issue$"):
            tools["CUSTOM_CREATE_ISSUE"](
                CreateIssueInput(team_id="t1", title="Fail"), EXECUTE_REQUEST, AUTH_CREDS
            )

    def test_create_issue_reported_unsuccessful_raises_even_when_an_issue_is_returned(
        self, tools, proxy
    ) -> None:
        _answers(proxy, {"issueCreate": {**_created("1", "Fail")["issueCreate"], "success": False}})

        with pytest.raises(RuntimeError, match=r"^Failed to create issue$"):
            tools["CUSTOM_CREATE_ISSUE"](
                CreateIssueInput(team_id="t1", title="Fail"), EXECUTE_REQUEST, AUTH_CREDS
            )

    def test_create_issue_creates_sub_issues_under_it_and_reports_the_failed_ones(
        self, tools, proxy
    ) -> None:
        unsuccessful = {"issueCreate": {**_created("3", "Sub B")["issueCreate"], "success": False}}
        _answers(proxy, _created("1", "Parent"), _created("2", "Sub A"), unsuccessful)

        result = tools["CUSTOM_CREATE_ISSUE"](
            CreateIssueInput(
                team_id="t1",
                title="Parent",
                sub_issues=[
                    CreateIssueSubItem(
                        title="Sub A", description="Details", assignee_id="u2", priority=2
                    ),
                    CreateIssueSubItem(title="Sub B"),
                ],
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

        assert result == {
            "issue": {
                "id": "1",
                "identifier": "ENG-1",
                "title": "Parent",
                "url": "https://linear.app/eng-1",
            },
            "sub_issues": [{"id": "2", "identifier": "ENG-2", "title": "Sub A"}],
            "sub_issue_errors": [{"title": "Sub B", "error": "Failed to create"}],
        }
        assert [body["variables"] for body in _bodies(proxy)[1:]] == [
            {
                "input": {
                    "teamId": "t1",
                    "title": "Sub A",
                    "parentId": "1",
                    "description": "Details",
                    "assigneeId": "u2",
                    "priority": 2,
                }
            },
            {"input": {"teamId": "t1", "title": "Sub B", "parentId": "1"}},
        ]
        assert _operations(proxy) == [(USER_ID, MUTATION_CREATE_ISSUE)] * 3

    def test_create_issue_with_all_fields(self, tools, proxy) -> None:
        _answers(proxy, _created("1", "Full"))

        tools["CUSTOM_CREATE_ISSUE"](
            CreateIssueInput(
                team_id="t1",
                title="Full",
                description="Desc",
                assignee_id="u1",
                priority=2,
                state_id="s1",
                label_ids=["l1"],
                project_id="p1",
                cycle_id="c1",
                due_date="2024-12-31",
                estimate=5,
                parent_id="parent-1",
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

        assert _bodies(proxy)[0]["variables"] == {
            "input": {
                "teamId": "t1",
                "title": "Full",
                "description": "Desc",
                "assigneeId": "u1",
                "priority": 2,
                "stateId": "s1",
                "labelIds": ["l1"],
                "projectId": "p1",
                "cycleId": "c1",
                "dueDate": "2024-12-31",
                "estimate": 5,
                "parentId": "parent-1",
            }
        }


class TestLinearCreateSubIssues:
    def test_create_sub_issues_with_parent_id(self, tools, proxy) -> None:
        _answers(
            proxy,
            {"issue": _full_issue(id="parent-1")},
            _created("2", "Sub 1"),
            {"issueCreate": {"success": False, "issue": None}},
        )

        result = tools["CUSTOM_CREATE_SUB_ISSUES"](
            CreateSubIssuesInput(
                parent_issue_id="parent-1",
                sub_issues=[SubIssueItem(title="Sub 1", priority=2), SubIssueItem(title="Sub 2")],
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

        assert result == {
            "parent": "parent-1",
            "created_count": 1,
            "sub_issues": [{"id": "2", "identifier": "ENG-2", "title": "Sub 1"}],
        }
        assert _bodies(proxy)[1]["variables"] == {
            "input": {"teamId": "t1", "title": "Sub 1", "parentId": "parent-1", "priority": 2}
        }
        assert _operations(proxy) == [
            (USER_ID, QUERY_ISSUE_BY_ID),
            (USER_ID, MUTATION_CREATE_ISSUE),
            (USER_ID, MUTATION_CREATE_ISSUE),
        ]

    def test_create_sub_issues_by_parent_identifier_fetches_it_by_identifier(
        self, tools, proxy
    ) -> None:
        _answers(proxy, {"issue": _full_issue(id="parent-1")}, _created("2", "Sub 1"))

        result = tools["CUSTOM_CREATE_SUB_ISSUES"](
            CreateSubIssuesInput(
                parent_identifier="ENG-1", sub_issues=[SubIssueItem(title="Sub 1")]
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

        assert result["parent"] == "ENG-1"
        assert _bodies(proxy)[0]["variables"] == {"id": "ENG-1"}
        assert _bodies(proxy)[1]["variables"]["input"]["parentId"] == "parent-1"

    def test_create_sub_issues_no_parent(self, tools, proxy) -> None:
        with pytest.raises(ValueError, match=r"^Could not resolve parent issue$"):
            tools["CUSTOM_CREATE_SUB_ISSUES"](
                CreateSubIssuesInput(sub_issues=[SubIssueItem(title="Sub 1")]),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )
        proxy.assert_not_called()

    @pytest.mark.parametrize(
        ("parent_identifier", "message"),
        [
            ("ENG", r"^Invalid parent identifier: ENG$"),
            ("ENG-abc", r"^Invalid issue number in: ENG-abc$"),
        ],
    )
    def test_create_sub_issues_rejects_a_malformed_parent_identifier(
        self, tools, proxy, parent_identifier, message
    ) -> None:
        with pytest.raises(ValueError, match=message):
            tools["CUSTOM_CREATE_SUB_ISSUES"](
                CreateSubIssuesInput(
                    parent_identifier=parent_identifier, sub_issues=[SubIssueItem(title="Sub 1")]
                ),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )
        proxy.assert_not_called()


class TestLinearCreateIssueRelation:
    def test_create_relation_success(self, tools, proxy) -> None:
        _answers(
            proxy,
            {
                "issueRelationCreate": {
                    "success": True,
                    "issueRelation": {"id": "r1", "type": "blocked_by"},
                }
            },
        )

        result = tools["CUSTOM_CREATE_ISSUE_RELATION"](
            CreateIssueRelationInput(
                issue_id="i1", related_issue_id="i2", relation_type="is_blocked_by"
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

        assert result == {
            "relation": {"id": "r1", "type": "is_blocked_by", "from_issue": "i1", "to_issue": "i2"}
        }
        assert _bodies(proxy)[0]["variables"] == {
            "issueId": "i1",
            "relatedIssueId": "i2",
            "type": "blocked_by",
        }
        assert _operations(proxy) == [(USER_ID, MUTATION_CREATE_RELATION)]

    @pytest.mark.parametrize(
        ("relation_type", "linear_type"),
        [("blocks", "blocks"), ("relates_to", "related"), ("duplicates", "duplicate")],
    )
    def test_create_relation_sends_linears_name_for_the_relation_type(
        self, tools, proxy, relation_type, linear_type
    ) -> None:
        _answers(
            proxy,
            {
                "issueRelationCreate": {
                    "success": True,
                    "issueRelation": {"id": "r1", "type": linear_type},
                }
            },
        )

        result = tools["CUSTOM_CREATE_ISSUE_RELATION"](
            CreateIssueRelationInput(
                issue_id="i1", related_issue_id="i2", relation_type=relation_type
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

        assert result["relation"]["type"] == relation_type
        assert _bodies(proxy)[0]["variables"]["type"] == linear_type

    def test_create_relation_failure(self, tools, proxy) -> None:
        _answers(
            proxy,
            {
                "issueRelationCreate": {
                    "success": False,
                    "issueRelation": {"id": "r1", "type": "blocks"},
                }
            },
        )

        with pytest.raises(RuntimeError, match=r"^Failed to create relation$"):
            tools["CUSTOM_CREATE_ISSUE_RELATION"](
                CreateIssueRelationInput(
                    issue_id="i1", related_issue_id="i2", relation_type="blocks"
                ),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )

    @pytest.mark.regression
    def test_create_relation_success_without_a_relation_raises_the_domain_error(
        self, tools, proxy
    ) -> None:
        """A success envelope with no relation used to crash reading relation.get; it is a failed create."""
        _answers(proxy, {"issueRelationCreate": {"success": True, "issueRelation": None}})

        with pytest.raises(RuntimeError, match=r"^Failed to create relation$"):
            tools["CUSTOM_CREATE_ISSUE_RELATION"](
                CreateIssueRelationInput(
                    issue_id="i1", related_issue_id="i2", relation_type="blocks"
                ),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )


# =============================================================================
# CUSTOM_GET_ISSUE_ACTIVITY
# =============================================================================


class TestLinearGetIssueActivity:
    def _run(self, tools, proxy, *entries: dict[str, Any]) -> Any:
        _answers(proxy, {"issue": {"history": {"nodes": list(entries)}}})
        return tools["CUSTOM_GET_ISSUE_ACTIVITY"](
            GetIssueActivityInput(issue_id="i1"), EXECUTE_REQUEST, AUTH_CREDS
        )

    def test_get_activity_by_id(self, tools, proxy) -> None:
        result = self._run(
            tools,
            proxy,
            _history(
                fromState={"id": "s0", "name": "Todo", "type": "unstarted"},
                toState={"id": "s9", "name": "Done", "type": "completed"},
            ),
            _history(id="h2"),
        )

        assert result == {
            "issue": "i1",
            "activity_count": 1,
            "activities": [
                {
                    "timestamp": "2024-01-01",
                    "actor": "Alice",
                    "change_type": "state",
                    "from": "Todo",
                    "to": "Done",
                }
            ],
        }
        assert _bodies(proxy)[0]["variables"] == {"issueId": "i1", "first": 10}
        assert _operations(proxy) == [(USER_ID, QUERY_ISSUE_HISTORY)]

    def test_get_activity_by_identifier(self, tools, proxy) -> None:
        _answers(proxy, {"issue": _full_issue(id="i9")}, {"issue": {"history": {"nodes": []}}})

        result = tools["CUSTOM_GET_ISSUE_ACTIVITY"](
            GetIssueActivityInput(issue_identifier="ENG-123"), EXECUTE_REQUEST, AUTH_CREDS
        )

        assert result == {"issue": "ENG-123", "activity_count": 0, "activities": []}
        assert _bodies(proxy)[1]["variables"]["issueId"] == "i9"
        assert _operations(proxy) == [(USER_ID, QUERY_ISSUE_BY_ID), (USER_ID, QUERY_ISSUE_HISTORY)]

    def test_get_activity_state_set_without_a_previous_state(self, tools, proxy) -> None:
        result = self._run(
            tools, proxy, _history(toState={"id": "s9", "name": "Done", "type": "completed"})
        )

        assert result["activities"] == [
            {
                "timestamp": "2024-01-01",
                "actor": "Alice",
                "change_type": "state",
                "from": None,
                "to": "Done",
            }
        ]

    def test_get_activity_no_issue(self, tools) -> None:
        with pytest.raises(ValueError, match=r"^Could not resolve issue$"):
            tools["CUSTOM_GET_ISSUE_ACTIVITY"](GetIssueActivityInput(), EXECUTE_REQUEST, AUTH_CREDS)

    def test_get_activity_priority_change(self, tools, proxy) -> None:
        result = self._run(
            tools,
            proxy,
            _history(actor=None, fromPriority=0, toPriority=1),
            _history(id="h2", fromPriority=3, toPriority=None),
        )

        assert result["activities"] == [
            {
                "timestamp": "2024-01-01",
                "actor": "System",
                "change_type": "priority",
                "from": "none",
                "to": "urgent",
            },
            {
                "timestamp": "2024-01-01",
                "actor": "Alice",
                "change_type": "priority",
                "from": "medium",
                "to": "none",
            },
        ]

    def test_get_activity_assignee_change(self, tools, proxy) -> None:
        result = self._run(
            tools,
            proxy,
            _history(toAssignee={"id": "u2", "name": "Bob"}),
            _history(id="h2", fromAssignee={"id": "u1", "name": "Alice"}),
        )

        assert result["activities"] == [
            {
                "timestamp": "2024-01-01",
                "actor": "Alice",
                "change_type": "assignee",
                "from": None,
                "to": "Bob",
            },
            {
                "timestamp": "2024-01-01",
                "actor": "Alice",
                "change_type": "assignee",
                "from": "Alice",
                "to": None,
            },
        ]

    def test_get_activity_labels_added(self, tools, proxy) -> None:
        """Linear's schema types addedLabels as [IssueLabel!], a plain list, not a connection."""
        result = self._run(tools, proxy, _history(addedLabels=[{"id": "l1", "name": "Bug"}]))

        assert result["activities"] == [
            {
                "timestamp": "2024-01-01",
                "actor": "Alice",
                "change_type": "labels_added",
                "labels": ["Bug"],
            }
        ]


# =============================================================================
# CUSTOM_GET_ACTIVE_SPRINT
# =============================================================================


def _cycle(cycle_id: str, team: dict[str, Any], *issues: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": cycle_id,
        "name": "Sprint 5",
        "number": 5,
        "startsAt": "2024-01-01",
        "endsAt": "2024-01-15",
        "progress": 0.5,
        "team": team,
        "issues": {"nodes": list(issues)},
    }


class TestLinearGetActiveSprint:
    def test_get_active_sprint(self, tools, proxy) -> None:
        started = {
            "id": "i1",
            "identifier": "ENG-1",
            "title": "Task",
            "state": {"name": "In Progress", "type": "started"},
            "priority": 1,
            "assignee": {"name": "Alice"},
        }
        todo = {
            "id": "i2",
            "identifier": "ENG-2",
            "title": "Next",
            "state": {"name": "Todo", "type": "unstarted"},
            "priority": 0,
            "assignee": None,
        }
        triage = {
            **todo,
            "id": "i3",
            "identifier": "ENG-3",
            "state": {"name": "Triage", "type": "triage"},
        }
        _answers(proxy, {"cycles": {"nodes": [_cycle("c1", TEAM, started, todo, triage)]}})

        result = tools["CUSTOM_GET_ACTIVE_SPRINT"](
            GetActiveSprintInput(), EXECUTE_REQUEST, AUTH_CREDS
        )

        assert result == {
            "sprint_count": 1,
            "sprints": [
                {
                    "id": "c1",
                    "name": "Sprint 5",
                    "number": 5,
                    "team": "Eng",
                    "team_key": "ENG",
                    "starts_at": "2024-01-01",
                    "ends_at": "2024-01-15",
                    "progress": 50.0,
                    "total_issues": 3,
                    "issues_by_state": {"backlog": 0, "unstarted": 1, "started": 1, "completed": 0},
                    "in_progress": [
                        {
                            "identifier": "ENG-1",
                            "title": "Task",
                            "priority": "urgent",
                            "assignee": "Alice",
                        }
                    ],
                    "todo": [
                        {
                            "identifier": "ENG-2",
                            "title": "Next",
                            "priority": "none",
                            "assignee": None,
                        }
                    ],
                }
            ],
        }
        assert _operations(proxy) == [(USER_ID, QUERY_ACTIVE_CYCLES)]

    def test_get_active_sprint_counts_every_issue_but_lists_at_most_the_limit_per_state(
        self, tools, proxy
    ) -> None:
        def issue(issue_id: str, state: dict[str, Any]) -> dict[str, Any]:
            return {
                "id": issue_id,
                "identifier": f"ENG-{issue_id}",
                "title": issue_id,
                "state": state,
                "priority": 0,
                "assignee": None,
            }

        started = {"name": "In Progress", "type": "started"}
        cycle = _cycle(
            "c1",
            TEAM,
            issue("a", started),
            issue("b", started),
            issue("untyped", {"name": "Todo"}),
        )
        _answers(proxy, {"cycles": {"nodes": [{**cycle, "progress": 0.12345}]}})

        sprint = tools["CUSTOM_GET_ACTIVE_SPRINT"](
            GetActiveSprintInput(issues_per_state_limit=1), EXECUTE_REQUEST, AUTH_CREDS
        )["sprints"][0]

        assert sprint["progress"] == 12.3
        assert sprint["issues_by_state"] == {
            "backlog": 0,
            "unstarted": 1,
            "started": 2,
            "completed": 0,
        }
        assert [line["identifier"] for line in sprint["in_progress"]] == ["ENG-a"]
        assert [line["identifier"] for line in sprint["todo"]] == ["ENG-untyped"]

    def test_get_active_sprint_filtered_by_team(self, tools, proxy) -> None:
        design = {"id": "t2", "key": "DES", "name": "Design"}
        _answers(proxy, {"cycles": {"nodes": [_cycle("c1", TEAM), _cycle("c2", design)]}})

        result = tools["CUSTOM_GET_ACTIVE_SPRINT"](
            GetActiveSprintInput(team_id="t1"), EXECUTE_REQUEST, AUTH_CREDS
        )

        assert [s["id"] for s in result["sprints"]] == ["c1"]


# =============================================================================
# CUSTOM_BULK_UPDATE_ISSUES
# =============================================================================


class TestLinearBulkUpdateIssues:
    def test_bulk_update_success(self, tools, proxy) -> None:
        _answers(
            proxy,
            {
                "issueBatchUpdate": {
                    "success": True,
                    "issues": [
                        {"id": "i1", "identifier": "ENG-1", "title": "A"},
                        {"id": "i2", "identifier": "ENG-2", "title": "B"},
                    ],
                }
            },
        )

        result = tools["CUSTOM_BULK_UPDATE_ISSUES"](
            BulkUpdateIssuesInput(issue_ids=["i1", "i2"], state_id="s1", assignee_id=""),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

        assert result == {
            "updated_count": 2,
            "updated_issues": [
                {"id": "i1", "identifier": "ENG-1"},
                {"id": "i2", "identifier": "ENG-2"},
            ],
        }
        assert _bodies(proxy) == [
            {
                "query": MUTATION_UPDATE_ISSUES,
                "variables": {
                    "issueIds": ["i1", "i2"],
                    "input": {"stateId": "s1", "assigneeId": None},
                },
            }
        ]
        assert _operations(proxy) == [(USER_ID, MUTATION_UPDATE_ISSUES)]

    def test_bulk_update_sends_every_requested_field(self, tools, proxy) -> None:
        _answers(proxy, {"issueBatchUpdate": {"success": True, "issues": []}})

        tools["CUSTOM_BULK_UPDATE_ISSUES"](
            BulkUpdateIssuesInput(
                issue_ids=["i1"],
                priority=2,
                assignee_id="u2",
                cycle_id="c1",
                project_id="p1",
                labels_to_add=["l1"],
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

        assert _bodies(proxy)[0]["variables"]["input"] == {
            "priority": 2,
            "assigneeId": "u2",
            "cycleId": "c1",
            "projectId": "p1",
            "labelIds": ["l1"],
        }

    def test_bulk_update_no_ids(self, tools) -> None:
        with pytest.raises(ValueError, match=r"^No issue IDs provided$"):
            tools["CUSTOM_BULK_UPDATE_ISSUES"](
                BulkUpdateIssuesInput(issue_ids=[], state_id="s1"), EXECUTE_REQUEST, AUTH_CREDS
            )

    def test_bulk_update_no_updates(self, tools) -> None:
        with pytest.raises(ValueError, match=r"^No updates specified$"):
            tools["CUSTOM_BULK_UPDATE_ISSUES"](
                BulkUpdateIssuesInput(issue_ids=["i1"]), EXECUTE_REQUEST, AUTH_CREDS
            )

    def test_bulk_update_failure(self, tools, proxy) -> None:
        _answers(proxy, {"issueBatchUpdate": {"success": False, "issues": []}})

        with pytest.raises(RuntimeError, match=r"^Batch update failed$"):
            tools["CUSTOM_BULK_UPDATE_ISSUES"](
                BulkUpdateIssuesInput(issue_ids=["i1"], state_id="s1"), EXECUTE_REQUEST, AUTH_CREDS
            )


# =============================================================================
# CUSTOM_GET_NOTIFICATIONS
# =============================================================================

_NOTIFICATIONS = {
    "notifications": {
        "nodes": [
            {
                "id": "n1",
                "type": "issueAssignedToYou",
                "createdAt": "2024-01-01",
                "readAt": None,
                "issue": {"id": "i1", "identifier": "ENG-1", "title": "Bug"},
                "actor": {"id": "u1", "name": "Alice"},
            },
            {
                "id": "n2",
                "type": "projectUpdate",
                "createdAt": "2024-01-02",
                "readAt": "2024-01-02",
                "actor": None,
            },
        ]
    }
}


class TestLinearGetNotifications:
    def test_get_notifications_unread(self, tools, proxy) -> None:
        # The read notification comes first: skipping it must not stop the scan.
        read_first = list(reversed(_NOTIFICATIONS["notifications"]["nodes"]))
        _answers(proxy, {"notifications": {"nodes": read_first}})

        result = tools["CUSTOM_GET_NOTIFICATIONS"](
            GetNotificationsInput(include_read=False, limit=5), EXECUTE_REQUEST, AUTH_CREDS
        )

        assert _bodies(proxy) == [{"query": QUERY_NOTIFICATIONS, "variables": {"first": 5}}]
        assert _operations(proxy) == [(USER_ID, QUERY_NOTIFICATIONS)]

        assert result == {
            "count": 1,
            "notifications": [
                {
                    "id": "n1",
                    "type": "issueAssignedToYou",
                    "created_at": "2024-01-01",
                    "read": False,
                    "issue": {"identifier": "ENG-1", "title": "Bug"},
                    "actor": "Alice",
                }
            ],
        }

    def test_get_notifications_include_read(self, tools, proxy) -> None:
        _answers(proxy, _NOTIFICATIONS)

        result = tools["CUSTOM_GET_NOTIFICATIONS"](
            GetNotificationsInput(include_read=True), EXECUTE_REQUEST, AUTH_CREDS
        )

        assert result["count"] == 2
        assert result["notifications"][1] == {
            "id": "n2",
            "type": "projectUpdate",
            "created_at": "2024-01-02",
            "read": True,
            "issue": None,
            "actor": None,
        }


# =============================================================================
# CUSTOM_GET_WORKSPACE_CONTEXT / CUSTOM_GATHER_CONTEXT
# =============================================================================


class TestLinearGetWorkspaceContext:
    def test_get_workspace_context(self, tools, proxy) -> None:
        local_today = datetime.now().date()
        yesterday = (local_today - timedelta(days=1)).isoformat()
        _answers(
            proxy,
            VIEWER,
            {
                "teams": {
                    "nodes": [
                        {
                            **TEAM,
                            "activeCycle": {"id": "c1", "name": "Sprint 5", "progress": 0.12345},
                        },
                        {"id": "t2", "key": "DES", "name": "Design", "activeCycle": None},
                    ]
                }
            },
            {
                "issues": {
                    "nodes": [
                        _summary(
                            "2",
                            priority=1,
                            dueDate=yesterday,
                            state={"id": "s9", "name": "Done", "type": "completed"},
                        ),
                        _summary("1", priority=1, dueDate=yesterday, slaBreachesAt="2024-01-01"),
                        _summary("undated"),
                        _summary("due_today", dueDate=local_today.isoformat()),
                    ]
                }
            },
        )

        with patch(f"{LINEAR_MODULE}._user_local_today", return_value=local_today):
            result = tools["CUSTOM_GET_WORKSPACE_CONTEXT"](
                GetWorkspaceContextInput(), EXECUTE_REQUEST, AUTH_CREDS
            )

        assert result["user"] == {
            "id": "u1",
            "name": "Alice",
            "email": "a@b.com",
            "assigned_issue_count": 1,
        }
        assert result["teams"] == [
            {
                "id": "t1",
                "name": "Eng",
                "key": "ENG",
                "active_cycle": "Sprint 5",
                "cycle_progress": 12.3,
            },
            {
                "id": "t2",
                "name": "Design",
                "key": "DES",
                "active_cycle": None,
                "cycle_progress": None,
            },
        ]
        assert {key: [i["id"] for i in items] for key, items in result["urgent_items"].items()} == {
            "overdue": ["1"],
            "high_priority": ["1"],
            "sla_at_risk": ["1"],
        }
        assert _bodies(proxy)[2]["variables"] == {
            "assigneeId": "u1",
            "includeCompleted": True,
            "first": 50,
        }
        assert _operations(proxy) == [
            (USER_ID, QUERY_VIEWER),
            (USER_ID, QUERY_TEAMS),
            (USER_ID, QUERY_MY_ISSUES),
        ]


@pytest.mark.parametrize(
    ("tool_name", "request_model", "expected_sizes"),
    [
        (
            "CUSTOM_GET_WORKSPACE_CONTEXT",
            GetWorkspaceContextInput(),
            {"overdue": 5, "high_priority": 5, "sla_at_risk": 3},
        ),
        ("CUSTOM_GATHER_CONTEXT", GatherContextInput(), {"overdue": 5, "high_priority": 5}),
    ],
)
def test_context_snapshots_cap_each_urgent_list(
    tools, proxy, tool_name, request_model, expected_sizes
) -> None:
    local_today = datetime.now().date()
    yesterday = (local_today - timedelta(days=1)).isoformat()
    urgent = [
        _summary(str(i), priority=1, dueDate=yesterday, slaBreachesAt="2024-01-01")
        for i in range(6)
    ]
    _answers(proxy, VIEWER, {"teams": {"nodes": [TEAM]}}, {"issues": {"nodes": urgent}})

    with patch(f"{LINEAR_MODULE}._user_local_today", return_value=local_today):
        result = tools[tool_name](request_model, EXECUTE_REQUEST, AUTH_CREDS)

    assert {key: len(items) for key, items in result["urgent_items"].items()} == expected_sizes


class TestLinearGatherContext:
    def test_gather_context(self, tools, proxy) -> None:
        local_today = datetime.now().date()
        yesterday = (local_today - timedelta(days=1)).isoformat()
        completed = {"id": "s9", "name": "Done", "type": "completed"}
        _answers(
            proxy,
            VIEWER,
            {"teams": {"nodes": [{**TEAM, "activeCycle": None}]}},
            {
                "issues": {
                    "nodes": [
                        _summary("done", priority=1, dueDate=yesterday, state=completed),
                        _summary("1", dueDate=yesterday),
                        _summary("2", priority=2),
                        _summary("due_today", dueDate=local_today.isoformat()),
                    ]
                }
            },
        )

        with patch(f"{LINEAR_MODULE}._user_local_today", return_value=local_today):
            result = tools["CUSTOM_GATHER_CONTEXT"](
                GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS
            )

        assert result["user"] == {"id": "u1", "name": "Alice", "email": "a@b.com"}
        assert result["teams"] == [{"id": "t1", "name": "Eng", "key": "ENG"}]
        assert [i["id"] for i in result["urgent_items"]["overdue"]] == ["1"]
        assert [i["id"] for i in result["urgent_items"]["high_priority"]] == ["2"]
        assert _bodies(proxy)[2]["variables"] == {
            "assigneeId": "u1",
            "includeCompleted": True,
            "first": 50,
        }
        assert _operations(proxy) == [
            (USER_ID, QUERY_VIEWER),
            (USER_ID, QUERY_TEAMS),
            (USER_ID, QUERY_MY_ISSUES),
        ]
