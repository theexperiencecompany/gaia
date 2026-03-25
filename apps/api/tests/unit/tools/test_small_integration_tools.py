"""Unit tests for smaller Composio integration tools.

Covers:
- github_tool.py
- hubspot_tool.py
- airtable_tool.py
- google_meet_tool.py
- google_maps_tool.py
- slack_tool.py
- reddit_tool.py
- instagram_tool.py
- todoist_tool.py
- asana_tool.py
- clickup_tool.py
- google_tasks_tool.py
- trello_tool.py
- urgency_tool.py
- microsoft_teams_tool.py

Strategy: Each register_*_custom_tools() function decorates inner functions with
@composio.tools.custom_tool(). We mock the Composio instance with a capturing
decorator, call register_*_custom_tools() to capture the inner functions,
then invoke them directly with mock auth_credentials and request objects.
"""

from typing import Any, Callable, Dict
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.models.common_models import GatherContextInput

# ── Constants ─────────────────────────────────────────────────────────────────

FAKE_ACCESS_TOKEN = "fake-access-token"
FAKE_USER_ID = "user-123"
AUTH_CREDS_TOKEN: Dict[str, Any] = {
    "access_token": FAKE_ACCESS_TOKEN,
    "user_id": FAKE_USER_ID,
}
AUTH_CREDS_USER_ONLY: Dict[str, Any] = {
    "user_id": FAKE_USER_ID,
}
EXECUTE_REQUEST = MagicMock()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_capturing_composio() -> tuple[MagicMock, Dict[str, Callable[..., Any]]]:
    """Create a Composio mock whose custom_tool decorator captures inner functions."""
    composio = MagicMock()
    captured: Dict[str, Callable[..., Any]] = {}

    def _custom_tool(**kwargs: Any) -> Callable[..., Any]:
        def wrapper(fn: Callable[..., Any]) -> Callable[..., Any]:
            captured[fn.__name__] = fn
            return fn

        return wrapper

    composio.tools.custom_tool = _custom_tool
    return composio, captured


