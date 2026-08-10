"""Unit tests for smaller Composio integration tools.

Covers:
- github_tool.py
- airtable_tool.py
- slack_tool.py
- todoist_tool.py
- asana_tool.py
- clickup_tool.py
- google_tasks_tool.py
- trello_tool.py
- urgency_tool.py

Strategy: Each register_*_custom_tools() function decorates inner functions with
@composio.tools.custom_tool(). We mock the Composio instance with a capturing
decorator, call register_*_custom_tools() to capture the inner functions,
then invoke them directly with mock auth_credentials and request objects.
"""

from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock, patch

from pydantic import ValidationError
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

    @patch(f"{ASANA_MODULE}.execute_tool")
    def test_no_overdue(self, mock_exec: MagicMock) -> None:
        """Tasks without due_on are not considered overdue."""
        mock_exec.return_value = {"data": [{"gid": "1", "name": "Task without due"}]}

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY)

        assert result["overdue_tasks"] == []


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

    @patch(f"{GOOGLE_TASKS_MODULE}.execute_tool")
    def test_fallback_to_tasks_key(self, mock_exec: MagicMock) -> None:
        """Falls back to 'tasks' key when 'items' not present."""
        mock_exec.return_value = {"tasks": [{"id": "1", "title": "Task"}]}

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY)

        assert len(result["tasks"]) == 1


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
        """Returns cards unchanged when data is a list."""
        mock_exec.return_value = [
            {"id": "c1", "name": "Card 1"},
            {"id": "c2", "name": "Card 2"},
        ]

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY)

        assert result == {
            "cards": [
                {"id": "c1", "name": "Card 1"},
                {"id": "c2", "name": "Card 2"},
            ]
        }
        mock_exec.assert_called_once_with(
            "TRELLO_GET_MEMBERS_CARDS_BY_ID_MEMBER",
            {"idMember": "me"},
            FAKE_USER_ID,
        )

    @patch(f"{TRELLO_MODULE}.execute_tool")
    def test_basic_success_dict_format(self, mock_exec: MagicMock) -> None:
        """Returns cards from the 'cards' key when data is a dict."""
        mock_exec.return_value = {"cards": [{"id": "c1", "name": "Card 1"}]}

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY)

        assert result == {"cards": [{"id": "c1", "name": "Card 1"}]}
        mock_exec.assert_called_once_with(
            "TRELLO_GET_MEMBERS_CARDS_BY_ID_MEMBER",
            {"idMember": "me"},
            FAKE_USER_ID,
        )

    @patch(f"{TRELLO_MODULE}.execute_tool")
    def test_dict_without_cards_key_defaults_to_empty(self, mock_exec: MagicMock) -> None:
        """Falls back to an empty list when a dict payload has no 'cards' key."""
        mock_exec.return_value = {"some_other_key": "value"}

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY)

        assert result == {"cards": []}

    @patch(f"{TRELLO_MODULE}.execute_tool")
    def test_empty_list_input(self, mock_exec: MagicMock) -> None:
        """Returns an empty cards list when data is an empty list."""
        mock_exec.return_value = []

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_USER_ONLY)

        assert result == {"cards": []}

    @patch(f"{TRELLO_MODULE}.execute_tool")
    def test_missing_user_id(self, mock_exec: MagicMock) -> None:
        """Raises ValueError without calling execute_tool when user_id is missing."""
        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        with pytest.raises(ValueError, match=r"^Missing user_id in auth_credentials$"):
            fn(GatherContextInput(), EXECUTE_REQUEST, {})
        mock_exec.assert_not_called()


# =============================================================================
# URGENCY AGGREGATOR TOOL
# =============================================================================

URGENCY_MODULE = "app.agents.tools.integrations.urgency_tool"

EMPTY_RESULT: dict[str, Any] = {
    "urgent_items": [],
    "total_urgent": 0,
    "summary": {"high_priority": 0, "medium_priority": 0, "low_priority": 0},
}


