"""Unit tests for smaller Composio integration tools: github, airtable, slack, todoist, asana, clickup, google_tasks, trello, urgency.

Each register_*_custom_tools() decorates inner functions with @composio.tools.custom_tool();
tests mock the Composio instance with a capturing decorator, call register_*_custom_tools() to
capture the inner functions, then invoke them directly with mock auth_credentials and request objects.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.models.common_models import GatherContextInput

# ── Constants ─────────────────────────────────────────────────────────────────

FAKE_USER_ID = "user-123"
AUTH_CREDS_USER_ONLY: dict[str, Any] = {
    "user_id": FAKE_USER_ID,
}
EXECUTE_REQUEST = MagicMock()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_capturing_composio() -> tuple[MagicMock, dict[str, Callable[..., Any]]]:
    """Create a Composio mock whose custom_tool decorator captures inner functions."""
    composio = MagicMock()
    captured: dict[str, Callable[..., Any]] = {}

    def _custom_tool(**kwargs: Any) -> Callable[..., Any]:
        def wrapper(fn: Callable[..., Any]) -> Callable[..., Any]:
            captured[fn.__name__] = fn
            return fn

        return wrapper

    composio.tools.custom_tool = _custom_tool
    return composio, captured


class _UTCOnlyDateTime(datetime):
    """datetime stand-in whose local-time now(None) reads the previous day, so an overdue check that computes "today" off a non-UTC clock fails these boundary assertions deterministically."""

    @classmethod
    def now(cls, tz: datetime | None = None) -> datetime:  # type: ignore[override]  # mirrors datetime.now's optional-tz signature deliberately
        if tz is None:
            return cls(2026, 6, 14, 20, 0)  # naive local read: previous day
        return cls(2026, 6, 15, 2, 0, tzinfo=UTC)


# =============================================================================
# GITHUB TOOLS
# =============================================================================

GITHUB_MODULE = "app.agents.tools.integrations.github_tool"


class TestGitHubGatherContext:
    """Tests for GitHub CUSTOM_GATHER_CONTEXT."""

    def _register(self) -> dict[str, Callable[..., Any]]:
        composio, captured = _make_capturing_composio()
        from app.agents.tools.integrations.github_tool import (
            register_github_custom_tools,
        )

        names = register_github_custom_tools(composio)
        assert "GITHUB_CUSTOM_GATHER_CONTEXT" in names
        return captured

    @patch(f"{GITHUB_MODULE}.execute_tool")
    def test_basic_success(self, mock_exec: MagicMock) -> None:
        """Returns issues, PRs, review requests, notifications."""
        mock_exec.side_effect = [
            # First call: list issues
            {
                "issues": [
                    {"id": 1, "title": "Bug"},
                    {"id": 2, "title": "PR item", "pull_request": {"url": "..."}},
                ]
            },
            # Second call: search review requests
            {"items": [{"id": 3, "title": "Review me"}]},
            # Third call: notifications
            {"notifications": [{"id": "n1", "reason": "mention"}]},
        ]

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY)

        assert len(result["assigned_issues"]) == 1
        assert result["assigned_issues"][0]["title"] == "Bug"
        assert len(result["assigned_prs"]) == 1
        assert result["assigned_prs"][0]["title"] == "PR item"
        assert len(result["review_requests"]) == 1
        assert len(result["notifications"]) == 1

    @patch(f"{GITHUB_MODULE}.execute_tool")
    def test_missing_user_id(self, mock_exec: MagicMock) -> None:
        """Raises ValueError when user_id is missing."""
        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        with pytest.raises(ValueError, match="Missing user_id"):
            fn(GatherContextInput(), EXECUTE_REQUEST, {})

    @patch(f"{GITHUB_MODULE}.execute_tool")
    def test_review_requests_exception(self, mock_exec: MagicMock) -> None:
        """Gracefully handles exception when fetching review requests."""
        mock_exec.side_effect = [
            {"items": []},  # issues
            Exception("API error"),  # review requests fail
            {"notifications": []},  # notifications
        ]

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY)

        assert result["review_requests"] == []
        assert result["notifications"] == []

    @patch(f"{GITHUB_MODULE}.execute_tool")
    def test_notifications_exception(self, mock_exec: MagicMock) -> None:
        """Gracefully handles exception when fetching notifications."""
        mock_exec.side_effect = [
            {"items": []},  # issues
            {"items": []},  # review requests
            Exception("timeout"),  # notifications fail
        ]

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY)

        assert result["notifications"] == []

    @patch(f"{GITHUB_MODULE}.execute_tool")
    def test_notifications_non_list(self, mock_exec: MagicMock) -> None:
        """Notifications that are not a list are returned as empty."""
        mock_exec.side_effect = [
            {"items": []},
            {"items": []},
            {"notifications": "not-a-list"},
        ]

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY)

        assert result["notifications"] == []

    @patch(f"{GITHUB_MODULE}.execute_tool")
    def test_bare_list_notifications_are_kept(self, mock_exec: MagicMock) -> None:
        """A bare-list notifications payload is not reported as "no notifications"."""
        mock_exec.side_effect = [
            {"items": []},
            {"items": []},
            [{"id": "n1", "reason": "mention", "unread": True}],
        ]

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY)

        assert result["notifications"] == [{"id": "n1", "reason": "mention", "unread": True}]

    @patch(f"{GITHUB_MODULE}.execute_tool")
    def test_items_forward_verbatim_and_calls_are_exact(self, mock_exec: MagicMock) -> None:
        """GitHub fields ride through untouched and pull_request decides the bucket."""
        issue = {"id": 1, "title": "Bug", "number": 7, "labels": [{"name": "p1"}], "assignee": None}
        pr = {"id": 2, "title": "PR", "pull_request": {"url": "u", "merged_at": None}}
        mock_exec.side_effect = [{"issues": [issue, pr]}, {"items": [pr]}, {"notifications": []}]

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY)

        assert result == {
            "assigned_issues": [issue],
            "assigned_prs": [pr],
            "review_requests": [pr],
            "notifications": [],
        }
        assert [c.args for c in mock_exec.call_args_list] == [
            (
                "GITHUB_LIST_ISSUES_ASSIGNED_TO_THE_AUTHENTICATED_USER",
                {"per_page": 20, "state": "open"},
                FAKE_USER_ID,
            ),
            (
                "GITHUB_SEARCH_GITHUB_ISSUES_AND_PULL_REQUESTS",
                {"q": "is:pr is:open review-requested:@me", "per_page": 10},
                FAKE_USER_ID,
            ),
            ("GITHUB_LIST_NOTIFICATIONS", {"per_page": 10, "all": False}, FAKE_USER_ID),
        ]

    @patch(f"{GITHUB_MODULE}.execute_tool")
    def test_issues_key_wins_over_items(self, mock_exec: MagicMock) -> None:
        mock_exec.side_effect = [
            {"issues": [], "items": [{"id": 1, "title": "ignored"}]},
            {"items": []},
            {"notifications": []},
        ]

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY)

        assert result["assigned_issues"] == []


# =============================================================================
# AIRTABLE TOOLS
# =============================================================================

AIRTABLE_MODULE = "app.agents.tools.integrations.airtable_tool"


class TestAirtableGatherContext:
    """Tests for Airtable CUSTOM_GATHER_CONTEXT."""

    def _register(self) -> dict[str, Callable[..., Any]]:
        composio, captured = _make_capturing_composio()
        from app.agents.tools.integrations.airtable_tool import (
            register_airtable_custom_tools,
        )

        names = register_airtable_custom_tools(composio)
        assert "AIRTABLE_CUSTOM_GATHER_CONTEXT" in names
        return captured

    @patch(f"{AIRTABLE_MODULE}.execute_tool")
    def test_basic_success(self, mock_exec: MagicMock) -> None:
        """Returns bases with their tables."""
        mock_exec.side_effect = [
            {"bases": [{"id": "app1", "name": "My Base"}]},
            {"tables": [{"id": "tbl1", "name": "Tasks"}]},
        ]

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY)

        assert result["base_count"] == 1
        assert len(result["bases"]) == 1
        assert result["bases"][0]["name"] == "My Base"
        assert result["bases"][0]["tables"][0]["name"] == "Tasks"

    @patch(f"{AIRTABLE_MODULE}.execute_tool")
    def test_missing_user_id(self, mock_exec: MagicMock) -> None:
        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        with pytest.raises(ValueError, match="Missing user_id"):
            fn(GatherContextInput(), EXECUTE_REQUEST, {})

    @patch(f"{AIRTABLE_MODULE}.execute_tool")
    def test_bases_fetch_fails(self, mock_exec: MagicMock) -> None:
        """When bases fetch fails, returns empty."""
        mock_exec.side_effect = Exception("API down")

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY)

        assert result["bases"] == []
        assert result["base_count"] == 0

    @patch(f"{AIRTABLE_MODULE}.execute_tool")
    def test_schema_fetch_fails(self, mock_exec: MagicMock) -> None:
        """When table schema fetch fails, base still added with empty tables."""
        mock_exec.side_effect = [
            {"bases": [{"id": "app1", "name": "Base"}]},
            Exception("schema error"),
        ]

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY)

        assert len(result["bases"]) == 1
        assert result["bases"][0]["tables"] == []

    @patch(f"{AIRTABLE_MODULE}.execute_tool")
    def test_limits_to_three_bases(self, mock_exec: MagicMock) -> None:
        """Only fetches schemas for first 3 bases."""
        bases = [{"id": f"app{i}", "name": f"Base {i}"} for i in range(5)]
        mock_exec.side_effect = [
            {"bases": bases},
            {"tables": []},
            {"tables": []},
            {"tables": []},
        ]

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY)

        assert len(result["bases"]) == 3
        assert result["base_count"] == 5

    @patch(f"{AIRTABLE_MODULE}.execute_tool")
    def test_exact_output_and_calls(self, mock_exec: MagicMock) -> None:
        mock_exec.side_effect = [
            {"bases": [{"id": "app1", "name": "CRM", "permissionLevel": "create"}]},
            {"tables": [{"id": "tbl1", "name": "Leads", "primaryFieldId": "fld1"}]},
        ]

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY)

        assert result == {
            "bases": [{"id": "app1", "name": "CRM", "tables": [{"id": "tbl1", "name": "Leads"}]}],
            "base_count": 1,
        }
        assert [c.args for c in mock_exec.call_args_list] == [
            ("AIRTABLE_LIST_BASES", {}, FAKE_USER_ID),
            ("AIRTABLE_GET_BASE_SCHEMA", {"base_id": "app1"}, FAKE_USER_ID),
        ]


# =============================================================================
# SLACK TOOLS
# =============================================================================

SLACK_MODULE = "app.agents.tools.integrations.slack_tool"


class TestSlackGatherContext:
    """Tests for Slack CUSTOM_GATHER_CONTEXT."""

    def _register(self) -> dict[str, Callable[..., Any]]:
        composio, captured = _make_capturing_composio()
        from app.agents.tools.integrations.slack_tool import register_slack_custom_tools

        names = register_slack_custom_tools(composio)
        assert "SLACK_CUSTOM_GATHER_CONTEXT" in names
        return captured

    @patch(f"{SLACK_MODULE}.execute_tool")
    def test_basic_success(self, mock_exec: MagicMock) -> None:
        """Returns messages, mentions, and unread count."""
        mock_exec.side_effect = [
            {
                "messages": {
                    "matches": [
                        {"ts": "1", "text": "hello"},
                        {"ts": "2", "text": "world"},
                    ]
                }
            },
            {
                "messages": {
                    "matches": [
                        {"ts": "1", "text": "hello @me"},
                    ]
                }
            },
        ]

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY)

        assert len(result["mentions"]) == 1
        # Messages exclude mentions by ts
        assert len(result["messages"]) == 1
        assert result["messages"][0]["ts"] == "2"
        assert result["unread_count"] == 2

    @patch(f"{SLACK_MODULE}.execute_tool")
    def test_missing_user_id(self, mock_exec: MagicMock) -> None:
        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        with pytest.raises(ValueError, match="Missing user_id"):
            fn(GatherContextInput(), EXECUTE_REQUEST, {})

    @patch(f"{SLACK_MODULE}.execute_tool")
    def test_mentions_exception(self, mock_exec: MagicMock) -> None:
        """Mentions fetch failure returns empty mentions list."""
        mock_exec.side_effect = [
            {"messages": {"matches": [{"ts": "1", "text": "hi"}]}},
            Exception("mentions error"),
        ]

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY)

        assert result["mentions"] == []
        assert len(result["messages"]) == 1

    @patch(f"{SLACK_MODULE}.datetime", _UTCOnlyDateTime)
    @patch(f"{SLACK_MODULE}.execute_tool")
    def test_exact_output_and_queries(self, mock_exec: MagicMock) -> None:
        """Matches ride through verbatim; the two searches carry the UTC day."""
        hello = {"ts": "1.0", "text": "hello", "user": "U1", "channel": {"id": "C1"}}
        world = {"ts": "2.0", "text": "world", "permalink": "p"}
        mock_exec.side_effect = [
            {"messages": {"matches": [hello, world], "total": 2}},
            {"messages": {"matches": [hello]}},
        ]

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY)

        assert result == {"messages": [world], "mentions": [hello], "unread_count": 2}
        assert [c.args for c in mock_exec.call_args_list] == [
            ("SLACK_SEARCH_MESSAGES", {"query": "on:2026-06-15", "count": 20}, FAKE_USER_ID),
            ("SLACK_SEARCH_MESSAGES", {"query": "on:2026-06-15 @me", "count": 10}, FAKE_USER_ID),
        ]


# =============================================================================
# TODOIST TOOLS
# =============================================================================

TODOIST_MODULE = "app.agents.tools.integrations.todoist_tool"


class TestTodoistGatherContext:
    """Tests for Todoist CUSTOM_GATHER_CONTEXT."""

    def _register(self) -> dict[str, Callable[..., Any]]:
        composio, captured = _make_capturing_composio()
        from app.agents.tools.integrations.todoist_tool import (
            register_todoist_custom_tools,
        )

        names = register_todoist_custom_tools(composio)
        assert "TODOIST_CUSTOM_GATHER_CONTEXT" in names
        return captured

    @patch(f"{TODOIST_MODULE}.execute_tool")
    def test_basic_success(self, mock_exec: MagicMock) -> None:
        """Returns tasks and identifies overdue ones."""
        mock_exec.return_value = {
            "items": [
                {"id": "1", "content": "Future task", "due": {"date": "9999-12-31"}},
                {"id": "2", "content": "Overdue task", "due": {"date": "2000-01-01"}},
                {"id": "3", "content": "No due date"},
            ]
        }

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY)

        assert len(result["tasks"]) == 3
        assert len(result["overdue_tasks"]) == 1
        assert result["overdue_tasks"][0]["content"] == "Overdue task"

    @patch(f"{TODOIST_MODULE}.execute_tool")
    def test_missing_user_id(self, mock_exec: MagicMock) -> None:
        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        with pytest.raises(ValueError, match="Missing user_id"):
            fn(GatherContextInput(), EXECUTE_REQUEST, {})

    @patch(f"{TODOIST_MODULE}.execute_tool")
    def test_data_not_dict(self, mock_exec: MagicMock) -> None:
        """When execute_tool returns a list directly."""
        mock_exec.return_value = [{"id": "1", "content": "Task", "due": {"date": "2000-01-01"}}]

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY)

        assert len(result["tasks"]) == 1
        assert len(result["overdue_tasks"]) == 1

    @patch(f"{TODOIST_MODULE}.execute_tool")
    def test_data_not_list_or_dict(self, mock_exec: MagicMock) -> None:
        """When data is dict but items/tasks keys not present and value is not list."""
        mock_exec.return_value = {"something_else": "value"}

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY)

        # Falls through to data itself which is a dict, isinstance check fails -> tasks = []
        assert result["tasks"] == []

    @patch(f"{TODOIST_MODULE}.datetime", _UTCOnlyDateTime)
    @patch(f"{TODOIST_MODULE}.execute_tool")
    def test_overdue_boundary_is_the_utc_today(self, mock_exec: MagicMock) -> None:
        """A task due today is not yet overdue; yesterday is. Pinned to a fake UTC clock so a local-time read or a mangled date format fails here."""
        mock_exec.return_value = {
            "items": [
                {"id": "1", "content": "Due today", "due": {"date": "2026-06-15"}},
                {"id": "2", "content": "Due tomorrow", "due": {"date": "2026-06-16"}},
                {"id": "3", "content": "Due yesterday", "due": {"date": "2026-06-14"}},
                {"id": "4", "content": "No due at all"},
                {
                    "id": "5",
                    "content": "Due object carrying no date",
                    "due": {"is_recurring": True},
                },
            ]
        }

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY)

        assert [t["content"] for t in result["overdue_tasks"]] == ["Due yesterday"]

    @patch(f"{TODOIST_MODULE}.execute_tool")
    def test_tasks_forward_verbatim(self, mock_exec: MagicMock) -> None:
        """No invented keys: a missing due stays missing, a null due stays null."""
        overdue = {"id": "2", "content": "B", "due": {"date": "2000-01-01", "is_recurring": False}}
        tasks = [{"id": "1", "content": "A", "priority": 4}, overdue, {"id": "3", "due": None}]
        mock_exec.return_value = {"items": tasks}

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY)

        assert result == {"tasks": tasks, "overdue_tasks": [overdue]}
        assert mock_exec.call_args.args == ("TODOIST_GET_ALL_TASKS", {}, FAKE_USER_ID)

    @patch(f"{TODOIST_MODULE}.execute_tool")
    def test_items_key_wins_even_when_not_a_list(self, mock_exec: MagicMock) -> None:
        mock_exec.return_value = {"items": "nope", "tasks": [{"id": "1", "content": "T"}]}

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY)

        assert result["tasks"] == []


# =============================================================================
# ASANA TOOLS
# =============================================================================

ASANA_MODULE = "app.agents.tools.integrations.asana_tool"


class TestAsanaGatherContext:
    """Tests for Asana CUSTOM_GATHER_CONTEXT."""

    def _register(self) -> dict[str, Callable[..., Any]]:
        composio, captured = _make_capturing_composio()
        from app.agents.tools.integrations.asana_tool import register_asana_custom_tools

        names = register_asana_custom_tools(composio)
        assert "ASANA_CUSTOM_GATHER_CONTEXT" in names
        return captured

    @patch(f"{ASANA_MODULE}.execute_tool")
    def test_basic_success(self, mock_exec: MagicMock) -> None:
        """Returns tasks and overdue items."""
        mock_exec.return_value = {
            "data": [
                {"gid": "1", "name": "Future task", "due_on": "9999-12-31"},
                {"gid": "2", "name": "Overdue task", "due_on": "2000-01-01"},
                {"gid": "3", "name": "No due date"},
            ]
        }

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY)

        assert len(result["tasks"]) == 3
        assert len(result["overdue_tasks"]) == 1
        assert result["overdue_tasks"][0]["name"] == "Overdue task"

    @patch(f"{ASANA_MODULE}.execute_tool")
    def test_missing_user_id(self, mock_exec: MagicMock) -> None:
        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        with pytest.raises(ValueError, match="Missing user_id"):
            fn(GatherContextInput(), EXECUTE_REQUEST, {})

    @patch(f"{ASANA_MODULE}.datetime", _UTCOnlyDateTime)
    @patch(f"{ASANA_MODULE}.execute_tool")
    def test_overdue_boundary_is_the_utc_today(self, mock_exec: MagicMock) -> None:
        """A task due today is not yet overdue; yesterday is. Pinned to a fake UTC clock so a local-time read or a mangled date format fails here."""
        mock_exec.return_value = {
            "data": [
                {"gid": "1", "name": "Due today", "due_on": "2026-06-15"},
                {"gid": "2", "name": "Due tomorrow", "due_on": "2026-06-16"},
                {"gid": "3", "name": "Due yesterday", "due_on": "2026-06-14"},
            ]
        }

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY)

        assert [t["name"] for t in result["overdue_tasks"]] == ["Due yesterday"]

    @patch(f"{ASANA_MODULE}.execute_tool")
    def test_no_overdue(self, mock_exec: MagicMock) -> None:
        """Tasks without due_on are not considered overdue."""
        mock_exec.return_value = {"data": [{"gid": "1", "name": "Task without due"}]}

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY)

        assert result["overdue_tasks"] == []

    @patch(f"{ASANA_MODULE}.execute_tool")
    def test_tasks_forward_verbatim_and_call_is_exact(self, mock_exec: MagicMock) -> None:
        overdue = {"gid": "2", "name": "B", "due_on": "2000-01-01", "resource_type": "task"}
        tasks = [{"gid": "1", "name": "A", "due_on": None}, overdue]
        mock_exec.return_value = {"data": tasks}

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY)

        assert result == {"tasks": tasks, "overdue_tasks": [overdue]}
        assert mock_exec.call_args.args == (
            "ASANA_SEARCH_TASKS_IN_WORKSPACE",
            {"assignee.any": "me", "completed": False, "limit": 10},
            FAKE_USER_ID,
        )

    @patch(f"{ASANA_MODULE}.execute_tool")
    def test_falls_back_to_tasks_key(self, mock_exec: MagicMock) -> None:
        mock_exec.return_value = {"tasks": [{"gid": "1", "name": "T"}]}

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY)

        assert result["tasks"] == [{"gid": "1", "name": "T"}]


# =============================================================================
# CLICKUP TOOLS
# =============================================================================

CLICKUP_MODULE = "app.agents.tools.integrations.clickup_tool"


class TestClickUpGatherContext:
    """Tests for ClickUp CUSTOM_GATHER_CONTEXT."""

    def _register(self) -> dict[str, Callable[..., Any]]:
        composio, captured = _make_capturing_composio()
        from app.agents.tools.integrations.clickup_tool import (
            register_clickup_custom_tools,
        )

        names = register_clickup_custom_tools(composio)
        assert "CLICKUP_CUSTOM_GATHER_CONTEXT" in names
        return captured

    @patch(f"{CLICKUP_MODULE}.execute_tool")
    def test_basic_success(self, mock_exec: MagicMock) -> None:
        """Returns tasks and overdue items based on due_date ms timestamp."""
        mock_exec.return_value = {
            "tasks": [
                {
                    "id": "1",
                    "name": "Future",
                    "due_date": "9999999999999",
                    "status": {"type": "open"},
                },
                {
                    "id": "2",
                    "name": "Overdue",
                    "due_date": "946684800000",  # 2000-01-01
                    "status": {"type": "open"},
                },
                {
                    "id": "3",
                    "name": "Closed overdue",
                    "due_date": "946684800000",
                    "status": {"type": "closed"},
                },
                {"id": "4", "name": "No due date"},
            ]
        }

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY)

        assert len(result["tasks"]) == 4
        assert len(result["overdue_tasks"]) == 1
        assert result["overdue_tasks"][0]["name"] == "Overdue"

    @patch(f"{CLICKUP_MODULE}.execute_tool")
    def test_tasks_forward_verbatim_and_call_is_exact(self, mock_exec: MagicMock) -> None:
        """A past-due task with no status counts as open, so it is overdue."""
        overdue = {"id": "2", "name": "O", "due_date": "946684800000", "status": {"type": "open"}}
        statusless = {"id": "3", "name": "S", "due_date": "946684800000"}
        tasks = [
            {"id": "1", "name": "N", "due_date": None, "status": {"type": "open", "color": "#f"}},
            overdue,
            statusless,
        ]
        mock_exec.return_value = {"tasks": tasks}

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY)

        assert result == {"tasks": tasks, "overdue_tasks": [overdue, statusless]}
        assert mock_exec.call_args.args == (
            "CLICKUP_GET_FILTERED_TEAM_TASKS",
            {"assignees": ["me"], "include_closed": False},
            FAKE_USER_ID,
        )

    @patch(f"{CLICKUP_MODULE}.datetime", _UTCOnlyDateTime)
    @patch(f"{CLICKUP_MODULE}.execute_tool")
    def test_a_task_due_this_exact_millisecond_is_not_yet_overdue(
        self, mock_exec: MagicMock
    ) -> None:
        now_ms = int(datetime(2026, 6, 15, 2, 0, tzinfo=UTC).timestamp() * 1000)
        mock_exec.return_value = {
            "tasks": [
                {"id": "1", "name": "Due now", "due_date": str(now_ms)},
                {"id": "2", "name": "Due a millisecond ago", "due_date": str(now_ms - 1)},
            ]
        }

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY)

        assert [t["name"] for t in result["overdue_tasks"]] == ["Due a millisecond ago"]

    @patch(f"{CLICKUP_MODULE}.execute_tool")
    def test_missing_user_id(self, mock_exec: MagicMock) -> None:
        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        with pytest.raises(ValueError, match="Missing user_id"):
            fn(GatherContextInput(), EXECUTE_REQUEST, {})


# =============================================================================
# GOOGLE TASKS TOOLS
# =============================================================================

GOOGLE_TASKS_MODULE = "app.agents.tools.integrations.google_tasks_tool"


class TestGoogleTasksGatherContext:
    """Tests for Google Tasks CUSTOM_GATHER_CONTEXT."""

    def _register(self) -> dict[str, Callable[..., Any]]:
        composio, captured = _make_capturing_composio()
        from app.agents.tools.integrations.google_tasks_tool import (
            register_google_tasks_custom_tools,
        )

        names = register_google_tasks_custom_tools(composio)
        assert "GOOGLETASKS_CUSTOM_GATHER_CONTEXT" in names
        return captured

    @patch(f"{GOOGLE_TASKS_MODULE}.execute_tool")
    def test_basic_success(self, mock_exec: MagicMock) -> None:
        """Returns tasks and overdue items."""
        mock_exec.return_value = {
            "items": [
                {"id": "1", "title": "Future", "due": "9999-12-31"},
                {"id": "2", "title": "Overdue", "due": "2000-01-01"},
                {"id": "3", "title": "No due"},
            ]
        }

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY)

        assert len(result["tasks"]) == 3
        assert len(result["overdue_tasks"]) == 1

    @patch(f"{GOOGLE_TASKS_MODULE}.execute_tool")
    def test_missing_user_id(self, mock_exec: MagicMock) -> None:
        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        with pytest.raises(ValueError, match="Missing user_id"):
            fn(GatherContextInput(), EXECUTE_REQUEST, {})

    @patch(f"{GOOGLE_TASKS_MODULE}.datetime", _UTCOnlyDateTime)
    @patch(f"{GOOGLE_TASKS_MODULE}.execute_tool")
    def test_overdue_boundary_is_the_utc_today(self, mock_exec: MagicMock) -> None:
        """A task due today is not yet overdue; yesterday is. Pinned to a fake UTC clock so a local-time read or a mangled date format fails here."""
        mock_exec.return_value = {
            "items": [
                {"id": "1", "title": "Due today", "due": "2026-06-15"},
                {"id": "2", "title": "Due tomorrow", "due": "2026-06-16"},
                {"id": "3", "title": "Due yesterday", "due": "2026-06-14"},
                {"id": "4", "title": "No due key"},
                {"id": "5", "title": "Explicitly null due", "due": None},
            ]
        }

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY)

        assert [t["title"] for t in result["overdue_tasks"]] == ["Due yesterday"]

    @patch(f"{GOOGLE_TASKS_MODULE}.execute_tool")
    def test_fallback_to_tasks_key(self, mock_exec: MagicMock) -> None:
        """Falls back to 'tasks' key when 'items' not present."""
        mock_exec.return_value = {"tasks": [{"id": "1", "title": "Task"}]}

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY)

        assert len(result["tasks"]) == 1

    @patch(f"{GOOGLE_TASKS_MODULE}.execute_tool")
    def test_tasks_forward_verbatim_and_call_is_exact(self, mock_exec: MagicMock) -> None:
        overdue = {
            "id": "2",
            "title": "B",
            "due": "2000-01-01T00:00:00.000Z",
            "status": "needsAction",
        }
        tasks = [{"id": "1", "title": "A", "notes": "n"}, overdue]
        mock_exec.return_value = {"items": tasks}

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY)

        assert result == {"tasks": tasks, "overdue_tasks": [overdue]}
        assert mock_exec.call_args.args == (
            "GOOGLETASKS_LIST_ALL_TASKS",
            {"showCompleted": False, "maxResults": 20},
            FAKE_USER_ID,
        )


# =============================================================================
# TRELLO TOOLS
# =============================================================================

TRELLO_MODULE = "app.agents.tools.integrations.trello_tool"


class TestTrelloGatherContext:
    """Tests for Trello CUSTOM_GATHER_CONTEXT."""

    def _register(self) -> dict[str, Callable[..., Any]]:
        composio, captured = _make_capturing_composio()
        from app.agents.tools.integrations.trello_tool import (
            register_trello_custom_tools,
        )

        names = register_trello_custom_tools(composio)
        assert "TRELLO_CUSTOM_GATHER_CONTEXT" in names
        return captured

    @patch(f"{TRELLO_MODULE}.execute_tool")
    def test_basic_success_list_format(self, mock_exec: MagicMock) -> None:
        """Returns cards when data is a list."""
        mock_exec.return_value = [
            {"id": "c1", "name": "Card 1"},
            {"id": "c2", "name": "Card 2"},
        ]

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY)

        assert len(result["cards"]) == 2

    @patch(f"{TRELLO_MODULE}.execute_tool")
    def test_basic_success_dict_format(self, mock_exec: MagicMock) -> None:
        """Returns cards when data is a dict with 'cards' key."""
        mock_exec.return_value = {"cards": [{"id": "c1", "name": "Card 1"}]}

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY)

        assert len(result["cards"]) == 1

    @patch(f"{TRELLO_MODULE}.execute_tool")
    def test_cards_forward_verbatim_and_call_is_exact(self, mock_exec: MagicMock) -> None:
        cards = [{"id": "c1", "name": "Card", "due": None, "idList": "l1", "labels": []}]
        mock_exec.return_value = cards

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY)

        assert result == {"cards": cards}
        assert mock_exec.call_args.args == (
            "TRELLO_GET_MEMBERS_CARDS_BY_ID_MEMBER",
            {"idMember": "me"},
            FAKE_USER_ID,
        )

    @patch(f"{TRELLO_MODULE}.execute_tool")
    def test_missing_user_id(self, mock_exec: MagicMock) -> None:
        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        with pytest.raises(ValueError, match="Missing user_id"):
            fn(GatherContextInput(), EXECUTE_REQUEST, {})


# =============================================================================
# URGENCY AGGREGATOR TOOL
# =============================================================================

URGENCY_MODULE = "app.agents.tools.integrations.urgency_tool"


class TestUrgencyAggregator:
    """Tests for CUSTOM_URGENCY_AGGREGATOR."""

    def _register(self) -> dict[str, Callable[..., Any]]:
        composio, captured = _make_capturing_composio()
        from app.agents.tools.integrations.urgency_tool import (
            register_urgency_custom_tools,
        )

        names = register_urgency_custom_tools(composio)
        assert "GAIA_CUSTOM_URGENCY_AGGREGATOR" in names
        return captured

    def _make_input(self, snapshots: dict[str, Any]) -> Any:
        from app.agents.tools.integrations.urgency_tool import UrgencyAggregatorInput

        return UrgencyAggregatorInput(snapshots=snapshots)

    def test_empty_snapshots(self) -> None:
        """Empty snapshots returns empty urgent items."""
        captured = self._register()
        fn = captured["CUSTOM_URGENCY_AGGREGATOR"]
        result = fn(self._make_input({}), EXECUTE_REQUEST, {})

        assert result["urgent_items"] == []
        assert result["total_urgent"] == 0

    def test_gmail_unread(self) -> None:
        """Gmail unread emails create urgency items."""
        captured = self._register()
        fn = captured["CUSTOM_URGENCY_AGGREGATOR"]

        # High priority: > 20 unread
        result = fn(
            self._make_input({"gmail": {"inbox_unread_count": 25}}),
            EXECUTE_REQUEST,
            {},
        )
        assert result["total_urgent"] == 1
        assert result["urgent_items"][0]["priority"] == "high"
        assert result["urgent_items"][0]["count"] == 25

    def test_gmail_medium_priority(self) -> None:
        """Gmail with <= 20 unread emails is medium priority."""
        captured = self._register()
        fn = captured["CUSTOM_URGENCY_AGGREGATOR"]

        result = fn(
            self._make_input({"gmail": {"inbox_unread_count": 5}}),
            EXECUTE_REQUEST,
            {},
        )
        assert result["urgent_items"][0]["priority"] == "medium"
        at_threshold = fn(
            self._make_input({"gmail": {"inbox_unread_count": 20}}), EXECUTE_REQUEST, {}
        )
        assert at_threshold["urgent_items"][0]["priority"] == "medium"

    def test_gmail_zero_unread(self) -> None:
        """Gmail with 0 unread does not create an item."""
        captured = self._register()
        fn = captured["CUSTOM_URGENCY_AGGREGATOR"]

        result = fn(
            self._make_input({"gmail": {"inbox_unread_count": 0}}),
            EXECUTE_REQUEST,
            {},
        )
        assert result["total_urgent"] == 0

    def test_slack_mentions(self) -> None:
        """Slack mentions create high priority items."""
        captured = self._register()
        fn = captured["CUSTOM_URGENCY_AGGREGATOR"]

        result = fn(
            self._make_input(
                {
                    "slack": {
                        "mentions": [{"text": "Hey @you check this"}],
                        "unread_count": 5,
                    }
                }
            ),
            EXECUTE_REQUEST,
            {},
        )
        items = [i for i in result["urgent_items"] if i["integration"] == "slack"]
        assert len(items) == 1
        assert items[0]["priority"] == "high"
        assert "1 Slack @mentions" in items[0]["description"]

    def test_slack_unread_no_mentions(self) -> None:
        """Slack unread without mentions uses unread_count."""
        captured = self._register()
        fn = captured["CUSTOM_URGENCY_AGGREGATOR"]

        result = fn(
            self._make_input({"slack": {"mentions": [], "unread_count": 10}}),
            EXECUTE_REQUEST,
            {},
        )
        items = [i for i in result["urgent_items"] if i["integration"] == "slack"]
        assert len(items) == 1
        assert "10 unread Slack messages" in items[0]["description"]

    def test_linear_overdue_issues(self) -> None:
        """Linear overdue issues create high priority items."""
        captured = self._register()
        fn = captured["CUSTOM_URGENCY_AGGREGATOR"]

        result = fn(
            self._make_input(
                {
                    "linear": {
                        "overdue_issues": [
                            {"title": "Fix bug"},
                            {"title": "Deploy"},
                        ]
                    }
                }
            ),
            EXECUTE_REQUEST,
            {},
        )
        items = [i for i in result["urgent_items"] if i["integration"] == "linear"]
        assert len(items) == 1
        assert items[0]["count"] == 2
        assert items[0]["priority"] == "high"

    def test_calendar_events(self) -> None:
        """Calendar events create medium priority items."""
        captured = self._register()
        fn = captured["CUSTOM_URGENCY_AGGREGATOR"]

        result = fn(
            self._make_input({"googlecalendar": {"events": [{"summary": "Standup"}]}}),
            EXECUTE_REQUEST,
            {},
        )
        items = [i for i in result["urgent_items"] if i["integration"] == "googlecalendar"]
        assert len(items) == 1
        assert items[0]["priority"] == "medium"

    def test_calendar_next_event(self) -> None:
        """Calendar with only next_event (no events list) still creates item."""
        captured = self._register()
        fn = captured["CUSTOM_URGENCY_AGGREGATOR"]

        result = fn(
            self._make_input({"googlecalendar": {"next_event": {"summary": "1:1"}}}),
            EXECUTE_REQUEST,
            {},
        )
        items = [i for i in result["urgent_items"] if i["integration"] == "googlecalendar"]
        assert len(items) == 1
        assert items[0]["count"] == 1

    def test_github_notifications_and_reviews(self) -> None:
        """GitHub notifications and review requests create separate items."""
        captured = self._register()
        fn = captured["CUSTOM_URGENCY_AGGREGATOR"]

        result = fn(
            self._make_input(
                {
                    "github": {
                        "notifications": [{"id": "n1"}],
                        "review_requests": [{"title": "PR #1"}, {"title": "PR #2"}],
                    }
                }
            ),
            EXECUTE_REQUEST,
            {},
        )
        gh_items = [i for i in result["urgent_items"] if i["integration"] == "github"]
        assert len(gh_items) == 2
        notif_item = next(i for i in gh_items if i["type"] == "unread_notifications")
        review_item = next(i for i in gh_items if i["type"] == "review_requests")
        assert notif_item["priority"] == "medium"
        assert review_item["priority"] == "high"
        assert review_item["count"] == 2

    def test_overdue_tasks(self) -> None:
        """Asana/Todoist/ClickUp overdue tasks create high priority items."""
        captured = self._register()
        fn = captured["CUSTOM_URGENCY_AGGREGATOR"]

        result = fn(
            self._make_input({"asana": {"overdue_tasks": [{"name": "Task 1"}]}}),
            EXECUTE_REQUEST,
            {},
        )
        items = [i for i in result["urgent_items"] if i["type"] == "overdue_tasks"]
        assert len(items) == 1
        assert items[0]["integration"] == "asana"
        assert items[0]["priority"] == "high"

    def test_urgent_tasks_fallback(self) -> None:
        """Falls back to urgent_tasks with overdue flag for Google Tasks."""
        captured = self._register()
        fn = captured["CUSTOM_URGENCY_AGGREGATOR"]

        result = fn(
            self._make_input(
                {
                    "googletasks": {
                        "urgent_tasks": [
                            {"title": "Overdue task", "overdue": True},
                            {"title": "Not overdue", "overdue": False},
                        ]
                    }
                }
            ),
            EXECUTE_REQUEST,
            {},
        )
        items = [i for i in result["urgent_items"] if i["type"] == "overdue_tasks"]
        assert len(items) == 1
        assert items[0]["count"] == 1

    def test_teams_unread_chats(self) -> None:
        """Teams unread chats create medium priority items."""
        captured = self._register()
        fn = captured["CUSTOM_URGENCY_AGGREGATOR"]

        result = fn(
            self._make_input({"teams": {"unread_chat_count": 3}}),
            EXECUTE_REQUEST,
            {},
        )
        items = [i for i in result["urgent_items"] if i["integration"] == "microsoft_teams"]
        assert len(items) == 1
        assert items[0]["priority"] == "medium"
        assert items[0]["count"] == 3

    def test_teams_zero_unread(self) -> None:
        """Teams with 0 unread chats does not create an item."""
        captured = self._register()
        fn = captured["CUSTOM_URGENCY_AGGREGATOR"]

        result = fn(
            self._make_input({"teams": {"unread_chat_count": 0}}),
            EXECUTE_REQUEST,
            {},
        )
        items = [i for i in result["urgent_items"] if i["integration"] == "microsoft_teams"]
        assert len(items) == 0

    def test_reddit_unread_messages(self) -> None:
        """Reddit unread messages create low priority items."""
        captured = self._register()
        fn = captured["CUSTOM_URGENCY_AGGREGATOR"]

        result = fn(
            self._make_input({"reddit": {"unread_message_count": 2}}),
            EXECUTE_REQUEST,
            {},
        )
        items = [i for i in result["urgent_items"] if i["integration"] == "reddit"]
        assert len(items) == 1
        assert items[0]["priority"] == "low"

    def test_sorting_by_priority_and_count(self) -> None:
        """Items are sorted high > medium > low, then by count descending."""
        captured = self._register()
        fn = captured["CUSTOM_URGENCY_AGGREGATOR"]

        result = fn(
            self._make_input(
                {
                    "gmail": {"inbox_unread_count": 5},  # medium, count=5
                    "linear": {"overdue_issues": [{"title": "a"}, {"title": "b"}]},  # high, count=2
                    "reddit": {"unread_message_count": 10},  # low, count=10
                    "github": {
                        "review_requests": [{"title": "PR"}],
                        "notifications": [],
                    },  # high, count=1
                }
            ),
            EXECUTE_REQUEST,
            {},
        )

        items = result["urgent_items"]
        assert len(items) >= 3
        # High priority items first
        high_items = [i for i in items if i["priority"] == "high"]
        medium_items = [i for i in items if i["priority"] == "medium"]
        low_items = [i for i in items if i["priority"] == "low"]

        # All high before all medium before all low
        high_indices = [items.index(i) for i in high_items]
        medium_indices = [items.index(i) for i in medium_items]
        low_indices = [items.index(i) for i in low_items]

        if high_indices and medium_indices:
            assert max(high_indices) < min(medium_indices)
        if medium_indices and low_indices:
            assert max(medium_indices) < min(low_indices)

    def test_summary_counts(self) -> None:
        """Summary contains correct high/medium/low counts."""
        captured = self._register()
        fn = captured["CUSTOM_URGENCY_AGGREGATOR"]

        result = fn(
            self._make_input(
                {
                    "linear": {"overdue_issues": [{"title": "a"}]},  # high
                    "gmail": {"inbox_unread_count": 5},  # medium
                    "reddit": {"unread_message_count": 1},  # low
                }
            ),
            EXECUTE_REQUEST,
            {},
        )

        assert result["summary"]["high_priority"] >= 1
        assert result["summary"]["medium_priority"] >= 1
        assert result["summary"]["low_priority"] >= 1

    def test_non_dict_snapshot_is_rejected_at_input(self) -> None:
        """The input schema refuses a non-object snapshot instead of reporting nothing urgent."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="snapshots.broken"):
            self._make_input({"broken": "not a dict", "gmail": {"inbox_unread_count": 3}})

    def test_branches_fire_on_key_presence_not_value(self) -> None:
        """An unread_count key names Slack and Gmail; an empty mentions list still yields items."""
        captured = self._register()
        fn = captured["CUSTOM_URGENCY_AGGREGATOR"]

        assert (
            fn(self._make_input({"slack": {"unread_count": 0}}), EXECUTE_REQUEST, {})[
                "urgent_items"
            ]
            == []
        )
        result = fn(
            self._make_input({"slack": {"mentions": [], "unread_count": 3}}), EXECUTE_REQUEST, {}
        )
        assert result["urgent_items"] == [
            {
                "integration": "slack",
                "type": "unread_messages",
                "count": 3,
                "priority": "high",
                "description": "3 unread Slack messages",
                "details": [],
            },
            {
                "integration": "gmail",
                "type": "unread_emails",
                "count": 3,
                "priority": "medium",
                "description": "3 unread emails in inbox",
            },
        ]
        without_mentions = fn(self._make_input({"slack": {"unread_count": 3}}), EXECUTE_REQUEST, {})
        assert without_mentions["urgent_items"] == result["urgent_items"]

    def test_a_single_unread_counts_and_every_priority_is_tallied_exactly(self) -> None:
        captured = self._register()
        fn = captured["CUSTOM_URGENCY_AGGREGATOR"]

        result = fn(
            self._make_input(
                {
                    "gmail": {"inbox_unread_count": 1},
                    "teams": {"unread_chat_count": 1},
                    "reddit": {"unread_message_count": 1},
                }
            ),
            EXECUTE_REQUEST,
            {},
        )

        assert result == {
            "urgent_items": [
                {
                    "integration": "gmail",
                    "type": "unread_emails",
                    "count": 1,
                    "priority": "medium",
                    "description": "1 unread emails in inbox",
                },
                {
                    "integration": "microsoft_teams",
                    "type": "unread_chats",
                    "count": 1,
                    "priority": "medium",
                    "description": "1 unread Microsoft Teams chats",
                },
                {
                    "integration": "reddit",
                    "type": "unread_messages",
                    "count": 1,
                    "priority": "low",
                    "description": "1 unread Reddit messages",
                },
            ],
            "total_urgent": 3,
            "summary": {"high_priority": 0, "medium_priority": 2, "low_priority": 1},
        }

    @pytest.mark.parametrize("unread", [0, None])
    def test_reddit_with_no_unread_messages_yields_nothing(self, unread: int | None) -> None:
        captured = self._register()
        fn = captured["CUSTOM_URGENCY_AGGREGATOR"]

        result = fn(
            self._make_input({"reddit": {"unread_message_count": unread}}), EXECUTE_REQUEST, {}
        )

        assert result["urgent_items"] == []

    def test_linear_with_an_empty_overdue_list_yields_nothing(self) -> None:
        captured = self._register()
        fn = captured["CUSTOM_URGENCY_AGGREGATOR"]

        result = fn(self._make_input({"linear": {"overdue_issues": []}}), EXECUTE_REQUEST, {})

        assert result["urgent_items"] == []

    def test_github_fires_on_notifications_alone_and_on_review_requests_alone(self) -> None:
        captured = self._register()
        fn = captured["CUSTOM_URGENCY_AGGREGATOR"]

        result = fn(
            self._make_input(
                {
                    "github": {"notifications": [{"id": "n1"}]},
                    "github_reviews": {"review_requests": [{"title": "PR"}]},
                }
            ),
            EXECUTE_REQUEST,
            {},
        )

        assert result["urgent_items"] == [
            {
                "integration": "github",
                "type": "review_requests",
                "count": 1,
                "priority": "high",
                "description": "1 GitHub PRs awaiting your review",
                "details": ["PR"],
            },
            {
                "integration": "github",
                "type": "unread_notifications",
                "count": 1,
                "priority": "medium",
                "description": "1 unread GitHub notifications",
            },
        ]

    def test_quoted_details_stop_at_three_and_blank_a_missing_label(self) -> None:
        captured = self._register()
        fn = captured["CUSTOM_URGENCY_AGGREGATOR"]

        result = fn(
            self._make_input(
                {
                    "slack": {"mentions": [{"text": "a"}, {}, {"text": "c"}, {"text": "d"}]},
                    "linear": {"overdue_issues": [{"title": str(n)} for n in range(1, 5)]},
                    "github": {
                        "review_requests": [{"title": "p"}, {}, {"title": "r"}, {"title": "s"}]
                    },
                    "asana": {"overdue_tasks": [{"name": f"t{n}"} for n in range(1, 5)]},
                }
            ),
            EXECUTE_REQUEST,
            {},
        )

        assert {
            (i["integration"], i["type"]): (i["count"], i["details"])
            for i in result["urgent_items"]
        } == {
            ("slack", "unread_messages"): (4, ["a", "", "c"]),
            ("linear", "overdue_issues"): (4, ["1", "2", "3"]),
            ("github", "review_requests"): (4, ["p", "", "r"]),
            ("asana", "overdue_tasks"): (4, ["t1", "t2", "t3"]),
        }

    def test_exact_items_and_details_shape(self) -> None:
        """Count-only branches omit details; quoting branches carry the first three labels."""
        captured = self._register()
        fn = captured["CUSTOM_URGENCY_AGGREGATOR"]

        result = fn(
            self._make_input(
                {
                    "gmail": {"inbox_unread_count": 21, "other": "ignored"},
                    "slack": {"mentions": [{"text": "x" * 100}, {"text": "y"}]},
                    "linear": {"overdue_issues": [{"title": "a"}, {"id": 2}]},
                    "googlecalendar": {
                        "events": [{"summary": "s"}, {"title": "t"}, {}, {"summary": "4"}]
                    },
                    "todoist": {"overdue_tasks": [{"name": "n"}, {"title": "t"}, {}]},
                    "teams": {"unread_chat_count": 3},
                }
            ),
            EXECUTE_REQUEST,
            {},
        )

        assert result == {
            "urgent_items": [
                {
                    "integration": "gmail",
                    "type": "unread_emails",
                    "count": 21,
                    "priority": "high",
                    "description": "21 unread emails in inbox",
                },
                {
                    "integration": "todoist",
                    "type": "overdue_tasks",
                    "count": 3,
                    "priority": "high",
                    "description": "3 overdue tasks in todoist",
                    "details": ["n", "t", None],
                },
                {
                    "integration": "slack",
                    "type": "unread_messages",
                    "count": 2,
                    "priority": "high",
                    "description": "2 Slack @mentions",
                    "details": ["x" * 80, "y"],
                },
                {
                    "integration": "linear",
                    "type": "overdue_issues",
                    "count": 2,
                    "priority": "high",
                    "description": "2 overdue Linear issues",
                    "details": ["a", None],
                },
                {
                    "integration": "googlecalendar",
                    "type": "upcoming_events",
                    "count": 4,
                    "priority": "medium",
                    "description": "4 calendar events today",
                    "details": ["s", "t", ""],
                },
                {
                    "integration": "microsoft_teams",
                    "type": "unread_chats",
                    "count": 3,
                    "priority": "medium",
                    "description": "3 unread Microsoft Teams chats",
                },
            ],
            "total_urgent": 6,
            "summary": {"high_priority": 4, "medium_priority": 2, "low_priority": 0},
        }

    def test_multiple_integrations(self) -> None:
        """Multiple integrations aggregate correctly."""
        captured = self._register()
        fn = captured["CUSTOM_URGENCY_AGGREGATOR"]

        result = fn(
            self._make_input(
                {
                    "gmail": {"inbox_unread_count": 3},
                    "slack": {"mentions": [{"text": "hey"}]},
                    "asana": {"overdue_tasks": [{"name": "task1"}]},
                    "teams": {"unread_chat_count": 2},
                    "reddit": {"unread_message_count": 1},
                }
            ),
            EXECUTE_REQUEST,
            {},
        )

        assert result["total_urgent"] == 5
        integrations = {i["integration"] for i in result["urgent_items"]}
        assert "gmail" in integrations
        assert "slack" in integrations
        assert "asana" in integrations
        assert "microsoft_teams" in integrations
        assert "reddit" in integrations
