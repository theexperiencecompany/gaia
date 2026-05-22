"""Unit tests for integration tool files.

Covers:
- linear_tool.py
- google_sheets_tool.py
- twitter_tool.py
- linkedin_tool.py
- notion_tool.py
- calendar_tool.py

Strategy: Each register_*_custom_tools() function decorates inner functions with
@composio.tools.custom_tool(). We mock the Composio instance so the decorator
is a pass-through, call register_*_custom_tools() to capture the inner functions,
then invoke them directly with mock auth_credentials and request objects.
"""

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

# ── Models ────────────────────────────────────────────────────────────────────
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
    SubIssueItem,
)

# ── Constants ─────────────────────────────────────────────────────────────────

FAKE_ACCESS_TOKEN = "fake-access-token"
FAKE_USER_ID = "user-123"
AUTH_CREDS: dict[str, Any] = {
    "access_token": FAKE_ACCESS_TOKEN,
    "user_id": FAKE_USER_ID,
    "version": "v1",
}
EXECUTE_REQUEST = MagicMock()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_composio_mock() -> MagicMock:
    """Create a Composio mock whose custom_tool decorator is a no-op passthrough."""
    composio = MagicMock()

    def _custom_tool(**kwargs):
        """Decorator that passes the function through unchanged."""

        def wrapper(fn):
            return fn

        return wrapper

    composio.tools.custom_tool = _custom_tool
    return composio


