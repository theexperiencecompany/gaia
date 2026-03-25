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

from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import httpx
import pytest

# ── Models ────────────────────────────────────────────────────────────────────
from app.models.calendar_models import (
    AddRecurrenceInput,
    CreateEventInput,
    DeleteEventInput,
    EventReference,
    FetchEventsInput,
    FindEventInput,
    GetDaySummaryInput,
    GetEventInput,
    ListCalendarsInput,
    PatchEventInput,
    SingleEventInput,
)
from app.models.common_models import GatherContextInput
from app.models.google_sheets_models import (
    ChartInput,
    ConditionalFormatInput,
    DataValidationInput,
    ShareRecipient,
    ShareSpreadsheetInput,
)
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
from app.models.linkedin_models import (
    AddCommentInput,
    CreatePostInput,
    DeleteReactionInput,
    GetPostCommentsInput,
    GetPostReactionsInput,
    ReactToPostInput,
)
from app.models.notion_models import (
    CreateTestPageInput,
    FetchDataInput,
    FetchPageAsMarkdownInput,
    InsertMarkdownInput,
    MovePageInput,
)
from app.models.twitter_models import (
    BatchFollowInput,
    BatchUnfollowInput,
    CreateThreadInput,
    ScheduleTweetInput,
    SearchUsersInput,
)

# ── Constants ─────────────────────────────────────────────────────────────────