def _ok_response(json_data: Any, status_code: int = 200) -> MagicMock:
    """Build a fake httpx.Response-like object."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    resp.text = ""
    resp.headers = {}
    return resp


def _error_response(
    status_code: int = 400, text: str = "Bad Request"
) -> httpx.Response:
    """Build a real httpx.Response that raises on .raise_for_status()."""
    return httpx.Response(
        status_code=status_code, text=text, request=httpx.Request("GET", "https://test")
    )


# =============================================================================
# GITHUB TOOLS
# =============================================================================

GITHUB_MODULE = "app.agents.tools.integrations.github_tool"


class TestGitHubGatherContext:
    """Tests for GitHub CUSTOM_GATHER_CONTEXT."""

    def _register(self) -> Dict[str, Callable[..., Any]]:
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
# HUBSPOT TOOLS
# =============================================================================

HUBSPOT_MODULE = "app.agents.tools.integrations.hubspot_tool"


class TestHubSpotGatherContext:
    """Tests for HubSpot CUSTOM_GATHER_CONTEXT."""

    def _register(self) -> Dict[str, Callable[..., Any]]:
        composio, captured = _make_capturing_composio()
        from app.agents.tools.integrations.hubspot_tool import (
            register_hubspot_custom_tools,
        )

        names = register_hubspot_custom_tools(composio)
        assert "HUBSPOT_CUSTOM_GATHER_CONTEXT" in names
        return captured

    @patch(f"{HUBSPOT_MODULE}.httpx")
    def test_basic_success(self, mock_httpx: MagicMock) -> None:
        """Returns contacts and deals from HubSpot API."""
        mock_httpx.get.side_effect = [
            _ok_response(
                {
                    "results": [
                        {
                            "id": "c1",
                            "properties": {
                                "firstname": "John",
                                "lastname": "Doe",
                                "email": "john@test.com",
                                "hs_lead_status": "NEW",
                            },
                        }
                    ]
                }
            ),
            _ok_response(
                {
                    "results": [
                        {
                            "id": "d1",
                            "properties": {
                                "dealname": "Big Deal",
                                "amount": "5000",
                                "dealstage": "closedwon",
                                "closedate": "2025-01-01",
                            },
                        }
                    ]
                }
            ),
        ]

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_TOKEN)

        assert result["contact_count"] == 1
        assert result["deal_count"] == 1
        assert result["recent_contacts"][0]["firstname"] == "John"
        assert result["recent_deals"][0]["dealname"] == "Big Deal"

    @patch(f"{HUBSPOT_MODULE}.httpx")
    def test_missing_token(self, mock_httpx: MagicMock) -> None:
        """Raises ValueError when access_token is missing."""
        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        with pytest.raises(ValueError, match="Missing access_token"):
            fn(GatherContextInput(), EXECUTE_REQUEST, {})

    @patch(f"{HUBSPOT_MODULE}.httpx")
    def test_contacts_fetch_fails(self, mock_httpx: MagicMock) -> None:
        """Contacts failure returns empty list, deals still work."""
        mock_httpx.get.side_effect = [
            Exception("contacts error"),
            _ok_response({"results": []}),
        ]

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_TOKEN)

        assert result["recent_contacts"] == []
        assert result["contact_count"] == 0

    @patch(f"{HUBSPOT_MODULE}.httpx")
    def test_deals_fetch_fails(self, mock_httpx: MagicMock) -> None:
        """Deals failure returns empty list, contacts still work."""
        mock_httpx.get.side_effect = [
            _ok_response({"results": []}),
            Exception("deals error"),
        ]

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_TOKEN)

        assert result["recent_deals"] == []
        assert result["deal_count"] == 0


# =============================================================================
# AIRTABLE TOOLS
# =============================================================================

AIRTABLE_MODULE = "app.agents.tools.integrations.airtable_tool"


class TestAirtableGatherContext:
    """Tests for Airtable CUSTOM_GATHER_CONTEXT."""

    def _register(self) -> Dict[str, Callable[..., Any]]:
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
# GOOGLE MEET TOOLS
# =============================================================================

GOOGLE_MEET_MODULE = "app.agents.tools.integrations.google_meet_tool"


class TestGoogleMeetGatherContext:
    """Tests for Google Meet CUSTOM_GATHER_CONTEXT."""

    def _register(self) -> Dict[str, Callable[..., Any]]:
        composio, captured = _make_capturing_composio()
        from app.agents.tools.integrations.google_meet_tool import (
            register_google_meet_custom_tools,
        )

        names = register_google_meet_custom_tools(composio)
        assert "GOOGLEMEET_CUSTOM_GATHER_CONTEXT" in names
        return captured

    @patch(f"{GOOGLE_MEET_MODULE}._http_client")
    def test_basic_success(self, mock_client: MagicMock) -> None:
        """Returns user info and upcoming meets."""
        mock_client.get.side_effect = [
            _ok_response(
                {"email": "user@test.com", "name": "Test User", "picture": "pic.jpg"}
            ),
            _ok_response(
                {
                    "items": [
                        {
                            "id": "ev1",
                            "summary": "Team Standup",
                            "start": {"dateTime": "2025-01-01T10:00:00Z"},
                            "conferenceData": {
                                "entryPoints": [
                                    {
                                        "entryPointType": "video",
                                        "uri": "https://meet.google.com/abc",
                                    }
                                ]
                            },
                        },
                        {
                            "id": "ev2",
                            "summary": "No Meet Link",
                            "start": {"date": "2025-01-01"},
                        },
                    ]
                }
            ),
        ]

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_TOKEN)

        assert result["user"]["email"] == "user@test.com"
        assert result["upcoming_meet_count"] == 1
        assert result["upcoming_meets"][0]["meet_link"] == "https://meet.google.com/abc"

    @patch(f"{GOOGLE_MEET_MODULE}._http_client")
    def test_missing_token(self, mock_client: MagicMock) -> None:
        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        with pytest.raises(ValueError, match="Missing access_token"):
            fn(GatherContextInput(), EXECUTE_REQUEST, {})

    @patch(f"{GOOGLE_MEET_MODULE}._http_client")
    def test_events_non_200(self, mock_client: MagicMock) -> None:
        """Non-200 events response returns empty meets list."""
        mock_client.get.side_effect = [
            _ok_response({"email": "user@test.com", "name": "User"}),
            _ok_response({}, status_code=403),
        ]

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_TOKEN)

        assert result["upcoming_meets"] == []
        assert result["upcoming_meet_count"] == 0

    @patch(f"{GOOGLE_MEET_MODULE}._http_client")
    def test_event_with_no_video_entry_point(self, mock_client: MagicMock) -> None:
        """Event with conferenceData but no video entry point gets meet_link=None."""
        mock_client.get.side_effect = [
            _ok_response({"email": "u@test.com"}),
            _ok_response(
                {
                    "items": [
                        {
                            "id": "ev1",
                            "summary": "Phone call",
                            "start": {"dateTime": "2025-01-01T10:00:00Z"},
                            "conferenceData": {
                                "entryPoints": [
                                    {"entryPointType": "phone", "uri": "tel:+123"}
                                ]
                            },
                        }
                    ]
                }
            ),
        ]

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_TOKEN)

        assert result["upcoming_meet_count"] == 1
        assert result["upcoming_meets"][0]["meet_link"] is None


# =============================================================================
# GOOGLE MAPS TOOLS
# =============================================================================

GOOGLE_MAPS_MODULE = "app.agents.tools.integrations.google_maps_tool"


class TestGoogleMapsGatherContext:
    """Tests for Google Maps CUSTOM_GATHER_CONTEXT."""

    def _register(self) -> Dict[str, Callable[..., Any]]:
        composio, captured = _make_capturing_composio()
        from app.agents.tools.integrations.google_maps_tool import (
            register_google_maps_custom_tools,
        )

        names = register_google_maps_custom_tools(composio)
        assert "GOOGLE_MAPS_CUSTOM_GATHER_CONTEXT" in names
        return captured

    @patch(f"{GOOGLE_MAPS_MODULE}._http_client")
    def test_connected_with_token(self, mock_client: MagicMock) -> None:
        """API returns OK status with access_token."""
        mock_client.get.return_value = _ok_response({"status": "OK"})

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_TOKEN)

        assert result["api_connected"] is True
        assert result["status"] == "OK"
        assert "geocoding" in result["available_services"]

    @patch(f"{GOOGLE_MAPS_MODULE}._http_client")
    def test_connected_with_api_key(self, mock_client: MagicMock) -> None:
        """API returns OK status with api_key."""
        mock_client.get.return_value = _ok_response({"status": "OK"})

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(
            GatherContextInput(),
            EXECUTE_REQUEST,
            {"api_key": "test-key"},  # pragma: allowlist secret
        )

        assert result["api_connected"] is True

    @patch(f"{GOOGLE_MAPS_MODULE}._http_client")
    def test_missing_both_auth(self, mock_client: MagicMock) -> None:
        """Raises ValueError when both token and api_key are missing."""
        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        with pytest.raises(ValueError, match="Missing access_token or api_key"):
            fn(GatherContextInput(), EXECUTE_REQUEST, {})

    @patch(f"{GOOGLE_MAPS_MODULE}._http_client")
    def test_api_denied(self, mock_client: MagicMock) -> None:
        """REQUEST_DENIED status results in api_connected=False."""
        mock_client.get.return_value = _ok_response({"status": "REQUEST_DENIED"})

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_TOKEN)

        assert result["api_connected"] is False
        assert result["status"] == "REQUEST_DENIED"

    @patch(f"{GOOGLE_MAPS_MODULE}._http_client")
    def test_api_non_200(self, mock_client: MagicMock) -> None:
        """Non-200 response results in api_connected=False."""
        mock_client.get.return_value = _ok_response({}, status_code=500)

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_TOKEN)

        assert result["api_connected"] is False


# =============================================================================
# SLACK TOOLS
# =============================================================================

SLACK_MODULE = "app.agents.tools.integrations.slack_tool"


class TestSlackGatherContext:
    """Tests for Slack CUSTOM_GATHER_CONTEXT."""

    def _register(self) -> Dict[str, Callable[..., Any]]:
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
# REDDIT TOOLS
# =============================================================================

REDDIT_MODULE = "app.agents.tools.integrations.reddit_tool"


class TestRedditGatherContext:
    """Tests for Reddit CUSTOM_GATHER_CONTEXT."""

    def _register(self) -> Dict[str, Callable[..., Any]]:
        composio, captured = _make_capturing_composio()
        from app.agents.tools.integrations.reddit_tool import (
            register_reddit_custom_tools,
        )

        names = register_reddit_custom_tools(composio)
        assert "REDDIT_CUSTOM_GATHER_CONTEXT" in names
        return captured

    @patch(f"{REDDIT_MODULE}._http_client")
    def test_basic_success(self, mock_client: MagicMock) -> None:
        """Returns user profile, subreddits, and unread messages."""
        mock_client.get.side_effect = [
            _ok_response(
                {
                    "name": "testuser",
                    "id": "u1",
                    "link_karma": 100,
                    "comment_karma": 200,
                    "total_karma": 300,
                    "icon_img": "https://img.jpg",
                    "is_gold": False,
                }
            ),
            _ok_response(
                {
                    "data": {
                        "children": [
                            {
                                "data": {
                                    "display_name": "python",
                                    "title": "Python",
                                    "subscribers": 1000000,
                                }
                            }
                        ]
                    }
                }
            ),
            _ok_response(
                {
                    "data": {
                        "children": [
                            {
                                "data": {
                                    "id": "m1",
                                    "subject": "New reply",
                                    "author": "someone",
                                    "created_utc": 1700000000,
                                }
                            }
                        ]
                    }
                }
            ),
        ]

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_TOKEN)

        assert result["user"]["name"] == "testuser"
        assert result["user"]["total_karma"] == 300
        assert len(result["subscribed_subreddits"]) == 1
        assert result["subscribed_subreddits"][0]["name"] == "python"
        assert len(result["unread_messages"]) == 1
        assert result["unread_message_count"] == 1

    @patch(f"{REDDIT_MODULE}._http_client")
    def test_missing_token(self, mock_client: MagicMock) -> None:
        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        with pytest.raises(ValueError, match="Missing access_token"):
            fn(GatherContextInput(), EXECUTE_REQUEST, {})

    @patch(f"{REDDIT_MODULE}._http_client")
    def test_subreddits_non_200(self, mock_client: MagicMock) -> None:
        """Non-200 subreddits response returns empty list."""
        mock_client.get.side_effect = [
            _ok_response({"name": "user"}),
            _ok_response({}, status_code=403),
            _ok_response({"data": {"children": []}}),
        ]

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_TOKEN)

        assert result["subscribed_subreddits"] == []

    @patch(f"{REDDIT_MODULE}._http_client")
    def test_messages_non_200(self, mock_client: MagicMock) -> None:
        """Non-200 messages response returns empty list."""
        mock_client.get.side_effect = [
            _ok_response({"name": "user"}),
            _ok_response({"data": {"children": []}}),
            _ok_response({}, status_code=500),
        ]

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_TOKEN)

        assert result["unread_messages"] == []
        assert result["unread_message_count"] == 0


# =============================================================================
# INSTAGRAM TOOLS
# =============================================================================

INSTAGRAM_MODULE = "app.agents.tools.integrations.instagram_tool"


class TestInstagramGatherContext:
    """Tests for Instagram CUSTOM_GATHER_CONTEXT."""

    def _register(self) -> Dict[str, Callable[..., Any]]:
        composio, captured = _make_capturing_composio()
        from app.agents.tools.integrations.instagram_tool import (
            register_instagram_custom_tools,
        )

        names = register_instagram_custom_tools(composio)
        assert "INSTAGRAM_CUSTOM_GATHER_CONTEXT" in names
        return captured

    @patch(f"{INSTAGRAM_MODULE}._http_client")
    def test_basic_success(self, mock_client: MagicMock) -> None:
        """Returns user profile and recent media."""
        mock_client.get.side_effect = [
            _ok_response(
                {
                    "id": "ig1",
                    "name": "Test User",
                    "username": "testuser",
                    "account_type": "PERSONAL",
                    "media_count": 50,
                    "followers_count": 1000,
                    "follows_count": 500,
                    "biography": "Hello world",
                }
            ),
            _ok_response(
                {
                    "data": [
                        {
                            "id": "m1",
                            "caption": "Nice photo",
                            "media_type": "IMAGE",
                            "timestamp": "2025-01-01T00:00:00Z",
                            "like_count": 42,
                            "comments_count": 5,
                            "permalink": "https://instagram.com/p/abc",
                        }
                    ]
                }
            ),
        ]

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_TOKEN)

        assert result["user"]["username"] == "testuser"
        assert result["user"]["followers"] == 1000
        assert len(result["recent_media"]) == 1
        assert result["recent_media"][0]["likes"] == 42

    @patch(f"{INSTAGRAM_MODULE}._http_client")
    def test_missing_token(self, mock_client: MagicMock) -> None:
        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        with pytest.raises(ValueError, match="Missing access_token"):
            fn(GatherContextInput(), EXECUTE_REQUEST, {})

    @patch(f"{INSTAGRAM_MODULE}._http_client")
    def test_media_non_200(self, mock_client: MagicMock) -> None:
        """Non-200 media response returns empty list."""
        mock_client.get.side_effect = [
            _ok_response({"id": "ig1", "username": "user"}),
            _ok_response({}, status_code=400),
        ]

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_TOKEN)

        assert result["recent_media"] == []

    @patch(f"{INSTAGRAM_MODULE}._http_client")
    def test_none_caption_and_biography(self, mock_client: MagicMock) -> None:
        """None caption and biography are handled gracefully."""
        mock_client.get.side_effect = [
            _ok_response({"id": "ig1", "biography": None}),
            _ok_response(
                {
                    "data": [{"id": "m1", "caption": None, "media_type": "IMAGE"}],
                }
            ),
        ]

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_TOKEN)

        assert result["user"]["biography"] == ""
        assert result["recent_media"][0]["caption"] == ""


# =============================================================================
# TODOIST TOOLS
# =============================================================================

TODOIST_MODULE = "app.agents.tools.integrations.todoist_tool"


class TestTodoistGatherContext:
    """Tests for Todoist CUSTOM_GATHER_CONTEXT."""

    def _register(self) -> Dict[str, Callable[..., Any]]:
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
        mock_exec.return_value = [
            {"id": "1", "content": "Task", "due": {"date": "2000-01-01"}}
        ]

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

    def _register(self) -> Dict[str, Callable[..., Any]]:
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

    def _register(self) -> Dict[str, Callable[..., Any]]:
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

    def _register(self) -> Dict[str, Callable[..., Any]]:
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

    def _register(self) -> Dict[str, Callable[..., Any]]:
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
    def test_missing_user_id(self, mock_exec: MagicMock) -> None:
        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        with pytest.raises(ValueError, match="Missing user_id"):
            fn(GatherContextInput(), EXECUTE_REQUEST, {})


# =============================================================================
# MICROSOFT TEAMS TOOLS
# =============================================================================

TEAMS_MODULE = "app.agents.tools.integrations.microsoft_teams_tool"


class TestMicrosoftTeamsGatherContext:
    """Tests for Microsoft Teams CUSTOM_GATHER_CONTEXT."""

    def _register(self) -> Dict[str, Callable[..., Any]]:
        composio, captured = _make_capturing_composio()
        from app.agents.tools.integrations.microsoft_teams_tool import (
            register_microsoft_teams_custom_tools,
        )

        names = register_microsoft_teams_custom_tools(composio)
        assert "MICROSOFT_TEAMS_CUSTOM_GATHER_CONTEXT" in names
        return captured

    @patch(f"{TEAMS_MODULE}.httpx")
    def test_basic_success(self, mock_httpx: MagicMock) -> None:
        """Returns user, teams, and chats."""
        mock_httpx.get.side_effect = [
            _ok_response(
                {
                    "id": "u1",
                    "displayName": "Test User",
                    "mail": "test@corp.com",
                }
            ),
            _ok_response(
                {
                    "value": [
                        {
                            "id": "t1",
                            "displayName": "Engineering",
                            "description": "Eng team",
                        }
                    ]
                }
            ),
            _ok_response(
                {
                    "value": [
                        {
                            "id": "ch1",
                            "topic": "General",
                            "chatType": "group",
                            "lastMessagePreview": {
                                "body": {"content": "Hello everyone"},
                                "isRead": False,
                            },
                        },
                        {
                            "id": "ch2",
                            "topic": "DM",
                            "chatType": "oneOnOne",
                            "lastMessagePreview": {
                                "body": {"content": "Hi"},
                                "isRead": True,
                            },
                        },
                    ]
                }
            ),
        ]

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_TOKEN)

        assert result["user"]["display_name"] == "Test User"
        assert result["team_count"] == 1
        assert result["chat_count"] == 2
        assert result["unread_chat_count"] == 1
        assert result["recent_chats"][0]["is_read"] is False
        assert result["recent_chats"][1]["is_read"] is True

    @patch(f"{TEAMS_MODULE}.httpx")
    def test_missing_token(self, mock_httpx: MagicMock) -> None:
        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        with pytest.raises(ValueError, match="Missing access_token"):
            fn(GatherContextInput(), EXECUTE_REQUEST, {})

    @patch(f"{TEAMS_MODULE}.httpx")
    def test_me_fetch_fails(self, mock_httpx: MagicMock) -> None:
        """User info failure returns empty dict, rest still works."""
        mock_httpx.get.side_effect = [
            Exception("auth error"),
            _ok_response({"value": []}),
            _ok_response({"value": []}),
        ]

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_TOKEN)

        assert result["user"] == {}
        assert result["teams"] == []

    @patch(f"{TEAMS_MODULE}.httpx")
    def test_teams_fetch_fails(self, mock_httpx: MagicMock) -> None:
        """Teams fetch failure returns empty list."""
        mock_httpx.get.side_effect = [
            _ok_response({"id": "u1", "displayName": "User"}),
            Exception("teams error"),
            _ok_response({"value": []}),
        ]

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_TOKEN)

        assert result["teams"] == []
        assert result["team_count"] == 0

    @patch(f"{TEAMS_MODULE}.httpx")
    def test_chats_fetch_fails(self, mock_httpx: MagicMock) -> None:
        """Chats fetch failure returns empty list."""
        mock_httpx.get.side_effect = [
            _ok_response({"id": "u1", "displayName": "User"}),
            _ok_response({"value": []}),
            Exception("chats error"),
        ]

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_TOKEN)

        assert result["recent_chats"] == []
        assert result["chat_count"] == 0
        assert result["unread_chat_count"] == 0

    @patch(f"{TEAMS_MODULE}.httpx")
    def test_chat_without_message_preview(self, mock_httpx: MagicMock) -> None:
        """Chat without lastMessagePreview is handled gracefully."""
        mock_httpx.get.side_effect = [
            _ok_response({"id": "u1", "displayName": "User"}),
            _ok_response({"value": []}),
            _ok_response(
                {
                    "value": [
                        {
                            "id": "ch1",
                            "topic": "Empty",
                            "chatType": "group",
                        },
                    ]
                }
            ),
        ]

        captured = self._register()
        fn = captured["CUSTOM_GATHER_CONTEXT"]
        result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS_TOKEN)

        assert result["recent_chats"][0]["last_message_preview"] is None
        assert result["recent_chats"][0]["is_read"] is True
        assert result["unread_chat_count"] == 0


# =============================================================================
# URGENCY AGGREGATOR TOOL
# =============================================================================

URGENCY_MODULE = "app.agents.tools.integrations.urgency_tool"


class TestUrgencyAggregator:
    """Tests for CUSTOM_URGENCY_AGGREGATOR."""

    def _register(self) -> Dict[str, Callable[..., Any]]:
        composio, captured = _make_capturing_composio()
        from app.agents.tools.integrations.urgency_tool import (
            register_urgency_custom_tools,
        )

        names = register_urgency_custom_tools(composio)
        assert "GAIA_CUSTOM_URGENCY_AGGREGATOR" in names
        return captured

    def _make_input(self, snapshots: Dict[str, Any]) -> Any:
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
        items = [
            i for i in result["urgent_items"] if i["integration"] == "googlecalendar"
        ]
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
        items = [
            i for i in result["urgent_items"] if i["integration"] == "googlecalendar"
        ]
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
        items = [
            i for i in result["urgent_items"] if i["integration"] == "microsoft_teams"
        ]
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
        items = [
            i for i in result["urgent_items"] if i["integration"] == "microsoft_teams"
        ]
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
                    "linear": {
                        "overdue_issues": [{"title": "a"}, {"title": "b"}]
                    },  # high, count=2
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

    def test_non_dict_snapshot_skipped(self) -> None:
        """Non-dict snapshots are skipped."""
        captured = self._register()
        fn = captured["CUSTOM_URGENCY_AGGREGATOR"]

        result = fn(
            self._make_input(
                {
                    "broken": "not a dict",
                    "also_broken": 123,
                }
            ),
            EXECUTE_REQUEST,
            {},
        )
        assert result["total_urgent"] == 0

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