def _ok_response(
    json_data: Any, status_code: int = 200, headers: dict[str, str] | None = None
) -> MagicMock:
    """Build a fake httpx.Response-like object with .json(), .status_code, .raise_for_status(), .headers."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    resp.text = ""
    resp.headers = headers or {}
    return resp


def _error_response(status_code: int = 400, text: str = "Bad Request") -> httpx.Response:
    """Build a real httpx.Response that will raise on .raise_for_status()."""
    resp = httpx.Response(
        status_code=status_code, text=text, request=httpx.Request("GET", "https://test")
    )
    return resp


# =============================================================================
# LINEAR TOOLS
# =============================================================================

LINEAR_MODULE = "app.agents.tools.integrations.linear_tool"


def _register_linear_tools() -> dict[str, Any]:
    """Register linear tools and return a dict of {func_name: func}."""
    composio = _make_composio_mock()
    # Import inside to avoid side effects at module level
    from app.agents.tools.integrations.linear_tool import register_linear_custom_tools

    register_linear_custom_tools(composio)
    # The inner functions are local to register_linear_custom_tools,
    # but since our mock decorator is a passthrough, they are returned as names only.
    # We need to re-import and directly call the code. Instead, let's patch graphql_request
    # and invoke via the module.
    return {}


class TestLinearResolveContext:
    """Tests for CUSTOM_RESOLVE_CONTEXT."""

    @patch(f"{LINEAR_MODULE}.graphql_request")
    @patch(f"{LINEAR_MODULE}.fuzzy_match")
    def test_resolve_context_basic(self, mock_fuzzy: MagicMock, mock_gql: MagicMock) -> None:
        """Resolve context with no optional fields returns current user only."""
        mock_gql.return_value = {"viewer": {"id": "u1", "name": "Alice", "email": "a@b.com"}}

        composio = _make_composio_mock()
        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        register_linear_custom_tools(composio)
        # After registration, the inner function is defined; call it via locals trick:
        # Actually, since our decorator passthrough doesn't store the functions anywhere,
        # we need a different approach. Let's capture them.
        captured: dict[str, Any] = {}

        def capturing_custom_tool(**kwargs):
            def wrapper(fn):
                captured[fn.__name__] = fn
                return fn

            return wrapper

        composio.tools.custom_tool = capturing_custom_tool
        register_linear_custom_tools(composio)

        fn = captured["CUSTOM_RESOLVE_CONTEXT"]
        request = ResolveContextInput()
        result = fn(request, EXECUTE_REQUEST, AUTH_CREDS)

        assert "data" in result
        assert result["data"]["current_user"]["id"] == "u1"
        assert result["data"]["current_user"]["name"] == "Alice"

    @patch(f"{LINEAR_MODULE}.graphql_request")
    @patch(
        f"{LINEAR_MODULE}.fuzzy_match",
        return_value=[{"id": "t1", "name": "Engineering"}],
    )
    def test_resolve_context_with_team_name(
        self, mock_fuzzy: MagicMock, mock_gql: MagicMock
    ) -> None:
        mock_gql.side_effect = [
            {"viewer": {"id": "u1", "name": "Alice", "email": "a@b.com"}},
            {"teams": {"nodes": [{"id": "t1", "name": "Engineering"}]}},
        ]

        composio = _make_composio_mock()
        captured: dict[str, Any] = {}

        def capturing_custom_tool(**kwargs):
            def wrapper(fn):
                captured[fn.__name__] = fn
                return fn

            return wrapper

        composio.tools.custom_tool = capturing_custom_tool
        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        register_linear_custom_tools(composio)
        fn = captured["CUSTOM_RESOLVE_CONTEXT"]

        request = ResolveContextInput(team_name="eng")
        result = fn(request, EXECUTE_REQUEST, AUTH_CREDS)

        assert "teams" in result["data"]
        mock_fuzzy.assert_called_once()

    @patch(f"{LINEAR_MODULE}.graphql_request")
    @patch(f"{LINEAR_MODULE}.fuzzy_match", return_value=[{"id": "u2", "name": "Bob"}])
    def test_resolve_context_with_user_name(
        self, mock_fuzzy: MagicMock, mock_gql: MagicMock
    ) -> None:
        mock_gql.side_effect = [
            {"viewer": {"id": "u1", "name": "Alice", "email": "a@b.com"}},
            {"users": {"nodes": [{"id": "u2", "name": "Bob", "active": True}]}},
        ]

        composio = _make_composio_mock()
        captured: dict[str, Any] = {}

        def capturing_custom_tool(**kwargs):
            def wrapper(fn):
                captured[fn.__name__] = fn
                return fn

            return wrapper

        composio.tools.custom_tool = capturing_custom_tool
        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        register_linear_custom_tools(composio)
        fn = captured["CUSTOM_RESOLVE_CONTEXT"]

        request = ResolveContextInput(user_name="bob")
        result = fn(request, EXECUTE_REQUEST, AUTH_CREDS)

        assert "users" in result["data"]

    @patch(f"{LINEAR_MODULE}.graphql_request")
    @patch(f"{LINEAR_MODULE}.fuzzy_match", return_value=[{"id": "l1", "name": "Bug"}])
    def test_resolve_context_labels_with_team_id(
        self, mock_fuzzy: MagicMock, mock_gql: MagicMock
    ) -> None:
        mock_gql.side_effect = [
            {"viewer": {"id": "u1", "name": "Alice", "email": "a@b.com"}},
            {"issueLabels": {"nodes": [{"id": "l1", "name": "Bug"}]}},
        ]

        composio = _make_composio_mock()
        captured: dict[str, Any] = {}

        def capturing_custom_tool(**kwargs):
            def wrapper(fn):
                captured[fn.__name__] = fn
                return fn

            return wrapper

        composio.tools.custom_tool = capturing_custom_tool
        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        register_linear_custom_tools(composio)
        fn = captured["CUSTOM_RESOLVE_CONTEXT"]

        request = ResolveContextInput(label_names=["bug"], team_id="t1")
        result = fn(request, EXECUTE_REQUEST, AUTH_CREDS)

        assert "labels" in result["data"]

    @patch(f"{LINEAR_MODULE}.graphql_request")
    @patch(f"{LINEAR_MODULE}.fuzzy_match", return_value=[{"id": "l1", "name": "Bug"}])
    def test_resolve_context_labels_without_team_id(
        self, mock_fuzzy: MagicMock, mock_gql: MagicMock
    ) -> None:
        mock_gql.side_effect = [
            {"viewer": {"id": "u1", "name": "Alice", "email": "a@b.com"}},
            {"issueLabels": {"nodes": [{"id": "l1", "name": "Bug"}]}},
        ]

        composio = _make_composio_mock()
        captured: dict[str, Any] = {}

        def capturing_custom_tool(**kwargs):
            def wrapper(fn):
                captured[fn.__name__] = fn
                return fn

            return wrapper

        composio.tools.custom_tool = capturing_custom_tool
        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        register_linear_custom_tools(composio)
        fn = captured["CUSTOM_RESOLVE_CONTEXT"]

        request = ResolveContextInput(label_names=["bug"])
        result = fn(request, EXECUTE_REQUEST, AUTH_CREDS)

        assert "labels" in result["data"]

    @patch(f"{LINEAR_MODULE}.graphql_request")
    @patch(f"{LINEAR_MODULE}.fuzzy_match", return_value=[{"id": "p1", "name": "GAIA"}])
    def test_resolve_context_with_project_name(
        self, mock_fuzzy: MagicMock, mock_gql: MagicMock
    ) -> None:
        mock_gql.side_effect = [
            {"viewer": {"id": "u1", "name": "Alice", "email": "a@b.com"}},
            {"projects": {"nodes": [{"id": "p1", "name": "GAIA"}]}},
        ]

        composio = _make_composio_mock()
        captured: dict[str, Any] = {}

        def capturing_custom_tool(**kwargs):
            def wrapper(fn):
                captured[fn.__name__] = fn
                return fn

            return wrapper

        composio.tools.custom_tool = capturing_custom_tool
        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        register_linear_custom_tools(composio)
        fn = captured["CUSTOM_RESOLVE_CONTEXT"]

        request = ResolveContextInput(project_name="gaia")
        result = fn(request, EXECUTE_REQUEST, AUTH_CREDS)

        assert "projects" in result["data"]

    @patch(f"{LINEAR_MODULE}.graphql_request")
    @patch(
        f"{LINEAR_MODULE}.fuzzy_match",
        return_value=[{"id": "s1", "name": "In Progress"}],
    )
    def test_resolve_context_with_state_and_team(
        self, mock_fuzzy: MagicMock, mock_gql: MagicMock
    ) -> None:
        mock_gql.side_effect = [
            {"viewer": {"id": "u1", "name": "Alice", "email": "a@b.com"}},
            {"workflowStates": {"nodes": [{"id": "s1", "name": "In Progress"}]}},
        ]

        composio = _make_composio_mock()
        captured: dict[str, Any] = {}

        def capturing_custom_tool(**kwargs):
            def wrapper(fn):
                captured[fn.__name__] = fn
                return fn

            return wrapper

        composio.tools.custom_tool = capturing_custom_tool
        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        register_linear_custom_tools(composio)
        fn = captured["CUSTOM_RESOLVE_CONTEXT"]

        request = ResolveContextInput(state_name="in progress", team_id="t1")
        result = fn(request, EXECUTE_REQUEST, AUTH_CREDS)

        assert "states" in result["data"]


# ── Helper to capture registered tool funcs ──────────────────────────────────


def _capture_tools(register_func) -> dict[str, Any]:
    """Call a register_*_custom_tools function and capture all inner tool functions."""
    composio = MagicMock()
    captured: dict[str, Any] = {}

    def capturing_custom_tool(**kwargs):
        def wrapper(fn):
            captured[fn.__name__] = fn
            return fn

        return wrapper

    composio.tools.custom_tool = capturing_custom_tool
    register_func(composio)
    return captured


# =============================================================================
# LINEAR - more tools
# =============================================================================


class TestLinearGetMyTasks:
    @patch(f"{LINEAR_MODULE}.graphql_request")
    @patch(
        f"{LINEAR_MODULE}.format_issue_summary",
        side_effect=lambda i: {"id": i.get("id"), "title": i.get("title")},
    )
    def test_get_my_tasks_all_filter(self, mock_fmt: MagicMock, mock_gql: MagicMock) -> None:
        mock_gql.side_effect = [
            {"viewer": {"id": "u1"}},
            {
                "issues": {
                    "nodes": [
                        {
                            "id": "i1",
                            "title": "Task 1",
                            "priority": 1,
                            "state": {"type": "started"},
                            "dueDate": None,
                        },
                        {
                            "id": "i2",
                            "title": "Task 2",
                            "priority": 3,
                            "state": {"type": "started"},
                            "dueDate": None,
                        },
                    ]
                }
            },
        ]

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_GET_MY_TASKS"]

        request = GetMyTasksInput(filter="all", limit=10)
        result = fn(request, EXECUTE_REQUEST, AUTH_CREDS)

        assert result["filter"] == "all"
        assert result["count"] == 2

    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_get_my_tasks_no_viewer(self, mock_gql: MagicMock) -> None:
        mock_gql.return_value = {"viewer": {}}

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_GET_MY_TASKS"]

        with pytest.raises(ValueError, match="Could not get current user"):
            fn(GetMyTasksInput(), EXECUTE_REQUEST, AUTH_CREDS)

    @patch(f"{LINEAR_MODULE}.graphql_request")
    @patch(
        f"{LINEAR_MODULE}.format_issue_summary",
        side_effect=lambda i: {"id": i.get("id")},
    )
    def test_get_my_tasks_high_priority_filter(
        self, mock_fmt: MagicMock, mock_gql: MagicMock
    ) -> None:
        mock_gql.side_effect = [
            {"viewer": {"id": "u1"}},
            {
                "issues": {
                    "nodes": [
                        {
                            "id": "i1",
                            "priority": 1,
                            "state": {"type": "started"},
                            "dueDate": None,
                        },
                        {
                            "id": "i2",
                            "priority": 4,
                            "state": {"type": "started"},
                            "dueDate": None,
                        },
                    ]
                }
            },
        ]

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_GET_MY_TASKS"]

        result = fn(GetMyTasksInput(filter="high_priority"), EXECUTE_REQUEST, AUTH_CREDS)
        assert result["count"] == 1

    @patch(f"{LINEAR_MODULE}.graphql_request")
    @patch(
        f"{LINEAR_MODULE}.format_issue_summary",
        side_effect=lambda i: {"id": i.get("id")},
    )
    def test_get_my_tasks_overdue_filter(self, mock_fmt: MagicMock, mock_gql: MagicMock) -> None:
        yesterday = (datetime.now().date() - timedelta(days=1)).isoformat()
        mock_gql.side_effect = [
            {"viewer": {"id": "u1"}},
            {
                "issues": {
                    "nodes": [
                        {
                            "id": "i1",
                            "priority": 3,
                            "state": {"type": "started"},
                            "dueDate": yesterday,
                        },
                        {
                            "id": "i2",
                            "priority": 3,
                            "state": {"type": "started"},
                            "dueDate": None,
                        },
                    ]
                }
            },
        ]

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_GET_MY_TASKS"]

        result = fn(GetMyTasksInput(filter="overdue"), EXECUTE_REQUEST, AUTH_CREDS)
        assert result["count"] == 1

    @patch(f"{LINEAR_MODULE}.graphql_request")
    @patch(
        f"{LINEAR_MODULE}.format_issue_summary",
        side_effect=lambda i: {"id": i.get("id")},
    )
    def test_get_my_tasks_excludes_completed(
        self, mock_fmt: MagicMock, mock_gql: MagicMock
    ) -> None:
        mock_gql.side_effect = [
            {"viewer": {"id": "u1"}},
            {
                "issues": {
                    "nodes": [
                        {
                            "id": "i1",
                            "priority": 3,
                            "state": {"type": "completed"},
                            "dueDate": None,
                        },
                        {
                            "id": "i2",
                            "priority": 3,
                            "state": {"type": "started"},
                            "dueDate": None,
                        },
                    ]
                }
            },
        ]

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_GET_MY_TASKS"]

        result = fn(
            GetMyTasksInput(filter="all", include_completed=False),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )
        assert result["count"] == 1

    @patch(f"{LINEAR_MODULE}.graphql_request")
    @patch(
        f"{LINEAR_MODULE}.format_issue_summary",
        side_effect=lambda i: {"id": i.get("id")},
    )
    def test_get_my_tasks_today_filter(self, mock_fmt: MagicMock, mock_gql: MagicMock) -> None:
        today = datetime.now().date().isoformat()
        mock_gql.side_effect = [
            {"viewer": {"id": "u1"}},
            {
                "issues": {
                    "nodes": [
                        {
                            "id": "i1",
                            "priority": 3,
                            "state": {"type": "started"},
                            "dueDate": today,
                        },
                        {
                            "id": "i2",
                            "priority": 3,
                            "state": {"type": "started"},
                            "dueDate": None,
                        },
                    ]
                }
            },
        ]

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_GET_MY_TASKS"]

        result = fn(GetMyTasksInput(filter="today"), EXECUTE_REQUEST, AUTH_CREDS)
        assert result["count"] == 1

    @patch(f"{LINEAR_MODULE}.graphql_request")
    @patch(
        f"{LINEAR_MODULE}.format_issue_summary",
        side_effect=lambda i: {"id": i.get("id")},
    )
    def test_get_my_tasks_this_week_filter(self, mock_fmt: MagicMock, mock_gql: MagicMock) -> None:
        tomorrow = (datetime.now().date() + timedelta(days=1)).isoformat()
        mock_gql.side_effect = [
            {"viewer": {"id": "u1"}},
            {
                "issues": {
                    "nodes": [
                        {
                            "id": "i1",
                            "priority": 3,
                            "state": {"type": "started"},
                            "dueDate": tomorrow,
                        },
                    ]
                }
            },
        ]

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_GET_MY_TASKS"]

        result = fn(GetMyTasksInput(filter="this_week"), EXECUTE_REQUEST, AUTH_CREDS)
        assert result["count"] == 1


class TestLinearSearchIssues:
    @patch(f"{LINEAR_MODULE}.graphql_request")
    @patch(
        f"{LINEAR_MODULE}.format_issue_summary",
        side_effect=lambda i: {"id": i.get("id")},
    )
    def test_search_issues_basic(self, mock_fmt: MagicMock, mock_gql: MagicMock) -> None:
        mock_gql.return_value = {
            "searchIssues": {
                "nodes": [
                    {
                        "id": "i1",
                        "title": "Bug fix",
                        "state": {"type": "started"},
                        "priority": 2,
                        "team": {"id": "t1"},
                        "assignee": {"id": "u1"},
                        "createdAt": "2024-01-01",
                    },
                ]
            },
        }

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_SEARCH_ISSUES"]

        result = fn(SearchIssuesInput(query="bug"), EXECUTE_REQUEST, AUTH_CREDS)
        assert result["query"] == "bug"
        assert result["count"] == 1

    @patch(f"{LINEAR_MODULE}.graphql_request")
    @patch(
        f"{LINEAR_MODULE}.format_issue_summary",
        side_effect=lambda i: {"id": i.get("id")},
    )
    def test_search_issues_with_team_filter(self, mock_fmt: MagicMock, mock_gql: MagicMock) -> None:
        mock_gql.return_value = {
            "searchIssues": {
                "nodes": [
                    {
                        "id": "i1",
                        "team": {"id": "t1"},
                        "state": {"type": "started"},
                        "priority": 0,
                        "createdAt": "2024-01-01",
                    },
                    {
                        "id": "i2",
                        "team": {"id": "t2"},
                        "state": {"type": "started"},
                        "priority": 0,
                        "createdAt": "2024-01-01",
                    },
                ]
            },
        }

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_SEARCH_ISSUES"]

        result = fn(SearchIssuesInput(query="test", team_id="t1"), EXECUTE_REQUEST, AUTH_CREDS)
        assert result["count"] == 1

    @patch(f"{LINEAR_MODULE}.graphql_request")
    @patch(
        f"{LINEAR_MODULE}.format_issue_summary",
        side_effect=lambda i: {"id": i.get("id")},
    )
    def test_search_issues_with_state_filter(
        self, mock_fmt: MagicMock, mock_gql: MagicMock
    ) -> None:
        mock_gql.return_value = {
            "searchIssues": {
                "nodes": [
                    {
                        "id": "i1",
                        "state": {"type": "completed"},
                        "priority": 0,
                        "createdAt": "2024-01-01",
                    },
                    {
                        "id": "i2",
                        "state": {"type": "started"},
                        "priority": 0,
                        "createdAt": "2024-01-01",
                    },
                ]
            },
        }

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_SEARCH_ISSUES"]

        result = fn(
            SearchIssuesInput(query="test", state_filter="completed"),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )
        assert result["count"] == 1

    @patch(f"{LINEAR_MODULE}.graphql_request")
    @patch(
        f"{LINEAR_MODULE}.format_issue_summary",
        side_effect=lambda i: {"id": i.get("id")},
    )
    @patch(f"{LINEAR_MODULE}.priority_to_int", return_value=1)
    def test_search_issues_with_priority_filter(
        self, mock_p2i: MagicMock, mock_fmt: MagicMock, mock_gql: MagicMock
    ) -> None:
        mock_gql.return_value = {
            "searchIssues": {
                "nodes": [
                    {
                        "id": "i1",
                        "state": {"type": "started"},
                        "priority": 1,
                        "createdAt": "2024-01-01",
                    },
                    {
                        "id": "i2",
                        "state": {"type": "started"},
                        "priority": 3,
                        "createdAt": "2024-01-01",
                    },
                ]
            },
        }

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_SEARCH_ISSUES"]

        result = fn(
            SearchIssuesInput(query="test", priority_filter="urgent"),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )
        assert result["count"] == 1

    @patch(f"{LINEAR_MODULE}.graphql_request")
    @patch(
        f"{LINEAR_MODULE}.format_issue_summary",
        side_effect=lambda i: {"id": i.get("id")},
    )
    def test_search_issues_with_created_after(
        self, mock_fmt: MagicMock, mock_gql: MagicMock
    ) -> None:
        mock_gql.return_value = {
            "searchIssues": {
                "nodes": [
                    {
                        "id": "i1",
                        "state": {"type": "started"},
                        "priority": 0,
                        "createdAt": "2024-06-01",
                    },
                    {
                        "id": "i2",
                        "state": {"type": "started"},
                        "priority": 0,
                        "createdAt": "2024-01-01",
                    },
                ]
            },
        }

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_SEARCH_ISSUES"]

        result = fn(
            SearchIssuesInput(query="test", created_after="2024-03-01"),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )
        assert result["count"] == 1


class TestLinearGetIssueFullContext:
    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_get_issue_by_id(self, mock_gql: MagicMock) -> None:
        mock_gql.return_value = {
            "issue": {
                "id": "i1",
                "identifier": "ENG-1",
                "title": "Bug",
                "description": "desc",
                "priority": 1,
                "state": {"name": "In Progress"},
                "dueDate": None,
                "estimate": 3,
                "team": {"name": "Eng"},
                "project": {"name": "GAIA"},
                "cycle": None,
                "assignee": {"name": "Alice"},
                "creator": {"name": "Bob"},
                "parent": None,
                "children": {"nodes": []},
                "relations": {"nodes": []},
                "comments": {"nodes": []},
                "history": {"nodes": []},
                "attachments": {"nodes": []},
            },
        }

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_GET_ISSUE_FULL_CONTEXT"]

        result = fn(GetIssueFullContextInput(issue_id="i1"), EXECUTE_REQUEST, AUTH_CREDS)
        assert result["issue"]["id"] == "i1"
        assert result["issue"]["priority"] == "urgent"

    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_get_issue_by_identifier(self, mock_gql: MagicMock) -> None:
        mock_gql.return_value = {
            "issue": {
                "id": "i1",
                "identifier": "ENG-123",
                "title": "Bug",
                "description": "",
                "priority": 0,
                "state": {"name": "Todo"},
                "dueDate": None,
                "estimate": None,
                "team": {"name": "Eng"},
                "project": None,
                "cycle": None,
                "assignee": None,
                "creator": {"name": "Bob"},
                "parent": None,
                "children": {"nodes": []},
                "relations": {"nodes": []},
                "comments": {"nodes": []},
                "history": {"nodes": []},
                "attachments": {"nodes": []},
            },
        }

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_GET_ISSUE_FULL_CONTEXT"]

        result = fn(
            GetIssueFullContextInput(issue_identifier="ENG-123"),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )
        assert result["issue"]["identifier"] == "ENG-123"

    def test_get_issue_no_id_or_identifier(self) -> None:
        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_GET_ISSUE_FULL_CONTEXT"]

        with pytest.raises(ValueError, match="Provide either"):
            fn(GetIssueFullContextInput(), EXECUTE_REQUEST, AUTH_CREDS)

    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_get_issue_invalid_identifier_format(self, mock_gql: MagicMock) -> None:
        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_GET_ISSUE_FULL_CONTEXT"]

        with pytest.raises(ValueError, match="Invalid identifier format"):
            fn(
                GetIssueFullContextInput(issue_identifier="BADFORMAT"),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )

    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_get_issue_invalid_number_in_identifier(self, mock_gql: MagicMock) -> None:
        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_GET_ISSUE_FULL_CONTEXT"]

        with pytest.raises(ValueError, match="Invalid issue number"):
            fn(
                GetIssueFullContextInput(issue_identifier="ENG-abc"),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )

    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_get_issue_not_found(self, mock_gql: MagicMock) -> None:
        mock_gql.return_value = {"issue": None}

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_GET_ISSUE_FULL_CONTEXT"]

        with pytest.raises(ValueError, match="Issue not found"):
            fn(
                GetIssueFullContextInput(issue_id="nonexistent"),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )

    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_get_issue_with_children_and_relations(self, mock_gql: MagicMock) -> None:
        mock_gql.return_value = {
            "issue": {
                "id": "i1",
                "identifier": "ENG-1",
                "title": "Parent",
                "description": "",
                "priority": 2,
                "state": {"name": "Todo"},
                "dueDate": None,
                "estimate": None,
                "team": {"name": "Eng"},
                "project": None,
                "cycle": None,
                "assignee": None,
                "creator": None,
                "parent": {"identifier": "ENG-0", "title": "Grand"},
                "children": {
                    "nodes": [
                        {
                            "identifier": "ENG-2",
                            "title": "Sub",
                            "state": {"name": "Done"},
                        }
                    ]
                },
                "relations": {
                    "nodes": [
                        {
                            "type": "blocks",
                            "relatedIssue": {"identifier": "ENG-3", "title": "Dep"},
                        }
                    ]
                },
                "comments": {
                    "nodes": [
                        {
                            "user": {"name": "Alice"},
                            "body": "comment",
                            "createdAt": "2024-01-01",
                        }
                    ]
                },
                "history": {
                    "nodes": [
                        {
                            "createdAt": "2024-01-01",
                            "actor": {"name": "Alice"},
                            "fromState": {"name": "Todo"},
                            "toState": {"name": "Done"},
                            "fromAssignee": None,
                            "toAssignee": None,
                            "addedLabels": None,
                            "removedLabels": None,
                        },
                    ]
                },
                "attachments": {
                    "nodes": [{"title": "file.pdf", "url": "https://example.com/file.pdf"}]
                },
            },
        }

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_GET_ISSUE_FULL_CONTEXT"]

        result = fn(GetIssueFullContextInput(issue_id="i1"), EXECUTE_REQUEST, AUTH_CREDS)
        assert result["issue"]["parent"]["identifier"] == "ENG-0"
        assert len(result["issue"]["sub_issues"]) == 1
        assert len(result["issue"]["relations"]) == 1
        assert len(result["issue"]["comments"]) == 1
        assert len(result["issue"]["activity"]) == 1
        assert len(result["issue"]["attachments"]) == 1


class TestLinearCreateIssue:
    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_create_issue_basic(self, mock_gql: MagicMock) -> None:
        mock_gql.return_value = {
            "issueCreate": {
                "success": True,
                "issue": {
                    "id": "i1",
                    "identifier": "ENG-1",
                    "title": "New Bug",
                    "url": "https://linear.app/eng-1",
                },
            },
        }

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_CREATE_ISSUE"]

        result = fn(CreateIssueInput(team_id="t1", title="New Bug"), EXECUTE_REQUEST, AUTH_CREDS)
        assert result["issue"]["id"] == "i1"

    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_create_issue_failure(self, mock_gql: MagicMock) -> None:
        mock_gql.return_value = {"issueCreate": {"success": False}}

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_CREATE_ISSUE"]

        with pytest.raises(RuntimeError, match="Failed to create issue"):
            fn(
                CreateIssueInput(team_id="t1", title="Fail"),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )

    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_create_issue_with_all_fields(self, mock_gql: MagicMock) -> None:
        mock_gql.return_value = {
            "issueCreate": {
                "success": True,
                "issue": {
                    "id": "i1",
                    "identifier": "ENG-1",
                    "title": "Full",
                    "url": "https://linear.app/eng-1",
                },
            },
        }

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_CREATE_ISSUE"]

        request = CreateIssueInput(
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
        )
        result = fn(request, EXECUTE_REQUEST, AUTH_CREDS)
        assert result["issue"]["id"] == "i1"
        call_args = mock_gql.call_args[0][1]
        assert call_args["input"]["assigneeId"] == "u1"


class TestLinearCreateSubIssues:
    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_create_sub_issues_with_parent_id(self, mock_gql: MagicMock) -> None:
        mock_gql.side_effect = [
            {"issue": {"id": "parent-1", "team": {"id": "t1"}}},
            {
                "issueCreate": {
                    "success": True,
                    "issue": {"id": "s1", "identifier": "ENG-2", "title": "Sub 1"},
                }
            },
        ]

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_CREATE_SUB_ISSUES"]

        result = fn(
            CreateSubIssuesInput(
                parent_issue_id="parent-1",
                sub_issues=[SubIssueItem(title="Sub 1")],
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )
        assert result["created_count"] == 1

    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_create_sub_issues_no_parent(self, mock_gql: MagicMock) -> None:
        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_CREATE_SUB_ISSUES"]

        with pytest.raises(ValueError, match="Could not resolve parent"):
            fn(
                CreateSubIssuesInput(sub_issues=[SubIssueItem(title="Sub 1")]),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )


class TestLinearCreateIssueRelation:
    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_create_relation_success(self, mock_gql: MagicMock) -> None:
        mock_gql.return_value = {
            "issueRelationCreate": {
                "success": True,
                "issueRelation": {"id": "r1", "type": "blocks"},
            },
        }

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_CREATE_ISSUE_RELATION"]

        result = fn(
            CreateIssueRelationInput(issue_id="i1", related_issue_id="i2", relation_type="blocks"),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )
        assert result["relation"]["type"] == "blocks"

    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_create_relation_failure(self, mock_gql: MagicMock) -> None:
        mock_gql.return_value = {"issueRelationCreate": {"success": False}}

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_CREATE_ISSUE_RELATION"]

        with pytest.raises(RuntimeError, match="Failed to create relation"):
            fn(
                CreateIssueRelationInput(
                    issue_id="i1", related_issue_id="i2", relation_type="blocks"
                ),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )


class TestLinearGetIssueActivity:
    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_get_activity_by_id(self, mock_gql: MagicMock) -> None:
        mock_gql.return_value = {
            "issue": {
                "history": {
                    "nodes": [
                        {
                            "createdAt": "2024-01-01",
                            "actor": {"name": "Alice"},
                            "fromState": {"name": "Todo"},
                            "toState": {"name": "Done"},
                            "fromAssignee": None,
                            "toAssignee": None,
                            "fromPriority": None,
                            "toPriority": None,
                            "addedLabels": None,
                            "removedLabels": None,
                        },
                    ]
                }
            },
        }

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_GET_ISSUE_ACTIVITY"]

        result = fn(GetIssueActivityInput(issue_id="i1"), EXECUTE_REQUEST, AUTH_CREDS)
        assert result["activity_count"] == 1
        assert result["activities"][0]["change_type"] == "state"

    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_get_activity_by_identifier(self, mock_gql: MagicMock) -> None:
        mock_gql.side_effect = [
            {"issue": {"id": "i1"}},
            {"issue": {"history": {"nodes": []}}},
        ]

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_GET_ISSUE_ACTIVITY"]

        result = fn(
            GetIssueActivityInput(issue_identifier="ENG-123"),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )
        assert result["activity_count"] == 0

    def test_get_activity_no_issue(self) -> None:
        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_GET_ISSUE_ACTIVITY"]

        with pytest.raises(ValueError, match="Could not resolve issue"):
            fn(GetIssueActivityInput(), EXECUTE_REQUEST, AUTH_CREDS)

    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_get_activity_priority_change(self, mock_gql: MagicMock) -> None:
        mock_gql.return_value = {
            "issue": {
                "history": {
                    "nodes": [
                        {
                            "createdAt": "2024-01-01",
                            "actor": {"name": "Alice"},
                            "fromState": None,
                            "toState": None,
                            "fromAssignee": None,
                            "toAssignee": None,
                            "fromPriority": 0,
                            "toPriority": 1,
                            "addedLabels": None,
                            "removedLabels": None,
                        },
                    ]
                }
            },
        }

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_GET_ISSUE_ACTIVITY"]

        result = fn(GetIssueActivityInput(issue_id="i1"), EXECUTE_REQUEST, AUTH_CREDS)
        assert result["activities"][0]["change_type"] == "priority"

    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_get_activity_labels_added(self, mock_gql: MagicMock) -> None:
        mock_gql.return_value = {
            "issue": {
                "history": {
                    "nodes": [
                        {
                            "createdAt": "2024-01-01",
                            "actor": {"name": "Alice"},
                            "fromState": None,
                            "toState": None,
                            "fromAssignee": None,
                            "toAssignee": None,
                            "fromPriority": None,
                            "toPriority": None,
                            "addedLabels": {"nodes": [{"name": "Bug"}]},
                            "removedLabels": None,
                        },
                    ]
                }
            },
        }

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_GET_ISSUE_ACTIVITY"]

        result = fn(GetIssueActivityInput(issue_id="i1"), EXECUTE_REQUEST, AUTH_CREDS)
        assert result["activities"][0]["change_type"] == "labels_added"


class TestLinearGetActiveSprint:
    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_get_active_sprint(self, mock_gql: MagicMock) -> None:
        mock_gql.return_value = {
            "cycles": {
                "nodes": [
                    {
                        "id": "c1",
                        "name": "Sprint 5",
                        "number": 5,
                        "startsAt": "2024-01-01",
                        "endsAt": "2024-01-15",
                        "progress": 0.5,
                        "team": {"id": "t1", "name": "Eng", "key": "ENG"},
                        "issues": {
                            "nodes": [
                                {
                                    "id": "i1",
                                    "identifier": "ENG-1",
                                    "title": "Task",
                                    "state": {"name": "In Progress", "type": "started"},
                                    "priority": 1,
                                    "assignee": {"name": "Alice"},
                                },
                            ]
                        },
                    }
                ]
            },
        }

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_GET_ACTIVE_SPRINT"]

        result = fn(GetActiveSprintInput(), EXECUTE_REQUEST, AUTH_CREDS)
        assert result["sprint_count"] == 1
        assert result["sprints"][0]["progress"] == pytest.approx(50.0)

    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_get_active_sprint_filtered_by_team(self, mock_gql: MagicMock) -> None:
        mock_gql.return_value = {
            "cycles": {
                "nodes": [
                    {
                        "id": "c1",
                        "team": {"id": "t1", "name": "Eng", "key": "ENG"},
                        "name": "S1",
                        "number": 1,
                        "startsAt": "2024-01-01",
                        "endsAt": "2024-01-15",
                        "progress": 0.0,
                        "issues": {"nodes": []},
                    },
                    {
                        "id": "c2",
                        "team": {"id": "t2", "name": "Design", "key": "DES"},
                        "name": "S1",
                        "number": 1,
                        "startsAt": "2024-01-01",
                        "endsAt": "2024-01-15",
                        "progress": 0.0,
                        "issues": {"nodes": []},
                    },
                ]
            },
        }

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_GET_ACTIVE_SPRINT"]

        result = fn(GetActiveSprintInput(team_id="t1"), EXECUTE_REQUEST, AUTH_CREDS)
        assert result["sprint_count"] == 1


class TestLinearBulkUpdateIssues:
    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_bulk_update_success(self, mock_gql: MagicMock) -> None:
        mock_gql.return_value = {
            "issueBatchUpdate": {
                "success": True,
                "issues": [
                    {"id": "i1", "identifier": "ENG-1"},
                    {"id": "i2", "identifier": "ENG-2"},
                ],
            },
        }

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_BULK_UPDATE_ISSUES"]

        result = fn(
            BulkUpdateIssuesInput(issue_ids=["i1", "i2"], state_id="s1"),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )
        assert result["updated_count"] == 2

    def test_bulk_update_no_ids(self) -> None:
        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_BULK_UPDATE_ISSUES"]

        with pytest.raises(ValueError, match="No issue IDs"):
            fn(
                BulkUpdateIssuesInput(issue_ids=[], state_id="s1"),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )

    def test_bulk_update_no_updates(self) -> None:
        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_BULK_UPDATE_ISSUES"]

        with pytest.raises(ValueError, match="No updates specified"):
            fn(BulkUpdateIssuesInput(issue_ids=["i1"]), EXECUTE_REQUEST, AUTH_CREDS)

    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_bulk_update_failure(self, mock_gql: MagicMock) -> None:
        mock_gql.return_value = {"issueBatchUpdate": {"success": False}}

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_BULK_UPDATE_ISSUES"]

        with pytest.raises(RuntimeError, match="Batch update failed"):
            fn(
                BulkUpdateIssuesInput(issue_ids=["i1"], state_id="s1"),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )


class TestLinearGetNotifications:
    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_get_notifications_unread(self, mock_gql: MagicMock) -> None:
        mock_gql.return_value = {
            "notifications": {
                "nodes": [
                    {
                        "id": "n1",
                        "type": "issueAssigned",
                        "createdAt": "2024-01-01",
                        "readAt": None,
                        "issue": {"identifier": "ENG-1", "title": "Bug"},
                        "actor": {"name": "Alice"},
                    },
                    {
                        "id": "n2",
                        "type": "issueComment",
                        "createdAt": "2024-01-02",
                        "readAt": "2024-01-02",
                        "issue": {"identifier": "ENG-2", "title": "Feature"},
                        "actor": {"name": "Bob"},
                    },
                ]
            },
        }

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_GET_NOTIFICATIONS"]

        result = fn(GetNotificationsInput(include_read=False), EXECUTE_REQUEST, AUTH_CREDS)
        assert result["count"] == 1

    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_get_notifications_include_read(self, mock_gql: MagicMock) -> None:
        mock_gql.return_value = {
            "notifications": {
                "nodes": [
                    {
                        "id": "n1",
                        "type": "issueAssigned",
                        "createdAt": "2024-01-01",
                        "readAt": None,
                        "issue": {"identifier": "ENG-1", "title": "Bug"},
                        "actor": None,
                    },
                    {
                        "id": "n2",
                        "type": "issueComment",
                        "createdAt": "2024-01-02",
                        "readAt": "2024-01-02",
                        "issue": None,
                        "actor": {"name": "Bob"},
                    },
                ]
            },
        }

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_GET_NOTIFICATIONS"]

        result = fn(GetNotificationsInput(include_read=True), EXECUTE_REQUEST, AUTH_CREDS)
        assert result["count"] == 2


class TestLinearGetWorkspaceContext:
    @patch(f"{LINEAR_MODULE}.graphql_request")
    @patch(
        f"{LINEAR_MODULE}.format_issue_summary",
        side_effect=lambda i: {"id": i.get("id")},
    )
    def test_get_workspace_context(self, mock_fmt: MagicMock, mock_gql: MagicMock) -> None:
        yesterday = (datetime.now().date() - timedelta(days=1)).isoformat()
        mock_gql.side_effect = [
            {
                "viewer": {
                    "id": "u1",
                    "name": "Alice",
                    "email": "a@b.com",
                    "assignedIssues": {"nodes": [{"id": "x"}]},
                }
            },
            {
                "teams": {
                    "nodes": [
                        {
                            "id": "t1",
                            "name": "Eng",
                            "key": "ENG",
                            "activeCycle": {"name": "Sprint 5", "progress": 0.5},
                        }
                    ]
                }
            },
            {
                "issues": {
                    "nodes": [
                        {
                            "id": "i1",
                            "priority": 1,
                            "state": {"type": "started"},
                            "dueDate": yesterday,
                            "slaBreachesAt": "2024-01-01",
                        },
                    ]
                }
            },
        ]

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_GET_WORKSPACE_CONTEXT"]

        result = fn(GetWorkspaceContextInput(), EXECUTE_REQUEST, AUTH_CREDS)
        assert result["user"]["name"] == "Alice"
        assert result["user"]["assigned_issue_count"] == 1
        assert len(result["teams"]) == 1
        assert result["teams"][0]["active_cycle"] == "Sprint 5"
        assert len(result["urgent_items"]["overdue"]) == 1
        assert len(result["urgent_items"]["high_priority"]) == 1
        assert len(result["urgent_items"]["sla_at_risk"]) == 1


class TestLinearGatherContext:
    @patch(f"{LINEAR_MODULE}.graphql_request")
    @patch(
        f"{LINEAR_MODULE}.format_issue_summary",
        side_effect=lambda i: {"id": i.get("id")},
    )
    def test_gather_context(self, mock_fmt: MagicMock, mock_gql: MagicMock) -> None:
        mock_gql.side_effect = [
            {"viewer": {"id": "u1", "name": "Alice", "email": "a@b.com"}},
            {"teams": {"nodes": [{"id": "t1", "name": "Eng", "key": "ENG"}]}},
            {"issues": {"nodes": []}},
        ]

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_GATHER_CONTEXT"]

        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS)
        assert result["user"]["id"] == "u1"
        assert len(result["teams"]) == 1