FAKE_ACCESS_TOKEN = "fake-access-token"
FAKE_USER_ID = "user-123"
AUTH_CREDS: Dict[str, Any] = {
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
    json_data: Any, status_code: int = 200, headers: Dict[str, str] | None = None
) -> MagicMock:
    """Build a fake httpx.Response-like object with .json(), .status_code, .raise_for_status(), .headers."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    resp.text = ""
    resp.headers = headers or {}
    return resp


def _error_response(
    status_code: int = 400, text: str = "Bad Request"
) -> httpx.Response:
    """Build a real httpx.Response that will raise on .raise_for_status()."""
    resp = httpx.Response(
        status_code=status_code, text=text, request=httpx.Request("GET", "https://test")
    )
    return resp


# =============================================================================
# LINEAR TOOLS
# =============================================================================

LINEAR_MODULE = "app.agents.tools.integrations.linear_tool"


def _register_linear_tools() -> Dict[str, Any]:
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
    def test_resolve_context_basic(
        self, mock_fuzzy: MagicMock, mock_gql: MagicMock
    ) -> None:
        """Resolve context with no optional fields returns current user only."""
        mock_gql.return_value = {
            "viewer": {"id": "u1", "name": "Alice", "email": "a@b.com"}
        }

        composio = _make_composio_mock()
        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        register_linear_custom_tools(composio)
        # After registration, the inner function is defined; call it via locals trick:
        # Actually, since our decorator passthrough doesn't store the functions anywhere,
        # we need a different approach. Let's capture them.
        captured: Dict[str, Any] = {}

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
        captured: Dict[str, Any] = {}

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
        captured: Dict[str, Any] = {}

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
        captured: Dict[str, Any] = {}

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
        captured: Dict[str, Any] = {}

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
        captured: Dict[str, Any] = {}

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
        captured: Dict[str, Any] = {}

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


def _capture_tools(register_func) -> Dict[str, Any]:
    """Call a register_*_custom_tools function and capture all inner tool functions."""
    composio = MagicMock()
    captured: Dict[str, Any] = {}

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
    def test_get_my_tasks_all_filter(
        self, mock_fmt: MagicMock, mock_gql: MagicMock
    ) -> None:
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

        result = fn(
            GetMyTasksInput(filter="high_priority"), EXECUTE_REQUEST, AUTH_CREDS
        )
        assert result["count"] == 1

    @patch(f"{LINEAR_MODULE}.graphql_request")
    @patch(
        f"{LINEAR_MODULE}.format_issue_summary",
        side_effect=lambda i: {"id": i.get("id")},
    )
    def test_get_my_tasks_overdue_filter(
        self, mock_fmt: MagicMock, mock_gql: MagicMock
    ) -> None:
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
    def test_get_my_tasks_today_filter(
        self, mock_fmt: MagicMock, mock_gql: MagicMock
    ) -> None:
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
    def test_get_my_tasks_this_week_filter(
        self, mock_fmt: MagicMock, mock_gql: MagicMock
    ) -> None:
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
    def test_search_issues_basic(
        self, mock_fmt: MagicMock, mock_gql: MagicMock
    ) -> None:
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
    def test_search_issues_with_team_filter(
        self, mock_fmt: MagicMock, mock_gql: MagicMock
    ) -> None:
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

        result = fn(
            SearchIssuesInput(query="test", team_id="t1"), EXECUTE_REQUEST, AUTH_CREDS
        )
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

        result = fn(
            GetIssueFullContextInput(issue_id="i1"), EXECUTE_REQUEST, AUTH_CREDS
        )
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
                    "nodes": [
                        {"title": "file.pdf", "url": "https://example.com/file.pdf"}
                    ]
                },
            },
        }

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_GET_ISSUE_FULL_CONTEXT"]

        result = fn(
            GetIssueFullContextInput(issue_id="i1"), EXECUTE_REQUEST, AUTH_CREDS
        )
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

        result = fn(
            CreateIssueInput(team_id="t1", title="New Bug"), EXECUTE_REQUEST, AUTH_CREDS
        )
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
            CreateIssueRelationInput(
                issue_id="i1", related_issue_id="i2", relation_type="blocks"
            ),
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

        result = fn(
            GetNotificationsInput(include_read=False), EXECUTE_REQUEST, AUTH_CREDS
        )
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

        result = fn(
            GetNotificationsInput(include_read=True), EXECUTE_REQUEST, AUTH_CREDS
        )
        assert result["count"] == 2


class TestLinearGetWorkspaceContext:
    @patch(f"{LINEAR_MODULE}.graphql_request")
    @patch(
        f"{LINEAR_MODULE}.format_issue_summary",
        side_effect=lambda i: {"id": i.get("id")},
    )
    def test_get_workspace_context(
        self, mock_fmt: MagicMock, mock_gql: MagicMock
    ) -> None:
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


# =============================================================================
# GOOGLE SHEETS TOOLS
# =============================================================================

SHEETS_MODULE = "app.agents.tools.integrations.google_sheets_tool"


class TestGoogleSheetsShareSpreadsheet:
    @patch(f"{SHEETS_MODULE}._http_client")
    def test_share_success(self, mock_client: MagicMock) -> None:
        mock_client.post.return_value = _ok_response({"id": "perm-1"})

        from app.agents.tools.integrations.google_sheets_tool import (
            register_google_sheets_custom_tools,
        )

        tools = _capture_tools(register_google_sheets_custom_tools)
        fn = tools["CUSTOM_SHARE_SPREADSHEET"]

        request = ShareSpreadsheetInput(
            spreadsheet_id="sheet-1",
            recipients=[ShareRecipient(email="bob@test.com", role="writer")],  # type: ignore[call-arg]
        )
        result = fn(request, EXECUTE_REQUEST, AUTH_CREDS)
        assert result["total_shared"] == 1
        assert result["total_failed"] == 0

    @patch(f"{SHEETS_MODULE}._http_client")
    def test_share_all_fail_raises(self, mock_client: MagicMock) -> None:
        error_resp = _error_response(403, "Forbidden")
        mock_client.post.side_effect = httpx.HTTPStatusError(
            "Forbidden",
            request=httpx.Request("POST", "https://test"),
            response=error_resp,
        )

        from app.agents.tools.integrations.google_sheets_tool import (
            register_google_sheets_custom_tools,
        )

        tools = _capture_tools(register_google_sheets_custom_tools)
        fn = tools["CUSTOM_SHARE_SPREADSHEET"]

        with pytest.raises(RuntimeError, match="Failed to share"):
            fn(
                ShareSpreadsheetInput(
                    spreadsheet_id="sheet-1",
                    recipients=[ShareRecipient(email="bob@test.com")],  # type: ignore[call-arg]
                ),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )

    @patch(f"{SHEETS_MODULE}._http_client")
    def test_share_partial_failure(self, mock_client: MagicMock) -> None:
        """Some succeed, some fail -- should not raise."""
        ok = _ok_response({"id": "perm-1"})
        error_resp = _error_response(403, "Forbidden")
        exc = httpx.HTTPStatusError(
            "Forbidden",
            request=httpx.Request("POST", "https://test"),
            response=error_resp,
        )
        mock_client.post.side_effect = [ok, exc]

        from app.agents.tools.integrations.google_sheets_tool import (
            register_google_sheets_custom_tools,
        )

        tools = _capture_tools(register_google_sheets_custom_tools)
        fn = tools["CUSTOM_SHARE_SPREADSHEET"]

        result = fn(
            ShareSpreadsheetInput(
                spreadsheet_id="sheet-1",
                recipients=[
                    ShareRecipient(email="alice@test.com"),  # type: ignore[call-arg]
                    ShareRecipient(email="bob@test.com"),  # type: ignore[call-arg]
                ],
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )
        assert result["total_shared"] == 1
        assert result["total_failed"] == 1


class TestGoogleSheetsSetDataValidation:
    @patch(f"{SHEETS_MODULE}.get_sheet_id_by_name", return_value=0)
    @patch(
        f"{SHEETS_MODULE}.parse_a1_range",
        return_value={
            "startRowIndex": 1,
            "endRowIndex": 100,
            "startColumnIndex": 0,
            "endColumnIndex": 1,
        },
    )
    @patch(f"{SHEETS_MODULE}._http_client")
    def test_dropdown_list_validation(
        self, mock_client: MagicMock, mock_parse: MagicMock, mock_sheet: MagicMock
    ) -> None:
        mock_client.post.return_value = _ok_response({})

        from app.agents.tools.integrations.google_sheets_tool import (
            register_google_sheets_custom_tools,
        )

        tools = _capture_tools(register_google_sheets_custom_tools)
        fn = tools["CUSTOM_SET_DATA_VALIDATION"]

        request = DataValidationInput(  # type: ignore[call-arg]
            spreadsheet_id="s1",
            sheet_name="Sheet1",
            range="A2:A100",
            validation_type="dropdown_list",
            values=["Yes", "No"],
        )
        result = fn(request, EXECUTE_REQUEST, AUTH_CREDS)
        assert result["validation_type"] == "dropdown_list"

    @patch(f"{SHEETS_MODULE}.get_sheet_id_by_name", return_value=None)
    def test_sheet_not_found(self, mock_sheet: MagicMock) -> None:
        from app.agents.tools.integrations.google_sheets_tool import (
            register_google_sheets_custom_tools,
        )

        tools = _capture_tools(register_google_sheets_custom_tools)
        fn = tools["CUSTOM_SET_DATA_VALIDATION"]

        with pytest.raises(ValueError, match="not found"):
            fn(
                DataValidationInput(  # type: ignore[call-arg]
                    spreadsheet_id="s1",
                    sheet_name="Missing",
                    range="A1:A10",
                    validation_type="dropdown_list",
                    values=["x"],
                ),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )

    @patch(f"{SHEETS_MODULE}.get_sheet_id_by_name", return_value=0)
    @patch(
        f"{SHEETS_MODULE}.parse_a1_range",
        return_value={
            "startRowIndex": 0,
            "endRowIndex": 1,
            "startColumnIndex": 0,
            "endColumnIndex": 1,
        },
    )
    @patch(f"{SHEETS_MODULE}._http_client")
    def test_number_between_validation(
        self, mock_client: MagicMock, mock_parse: MagicMock, mock_sheet: MagicMock
    ) -> None:
        mock_client.post.return_value = _ok_response({})

        from app.agents.tools.integrations.google_sheets_tool import (
            register_google_sheets_custom_tools,
        )

        tools = _capture_tools(register_google_sheets_custom_tools)
        fn = tools["CUSTOM_SET_DATA_VALIDATION"]

        request = DataValidationInput(  # type: ignore[call-arg]
            spreadsheet_id="s1",
            sheet_name="Sheet1",
            range="A1",
            validation_type="number",
            min_value="0",
            max_value="100",
        )
        result = fn(request, EXECUTE_REQUEST, AUTH_CREDS)
        assert result["validation_type"] == "number"

    @patch(f"{SHEETS_MODULE}.get_sheet_id_by_name", return_value=0)
    @patch(
        f"{SHEETS_MODULE}.parse_a1_range",
        return_value={
            "startRowIndex": 0,
            "endRowIndex": 1,
            "startColumnIndex": 0,
            "endColumnIndex": 1,
        },
    )
    @patch(f"{SHEETS_MODULE}._http_client")
    def test_custom_formula_validation(
        self, mock_client: MagicMock, mock_parse: MagicMock, mock_sheet: MagicMock
    ) -> None:
        mock_client.post.return_value = _ok_response({})

        from app.agents.tools.integrations.google_sheets_tool import (
            register_google_sheets_custom_tools,
        )

        tools = _capture_tools(register_google_sheets_custom_tools)
        fn = tools["CUSTOM_SET_DATA_VALIDATION"]

        request = DataValidationInput(  # type: ignore[call-arg]
            spreadsheet_id="s1",
            sheet_name="Sheet1",
            range="A1",
            validation_type="custom_formula",
            formula="=LEN(A1)<=50",
        )
        result = fn(request, EXECUTE_REQUEST, AUTH_CREDS)
        assert result["validation_type"] == "custom_formula"

    @patch(f"{SHEETS_MODULE}.get_sheet_id_by_name", return_value=0)
    @patch(
        f"{SHEETS_MODULE}.parse_a1_range",
        return_value={
            "startRowIndex": 0,
            "endRowIndex": 1,
            "startColumnIndex": 0,
            "endColumnIndex": 1,
        },
    )
    def test_dropdown_list_no_values(
        self, mock_parse: MagicMock, mock_sheet: MagicMock
    ) -> None:
        from app.agents.tools.integrations.google_sheets_tool import (
            register_google_sheets_custom_tools,
        )

        tools = _capture_tools(register_google_sheets_custom_tools)
        fn = tools["CUSTOM_SET_DATA_VALIDATION"]

        with pytest.raises(ValueError, match="values required"):
            fn(
                DataValidationInput(  # type: ignore[call-arg]
                    spreadsheet_id="s1",
                    sheet_name="Sheet1",
                    range="A1",
                    validation_type="dropdown_list",
                ),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )

    @patch(f"{SHEETS_MODULE}.get_sheet_id_by_name", return_value=0)
    @patch(
        f"{SHEETS_MODULE}.parse_a1_range",
        return_value={
            "startRowIndex": 0,
            "endRowIndex": 1,
            "startColumnIndex": 0,
            "endColumnIndex": 1,
        },
    )
    def test_number_validation_no_bounds(
        self, mock_parse: MagicMock, mock_sheet: MagicMock
    ) -> None:
        from app.agents.tools.integrations.google_sheets_tool import (
            register_google_sheets_custom_tools,
        )

        tools = _capture_tools(register_google_sheets_custom_tools)
        fn = tools["CUSTOM_SET_DATA_VALIDATION"]

        with pytest.raises(ValueError, match="min_value or max_value required"):
            fn(
                DataValidationInput(  # type: ignore[call-arg]
                    spreadsheet_id="s1",
                    sheet_name="Sheet1",
                    range="A1",
                    validation_type="number",
                ),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )

    @patch(f"{SHEETS_MODULE}.get_sheet_id_by_name", return_value=0)
    @patch(
        f"{SHEETS_MODULE}.parse_a1_range",
        return_value={
            "startRowIndex": 0,
            "endRowIndex": 1,
            "startColumnIndex": 0,
            "endColumnIndex": 1,
        },
    )
    @patch(f"{SHEETS_MODULE}._http_client")
    def test_dropdown_range_validation(
        self, mock_client: MagicMock, mock_parse: MagicMock, mock_sheet: MagicMock
    ) -> None:
        mock_client.post.return_value = _ok_response({})

        from app.agents.tools.integrations.google_sheets_tool import (
            register_google_sheets_custom_tools,
        )

        tools = _capture_tools(register_google_sheets_custom_tools)
        fn = tools["CUSTOM_SET_DATA_VALIDATION"]

        request = DataValidationInput(  # type: ignore[call-arg]
            spreadsheet_id="s1",
            sheet_name="Sheet1",
            range="A1",
            validation_type="dropdown_range",
            source_range="Sheet2!A:A",
        )
        result = fn(request, EXECUTE_REQUEST, AUTH_CREDS)
        assert result["validation_type"] == "dropdown_range"

    @patch(f"{SHEETS_MODULE}.get_sheet_id_by_name", return_value=0)
    @patch(
        f"{SHEETS_MODULE}.parse_a1_range",
        return_value={
            "startRowIndex": 0,
            "endRowIndex": 1,
            "startColumnIndex": 0,
            "endColumnIndex": 1,
        },
    )
    @patch(f"{SHEETS_MODULE}._http_client")
    def test_date_between_validation(
        self, mock_client: MagicMock, mock_parse: MagicMock, mock_sheet: MagicMock
    ) -> None:
        mock_client.post.return_value = _ok_response({})

        from app.agents.tools.integrations.google_sheets_tool import (
            register_google_sheets_custom_tools,
        )

        tools = _capture_tools(register_google_sheets_custom_tools)
        fn = tools["CUSTOM_SET_DATA_VALIDATION"]

        request = DataValidationInput(  # type: ignore[call-arg]
            spreadsheet_id="s1",
            sheet_name="Sheet1",
            range="A1",
            validation_type="date",
            min_value="2024-01-01",
            max_value="2024-12-31",
        )
        result = fn(request, EXECUTE_REQUEST, AUTH_CREDS)
        assert result["validation_type"] == "date"


class TestGoogleSheetsConditionalFormat:
    @patch(f"{SHEETS_MODULE}.get_sheet_id_by_name", return_value=0)
    @patch(
        f"{SHEETS_MODULE}.parse_a1_range",
        return_value={
            "startRowIndex": 0,
            "endRowIndex": 10,
            "startColumnIndex": 0,
            "endColumnIndex": 1,
        },
    )
    @patch(f"{SHEETS_MODULE}._http_client")
    def test_color_scale(
        self, mock_client: MagicMock, mock_parse: MagicMock, mock_sheet: MagicMock
    ) -> None:
        mock_client.post.return_value = _ok_response({})

        from app.agents.tools.integrations.google_sheets_tool import (
            register_google_sheets_custom_tools,
        )

        tools = _capture_tools(register_google_sheets_custom_tools)
        fn = tools["CUSTOM_ADD_CONDITIONAL_FORMAT"]

        request = ConditionalFormatInput(  # type: ignore[call-arg]
            spreadsheet_id="s1",
            sheet_name="Sheet1",
            range="A1:A10",
            format_type="color_scale",
            min_color="#FF0000",
            max_color="#00FF00",
        )
        result = fn(request, EXECUTE_REQUEST, AUTH_CREDS)
        assert result["format_type"] == "color_scale"

    @patch(f"{SHEETS_MODULE}.get_sheet_id_by_name", return_value=0)
    @patch(
        f"{SHEETS_MODULE}.parse_a1_range",
        return_value={
            "startRowIndex": 0,
            "endRowIndex": 10,
            "startColumnIndex": 0,
            "endColumnIndex": 1,
        },
    )
    @patch(f"{SHEETS_MODULE}._http_client")
    def test_value_based_greater_than(
        self, mock_client: MagicMock, mock_parse: MagicMock, mock_sheet: MagicMock
    ) -> None:
        mock_client.post.return_value = _ok_response({})

        from app.agents.tools.integrations.google_sheets_tool import (
            register_google_sheets_custom_tools,
        )

        tools = _capture_tools(register_google_sheets_custom_tools)
        fn = tools["CUSTOM_ADD_CONDITIONAL_FORMAT"]

        request = ConditionalFormatInput(  # type: ignore[call-arg]
            spreadsheet_id="s1",
            sheet_name="Sheet1",
            range="B1:B10",
            format_type="value_based",
            condition="greater_than",
            condition_values=["100"],
            background_color="#FF0000",
            bold=True,
        )
        result = fn(request, EXECUTE_REQUEST, AUTH_CREDS)
        assert result["format_type"] == "value_based"

    @patch(f"{SHEETS_MODULE}.get_sheet_id_by_name", return_value=0)
    @patch(
        f"{SHEETS_MODULE}.parse_a1_range",
        return_value={
            "startRowIndex": 0,
            "endRowIndex": 10,
            "startColumnIndex": 0,
            "endColumnIndex": 1,
        },
    )
    @patch(f"{SHEETS_MODULE}._http_client")
    def test_value_based_is_empty(
        self, mock_client: MagicMock, mock_parse: MagicMock, mock_sheet: MagicMock
    ) -> None:
        mock_client.post.return_value = _ok_response({})

        from app.agents.tools.integrations.google_sheets_tool import (
            register_google_sheets_custom_tools,
        )

        tools = _capture_tools(register_google_sheets_custom_tools)
        fn = tools["CUSTOM_ADD_CONDITIONAL_FORMAT"]

        request = ConditionalFormatInput(  # type: ignore[call-arg]
            spreadsheet_id="s1",
            sheet_name="Sheet1",
            range="A1:A10",
            format_type="value_based",
            condition="is_empty",
            background_color="#CCCCCC",
        )
        result = fn(request, EXECUTE_REQUEST, AUTH_CREDS)
        assert result["format_type"] == "value_based"

    @patch(f"{SHEETS_MODULE}.get_sheet_id_by_name", return_value=0)
    @patch(
        f"{SHEETS_MODULE}.parse_a1_range",
        return_value={
            "startRowIndex": 0,
            "endRowIndex": 10,
            "startColumnIndex": 0,
            "endColumnIndex": 1,
        },
    )
    def test_value_based_no_condition(
        self, mock_parse: MagicMock, mock_sheet: MagicMock
    ) -> None:
        from app.agents.tools.integrations.google_sheets_tool import (
            register_google_sheets_custom_tools,
        )

        tools = _capture_tools(register_google_sheets_custom_tools)
        fn = tools["CUSTOM_ADD_CONDITIONAL_FORMAT"]

        with pytest.raises(ValueError, match="condition required"):
            fn(
                ConditionalFormatInput(  # type: ignore[call-arg]
                    spreadsheet_id="s1",
                    sheet_name="Sheet1",
                    range="A1:A10",
                    format_type="value_based",
                ),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )

    @patch(f"{SHEETS_MODULE}.get_sheet_id_by_name", return_value=None)
    def test_conditional_format_sheet_not_found(self, mock_sheet: MagicMock) -> None:
        from app.agents.tools.integrations.google_sheets_tool import (
            register_google_sheets_custom_tools,
        )

        tools = _capture_tools(register_google_sheets_custom_tools)
        fn = tools["CUSTOM_ADD_CONDITIONAL_FORMAT"]

        with pytest.raises(ValueError, match="not found"):
            fn(
                ConditionalFormatInput(  # type: ignore[call-arg]
                    spreadsheet_id="s1",
                    sheet_name="Missing",
                    range="A1",
                    format_type="color_scale",
                ),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )


class TestGoogleSheetsCreateChart:
    @patch(f"{SHEETS_MODULE}.get_sheet_id_by_name", return_value=0)
    @patch(
        f"{SHEETS_MODULE}.parse_a1_range",
        return_value={
            "startRowIndex": 0,
            "endRowIndex": 10,
            "startColumnIndex": 0,
            "endColumnIndex": 2,
        },
    )
    @patch(f"{SHEETS_MODULE}._http_client")
    def test_create_bar_chart(
        self, mock_client: MagicMock, mock_parse: MagicMock, mock_sheet: MagicMock
    ) -> None:
        mock_client.post.return_value = _ok_response(
            {
                "replies": [{"addChart": {"chart": {"chartId": 42}}}],
            }
        )

        from app.agents.tools.integrations.google_sheets_tool import (
            register_google_sheets_custom_tools,
        )

        tools = _capture_tools(register_google_sheets_custom_tools)
        fn = tools["CUSTOM_CREATE_CHART"]

        request = ChartInput(  # type: ignore[call-arg]
            spreadsheet_id="s1",
            sheet_name="Sheet1",
            data_range="A1:B10",
            chart_type="BAR",
            title="Sales",
        )
        result = fn(request, EXECUTE_REQUEST, AUTH_CREDS)
        assert result["chart_id"] == 42
        assert result["chart_type"] == "BAR"

    @patch(f"{SHEETS_MODULE}.get_sheet_id_by_name")
    @patch(
        f"{SHEETS_MODULE}.parse_a1_range",
        return_value={
            "startRowIndex": 0,
            "endRowIndex": 10,
            "startColumnIndex": 0,
            "endColumnIndex": 2,
        },
    )
    @patch(f"{SHEETS_MODULE}._http_client")
    def test_create_pie_chart(
        self, mock_client: MagicMock, mock_parse: MagicMock, mock_sheet: MagicMock
    ) -> None:
        mock_sheet.return_value = 0
        mock_client.post.return_value = _ok_response(
            {
                "replies": [{"addChart": {"chart": {"chartId": 99}}}],
            }
        )

        from app.agents.tools.integrations.google_sheets_tool import (
            register_google_sheets_custom_tools,
        )

        tools = _capture_tools(register_google_sheets_custom_tools)
        fn = tools["CUSTOM_CREATE_CHART"]

        request = ChartInput(  # type: ignore[call-arg]
            spreadsheet_id="s1",
            sheet_name="Sheet1",
            data_range="A1:B10",
            chart_type="PIE",
        )
        result = fn(request, EXECUTE_REQUEST, AUTH_CREDS)
        assert result["chart_type"] == "PIE"

    @patch(f"{SHEETS_MODULE}.get_sheet_id_by_name", return_value=None)
    def test_chart_source_sheet_not_found(self, mock_sheet: MagicMock) -> None:
        from app.agents.tools.integrations.google_sheets_tool import (
            register_google_sheets_custom_tools,
        )

        tools = _capture_tools(register_google_sheets_custom_tools)
        fn = tools["CUSTOM_CREATE_CHART"]

        with pytest.raises(ValueError, match="not found"):
            fn(
                ChartInput(  # type: ignore[call-arg]
                    spreadsheet_id="s1",
                    sheet_name="Missing",
                    data_range="A1:B10",
                    chart_type="BAR",
                ),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )


class TestGoogleSheetsGatherContext:
    @patch(f"{SHEETS_MODULE}._http_client")
    def test_gather_context(self, mock_client: MagicMock) -> None:
        mock_client.get.return_value = _ok_response(
            {
                "files": [
                    {
                        "id": "f1",
                        "name": "Budget",
                        "modifiedTime": "2024-01-01",
                        "webViewLink": "https://sheets",
                    }
                ],
            }
        )

        from app.agents.tools.integrations.google_sheets_tool import (
            register_google_sheets_custom_tools,
        )

        tools = _capture_tools(register_google_sheets_custom_tools)
        fn = tools["CUSTOM_GATHER_CONTEXT"]

        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS)
        assert result["spreadsheet_count"] == 1

    @patch(f"{SHEETS_MODULE}._http_client")
    def test_gather_context_api_failure(self, mock_client: MagicMock) -> None:
        mock_client.get.side_effect = Exception("API down")

        from app.agents.tools.integrations.google_sheets_tool import (
            register_google_sheets_custom_tools,
        )

        tools = _capture_tools(register_google_sheets_custom_tools)
        fn = tools["CUSTOM_GATHER_CONTEXT"]

        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS)
        assert result["spreadsheet_count"] == 0


# =============================================================================
# TWITTER TOOLS
# =============================================================================

TWITTER_MODULE = "app.agents.tools.integrations.twitter_tool"


class TestTwitterBatchFollow:
    @patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=MagicMock())
    @patch(f"{TWITTER_MODULE}.follow_user", return_value={"success": True})
    @patch(f"{TWITTER_MODULE}.get_my_user_id", return_value="my-123")
    @patch(f"{TWITTER_MODULE}.get_access_token", return_value=FAKE_ACCESS_TOKEN)
    def test_follow_by_user_ids(
        self,
        mock_token: MagicMock,
        mock_uid: MagicMock,
        mock_follow: MagicMock,
        mock_writer: MagicMock,
    ) -> None:
        from app.agents.tools.integrations.twitter_tool import (
            register_twitter_custom_tools,
        )

        tools = _capture_tools(register_twitter_custom_tools)
        fn = tools["CUSTOM_BATCH_FOLLOW"]

        result = fn(
            BatchFollowInput(user_ids=["u1", "u2"]),
            EXECUTE_REQUEST,
            AUTH_CREDS,  # type: ignore[call-arg]
        )
        assert result["followed_count"] == 2

    @patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=MagicMock())
    @patch(f"{TWITTER_MODULE}.follow_user", return_value={"success": True})
    @patch(
        f"{TWITTER_MODULE}.lookup_user_by_username",
        return_value={"id": "u1", "username": "alice", "name": "Alice"},
    )
    @patch(f"{TWITTER_MODULE}.get_my_user_id", return_value="my-123")
    @patch(f"{TWITTER_MODULE}.get_access_token", return_value=FAKE_ACCESS_TOKEN)
    def test_follow_by_usernames(
        self,
        mock_token: MagicMock,
        mock_uid: MagicMock,
        mock_lookup: MagicMock,
        mock_follow: MagicMock,
        mock_writer: MagicMock,
    ) -> None:
        from app.agents.tools.integrations.twitter_tool import (
            register_twitter_custom_tools,
        )

        tools = _capture_tools(register_twitter_custom_tools)
        fn = tools["CUSTOM_BATCH_FOLLOW"]

        result = fn(BatchFollowInput(usernames=["alice"]), EXECUTE_REQUEST, AUTH_CREDS)  # type: ignore[call-arg]
        assert result["followed_count"] == 1

    @patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=MagicMock())
    @patch(f"{TWITTER_MODULE}.get_my_user_id", return_value="my-123")
    @patch(f"{TWITTER_MODULE}.get_access_token", return_value=FAKE_ACCESS_TOKEN)
    def test_follow_no_input(
        self, mock_token: MagicMock, mock_uid: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.agents.tools.integrations.twitter_tool import (
            register_twitter_custom_tools,
        )

        tools = _capture_tools(register_twitter_custom_tools)
        fn = tools["CUSTOM_BATCH_FOLLOW"]

        with pytest.raises(ValueError, match="Either usernames or user_ids"):
            fn(BatchFollowInput(), EXECUTE_REQUEST, AUTH_CREDS)  # type: ignore[call-arg]

    @patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=MagicMock())
    @patch(f"{TWITTER_MODULE}.get_my_user_id", return_value=None)
    @patch(f"{TWITTER_MODULE}.get_access_token", return_value=FAKE_ACCESS_TOKEN)
    def test_follow_no_user_id(
        self, mock_token: MagicMock, mock_uid: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.agents.tools.integrations.twitter_tool import (
            register_twitter_custom_tools,
        )

        tools = _capture_tools(register_twitter_custom_tools)
        fn = tools["CUSTOM_BATCH_FOLLOW"]

        with pytest.raises(ValueError, match="Could not get authenticated user"):
            fn(BatchFollowInput(user_ids=["u1"]), EXECUTE_REQUEST, AUTH_CREDS)  # type: ignore[call-arg]

    @patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=MagicMock())
    @patch(
        f"{TWITTER_MODULE}.follow_user",
        return_value={"success": False, "error": "rate limited"},
    )
    @patch(f"{TWITTER_MODULE}.get_my_user_id", return_value="my-123")
    @patch(f"{TWITTER_MODULE}.get_access_token", return_value=FAKE_ACCESS_TOKEN)
    def test_follow_all_fail_raises(
        self,
        mock_token: MagicMock,
        mock_uid: MagicMock,
        mock_follow: MagicMock,
        mock_writer: MagicMock,
    ) -> None:
        from app.agents.tools.integrations.twitter_tool import (
            register_twitter_custom_tools,
        )

        tools = _capture_tools(register_twitter_custom_tools)
        fn = tools["CUSTOM_BATCH_FOLLOW"]

        with pytest.raises(RuntimeError, match="Failed to follow all users"):
            fn(BatchFollowInput(user_ids=["u1"]), EXECUTE_REQUEST, AUTH_CREDS)  # type: ignore[call-arg]

    @patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=MagicMock())
    @patch(f"{TWITTER_MODULE}.lookup_user_by_username", return_value=None)
    @patch(f"{TWITTER_MODULE}.get_my_user_id", return_value="my-123")
    @patch(f"{TWITTER_MODULE}.get_access_token", return_value=FAKE_ACCESS_TOKEN)
    def test_follow_username_not_found(
        self,
        mock_token: MagicMock,
        mock_uid: MagicMock,
        mock_lookup: MagicMock,
        mock_writer: MagicMock,
    ) -> None:
        from app.agents.tools.integrations.twitter_tool import (
            register_twitter_custom_tools,
        )

        tools = _capture_tools(register_twitter_custom_tools)
        fn = tools["CUSTOM_BATCH_FOLLOW"]

        with pytest.raises(RuntimeError, match="Failed to follow all users"):
            fn(BatchFollowInput(usernames=["nonexistent"]), EXECUTE_REQUEST, AUTH_CREDS)  # type: ignore[call-arg]


class TestTwitterBatchUnfollow:
    @patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=MagicMock())
    @patch(f"{TWITTER_MODULE}.unfollow_user", return_value={"success": True})
    @patch(f"{TWITTER_MODULE}.get_my_user_id", return_value="my-123")
    @patch(f"{TWITTER_MODULE}.get_access_token", return_value=FAKE_ACCESS_TOKEN)
    def test_unfollow_by_ids(
        self,
        mock_token: MagicMock,
        mock_uid: MagicMock,
        mock_unfollow: MagicMock,
        mock_writer: MagicMock,
    ) -> None:
        from app.agents.tools.integrations.twitter_tool import (
            register_twitter_custom_tools,
        )

        tools = _capture_tools(register_twitter_custom_tools)
        fn = tools["CUSTOM_BATCH_UNFOLLOW"]

        result = fn(BatchUnfollowInput(user_ids=["u1"]), EXECUTE_REQUEST, AUTH_CREDS)  # type: ignore[call-arg]
        assert result["unfollowed_count"] == 1

    @patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=MagicMock())
    @patch(f"{TWITTER_MODULE}.get_my_user_id", return_value="my-123")
    @patch(f"{TWITTER_MODULE}.get_access_token", return_value=FAKE_ACCESS_TOKEN)
    def test_unfollow_no_input(
        self, mock_token: MagicMock, mock_uid: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.agents.tools.integrations.twitter_tool import (
            register_twitter_custom_tools,
        )

        tools = _capture_tools(register_twitter_custom_tools)
        fn = tools["CUSTOM_BATCH_UNFOLLOW"]

        with pytest.raises(ValueError, match="Either usernames or user_ids"):
            fn(BatchUnfollowInput(), EXECUTE_REQUEST, AUTH_CREDS)  # type: ignore[call-arg]


class TestTwitterCreateThread:
    @patch(f"{TWITTER_MODULE}._twitter_utils_module")
    @patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=MagicMock())
    @patch(f"{TWITTER_MODULE}.create_tweet")
    @patch(f"{TWITTER_MODULE}.get_access_token", return_value=FAKE_ACCESS_TOKEN)
    def test_create_thread_success(
        self,
        mock_token: MagicMock,
        mock_create: MagicMock,
        mock_writer: MagicMock,
        mock_utils: MagicMock,
    ) -> None:
        mock_create.side_effect = [
            {"success": True, "data": {"id": "t1"}},
            {"success": True, "data": {"id": "t2"}},
        ]
        me_resp = _ok_response({"data": {"username": "alice"}})
        mock_utils._http_client.get.return_value = me_resp

        from app.agents.tools.integrations.twitter_tool import (
            register_twitter_custom_tools,
        )

        tools = _capture_tools(register_twitter_custom_tools)
        fn = tools["CUSTOM_CREATE_THREAD"]

        result = fn(
            CreateThreadInput(tweets=["Hello", "World"]),  # type: ignore[call-arg]
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )
        assert result["tweet_count"] == 2
        assert result["thread_id"] == "t1"
        assert "alice" in result["thread_url"]

    @patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=MagicMock())
    @patch(
        f"{TWITTER_MODULE}.create_tweet",
        return_value={"success": False, "error": "rate limited"},
    )
    @patch(f"{TWITTER_MODULE}.get_access_token", return_value=FAKE_ACCESS_TOKEN)
    def test_create_thread_fail_on_first(
        self, mock_token: MagicMock, mock_create: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.agents.tools.integrations.twitter_tool import (
            register_twitter_custom_tools,
        )

        tools = _capture_tools(register_twitter_custom_tools)
        fn = tools["CUSTOM_CREATE_THREAD"]

        with pytest.raises(RuntimeError, match="Failed at tweet 1"):
            fn(
                CreateThreadInput(tweets=["Hello", "World"]),  # type: ignore[call-arg]
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )


class TestTwitterSearchUsers:
    @patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=MagicMock())
    @patch(f"{TWITTER_MODULE}.search_tweets")
    @patch(f"{TWITTER_MODULE}.get_access_token", return_value=FAKE_ACCESS_TOKEN)
    def test_search_users_success(
        self, mock_token: MagicMock, mock_search: MagicMock, mock_writer: MagicMock
    ) -> None:
        mock_search.return_value = {
            "success": True,
            "data": {
                "includes": {
                    "users": [
                        {
                            "id": "u1",
                            "username": "alice",
                            "name": "Alice",
                            "description": "Dev",
                            "verified": False,
                            "public_metrics": {"followers_count": 100},
                        },
                    ]
                },
            },
        }

        from app.agents.tools.integrations.twitter_tool import (
            register_twitter_custom_tools,
        )

        tools = _capture_tools(register_twitter_custom_tools)
        fn = tools["CUSTOM_SEARCH_USERS"]

        result = fn(SearchUsersInput(query="alice"), EXECUTE_REQUEST, AUTH_CREDS)  # type: ignore[call-arg]
        assert result["count"] == 1

    @patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=MagicMock())
    @patch(
        f"{TWITTER_MODULE}.search_tweets",
        return_value={"success": False, "error": "API error"},
    )
    @patch(f"{TWITTER_MODULE}.get_access_token", return_value=FAKE_ACCESS_TOKEN)
    def test_search_users_api_failure(
        self, mock_token: MagicMock, mock_search: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.agents.tools.integrations.twitter_tool import (
            register_twitter_custom_tools,
        )

        tools = _capture_tools(register_twitter_custom_tools)
        fn = tools["CUSTOM_SEARCH_USERS"]

        with pytest.raises(RuntimeError, match="Search failed"):
            fn(SearchUsersInput(query="alice"), EXECUTE_REQUEST, AUTH_CREDS)  # type: ignore[call-arg]


class TestTwitterScheduleTweet:
    @patch(f"{TWITTER_MODULE}.get_stream_writer", return_value=MagicMock())
    @patch(f"{TWITTER_MODULE}.get_access_token", return_value=FAKE_ACCESS_TOKEN)
    def test_schedule_tweet(
        self, mock_token: MagicMock, mock_writer: MagicMock
    ) -> None:
        from app.agents.tools.integrations.twitter_tool import (
            register_twitter_custom_tools,
        )

        tools = _capture_tools(register_twitter_custom_tools)
        fn = tools["CUSTOM_SCHEDULE_TWEET"]

        result = fn(
            ScheduleTweetInput(text="Hello!", scheduled_time="2024-12-25T10:00:00Z"),  # type: ignore[call-arg]
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )
        assert "draft" in result
        assert result["draft"]["text"] == "Hello!"


class TestTwitterGatherContext:
    @patch(f"{TWITTER_MODULE}._twitter_utils_module")
    @patch(
        f"{TWITTER_MODULE}.twitter_headers",
        return_value={"Authorization": "Bearer fake"},
    )
    @patch(f"{TWITTER_MODULE}.get_access_token", return_value=FAKE_ACCESS_TOKEN)
    def test_gather_context(
        self, mock_token: MagicMock, mock_headers: MagicMock, mock_utils: MagicMock
    ) -> None:
        me_resp = _ok_response(
            {
                "data": {
                    "id": "u1",
                    "username": "alice",
                    "name": "Alice",
                    "description": "Dev",
                    "public_metrics": {
                        "followers_count": 100,
                        "following_count": 50,
                        "tweet_count": 200,
                    },
                },
            }
        )
        me_resp.status_code = 200
        tweets_resp = _ok_response(
            {
                "data": [
                    {
                        "id": "tw1",
                        "text": "Hello world",
                        "created_at": "2024-01-01",
                        "public_metrics": {"like_count": 5, "retweet_count": 2},
                    }
                ],
            }
        )
        tweets_resp.status_code = 200
        mock_utils._http_client.get.side_effect = [me_resp, tweets_resp]

        from app.agents.tools.integrations.twitter_tool import (
            register_twitter_custom_tools,
        )

        tools = _capture_tools(register_twitter_custom_tools)
        fn = tools["CUSTOM_GATHER_CONTEXT"]

        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS)
        assert result["user"]["username"] == "alice"
        assert len(result["recent_tweets"]) == 1


# =============================================================================
# LINKEDIN TOOLS
# =============================================================================

LINKEDIN_MODULE = "app.agents.tools.integrations.linkedin_tool"


class TestLinkedInCreatePost:
    @patch(f"{LINKEDIN_MODULE}._http_client")
    @patch(f"{LINKEDIN_MODULE}.get_author_urn", return_value="urn:li:person:123")
    @patch(f"{LINKEDIN_MODULE}.get_access_token", return_value=FAKE_ACCESS_TOKEN)
    @patch(
        f"{LINKEDIN_MODULE}.linkedin_headers",
        return_value={"Authorization": "Bearer fake"},
    )
    def test_create_text_post(
        self,
        mock_headers: MagicMock,
        mock_token: MagicMock,
        mock_urn: MagicMock,
        mock_client: MagicMock,
    ) -> None:
        resp = _ok_response({}, headers={"x-restli-id": "urn:li:share:456"})
        mock_client.post.return_value = resp

        from app.agents.tools.integrations.linkedin_tool import (
            register_linkedin_custom_tools,
        )

        tools = _capture_tools(register_linkedin_custom_tools)
        fn = tools["CUSTOM_CREATE_POST"]

        result = fn(
            CreatePostInput(commentary="Hello LinkedIn!"),
            EXECUTE_REQUEST,
            AUTH_CREDS,  # type: ignore[call-arg]
        )
        assert result["post_id"] == "urn:li:share:456"
        assert result["media_type"] == "text"

    @patch(f"{LINKEDIN_MODULE}._http_client")
    @patch(f"{LINKEDIN_MODULE}.upload_image_from_url", return_value="urn:li:image:789")
    @patch(f"{LINKEDIN_MODULE}.get_author_urn", return_value="urn:li:person:123")
    @patch(f"{LINKEDIN_MODULE}.get_access_token", return_value=FAKE_ACCESS_TOKEN)
    @patch(
        f"{LINKEDIN_MODULE}.linkedin_headers",
        return_value={"Authorization": "Bearer fake"},
    )
    def test_create_image_post(
        self,
        mock_headers: MagicMock,
        mock_token: MagicMock,
        mock_urn: MagicMock,
        mock_upload: MagicMock,
        mock_client: MagicMock,
    ) -> None:
        resp = _ok_response({}, headers={"x-restli-id": "urn:li:share:456"})
        mock_client.post.return_value = resp

        from app.agents.tools.integrations.linkedin_tool import (
            register_linkedin_custom_tools,
        )

        tools = _capture_tools(register_linkedin_custom_tools)
        fn = tools["CUSTOM_CREATE_POST"]

        result = fn(
            CreatePostInput(  # type: ignore[call-arg]
                commentary="Photo!", image_url="https://example.com/img.jpg"
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )
        assert result["media_type"] == "image"

    @patch(f"{LINKEDIN_MODULE}._http_client")
    @patch(f"{LINKEDIN_MODULE}.upload_document_from_url", return_value="urn:li:doc:789")
    @patch(f"{LINKEDIN_MODULE}.get_author_urn", return_value="urn:li:person:123")
    @patch(f"{LINKEDIN_MODULE}.get_access_token", return_value=FAKE_ACCESS_TOKEN)
    @patch(
        f"{LINKEDIN_MODULE}.linkedin_headers",
        return_value={"Authorization": "Bearer fake"},
    )
    def test_create_document_post(
        self,
        mock_headers: MagicMock,
        mock_token: MagicMock,
        mock_urn: MagicMock,
        mock_upload: MagicMock,
        mock_client: MagicMock,
    ) -> None:
        resp = _ok_response({}, headers={"x-restli-id": "urn:li:share:456"})
        mock_client.post.return_value = resp

        from app.agents.tools.integrations.linkedin_tool import (
            register_linkedin_custom_tools,
        )

        tools = _capture_tools(register_linkedin_custom_tools)
        fn = tools["CUSTOM_CREATE_POST"]

        result = fn(
            CreatePostInput(  # type: ignore[call-arg]
                commentary="Doc!",
                document_url="https://example.com/doc.pdf",
                document_title="My Doc",
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )
        assert result["media_type"] == "document"

    @patch(f"{LINKEDIN_MODULE}.get_author_urn", return_value="urn:li:person:123")
    @patch(f"{LINKEDIN_MODULE}.get_access_token", return_value=FAKE_ACCESS_TOKEN)
    @patch(
        f"{LINKEDIN_MODULE}.linkedin_headers",
        return_value={"Authorization": "Bearer fake"},
    )
    def test_create_document_no_title_raises(
        self, mock_headers: MagicMock, mock_token: MagicMock, mock_urn: MagicMock
    ) -> None:
        from app.agents.tools.integrations.linkedin_tool import (
            register_linkedin_custom_tools,
        )

        tools = _capture_tools(register_linkedin_custom_tools)
        fn = tools["CUSTOM_CREATE_POST"]

        with pytest.raises(ValueError, match="document_title is required"):
            fn(
                CreatePostInput(  # type: ignore[call-arg]
                    commentary="Doc!", document_url="https://example.com/doc.pdf"
                ),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )

    @patch(f"{LINKEDIN_MODULE}._http_client")
    @patch(f"{LINKEDIN_MODULE}.get_author_urn", return_value="urn:li:person:123")
    @patch(f"{LINKEDIN_MODULE}.get_access_token", return_value=FAKE_ACCESS_TOKEN)
    @patch(
        f"{LINKEDIN_MODULE}.linkedin_headers",
        return_value={"Authorization": "Bearer fake"},
    )
    def test_create_article_post(
        self,
        mock_headers: MagicMock,
        mock_token: MagicMock,
        mock_urn: MagicMock,
        mock_client: MagicMock,
    ) -> None:
        resp = _ok_response({}, headers={"x-restli-id": "urn:li:share:456"})
        mock_client.post.return_value = resp

        from app.agents.tools.integrations.linkedin_tool import (
            register_linkedin_custom_tools,
        )

        tools = _capture_tools(register_linkedin_custom_tools)
        fn = tools["CUSTOM_CREATE_POST"]

        result = fn(
            CreatePostInput(  # type: ignore[call-arg]
                commentary="Read this!", article_url="https://blog.example.com/post"
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )
        assert result["media_type"] == "article"


class TestLinkedInAddComment:
    @patch(f"{LINKEDIN_MODULE}._http_client")
    @patch(f"{LINKEDIN_MODULE}.get_author_urn", return_value="urn:li:person:123")
    @patch(f"{LINKEDIN_MODULE}.get_access_token", return_value=FAKE_ACCESS_TOKEN)
    @patch(
        f"{LINKEDIN_MODULE}.linkedin_headers",
        return_value={"Authorization": "Bearer fake"},
    )
    def test_add_comment(
        self,
        mock_headers: MagicMock,
        mock_token: MagicMock,
        mock_urn: MagicMock,
        mock_client: MagicMock,
    ) -> None:
        mock_client.post.return_value = _ok_response(
            {"id": "cmt-1"}, headers={"x-restli-id": "cmt-1"}
        )

        from app.agents.tools.integrations.linkedin_tool import (
            register_linkedin_custom_tools,
        )

        tools = _capture_tools(register_linkedin_custom_tools)
        fn = tools["CUSTOM_ADD_COMMENT"]

        result = fn(
            AddCommentInput(post_urn="urn:li:share:123", comment_text="Nice post!"),  # type: ignore[call-arg]
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )
        assert result["comment_id"] == "cmt-1"


class TestLinkedInGetPostComments:
    @patch(f"{LINKEDIN_MODULE}._http_client")
    @patch(f"{LINKEDIN_MODULE}.get_access_token", return_value=FAKE_ACCESS_TOKEN)
    @patch(
        f"{LINKEDIN_MODULE}.linkedin_headers",
        return_value={"Authorization": "Bearer fake"},
    )
    def test_get_comments(
        self, mock_headers: MagicMock, mock_token: MagicMock, mock_client: MagicMock
    ) -> None:
        mock_client.get.return_value = _ok_response(
            {
                "elements": [
                    {
                        "id": "c1",
                        "actor": "urn:li:person:456",
                        "message": {"text": "Great!"},
                        "created": {"time": 1234567890},
                        "parentComment": None,
                    },
                ],
                "paging": {"total": 1},
            }
        )

        from app.agents.tools.integrations.linkedin_tool import (
            register_linkedin_custom_tools,
        )

        tools = _capture_tools(register_linkedin_custom_tools)
        fn = tools["CUSTOM_GET_POST_COMMENTS"]

        result = fn(
            GetPostCommentsInput(post_urn="urn:li:share:123"),  # type: ignore[call-arg]
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )
        assert result["total_count"] == 1
        assert result["comments"][0]["text"] == "Great!"


class TestLinkedInReactToPost:
    @patch(f"{LINKEDIN_MODULE}._http_client")
    @patch(f"{LINKEDIN_MODULE}.get_author_urn", return_value="urn:li:person:123")
    @patch(f"{LINKEDIN_MODULE}.get_access_token", return_value=FAKE_ACCESS_TOKEN)
    @patch(
        f"{LINKEDIN_MODULE}.linkedin_headers",
        return_value={"Authorization": "Bearer fake"},
    )
    def test_react_to_post(
        self,
        mock_headers: MagicMock,
        mock_token: MagicMock,
        mock_urn: MagicMock,
        mock_client: MagicMock,
    ) -> None:
        mock_client.post.return_value = _ok_response({})

        from app.agents.tools.integrations.linkedin_tool import (
            register_linkedin_custom_tools,
        )

        tools = _capture_tools(register_linkedin_custom_tools)
        fn = tools["CUSTOM_REACT_TO_POST"]

        result = fn(
            ReactToPostInput(post_urn="urn:li:share:123", reaction_type="LIKE"),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )
        assert result["reaction_type"] == "LIKE"


class TestLinkedInDeleteReaction:
    @patch(f"{LINKEDIN_MODULE}._http_client")
    @patch(f"{LINKEDIN_MODULE}.get_author_urn", return_value="urn:li:person:123")
    @patch(f"{LINKEDIN_MODULE}.get_access_token", return_value=FAKE_ACCESS_TOKEN)
    @patch(
        f"{LINKEDIN_MODULE}.linkedin_headers",
        return_value={"Authorization": "Bearer fake"},
    )
    def test_delete_reaction(
        self,
        mock_headers: MagicMock,
        mock_token: MagicMock,
        mock_urn: MagicMock,
        mock_client: MagicMock,
    ) -> None:
        mock_client.delete.return_value = _ok_response({})

        from app.agents.tools.integrations.linkedin_tool import (
            register_linkedin_custom_tools,
        )

        tools = _capture_tools(register_linkedin_custom_tools)
        fn = tools["CUSTOM_DELETE_REACTION"]

        result = fn(
            DeleteReactionInput(post_urn="urn:li:share:123"),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )
        assert result["message"] == "Reaction removed successfully"


class TestLinkedInGetPostReactions:
    @patch(f"{LINKEDIN_MODULE}._http_client")
    @patch(f"{LINKEDIN_MODULE}.get_access_token", return_value=FAKE_ACCESS_TOKEN)
    @patch(
        f"{LINKEDIN_MODULE}.linkedin_headers",
        return_value={"Authorization": "Bearer fake"},
    )
    def test_get_reactions(
        self, mock_headers: MagicMock, mock_token: MagicMock, mock_client: MagicMock
    ) -> None:
        mock_client.get.return_value = _ok_response(
            {
                "elements": [
                    {
                        "actor": "urn:li:person:456",
                        "reactionType": "LIKE",
                        "created": {"time": 1234},
                    }
                ],
                "paging": {"total": 1},
            }
        )

        from app.agents.tools.integrations.linkedin_tool import (
            register_linkedin_custom_tools,
        )

        tools = _capture_tools(register_linkedin_custom_tools)
        fn = tools["CUSTOM_GET_POST_REACTIONS"]

        result = fn(
            GetPostReactionsInput(post_urn="urn:li:share:123"),  # type: ignore[call-arg]
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )
        assert result["total_count"] == 1


class TestLinkedInGatherContext:
    @patch(f"{LINKEDIN_MODULE}._http_client")
    @patch(f"{LINKEDIN_MODULE}.get_access_token", return_value=FAKE_ACCESS_TOKEN)
    @patch(
        f"{LINKEDIN_MODULE}.linkedin_headers",
        return_value={"Authorization": "Bearer fake"},
    )
    def test_gather_context(
        self, mock_headers: MagicMock, mock_token: MagicMock, mock_client: MagicMock
    ) -> None:
        userinfo_resp = _ok_response(
            {
                "sub": "abc123",
                "name": "Alice Doe",
                "given_name": "Alice",
                "family_name": "Doe",
                "email": "alice@example.com",
                "picture": "https://pic",
            }
        )
        posts_resp = _ok_response({"elements": []})
        posts_resp.status_code = 200
        mock_client.get.side_effect = [userinfo_resp, posts_resp]

        from app.agents.tools.integrations.linkedin_tool import (
            register_linkedin_custom_tools,
        )

        tools = _capture_tools(register_linkedin_custom_tools)
        fn = tools["CUSTOM_GATHER_CONTEXT"]

        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS)
        assert result["user"]["id"] == "abc123"
        assert result["user"]["name"] == "Alice Doe"


# =============================================================================
# NOTION TOOLS
# =============================================================================

NOTION_MODULE = "app.agents.tools.integrations.notion_tool"


class TestNotionMovePage:
    def test_move_page_to_page(self) -> None:
        from app.agents.tools.integrations.notion_tool import (
            register_notion_custom_tools,
        )

        exec_req = MagicMock()
        exec_resp = MagicMock()
        exec_resp.data = {"id": "page-1", "url": "https://notion.so/page-1"}
        exec_req.return_value = exec_resp

        tools = _capture_tools(register_notion_custom_tools)
        fn = tools["MOVE_PAGE"]

        result = fn(
            MovePageInput(
                page_id="page-1", parent_type="page_id", parent_id="parent-1"
            ),
            exec_req,
            AUTH_CREDS,
        )
        assert result["page_id"] == "page-1"
        exec_req.assert_called_once()

    def test_move_page_to_database(self) -> None:
        from app.agents.tools.integrations.notion_tool import (
            register_notion_custom_tools,
        )

        exec_req = MagicMock()
        exec_resp = MagicMock()
        exec_resp.data = {"id": "page-1", "url": "https://notion.so/page-1"}
        exec_req.return_value = exec_resp

        tools = _capture_tools(register_notion_custom_tools)
        fn = tools["MOVE_PAGE"]

        fn(
            MovePageInput(
                page_id="page-1", parent_type="database_id", parent_id="db-1"
            ),
            exec_req,
            AUTH_CREDS,
        )
        call_kwargs = exec_req.call_args
        assert "database_id" in str(call_kwargs)


class TestNotionFetchPageAsMarkdown:
    def test_fetch_page_success(self) -> None:
        from app.agents.tools.integrations.notion_tool import (
            register_notion_custom_tools,
        )

        composio = MagicMock()
        captured: Dict[str, Any] = {}

        def capturing_custom_tool(**kwargs):
            def wrapper(fn):
                captured[fn.__name__] = fn
                return fn

            return wrapper

        composio.tools.custom_tool = capturing_custom_tool
        composio.tools.execute.side_effect = [
            # title call
            {
                "successful": True,
                "data": {
                    "results": [{"type": "title", "title": {"plain_text": "My Page"}}]
                },
            },
            # blocks call
            {
                "successful": True,
                "data": {
                    "results": [
                        {
                            "type": "paragraph",
                            "paragraph": {"rich_text": [{"plain_text": "Hello"}]},
                        }
                    ]
                },
            },
        ]
        register_notion_custom_tools(composio)
        fn = captured["FETCH_PAGE_AS_MARKDOWN"]

        result = fn(
            FetchPageAsMarkdownInput(page_id="page-1"), EXECUTE_REQUEST, AUTH_CREDS
        )
        assert result["page_id"] == "page-1"
        assert result["title"] == "My Page"

    def test_fetch_page_blocks_failure(self) -> None:
        from app.agents.tools.integrations.notion_tool import (
            register_notion_custom_tools,
        )

        composio = MagicMock()
        captured: Dict[str, Any] = {}

        def capturing_custom_tool(**kwargs):
            def wrapper(fn):
                captured[fn.__name__] = fn
                return fn

            return wrapper

        composio.tools.custom_tool = capturing_custom_tool
        composio.tools.execute.side_effect = [
            {"successful": True, "data": {"results": []}},
            {"successful": False, "error": "Access denied"},
        ]
        register_notion_custom_tools(composio)
        fn = captured["FETCH_PAGE_AS_MARKDOWN"]

        with pytest.raises(ValueError, match="Failed to fetch blocks"):
            fn(FetchPageAsMarkdownInput(page_id="page-1"), EXECUTE_REQUEST, AUTH_CREDS)


class TestNotionInsertMarkdown:
    def test_insert_markdown_success(self) -> None:
        from app.agents.tools.integrations.notion_tool import (
            register_notion_custom_tools,
        )

        composio = MagicMock()
        captured: Dict[str, Any] = {}

        def capturing_custom_tool(**kwargs):
            def wrapper(fn):
                captured[fn.__name__] = fn
                return fn

            return wrapper

        composio.tools.custom_tool = capturing_custom_tool
        composio.tools.execute.return_value = {"successful": True, "data": {}}
        register_notion_custom_tools(composio)
        fn = captured["INSERT_MARKDOWN"]

        result = fn(
            InsertMarkdownInput(parent_block_id="block-1", markdown="# Hello\n\nWorld"),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )
        assert result["parent_block_id"] == "block-1"
        assert result["blocks_added"] > 0

    def test_insert_empty_markdown_raises(self) -> None:
        from app.agents.tools.integrations.notion_tool import (
            register_notion_custom_tools,
        )

        composio = MagicMock()
        captured: Dict[str, Any] = {}

        def capturing_custom_tool(**kwargs):
            def wrapper(fn):
                captured[fn.__name__] = fn
                return fn

            return wrapper

        composio.tools.custom_tool = capturing_custom_tool
        register_notion_custom_tools(composio)
        fn = captured["INSERT_MARKDOWN"]

        with pytest.raises(ValueError, match="No content to insert"):
            fn(
                InsertMarkdownInput(parent_block_id="block-1", markdown=""),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )


class TestNotionFetchData:
    @patch(f"{NOTION_MODULE}.httpx")
    def test_fetch_databases(self, mock_httpx: MagicMock) -> None:
        mock_httpx.post.return_value = _ok_response(
            {
                "results": [
                    {
                        "id": "db-1",
                        "object": "database",
                        "title": [{"plain_text": "Tasks"}],
                    },
                ],
                "has_more": False,
            }
        )

        from app.agents.tools.integrations.notion_tool import (
            register_notion_custom_tools,
        )

        tools = _capture_tools(register_notion_custom_tools)
        fn = tools["FETCH_DATA"]

        result = fn(FetchDataInput(fetch_type="databases"), EXECUTE_REQUEST, AUTH_CREDS)
        assert result["count"] == 1
        assert result["values"][0]["title"] == "Tasks"

    @patch(f"{NOTION_MODULE}.httpx")
    def test_fetch_pages(self, mock_httpx: MagicMock) -> None:
        mock_httpx.post.return_value = _ok_response(
            {
                "results": [
                    {
                        "id": "pg-1",
                        "object": "page",
                        "properties": {
                            "Name": {
                                "type": "title",
                                "title": [{"plain_text": "Notes"}],
                            }
                        },
                    },
                ],
                "has_more": False,
            }
        )

        from app.agents.tools.integrations.notion_tool import (
            register_notion_custom_tools,
        )

        tools = _capture_tools(register_notion_custom_tools)
        fn = tools["FETCH_DATA"]

        result = fn(FetchDataInput(fetch_type="pages"), EXECUTE_REQUEST, AUTH_CREDS)
        assert result["count"] == 1
        assert result["values"][0]["title"] == "Notes"

    @patch(f"{NOTION_MODULE}.httpx")
    def test_fetch_data_api_error(self, mock_httpx: MagicMock) -> None:
        error_resp = _error_response(500, "Internal Server Error")
        mock_httpx.post.side_effect = httpx.HTTPStatusError(
            "Server error",
            request=httpx.Request("POST", "https://test"),
            response=error_resp,
        )
        mock_httpx.HTTPStatusError = httpx.HTTPStatusError

        from app.agents.tools.integrations.notion_tool import (
            register_notion_custom_tools,
        )

        tools = _capture_tools(register_notion_custom_tools)
        fn = tools["FETCH_DATA"]

        with pytest.raises(RuntimeError, match="Failed to fetch"):
            fn(FetchDataInput(fetch_type="databases"), EXECUTE_REQUEST, AUTH_CREDS)


class TestNotionCreateTestPage:
    @patch(f"{NOTION_MODULE}.httpx")
    def test_create_test_page(self, mock_httpx: MagicMock) -> None:
        mock_httpx.post.return_value = _ok_response(
            {"id": "new-page-1", "url": "https://notion.so/new"}
        )

        from app.agents.tools.integrations.notion_tool import (
            register_notion_custom_tools,
        )

        tools = _capture_tools(register_notion_custom_tools)
        fn = tools["CUSTOM_CREATE_TEST_PAGE"]

        result = fn(
            CreateTestPageInput(title="Test Page", parent_page_id="parent-1"),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )
        assert result["page_id"] == "new-page-1"


class TestNotionGatherContext:
    @patch(
        f"{NOTION_MODULE}.execute_tool",
        return_value={"results": [{"id": "p1", "title": "Notes"}]},
    )
    def test_gather_context(self, mock_exec: MagicMock) -> None:
        from app.agents.tools.integrations.notion_tool import (
            register_notion_custom_tools,
        )

        tools = _capture_tools(register_notion_custom_tools)
        fn = tools["CUSTOM_GATHER_CONTEXT"]

        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS)
        assert "relevant_pages" in result

    def test_gather_context_no_user_id(self) -> None:
        from app.agents.tools.integrations.notion_tool import (
            register_notion_custom_tools,
        )

        tools = _capture_tools(register_notion_custom_tools)
        fn = tools["CUSTOM_GATHER_CONTEXT"]

        with pytest.raises(ValueError, match="Missing user_id"):
            fn(GatherContextInput(), EXECUTE_REQUEST, {"access_token": "tok"})


# =============================================================================
# CALENDAR TOOLS
# =============================================================================

CALENDAR_MODULE = "app.agents.tools.integrations.calendar_tool"


class TestCalendarListCalendars:
    @patch(f"{CALENDAR_MODULE}.get_stream_writer", return_value=MagicMock())
    @patch(f"{CALENDAR_MODULE}.calendar_service")
    @patch(f"{CALENDAR_MODULE}._get_access_token", return_value=FAKE_ACCESS_TOKEN)
    def test_list_calendars(
        self, mock_token: MagicMock, mock_cal_svc: MagicMock, mock_writer: MagicMock
    ) -> None:
        mock_cal_svc.list_calendars.return_value = [
            {
                "id": "primary",
                "summary": "My Calendar",
                "description": "",
                "backgroundColor": "#4285f4",
            },
        ]

        from app.agents.tools.integrations.calendar_tool import (
            register_calendar_custom_tools,
        )

        tools = _capture_tools(register_calendar_custom_tools)
        fn = tools["CUSTOM_LIST_CALENDARS"]

        result = fn(ListCalendarsInput(), EXECUTE_REQUEST, AUTH_CREDS)
        assert len(result["calendars"]) == 1


class TestCalendarFetchEvents:
    @patch(f"{CALENDAR_MODULE}.get_stream_writer", return_value=MagicMock())
    @patch(f"{CALENDAR_MODULE}.calendar_service")
    @patch(f"{CALENDAR_MODULE}._get_user_id", return_value=FAKE_USER_ID)
    @patch(f"{CALENDAR_MODULE}._get_access_token", return_value=FAKE_ACCESS_TOKEN)
    def test_fetch_events(
        self,
        mock_token: MagicMock,
        mock_uid: MagicMock,
        mock_cal_svc: MagicMock,
        mock_writer: MagicMock,
    ) -> None:
        mock_cal_svc.get_calendar_events.return_value = {
            "events": [
                {
                    "summary": "Meeting",
                    "start": {"dateTime": "2024-01-01T10:00:00Z"},
                    "end": {"dateTime": "2024-01-01T11:00:00Z"},
                }
            ],
            "has_more": False,
        }
        mock_cal_svc.get_calendar_metadata_map.return_value = ({}, {})
        mock_cal_svc.format_event_for_frontend.side_effect = lambda e, c, n: e

        from app.agents.tools.integrations.calendar_tool import (
            register_calendar_custom_tools,
        )

        tools = _capture_tools(register_calendar_custom_tools)
        fn = tools["CUSTOM_FETCH_EVENTS"]

        result = fn(FetchEventsInput(), EXECUTE_REQUEST, AUTH_CREDS)
        assert len(result["calendar_fetch_data"]) == 1

    @patch(f"{CALENDAR_MODULE}.get_stream_writer", return_value=MagicMock())
    @patch(f"{CALENDAR_MODULE}.calendar_service")
    @patch(f"{CALENDAR_MODULE}._get_user_id", return_value=FAKE_USER_ID)
    @patch(f"{CALENDAR_MODULE}._get_access_token", return_value=FAKE_ACCESS_TOKEN)
    def test_fetch_events_metadata_failure(
        self,
        mock_token: MagicMock,
        mock_uid: MagicMock,
        mock_cal_svc: MagicMock,
        mock_writer: MagicMock,
    ) -> None:
        """When metadata map fails, events should still be returned raw."""
        mock_cal_svc.get_calendar_events.return_value = {
            "events": [{"summary": "Meeting"}],
            "has_more": False,
        }
        mock_cal_svc.get_calendar_metadata_map.side_effect = Exception("API Error")

        from app.agents.tools.integrations.calendar_tool import (
            register_calendar_custom_tools,
        )

        tools = _capture_tools(register_calendar_custom_tools)
        fn = tools["CUSTOM_FETCH_EVENTS"]

        result = fn(FetchEventsInput(), EXECUTE_REQUEST, AUTH_CREDS)
        assert len(result["calendar_fetch_data"]) == 1


class TestCalendarFindEvent:
    @patch(f"{CALENDAR_MODULE}.get_stream_writer", return_value=MagicMock())
    @patch(f"{CALENDAR_MODULE}.calendar_service")
    @patch(f"{CALENDAR_MODULE}._get_user_id", return_value=FAKE_USER_ID)
    @patch(f"{CALENDAR_MODULE}._get_access_token", return_value=FAKE_ACCESS_TOKEN)
    def test_find_event(
        self,
        mock_token: MagicMock,
        mock_uid: MagicMock,
        mock_cal_svc: MagicMock,
        mock_writer: MagicMock,
    ) -> None:
        mock_cal_svc.search_calendar_events_native.return_value = {
            "matching_events": [
                {"summary": "Standup", "start": {"dateTime": "2024-01-01T09:00:00Z"}}
            ],
        }
        mock_cal_svc.get_calendar_metadata_map.return_value = ({}, {})
        mock_cal_svc.format_event_for_frontend.side_effect = lambda e, c, n: e

        from app.agents.tools.integrations.calendar_tool import (
            register_calendar_custom_tools,
        )

        tools = _capture_tools(register_calendar_custom_tools)
        fn = tools["CUSTOM_FIND_EVENT"]

        result = fn(FindEventInput(query="standup"), EXECUTE_REQUEST, AUTH_CREDS)
        assert len(result["events"]) == 1


class TestCalendarGetEvent:
    @patch(f"{CALENDAR_MODULE}._http_client")
    @patch(f"{CALENDAR_MODULE}._get_access_token", return_value=FAKE_ACCESS_TOKEN)
    def test_get_event_success(
        self, mock_token: MagicMock, mock_client: MagicMock
    ) -> None:
        mock_client.get.return_value = _ok_response(
            {"id": "ev-1", "summary": "Meeting"}
        )

        from app.agents.tools.integrations.calendar_tool import (
            register_calendar_custom_tools,
        )

        tools = _capture_tools(register_calendar_custom_tools)
        fn = tools["CUSTOM_GET_EVENT"]

        result = fn(
            GetEventInput(
                events=[EventReference(event_id="ev-1", calendar_id="primary")]
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )
        assert len(result["events"]) == 1

    @patch(f"{CALENDAR_MODULE}._http_client")
    @patch(f"{CALENDAR_MODULE}._get_access_token", return_value=FAKE_ACCESS_TOKEN)
    def test_get_event_all_fail(
        self, mock_token: MagicMock, mock_client: MagicMock
    ) -> None:
        error_resp = _error_response(404, "Not Found")
        mock_client.get.side_effect = httpx.HTTPStatusError(
            "Not Found",
            request=httpx.Request("GET", "https://test"),
            response=error_resp,
        )

        from app.agents.tools.integrations.calendar_tool import (
            register_calendar_custom_tools,
        )

        tools = _capture_tools(register_calendar_custom_tools)
        fn = tools["CUSTOM_GET_EVENT"]

        with pytest.raises(RuntimeError, match="Failed to get events"):
            fn(
                GetEventInput(
                    events=[EventReference(event_id="bad", calendar_id="primary")]
                ),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )


class TestCalendarDeleteEvent:
    @patch(f"{CALENDAR_MODULE}._http_client")
    @patch(f"{CALENDAR_MODULE}._get_access_token", return_value=FAKE_ACCESS_TOKEN)
    def test_delete_event_success(
        self, mock_token: MagicMock, mock_client: MagicMock
    ) -> None:
        mock_client.delete.return_value = _ok_response({})

        from app.agents.tools.integrations.calendar_tool import (
            register_calendar_custom_tools,
        )

        tools = _capture_tools(register_calendar_custom_tools)
        fn = tools["CUSTOM_DELETE_EVENT"]

        result = fn(
            DeleteEventInput(
                events=[EventReference(event_id="ev-1", calendar_id="primary")]
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )
        assert len(result["deleted"]) == 1

    @patch(f"{CALENDAR_MODULE}._http_client")
    @patch(f"{CALENDAR_MODULE}._get_access_token", return_value=FAKE_ACCESS_TOKEN)
    def test_delete_event_all_fail(
        self, mock_token: MagicMock, mock_client: MagicMock
    ) -> None:
        error_resp = _error_response(404, "Not Found")
        mock_client.delete.side_effect = httpx.HTTPStatusError(
            "Not Found",
            request=httpx.Request("DELETE", "https://test"),
            response=error_resp,
        )

        from app.agents.tools.integrations.calendar_tool import (
            register_calendar_custom_tools,
        )

        tools = _capture_tools(register_calendar_custom_tools)
        fn = tools["CUSTOM_DELETE_EVENT"]

        with pytest.raises(RuntimeError, match="Failed to delete"):
            fn(
                DeleteEventInput(
                    events=[EventReference(event_id="ev-1", calendar_id="primary")]
                ),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )


class TestCalendarPatchEvent:
    @patch(f"{CALENDAR_MODULE}._http_client")
    @patch(f"{CALENDAR_MODULE}._get_access_token", return_value=FAKE_ACCESS_TOKEN)
    def test_patch_event(self, mock_token: MagicMock, mock_client: MagicMock) -> None:
        mock_client.patch.return_value = _ok_response(
            {"id": "ev-1", "summary": "Updated"}
        )

        from app.agents.tools.integrations.calendar_tool import (
            register_calendar_custom_tools,
        )

        tools = _capture_tools(register_calendar_custom_tools)
        fn = tools["CUSTOM_PATCH_EVENT"]

        result = fn(
            PatchEventInput(event_id="ev-1", calendar_id="primary", summary="Updated"),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )
        assert result["event"]["summary"] == "Updated"

    @patch(f"{CALENDAR_MODULE}._http_client")
    @patch(f"{CALENDAR_MODULE}._get_access_token", return_value=FAKE_ACCESS_TOKEN)
    def test_patch_event_with_attendees(
        self, mock_token: MagicMock, mock_client: MagicMock
    ) -> None:
        mock_client.patch.return_value = _ok_response({"id": "ev-1"})

        from app.agents.tools.integrations.calendar_tool import (
            register_calendar_custom_tools,
        )

        tools = _capture_tools(register_calendar_custom_tools)
        fn = tools["CUSTOM_PATCH_EVENT"]

        fn(
            PatchEventInput(event_id="ev-1", attendees=["alice@test.com"]),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )
        call_kwargs = mock_client.patch.call_args
        body = call_kwargs.kwargs["json"]
        assert body["attendees"] == [{"email": "alice@test.com"}]


class TestCalendarAddRecurrence:
    @patch(f"{CALENDAR_MODULE}._http_client")
    @patch(f"{CALENDAR_MODULE}._get_access_token", return_value=FAKE_ACCESS_TOKEN)
    def test_add_recurrence(
        self, mock_token: MagicMock, mock_client: MagicMock
    ) -> None:
        mock_client.get.return_value = _ok_response(
            {"id": "ev-1", "summary": "Standup"}
        )
        mock_client.put.return_value = _ok_response(
            {"id": "ev-1", "recurrence": ["RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR"]}
        )

        from app.agents.tools.integrations.calendar_tool import (
            register_calendar_custom_tools,
        )

        tools = _capture_tools(register_calendar_custom_tools)
        fn = tools["CUSTOM_ADD_RECURRENCE"]

        result = fn(
            AddRecurrenceInput(
                event_id="ev-1",
                calendar_id="primary",
                frequency="WEEKLY",
                by_day=["MO", "WE", "FR"],
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )
        assert "FREQ=WEEKLY" in result["recurrence_rule"]
        assert "BYDAY=MO,WE,FR" in result["recurrence_rule"]

    @patch(f"{CALENDAR_MODULE}._http_client")
    @patch(f"{CALENDAR_MODULE}._get_access_token", return_value=FAKE_ACCESS_TOKEN)
    def test_add_recurrence_with_count(
        self, mock_token: MagicMock, mock_client: MagicMock
    ) -> None:
        mock_client.get.return_value = _ok_response({"id": "ev-1"})
        mock_client.put.return_value = _ok_response({"id": "ev-1"})

        from app.agents.tools.integrations.calendar_tool import (
            register_calendar_custom_tools,
        )

        tools = _capture_tools(register_calendar_custom_tools)
        fn = tools["CUSTOM_ADD_RECURRENCE"]

        result = fn(
            AddRecurrenceInput(event_id="ev-1", frequency="DAILY", count=10),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )
        assert "COUNT=10" in result["recurrence_rule"]


class TestCalendarCreateEvent:
    @patch(f"{CALENDAR_MODULE}.get_stream_writer", return_value=MagicMock())
    @patch(f"{CALENDAR_MODULE}._http_client")
    @patch(f"{CALENDAR_MODULE}.calendar_service")
    @patch(f"{CALENDAR_MODULE}._get_access_token", return_value=FAKE_ACCESS_TOKEN)
    def test_create_event_immediately(
        self,
        mock_token: MagicMock,
        mock_cal_svc: MagicMock,
        mock_client: MagicMock,
        mock_writer: MagicMock,
    ) -> None:
        mock_cal_svc.get_calendar_metadata_map.return_value = (
            {"primary": "#4285f4"},
            {"primary": "My Cal"},
        )
        mock_client.post.return_value = _ok_response(
            {"id": "ev-1", "htmlLink": "https://calendar/ev-1"}
        )

        from app.agents.tools.integrations.calendar_tool import (
            register_calendar_custom_tools,
        )

        tools = _capture_tools(register_calendar_custom_tools)
        fn = tools["CUSTOM_CREATE_EVENT"]

        now = datetime.now(timezone.utc)
        start = (now + timedelta(hours=1)).isoformat()

        result = fn(
            CreateEventInput(
                events=[
                    SingleEventInput(
                        summary="Meeting", start_datetime=start, duration_hours=1
                    )
                ],
                confirm_immediately=True,
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )
        assert result["created"] is True
        assert len(result["created_events"]) == 1

    @patch(f"{CALENDAR_MODULE}.get_stream_writer", return_value=MagicMock())
    @patch(f"{CALENDAR_MODULE}.calendar_service")
    @patch(f"{CALENDAR_MODULE}._get_access_token", return_value=FAKE_ACCESS_TOKEN)
    def test_create_event_draft(
        self, mock_token: MagicMock, mock_cal_svc: MagicMock, mock_writer: MagicMock
    ) -> None:
        mock_cal_svc.get_calendar_metadata_map.return_value = ({}, {})

        from app.agents.tools.integrations.calendar_tool import (
            register_calendar_custom_tools,
        )

        tools = _capture_tools(register_calendar_custom_tools)
        fn = tools["CUSTOM_CREATE_EVENT"]

        now = datetime.now(timezone.utc)
        start = (now + timedelta(hours=1)).isoformat()

        result = fn(
            CreateEventInput(
                events=[SingleEventInput(summary="Meeting", start_datetime=start)],
                confirm_immediately=False,
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )
        assert result["created"] is False
        assert len(result["calendar_options"]) == 1

    @patch(f"{CALENDAR_MODULE}.get_stream_writer", return_value=MagicMock())
    @patch(f"{CALENDAR_MODULE}.calendar_service")
    @patch(f"{CALENDAR_MODULE}._get_access_token", return_value=FAKE_ACCESS_TOKEN)
    def test_create_event_invalid_datetime(
        self, mock_token: MagicMock, mock_cal_svc: MagicMock, mock_writer: MagicMock
    ) -> None:
        mock_cal_svc.get_calendar_metadata_map.return_value = ({}, {})

        from app.agents.tools.integrations.calendar_tool import (
            register_calendar_custom_tools,
        )

        tools = _capture_tools(register_calendar_custom_tools)
        fn = tools["CUSTOM_CREATE_EVENT"]

        with pytest.raises(ValueError, match="All events failed validation"):
            fn(
                CreateEventInput(
                    events=[
                        SingleEventInput(summary="Bad", start_datetime="not-a-date")
                    ],
                    confirm_immediately=True,
                ),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )


class TestCalendarGatherContext:
    @patch(
        f"{CALENDAR_MODULE}.execute_tool",
        return_value={"date": "2024-01-01", "events": []},
    )
    @patch(f"{CALENDAR_MODULE}._get_user_id", return_value=FAKE_USER_ID)
    def test_gather_context(self, mock_uid: MagicMock, mock_exec: MagicMock) -> None:
        from app.agents.tools.integrations.calendar_tool import (
            register_calendar_custom_tools,
        )

        tools = _capture_tools(register_calendar_custom_tools)
        fn = tools["CUSTOM_GATHER_CONTEXT"]

        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS)
        assert "date" in result

    @patch(f"{CALENDAR_MODULE}._get_user_id", return_value="")
    def test_gather_context_no_user_id(self, mock_uid: MagicMock) -> None:
        from app.agents.tools.integrations.calendar_tool import (
            register_calendar_custom_tools,
        )

        tools = _capture_tools(register_calendar_custom_tools)
        fn = tools["CUSTOM_GATHER_CONTEXT"]

        with pytest.raises(ValueError, match="Missing user_id"):
            fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS)


# =============================================================================
# CALENDAR HELPER FUNCTIONS (module-level, not inside register_*)
# =============================================================================


class TestCalendarGetDaySummary:
    @patch(f"{CALENDAR_MODULE}.get_stream_writer", return_value=MagicMock())
    @patch(f"{CALENDAR_MODULE}.calendar_service")
    @patch(f"{CALENDAR_MODULE}.user_service")
    @patch(f"{CALENDAR_MODULE}._get_user_id", return_value=FAKE_USER_ID)
    @patch(f"{CALENDAR_MODULE}._get_access_token", return_value=FAKE_ACCESS_TOKEN)
    def test_get_day_summary_with_events(
        self,
        mock_token: MagicMock,
        mock_uid: MagicMock,
        mock_user_svc: MagicMock,
        mock_cal_svc: MagicMock,
        mock_writer: MagicMock,
    ) -> None:
        """Test day summary with timed events, busy hours, and next event."""
        # user_service.get_user_by_id is async; we need asyncio.run to not find a loop
        mock_user_svc.get_user_by_id = MagicMock(return_value={"timezone": "UTC"})

        now_utc = datetime.now(timezone.utc)
        future_time = (now_utc + timedelta(hours=2)).isoformat()
        past_time = (now_utc - timedelta(hours=1)).isoformat()
        past_end = (now_utc - timedelta(minutes=30)).isoformat()

        mock_cal_svc.get_calendar_events.return_value = {
            "events": [
                {
                    "summary": "Past",
                    "start": {"dateTime": past_time},
                    "end": {"dateTime": past_end},
                },
                {
                    "summary": "Future",
                    "start": {"dateTime": future_time},
                    "end": {"dateTime": (now_utc + timedelta(hours=3)).isoformat()},
                },
            ],
        }
        mock_cal_svc.get_calendar_metadata_map.return_value = ({}, {})
        mock_cal_svc.format_event_for_frontend.side_effect = lambda e, c, n: e

        from app.agents.tools.integrations.calendar_tool import (
            register_calendar_custom_tools,
        )

        tools = _capture_tools(register_calendar_custom_tools)
        fn = tools["CUSTOM_GET_DAY_SUMMARY"]

        today_str = datetime.now().strftime("%Y-%m-%d")
        result = fn(GetDaySummaryInput(date=today_str), EXECUTE_REQUEST, AUTH_CREDS)
        assert result["date"] == today_str
        assert result["busy_hours"] > 0
        assert len(result["events"]) == 2

    @patch(f"{CALENDAR_MODULE}.get_stream_writer", return_value=MagicMock())
    @patch(f"{CALENDAR_MODULE}.calendar_service")
    @patch(f"{CALENDAR_MODULE}.user_service")
    @patch(f"{CALENDAR_MODULE}._get_user_id", return_value=FAKE_USER_ID)
    @patch(f"{CALENDAR_MODULE}._get_access_token", return_value=FAKE_ACCESS_TOKEN)
    def test_get_day_summary_no_user_timezone(
        self,
        mock_token: MagicMock,
        mock_uid: MagicMock,
        mock_user_svc: MagicMock,
        mock_cal_svc: MagicMock,
        mock_writer: MagicMock,
    ) -> None:
        """Falls back to UTC when user has no timezone."""
        mock_user_svc.get_user_by_id = MagicMock(return_value=None)
        mock_cal_svc.get_calendar_events.return_value = {"events": []}
        mock_cal_svc.get_calendar_metadata_map.return_value = ({}, {})

        from app.agents.tools.integrations.calendar_tool import (
            register_calendar_custom_tools,
        )

        tools = _capture_tools(register_calendar_custom_tools)
        fn = tools["CUSTOM_GET_DAY_SUMMARY"]

        result = fn(GetDaySummaryInput(), EXECUTE_REQUEST, AUTH_CREDS)
        assert result["timezone"] == "UTC"

    @patch(f"{CALENDAR_MODULE}.get_stream_writer", return_value=MagicMock())
    @patch(f"{CALENDAR_MODULE}.calendar_service")
    @patch(f"{CALENDAR_MODULE}.user_service")
    @patch(f"{CALENDAR_MODULE}._get_user_id", return_value=FAKE_USER_ID)
    @patch(f"{CALENDAR_MODULE}._get_access_token", return_value=FAKE_ACCESS_TOKEN)
    def test_get_day_summary_invalid_date_format(
        self,
        mock_token: MagicMock,
        mock_uid: MagicMock,
        mock_user_svc: MagicMock,
        mock_cal_svc: MagicMock,
        mock_writer: MagicMock,
    ) -> None:
        mock_user_svc.get_user_by_id = MagicMock(return_value=None)

        from app.agents.tools.integrations.calendar_tool import (
            register_calendar_custom_tools,
        )

        tools = _capture_tools(register_calendar_custom_tools)
        fn = tools["CUSTOM_GET_DAY_SUMMARY"]

        with pytest.raises(ValueError, match="Invalid date format"):
            fn(GetDaySummaryInput(date="not-a-date"), EXECUTE_REQUEST, AUTH_CREDS)

    @patch(f"{CALENDAR_MODULE}.get_stream_writer", return_value=MagicMock())
    @patch(f"{CALENDAR_MODULE}.calendar_service")
    @patch(f"{CALENDAR_MODULE}.user_service")
    @patch(f"{CALENDAR_MODULE}._get_user_id", return_value=FAKE_USER_ID)
    @patch(f"{CALENDAR_MODULE}._get_access_token", return_value=FAKE_ACCESS_TOKEN)
    def test_get_day_summary_metadata_failure(
        self,
        mock_token: MagicMock,
        mock_uid: MagicMock,
        mock_user_svc: MagicMock,
        mock_cal_svc: MagicMock,
        mock_writer: MagicMock,
    ) -> None:
        """When metadata fails, events returned raw."""
        mock_user_svc.get_user_by_id = MagicMock(return_value=None)
        mock_cal_svc.get_calendar_events.return_value = {
            "events": [{"summary": "Test"}]
        }
        mock_cal_svc.get_calendar_metadata_map.side_effect = Exception("fail")

        from app.agents.tools.integrations.calendar_tool import (
            register_calendar_custom_tools,
        )

        tools = _capture_tools(register_calendar_custom_tools)
        fn = tools["CUSTOM_GET_DAY_SUMMARY"]

        result = fn(GetDaySummaryInput(), EXECUTE_REQUEST, AUTH_CREDS)
        assert len(result["events"]) == 1

    @patch(f"{CALENDAR_MODULE}.get_stream_writer", return_value=MagicMock())
    @patch(f"{CALENDAR_MODULE}.calendar_service")
    @patch(f"{CALENDAR_MODULE}.user_service")
    @patch(f"{CALENDAR_MODULE}._get_user_id", return_value=FAKE_USER_ID)
    @patch(f"{CALENDAR_MODULE}._get_access_token", return_value=FAKE_ACCESS_TOKEN)
    def test_get_day_summary_user_service_exception(
        self,
        mock_token: MagicMock,
        mock_uid: MagicMock,
        mock_user_svc: MagicMock,
        mock_cal_svc: MagicMock,
        mock_writer: MagicMock,
    ) -> None:
        """When user_service raises, timezone falls back to UTC."""
        mock_user_svc.get_user_by_id = MagicMock(side_effect=Exception("DB down"))
        mock_cal_svc.get_calendar_events.return_value = {"events": []}
        mock_cal_svc.get_calendar_metadata_map.return_value = ({}, {})

        from app.agents.tools.integrations.calendar_tool import (
            register_calendar_custom_tools,
        )

        tools = _capture_tools(register_calendar_custom_tools)
        fn = tools["CUSTOM_GET_DAY_SUMMARY"]

        result = fn(GetDaySummaryInput(), EXECUTE_REQUEST, AUTH_CREDS)
        assert result["timezone"] == "UTC"


class TestCalendarCreateEventAdvanced:
    @patch(f"{CALENDAR_MODULE}.get_stream_writer", return_value=MagicMock())
    @patch(f"{CALENDAR_MODULE}._http_client")
    @patch(f"{CALENDAR_MODULE}.calendar_service")
    @patch(f"{CALENDAR_MODULE}._get_access_token", return_value=FAKE_ACCESS_TOKEN)
    def test_create_all_day_event(
        self,
        mock_token: MagicMock,
        mock_cal_svc: MagicMock,
        mock_client: MagicMock,
        mock_writer: MagicMock,
    ) -> None:
        mock_cal_svc.get_calendar_metadata_map.return_value = ({}, {})
        mock_client.post.return_value = _ok_response(
            {"id": "ev-1", "htmlLink": "https://cal"}
        )

        from app.agents.tools.integrations.calendar_tool import (
            register_calendar_custom_tools,
        )

        tools = _capture_tools(register_calendar_custom_tools)
        fn = tools["CUSTOM_CREATE_EVENT"]

        result = fn(
            CreateEventInput(
                events=[
                    SingleEventInput(
                        summary="Holiday",
                        start_datetime="2024-12-25T00:00:00",
                        is_all_day=True,
                        duration_hours=23,
                        duration_minutes=59,
                    )
                ],
                confirm_immediately=True,
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )
        assert result["created"] is True
        # Check the body had 'date' fields, not 'dateTime'
        call_kwargs = mock_client.post.call_args
        body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert "date" in body["start"]

    @patch(
        f"{CALENDAR_MODULE}._get_user_timezone",
        return_value=timezone(timedelta(hours=5, minutes=30)),
    )
    @patch(f"{CALENDAR_MODULE}.get_stream_writer", return_value=MagicMock())
    @patch(f"{CALENDAR_MODULE}._http_client")
    @patch(f"{CALENDAR_MODULE}.calendar_service")
    @patch(f"{CALENDAR_MODULE}._get_access_token", return_value=FAKE_ACCESS_TOKEN)
    def test_create_event_naive_datetime_with_user_tz(
        self,
        mock_token: MagicMock,
        mock_cal_svc: MagicMock,
        mock_client: MagicMock,
        mock_writer: MagicMock,
        mock_tz: MagicMock,
    ) -> None:
        """Naive datetime should have user timezone applied."""
        mock_cal_svc.get_calendar_metadata_map.return_value = ({}, {})
        mock_client.post.return_value = _ok_response(
            {"id": "ev-1", "htmlLink": "https://cal"}
        )

        from app.agents.tools.integrations.calendar_tool import (
            register_calendar_custom_tools,
        )

        tools = _capture_tools(register_calendar_custom_tools)
        fn = tools["CUSTOM_CREATE_EVENT"]

        result = fn(
            CreateEventInput(
                events=[
                    SingleEventInput(
                        summary="Meeting",
                        start_datetime="2024-06-15T14:00:00",
                        duration_hours=1,
                    )
                ],
                confirm_immediately=True,
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )
        assert result["created"] is True

    @patch(f"{CALENDAR_MODULE}.get_stream_writer", return_value=MagicMock())
    @patch(f"{CALENDAR_MODULE}._http_client")
    @patch(f"{CALENDAR_MODULE}.calendar_service")
    @patch(f"{CALENDAR_MODULE}._get_access_token", return_value=FAKE_ACCESS_TOKEN)
    def test_create_event_with_description_location_attendees_meet(
        self,
        mock_token: MagicMock,
        mock_cal_svc: MagicMock,
        mock_client: MagicMock,
        mock_writer: MagicMock,
    ) -> None:
        mock_cal_svc.get_calendar_metadata_map.return_value = ({}, {})
        mock_client.post.return_value = _ok_response(
            {"id": "ev-1", "htmlLink": "https://cal"}
        )

        from app.agents.tools.integrations.calendar_tool import (
            register_calendar_custom_tools,
        )

        tools = _capture_tools(register_calendar_custom_tools)
        fn = tools["CUSTOM_CREATE_EVENT"]

        now = datetime.now(timezone.utc)
        start = (now + timedelta(hours=1)).isoformat()

        result = fn(
            CreateEventInput(
                events=[
                    SingleEventInput(
                        summary="Team Sync",
                        start_datetime=start,
                        duration_hours=1,
                        description="Weekly sync",
                        location="Room 42",
                        attendees=["alice@test.com", "bob@test.com"],
                        create_meeting_room=True,
                    )
                ],
                confirm_immediately=True,
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )
        assert result["created"] is True
        call_kwargs = mock_client.post.call_args
        body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert body["description"] == "Weekly sync"
        assert body["location"] == "Room 42"
        assert len(body["attendees"]) == 2
        assert "conferenceData" in body
        # Check conferenceDataVersion param
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params")
        assert params.get("conferenceDataVersion") == "1"

    @patch(f"{CALENDAR_MODULE}.get_stream_writer", return_value=MagicMock())
    @patch(f"{CALENDAR_MODULE}.calendar_service")
    @patch(f"{CALENDAR_MODULE}._get_access_token", return_value=FAKE_ACCESS_TOKEN)
    def test_create_event_draft_with_location_and_attendees(
        self, mock_token: MagicMock, mock_cal_svc: MagicMock, mock_writer: MagicMock
    ) -> None:
        mock_cal_svc.get_calendar_metadata_map.return_value = (
            {"primary": "#4285f4"},
            {"primary": "Main"},
        )

        from app.agents.tools.integrations.calendar_tool import (
            register_calendar_custom_tools,
        )

        tools = _capture_tools(register_calendar_custom_tools)
        fn = tools["CUSTOM_CREATE_EVENT"]

        now = datetime.now(timezone.utc)
        start = (now + timedelta(hours=1)).isoformat()

        result = fn(
            CreateEventInput(
                events=[
                    SingleEventInput(
                        summary="Draft",
                        start_datetime=start,
                        location="Office",
                        attendees=["alice@test.com"],
                        create_meeting_room=True,
                    )
                ],
                confirm_immediately=False,
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )
        assert result["created"] is False
        opt = result["calendar_options"][0]
        assert opt["location"] == "Office"
        assert opt["attendees"] == ["alice@test.com"]
        assert opt["create_meeting_room"] is True

    @patch(f"{CALENDAR_MODULE}.get_stream_writer", return_value=MagicMock())
    @patch(f"{CALENDAR_MODULE}.calendar_service")
    @patch(f"{CALENDAR_MODULE}._get_access_token", return_value=FAKE_ACCESS_TOKEN)
    def test_create_event_metadata_map_failure(
        self, mock_token: MagicMock, mock_cal_svc: MagicMock, mock_writer: MagicMock
    ) -> None:
        """When metadata map fails, should still produce options with defaults."""
        mock_cal_svc.get_calendar_metadata_map.side_effect = Exception("fail")

        from app.agents.tools.integrations.calendar_tool import (
            register_calendar_custom_tools,
        )

        tools = _capture_tools(register_calendar_custom_tools)
        fn = tools["CUSTOM_CREATE_EVENT"]

        now = datetime.now(timezone.utc)
        start = (now + timedelta(hours=1)).isoformat()

        result = fn(
            CreateEventInput(
                events=[SingleEventInput(summary="Meeting", start_datetime=start)],
                confirm_immediately=False,
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )
        assert result["created"] is False
        assert len(result["calendar_options"]) == 1


class TestCalendarHelpers:
    def test_extract_datetime_string(self) -> None:
        from app.agents.tools.integrations.calendar_tool import _extract_datetime

        assert _extract_datetime("2024-01-01T10:00:00Z") == "2024-01-01T10:00:00Z"
        assert _extract_datetime("") == ""
        assert _extract_datetime(None) == ""

    def test_extract_datetime_dict(self) -> None:
        from app.agents.tools.integrations.calendar_tool import _extract_datetime

        assert (
            _extract_datetime({"dateTime": "2024-01-01T10:00:00Z"})
            == "2024-01-01T10:00:00Z"
        )
        assert _extract_datetime({"date": "2024-01-01"}) == "2024-01-01"
        assert _extract_datetime({}) == ""

    def test_format_event_for_stream(self) -> None:
        from app.agents.tools.integrations.calendar_tool import _format_event_for_stream

        event = {
            "summary": "Standup",
            "start": {"dateTime": "2024-01-01T09:00:00Z"},
            "end": {"dateTime": "2024-01-01T09:30:00Z"},
            "calendarTitle": "Work",
            "backgroundColor": "#00FF00",
        }
        result = _format_event_for_stream(event)
        assert result["summary"] == "Standup"
        assert result["calendar_name"] == "Work"

    def test_format_calendar_for_stream(self) -> None:
        from app.agents.tools.integrations.calendar_tool import (
            _format_calendar_for_stream,
        )

        cal = {
            "summary": "Work",
            "id": "cal-1",
            "description": "Work calendar",
            "backgroundColor": "#00FF00",
        }
        result = _format_calendar_for_stream(cal)
        assert result["name"] == "Work"
        assert result["id"] == "cal-1"

    def test_get_access_token_missing(self) -> None:
        from app.agents.tools.integrations.calendar_tool import _get_access_token

        with pytest.raises(ValueError, match="Missing access_token"):
            _get_access_token({})

    def test_get_access_token_present(self) -> None:
        from app.agents.tools.integrations.calendar_tool import _get_access_token

        assert _get_access_token({"access_token": "tok"}) == "tok"

    def test_auth_headers(self) -> None:
        from app.agents.tools.integrations.calendar_tool import _auth_headers

        headers = _auth_headers("tok123")
        assert headers["Authorization"] == "Bearer tok123"

    def test_get_user_id(self) -> None:
        from app.agents.tools.integrations.calendar_tool import _get_user_id

        assert _get_user_id({"user_id": "u1"}) == "u1"
        assert _get_user_id({}) == ""

    def test_format_calendar_option_for_stream(self) -> None:
        from app.agents.tools.integrations.calendar_tool import (
            _format_calendar_option_for_stream,
        )

        opt = {
            "summary": "Meeting",
            "description": "Team sync",
            "is_all_day": False,
            "calendar_id": "primary",
            "calendar_name": "Work",
            "color": "#4285f4",
            "start": {"dateTime": "2024-01-01T10:00:00Z"},
            "end": {"dateTime": "2024-01-01T11:00:00Z"},
            "location": "Room 1",
            "attendees": ["a@b.com"],
            "create_meeting_room": True,
        }
        result = _format_calendar_option_for_stream(opt)
        assert result["summary"] == "Meeting"
        assert result["location"] == "Room 1"
        assert result["attendees"] == ["a@b.com"]
        assert result["create_meeting_room"] is True


# =============================================================================
# GOOGLE DOCS TOOLS
# =============================================================================

GOOGLE_DOCS_MODULE = "app.agents.tools.integrations.google_docs_tool"


def _register_google_docs_tools():
    """Register google docs tools and capture inner functions."""
    captured = {}

    def capturing_custom_tool(**kwargs):
        def wrapper(fn):
            captured[fn.__name__] = fn
            return fn

        return wrapper

    composio = MagicMock()
    composio.tools.custom_tool = capturing_custom_tool
    composio.tools.execute = MagicMock()

    from app.agents.tools.integrations.google_docs_tool import (
        register_google_docs_custom_tools,
    )

    names = register_google_docs_custom_tools(composio)
    return captured, composio, names


class TestGoogleDocsGetAccessToken:
    """Tests for _get_access_token helper."""

    def test_returns_token(self) -> None:
        from app.agents.tools.integrations.google_docs_tool import _get_access_token

        assert _get_access_token({"access_token": "tok-123"}) == "tok-123"

    def test_missing_token_raises(self) -> None:
        from app.agents.tools.integrations.google_docs_tool import _get_access_token

        with pytest.raises(ValueError, match="Missing access_token"):
            _get_access_token({})


class TestGoogleDocsAuthHeaders:
    """Tests for _auth_headers helper."""

    def test_bearer_header(self) -> None:
        from app.agents.tools.integrations.google_docs_tool import _auth_headers

        headers = _auth_headers("my-token")
        assert headers == {"Authorization": "Bearer my-token"}


class TestGoogleDocsShareDoc:
    """Tests for CUSTOM_SHARE_DOC."""

    @patch(f"{GOOGLE_DOCS_MODULE}._http_client")
    def test_share_single_recipient(self, mock_client: MagicMock) -> None:
        from app.models.google_docs_models import ShareDocInput, ShareRecipient

        captured, composio, _ = _register_google_docs_tools()
        fn = captured["CUSTOM_SHARE_DOC"]

        mock_resp = _ok_response({"id": "perm-1"})
        mock_client.post.return_value = mock_resp

        request = ShareDocInput(
            document_id="doc-1",
            recipients=[
                ShareRecipient(
                    email="user@test.com", role="writer", send_notification=True
                )
            ],
        )
        result = fn(request, EXECUTE_REQUEST, AUTH_CREDS)

        assert result["document_id"] == "doc-1"
        assert len(result["shared"]) == 1
        assert result["shared"][0]["email"] == "user@test.com"
        assert result["shared"][0]["permission_id"] == "perm-1"
        assert "url" in result

    @patch(f"{GOOGLE_DOCS_MODULE}._http_client")
    def test_share_multiple_recipients_partial_failure(
        self, mock_client: MagicMock
    ) -> None:
        from app.models.google_docs_models import ShareDocInput, ShareRecipient

        captured, _, _ = _register_google_docs_tools()
        fn = captured["CUSTOM_SHARE_DOC"]

        ok_resp = _ok_response({"id": "perm-1"})
        err_resp = _error_response(403, "Forbidden")

        mock_client.post.side_effect = [
            ok_resp,
            httpx.HTTPStatusError(
                "err", request=httpx.Request("POST", "https://test"), response=err_resp
            ),
        ]

        request = ShareDocInput(
            document_id="doc-1",
            recipients=[
                ShareRecipient(email="ok@test.com", role="writer"),  # type: ignore[call-arg]
                ShareRecipient(email="fail@test.com", role="reader"),  # type: ignore[call-arg]
            ],
        )
        result = fn(request, EXECUTE_REQUEST, AUTH_CREDS)

        assert len(result["shared"]) == 1
        assert result["shared"][0]["email"] == "ok@test.com"

    @patch(f"{GOOGLE_DOCS_MODULE}._http_client")
    def test_share_all_fail_raises(self, mock_client: MagicMock) -> None:
        from app.models.google_docs_models import ShareDocInput, ShareRecipient

        captured, _, _ = _register_google_docs_tools()
        fn = captured["CUSTOM_SHARE_DOC"]

        err_resp = _error_response(403, "Forbidden")
        mock_client.post.side_effect = httpx.HTTPStatusError(
            "err", request=httpx.Request("POST", "https://test"), response=err_resp
        )

        request = ShareDocInput(
            document_id="doc-1",
            recipients=[ShareRecipient(email="fail@test.com", role="reader")],  # type: ignore[call-arg]
        )
        with pytest.raises(RuntimeError, match="Failed to share document"):
            fn(request, EXECUTE_REQUEST, AUTH_CREDS)


class TestGoogleDocsCreateTOC:
    """Tests for CUSTOM_CREATE_TOC."""

    @patch(
        f"{GOOGLE_DOCS_MODULE}.generate_toc_text", return_value="# TOC\n- Heading 1\n"
    )
    @patch(
        f"{GOOGLE_DOCS_MODULE}.extract_headings_from_document",
        return_value=[{"text": "Heading 1", "level": 1}],
    )
    def test_create_toc_success(
        self, mock_extract: MagicMock, mock_gen: MagicMock
    ) -> None:
        from app.models.google_docs_models import CreateTOCInput

        captured, composio, _ = _register_google_docs_tools()
        fn = captured["CUSTOM_CREATE_TOC"]

        # Mock composio.tools.execute for GET_DOCUMENT and INSERT_TEXT
        composio.tools.execute.side_effect = [
            {"successful": True, "data": {"body": {"content": []}}},
            {"successful": True, "data": {"writeControl": {}}},
        ]

        request = CreateTOCInput(document_id="doc-1", insertion_index=1)
        result = fn(request, EXECUTE_REQUEST, AUTH_CREDS)

        assert result["document_id"] == "doc-1"
        assert result["headings_found"] == 1
        assert "url" in result

    def test_create_toc_get_doc_fails(self) -> None:
        from app.models.google_docs_models import CreateTOCInput

        captured, composio, _ = _register_google_docs_tools()
        fn = captured["CUSTOM_CREATE_TOC"]

        composio.tools.execute.return_value = {
            "successful": False,
            "error": "Not found",
        }

        request = CreateTOCInput(document_id="doc-1")
        with pytest.raises(ValueError, match="Failed to get document"):
            fn(request, EXECUTE_REQUEST, AUTH_CREDS)

    def test_create_toc_no_body(self) -> None:
        from app.models.google_docs_models import CreateTOCInput

        captured, composio, _ = _register_google_docs_tools()
        fn = captured["CUSTOM_CREATE_TOC"]

        composio.tools.execute.return_value = {
            "successful": True,
            "data": {"title": "My Doc"},
        }

        request = CreateTOCInput(document_id="doc-1")
        with pytest.raises(ValueError, match="no body content"):
            fn(request, EXECUTE_REQUEST, AUTH_CREDS)

    def test_create_toc_stringified_data(self) -> None:
        """When data is a JSON string, it should be parsed."""
        import json
        from app.models.google_docs_models import CreateTOCInput

        captured, composio, _ = _register_google_docs_tools()
        fn = captured["CUSTOM_CREATE_TOC"]

        doc_data = json.dumps({"body": {"content": []}})
        composio.tools.execute.side_effect = [
            {"successful": True, "data": doc_data},
            {"successful": True, "data": {}},
        ]

        with patch(
            f"{GOOGLE_DOCS_MODULE}.extract_headings_from_document", return_value=[]
        ):
            with patch(
                f"{GOOGLE_DOCS_MODULE}.generate_toc_text", return_value="# TOC\n"
            ):
                request = CreateTOCInput(document_id="doc-1")
                result = fn(request, EXECUTE_REQUEST, AUTH_CREDS)

        assert result["headings_found"] == 0

    @patch(f"{GOOGLE_DOCS_MODULE}.generate_toc_text", return_value="# TOC\n")
    @patch(f"{GOOGLE_DOCS_MODULE}.extract_headings_from_document", return_value=[])
    def test_create_toc_insert_fails(
        self, mock_extract: MagicMock, mock_gen: MagicMock
    ) -> None:
        from app.models.google_docs_models import CreateTOCInput

        captured, composio, _ = _register_google_docs_tools()
        fn = captured["CUSTOM_CREATE_TOC"]

        composio.tools.execute.side_effect = [
            {"successful": True, "data": {"body": {"content": []}}},
            {"successful": False, "error": "Insert failed"},
        ]

        request = CreateTOCInput(document_id="doc-1")
        with pytest.raises(ValueError, match="Failed to insert text"):
            fn(request, EXECUTE_REQUEST, AUTH_CREDS)


class TestGoogleDocsDeleteDoc:
    """Tests for CUSTOM_DELETE_DOC."""

    @patch(f"{GOOGLE_DOCS_MODULE}._http_client")
    def test_delete_success(self, mock_client: MagicMock) -> None:
        from app.models.google_docs_models import DeleteDocInput

        captured, _, _ = _register_google_docs_tools()
        fn = captured["CUSTOM_DELETE_DOC"]

        mock_resp = _ok_response({}, status_code=204)
        mock_client.delete.return_value = mock_resp

        request = DeleteDocInput(document_id="doc-1")
        result = fn(request, EXECUTE_REQUEST, AUTH_CREDS)

        assert result["successful"] is True
        assert result["document_id"] == "doc-1"

    @patch(f"{GOOGLE_DOCS_MODULE}._http_client")
    def test_delete_error_raises(self, mock_client: MagicMock) -> None:
        from app.models.google_docs_models import DeleteDocInput

        captured, _, _ = _register_google_docs_tools()
        fn = captured["CUSTOM_DELETE_DOC"]

        err_resp = _error_response(404, "Not Found")
        mock_client.delete.side_effect = httpx.HTTPStatusError(
            "err", request=httpx.Request("DELETE", "https://test"), response=err_resp
        )

        request = DeleteDocInput(document_id="doc-1")
        with pytest.raises(RuntimeError, match="Failed to delete document"):
            fn(request, EXECUTE_REQUEST, AUTH_CREDS)


class TestGoogleDocsGatherContext:
    """Tests for CUSTOM_GATHER_CONTEXT."""

    @patch(f"{GOOGLE_DOCS_MODULE}._http_client")
    def test_gather_context_success(self, mock_client: MagicMock) -> None:
        captured, _, _ = _register_google_docs_tools()
        fn = captured["CUSTOM_GATHER_CONTEXT"]

        mock_resp = _ok_response(
            {
                "files": [
                    {
                        "id": "f1",
                        "name": "Doc 1",
                        "modifiedTime": "2024-01-01",
                        "webViewLink": "https://link",
                    },
                ]
            }
        )
        mock_client.get.return_value = mock_resp

        request = GatherContextInput()
        result = fn(request, EXECUTE_REQUEST, AUTH_CREDS)

        assert result["doc_count"] == 1
        assert result["recent_docs"][0]["id"] == "f1"
        assert result["recent_docs"][0]["name"] == "Doc 1"

    @patch(f"{GOOGLE_DOCS_MODULE}._http_client")
    def test_gather_context_empty(self, mock_client: MagicMock) -> None:
        captured, _, _ = _register_google_docs_tools()
        fn = captured["CUSTOM_GATHER_CONTEXT"]

        mock_resp = _ok_response({"files": []})
        mock_client.get.return_value = mock_resp

        request = GatherContextInput()
        result = fn(request, EXECUTE_REQUEST, AUTH_CREDS)

        assert result["doc_count"] == 0
        assert result["recent_docs"] == []

    @patch(f"{GOOGLE_DOCS_MODULE}._http_client")
    def test_gather_context_api_error_returns_empty(
        self, mock_client: MagicMock
    ) -> None:
        captured, _, _ = _register_google_docs_tools()
        fn = captured["CUSTOM_GATHER_CONTEXT"]

        mock_client.get.side_effect = Exception("API failure")

        request = GatherContextInput()
        result = fn(request, EXECUTE_REQUEST, AUTH_CREDS)

        assert result["doc_count"] == 0
        assert result["recent_docs"] == []


class TestRegisterGoogleDocsCustomTools:
    """Tests for register_google_docs_custom_tools return value."""

    def test_returns_expected_tool_names(self) -> None:
        _, _, names = _register_google_docs_tools()
        assert "GOOGLEDOCS_CUSTOM_SHARE_DOC" in names
        assert "GOOGLEDOCS_CUSTOM_CREATE_TOC" in names
        assert "GOOGLEDOCS_CUSTOM_DELETE_DOC" in names
        assert "GOOGLEDOCS_CUSTOM_GATHER_CONTEXT" in names
        assert len(names) == 4