class TestUrgencyAggregator:
    """Tests for CUSTOM_URGENCY_AGGREGATOR."""

    def _register(self) -> dict[str, Callable[..., Any]]:
        composio, captured = _make_capturing_composio()
        from app.agents.tools.integrations.urgency_tool import (
            register_urgency_custom_tools,
        )

        names = register_urgency_custom_tools(composio)
        assert names == ["GAIA_CUSTOM_URGENCY_AGGREGATOR"]
        return captured

    def _make_input(self, snapshots: dict[str, Any]) -> Any:
        from app.agents.tools.integrations.urgency_tool import UrgencyAggregatorInput

        return UrgencyAggregatorInput(snapshots=snapshots)

    def _aggregate(self, snapshots: dict[str, Any]) -> Any:
        captured = self._register()
        fn = captured["CUSTOM_URGENCY_AGGREGATOR"]
        return fn(self._make_input(snapshots), EXECUTE_REQUEST, {})

    def test_empty_snapshots_return_empty_aggregate(self) -> None:
        """Empty snapshots returns the empty aggregate result verbatim."""
        assert self._aggregate({}) == EMPTY_RESULT

    def test_input_model_requires_snapshots(self) -> None:
        """snapshots is a required field — building the model without it fails."""
        from app.agents.tools.integrations.urgency_tool import UrgencyAggregatorInput

        with pytest.raises(ValidationError):
            UrgencyAggregatorInput()

    def test_input_model_snapshots_description(self) -> None:
        """The snapshots field description documents the accepted shape."""
        from app.agents.tools.integrations.urgency_tool import UrgencyAggregatorInput

        assert UrgencyAggregatorInput.model_fields["snapshots"].description == (
            "Dict mapping integration name to its CUSTOM_GATHER_CONTEXT output. "
            "Example: {'gmail': {...}, 'slack': {...}, 'linear': {...}}"
        )

    def test_gmail_unread_over_20_is_high_priority(self) -> None:
        """Gmail with > 20 unread emails is a high-priority item."""
        result = self._aggregate({"gmail": {"inbox_unread_count": 25}})

        assert result == {
            "urgent_items": [
                {
                    "integration": "gmail",
                    "type": "unread_emails",
                    "count": 25,
                    "priority": "high",
                    "description": "25 unread emails in inbox",
                }
            ],
            "total_urgent": 1,
            "summary": {"high_priority": 1, "medium_priority": 0, "low_priority": 0},
        }

    def test_gmail_exactly_20_unread_is_medium_priority(self) -> None:
        """20 unread emails stays medium — only strictly more than 20 is high."""
        result = self._aggregate({"gmail": {"inbox_unread_count": 20}})

        item = result["urgent_items"][0]
        assert item["count"] == 20
        assert item["priority"] == "medium"
        assert item["description"] == "20 unread emails in inbox"

    def test_gmail_exactly_21_unread_is_high_priority(self) -> None:
        """21 unread emails crosses into high priority."""
        result = self._aggregate({"gmail": {"inbox_unread_count": 21}})

        assert result["urgent_items"][0]["priority"] == "high"

    def test_gmail_one_unread_creates_item(self) -> None:
        """A single unread email still creates an item."""
        result = self._aggregate({"gmail": {"inbox_unread_count": 1}})

        assert result["total_urgent"] == 1
        assert result["urgent_items"][0]["count"] == 1
        assert result["urgent_items"][0]["description"] == "1 unread emails in inbox"

    def test_gmail_zero_unread_creates_no_item(self) -> None:
        """Gmail with 0 unread emails creates nothing."""
        assert self._aggregate({"gmail": {"inbox_unread_count": 0}}) == EMPTY_RESULT

    def test_gmail_falls_back_to_unread_count_when_inbox_count_zero(self) -> None:
        """Zero inbox_unread_count falls through the `or` chain to unread_count.

        unread_count also satisfies the Slack detection block, so both the
        gmail item (via the fallback) and a slack item are produced.
        """
        result = self._aggregate({"gmail": {"inbox_unread_count": 0, "unread_count": 4}})

        assert result["total_urgent"] == 2
        gmail_item = next(i for i in result["urgent_items"] if i["integration"] == "gmail")
        assert gmail_item == {
            "integration": "gmail",
            "type": "unread_emails",
            "count": 4,
            "priority": "medium",
            "description": "4 unread emails in inbox",
        }
        slack_item = next(i for i in result["urgent_items"] if i["integration"] == "slack")
        assert slack_item["count"] == 4

    def test_gmail_unread_count_key_alone_triggers_gmail_and_slack_blocks(self) -> None:
        """A bare unread_count key is detected by both the gmail and slack blocks."""
        result = self._aggregate({"gmail": {"unread_count": 7}})

        assert result["total_urgent"] == 2
        assert {i["integration"] for i in result["urgent_items"]} == {"gmail", "slack"}
        gmail_item = next(i for i in result["urgent_items"] if i["integration"] == "gmail")
        assert gmail_item["count"] == 7
        slack_item = next(i for i in result["urgent_items"] if i["integration"] == "slack")
        assert slack_item["count"] == 7
        assert slack_item["description"] == "7 unread Slack messages"

    def test_slack_mentions_use_mention_count_and_truncated_details(self) -> None:
        """Mentions win over unread_count; details truncate text to 80 and keep 3."""
        result = self._aggregate(
            {
                "slack": {
                    "mentions": [
                        {"text": "x" * 100},
                        {"text": "second"},
                        {},
                        {"text": "fourth"},
                    ],
                    "unread_count": 99,
                }
            }
        )

        slack_items = [i for i in result["urgent_items"] if i["integration"] == "slack"]
        assert len(slack_items) == 1
        assert slack_items[0] == {
            "integration": "slack",
            "type": "unread_messages",
            "count": 4,
            "priority": "high",
            "description": "4 Slack @mentions",
            "details": ["x" * 80, "second", ""],
        }

    def test_slack_mentions_with_zero_unread_count_still_create_item(self) -> None:
        """Mentions alone (unread_count 0) are enough to create the item."""
        result = self._aggregate(
            {"slack": {"mentions": [{"text": "hi"}], "unread_count": 0}}
        )

        slack_items = [i for i in result["urgent_items"] if i["integration"] == "slack"]
        assert len(slack_items) == 1
        assert slack_items[0]["count"] == 1
        assert slack_items[0]["description"] == "1 Slack @mentions"

    def test_slack_unread_count_without_mentions(self) -> None:
        """Slack unread without mentions uses unread_count with an empty details list."""
        result = self._aggregate({"slack": {"mentions": [], "unread_count": 10}})

        # unread_count also triggers the gmail block, hence 2 items.
        assert result["total_urgent"] == 2
        slack_item = next(i for i in result["urgent_items"] if i["integration"] == "slack")
        assert slack_item == {
            "integration": "slack",
            "type": "unread_messages",
            "count": 10,
            "priority": "high",
            "description": "10 unread Slack messages",
            "details": [],
        }
        gmail_item = next(i for i in result["urgent_items"] if i["integration"] == "gmail")
        assert gmail_item["count"] == 10

    def test_slack_no_signals_creates_no_item(self) -> None:
        """Empty mentions and no unread_count create nothing."""
        assert self._aggregate({"slack": {"mentions": []}}) == EMPTY_RESULT
        assert self._aggregate({"slack": {"mentions": [], "unread_count": 0}}) == EMPTY_RESULT

    def test_linear_overdue_issues_with_truncated_details(self) -> None:
        """Linear overdue issues create a high-priority item; details keep 3 titles."""
        result = self._aggregate(
            {
                "linear": {
                    "overdue_issues": [
                        {"title": "Fix bug"},
                        {"title": "Deploy"},
                        {},
                        {"title": "Fourth"},
                    ]
                }
            }
        )

        assert result["urgent_items"] == [
            {
                "integration": "linear",
                "type": "overdue_issues",
                "count": 4,
                "priority": "high",
                "description": "4 overdue Linear issues",
                "details": ["Fix bug", "Deploy", None],
            }
        ]

    def test_linear_empty_overdue_list_creates_no_item(self) -> None:
        """An empty overdue_issues list creates nothing."""
        assert self._aggregate({"linear": {"overdue_issues": []}}) == EMPTY_RESULT

    def test_calendar_events_preferred_over_next_event(self) -> None:
        """events wins over next_event; summary beats title; details keep 3 entries."""
        result = self._aggregate(
            {
                "googlecalendar": {
                    "events": [
                        {"summary": "Standup", "title": "Standup alias"},
                        {"title": "1:1"},
                        {},
                        {"summary": "Fourth"},
                    ],
                    "next_event": {"summary": "Next"},
                }
            }
        )

        calendar_items = [
            i for i in result["urgent_items"] if i["integration"] == "googlecalendar"
        ]
        assert len(calendar_items) == 1
        assert calendar_items[0] == {
            "integration": "googlecalendar",
            "type": "upcoming_events",
            "count": 4,
            "priority": "medium",
            "description": "4 calendar events today",
            "details": ["Standup", "1:1", ""],
        }

    def test_calendar_next_event_fallback(self) -> None:
        """A lone next_event still creates an item, using its title as detail."""
        result = self._aggregate(
            {"googlecalendar": {"next_event": {"title": "1:1"}}}
        )

        calendar_items = [
            i for i in result["urgent_items"] if i["integration"] == "googlecalendar"
        ]
        assert len(calendar_items) == 1
        assert calendar_items[0]["count"] == 1
        assert calendar_items[0]["description"] == "1 calendar events today"
        assert calendar_items[0]["details"] == ["1:1"]

    def test_calendar_events_without_next_event_key(self) -> None:
        """A snapshot carrying only events (no next_event key) still creates an item."""
        result = self._aggregate(
            {"googlecalendar": {"events": [{"summary": "Standup"}]}}
        )

        calendar_items = [
            i for i in result["urgent_items"] if i["integration"] == "googlecalendar"
        ]
        assert len(calendar_items) == 1
        assert calendar_items[0]["count"] == 1

    def test_calendar_empty_events_creates_no_item(self) -> None:
        """Empty events with no next_event create nothing."""
        assert (
            self._aggregate(
                {"googlecalendar": {"events": [], "next_event": None}}
            )
            == EMPTY_RESULT
        )

    def test_github_notifications_only(self) -> None:
        """GitHub notifications alone create a medium-priority item."""
        result = self._aggregate(
            {"github": {"notifications": [{"id": "n1"}, {"id": "n2"}]}}
        )

        assert result["urgent_items"] == [
            {
                "integration": "github",
                "type": "unread_notifications",
                "count": 2,
                "priority": "medium",
                "description": "2 unread GitHub notifications",
            }
        ]

    def test_github_review_requests_only(self) -> None:
        """GitHub review requests alone create a high-priority item with details."""
        result = self._aggregate(
            {
                "github": {
                    "review_requests": [
                        {"title": "PR #1"},
                        {},
                        {"title": "PR #3"},
                        {"title": "PR #4"},
                    ]
                }
            }
        )

        assert result["urgent_items"] == [
            {
                "integration": "github",
                "type": "review_requests",
                "count": 4,
                "priority": "high",
                "description": "4 GitHub PRs awaiting your review",
                "details": ["PR #1", "", "PR #3"],
            }
        ]

    def test_github_both_notifications_and_reviews(self) -> None:
        """Notifications and review requests produce two items, review first."""
        result = self._aggregate(
            {
                "github": {
                    "notifications": [{"id": "n1"}],
                    "review_requests": [{"title": "PR"}],
                }
            }
        )

        assert result["total_urgent"] == 2
        assert [i["type"] for i in result["urgent_items"]] == [
            "review_requests",
            "unread_notifications",
        ]

    def test_github_empty_lists_creates_no_item(self) -> None:
        """Empty notifications and review_requests create nothing."""
        assert (
            self._aggregate(
                {"github": {"notifications": [], "review_requests": []}}
            )
            == EMPTY_RESULT
        )

    def test_overdue_tasks_lowercase_integration_and_detail_fallbacks(self) -> None:
        """Overdue tasks use the lowercased integration name; name beats title."""
        result = self._aggregate(
            {
                "MyAsana": {
                    "overdue_tasks": [
                        {"name": "Named", "title": "Named alias"},
                        {"title": "Titled only"},
                        {"neither": True},
                        {"name": "Fourth"},
                    ]
                }
            }
        )

        assert result["urgent_items"] == [
            {
                "integration": "myasana",
                "type": "overdue_tasks",
                "count": 4,
                "priority": "high",
                "description": "4 overdue tasks in myasana",
                "details": ["Named", "Titled only", None],
            }
        ]

    def test_urgent_tasks_fallback_filters_overdue_flag(self) -> None:
        """urgent_tasks fallback keeps only entries with a truthy overdue flag."""
        result = self._aggregate(
            {
                "googletasks": {
                    "urgent_tasks": [
                        {"title": "Overdue", "overdue": True},
                        {"title": "Not overdue", "overdue": False},
                        {"title": "Missing flag"},
                        {"title": "Truthy flag", "overdue": 1},
                    ]
                }
            }
        )

        item = result["urgent_items"][0]
        assert item["type"] == "overdue_tasks"
        assert item["count"] == 2
        assert item["details"] == ["Overdue", "Truthy flag"]

    def test_overdue_tasks_prefer_overdue_tasks_key(self) -> None:
        """A present overdue_tasks key shadows the urgent_tasks fallback."""
        result = self._aggregate(
            {
                "asana": {
                    "overdue_tasks": [{"name": "From overdue_tasks"}],
                    "urgent_tasks": [
                        {"name": "From urgent_tasks", "overdue": True}
                    ],
                }
            }
        )

        item = result["urgent_items"][0]
        assert item["count"] == 1
        assert item["details"] == ["From overdue_tasks"]

    def test_no_overdue_signals_creates_no_task_item(self) -> None:
        """Snapshots without overdue or urgent tasks create nothing."""
        assert self._aggregate({"asana": {}}) == EMPTY_RESULT
        assert (
            self._aggregate({"asana": {"urgent_tasks": [{"name": "Not overdue"}]}})
            == EMPTY_RESULT
        )

    def test_teams_unread_chats(self) -> None:
        """Teams unread chats create a medium-priority item."""
        result = self._aggregate({"teams": {"unread_chat_count": 3}})

        assert result["urgent_items"] == [
            {
                "integration": "microsoft_teams",
                "type": "unread_chats",
                "count": 3,
                "priority": "medium",
                "description": "3 unread Microsoft Teams chats",
            }
        ]

    def test_teams_one_unread_chat_creates_item(self) -> None:
        """A single unread chat still creates an item."""
        assert self._aggregate({"teams": {"unread_chat_count": 1}})["total_urgent"] == 1

    def test_teams_zero_unread_chats_creates_no_item(self) -> None:
        """Zero unread chats create nothing."""
        assert self._aggregate({"teams": {"unread_chat_count": 0}}) == EMPTY_RESULT

    def test_reddit_unread_messages(self) -> None:
        """Reddit unread messages create a low-priority item."""
        result = self._aggregate({"reddit": {"unread_message_count": 2}})

        assert result["urgent_items"] == [
            {
                "integration": "reddit",
                "type": "unread_messages",
                "count": 2,
                "priority": "low",
                "description": "2 unread Reddit messages",
            }
        ]

    def test_reddit_one_unread_message_creates_item(self) -> None:
        """A single unread message still creates an item."""
        assert self._aggregate({"reddit": {"unread_message_count": 1}})["total_urgent"] == 1

    def test_reddit_zero_unread_messages_creates_no_item(self) -> None:
        """Zero unread messages create nothing."""
        assert self._aggregate({"reddit": {"unread_message_count": 0}}) == EMPTY_RESULT

    def test_items_sorted_by_priority_then_count_descending(self) -> None:
        """Items are sorted high > medium > low, then by count descending.

        The high tier is deliberately inserted in count-ascending order
        (review_requests before overdue_issues) so that a sort key that
        ignores the count would produce a visibly different order.
        """
        result = self._aggregate(
            {
                "github": {
                    "review_requests": [{"title": "PR"}],  # high, count 1 — inserted first
                    "notifications": [{"id": "n1"}],  # medium, count 1
                },
                "linear": {"overdue_issues": [{"title": "a"}, {"title": "b"}, {"title": "c"}]},  # high, count 3
                "gmail": {"inbox_unread_count": 5},  # medium, count 5
                "reddit": {"unread_message_count": 10},  # low, count 10
            }
        )

        assert [i["type"] for i in result["urgent_items"]] == [
            "overdue_issues",  # high, count 3 — first among highs (desc count)
            "review_requests",  # high, count 1
            "unread_emails",  # medium, count 5
            "unread_notifications",  # medium, count 1
            "unread_messages",  # low, count 10
        ]
        assert result["total_urgent"] == 5

    def test_summary_counts_exact(self) -> None:
        """Summary reports exact per-priority counts."""
        result = self._aggregate(
            {
                "linear": {"overdue_issues": [{"title": "a"}]},  # high
                "gmail": {"inbox_unread_count": 5},  # medium
                "reddit": {"unread_message_count": 1},  # low
            }
        )

        assert result["total_urgent"] == 3
        assert result["summary"] == {
            "high_priority": 1,
            "medium_priority": 1,
            "low_priority": 1,
        }

    def test_non_dict_snapshot_skipped(self) -> None:
        """Non-dict snapshots are skipped without stopping later integrations."""
        result = self._aggregate(
            {
                "broken": "not a dict",
                "also_broken": 123,
                "gmail": {"inbox_unread_count": 5},
            }
        )

        assert result["total_urgent"] == 1
        assert result["urgent_items"][0]["integration"] == "gmail"
        assert result["summary"] == {
            "high_priority": 0,
            "medium_priority": 1,
            "low_priority": 0,
        }

    def test_multiple_integrations(self) -> None:
        """Multiple integrations aggregate into a single sorted result."""
        result = self._aggregate(
            {
                "gmail": {"inbox_unread_count": 3},
                "slack": {"mentions": [{"text": "hey"}]},
                "asana": {"overdue_tasks": [{"name": "task1"}]},
                "teams": {"unread_chat_count": 2},
                "reddit": {"unread_message_count": 1},
            }
        )

        assert result["total_urgent"] == 5
        assert [i["type"] for i in result["urgent_items"]] == [
            "unread_messages",  # slack mention — high, count 1 (inserted first)
            "overdue_tasks",  # asana — high, count 1
            "unread_emails",  # gmail — medium, count 3
            "unread_chats",  # teams — medium, count 2
            "unread_messages",  # reddit — low
        ]
        assert result["summary"] == {
            "high_priority": 2,
            "medium_priority": 2,
            "low_priority": 1,
        }
