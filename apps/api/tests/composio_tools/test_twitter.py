"""
Twitter custom tool tests using pytest.

Tests Twitter tools including destructive actions (Follow/Unfollow, Thread creation).
Requires manual confirmation for destructive tests.
Unfollow targets are read from config/env (TWITTER_UNFOLLOW_USERS).

Usage:
    pytest -s tests/composio_tools/test_twitter.py -v --user-id USER_ID
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from pytest_check import check

from tests.composio_tools.config_utils import get_integration_config
from tests.composio_tools.conftest import execute_tool


# Mock get_stream_writer for tools that use LangGraph context
@pytest.fixture(autouse=True)
def mock_stream_writer():
    with patch("app.agents.tools.twitter_tool.get_stream_writer") as mock:
        mock.return_value = MagicMock()
        yield mock


class TestTwitterReadOperations:
    """Tests for read-only Twitter operations."""

    def test_search_users(self, composio_client, user_id):
        """Test CUSTOM_SEARCH_USERS returns matching users."""
        result = execute_tool(
            composio_client,
            "TWITTER_CUSTOM_SEARCH_USERS",
            {
                "query": "developer",
                "max_results": 5,
            },
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"
        data = result.get("data", {})

        with check:
            assert "users" in data, "Should have 'users' in response"
            assert isinstance(data.get("users"), list), "users should be a list"


class TestTwitterDraftOperations:
    """Tests that create drafts but don't post publicly."""

    def test_schedule_tweet(self, composio_client, user_id):
        """Test CUSTOM_SCHEDULE_TWEET creates a scheduled draft."""
        scheduled_time = (datetime.now() + timedelta(hours=24)).isoformat()

        result = execute_tool(
            composio_client,
            "TWITTER_CUSTOM_SCHEDULE_TWEET",
            {
                "text": "Test scheduled tweet from pytest - will be canceled",
                "scheduled_time": scheduled_time,
            },
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"
        data = result.get("data", {})
        assert data, "Expected response data"


class TestTwitterDestructiveOperations:
    """Tests that affect real Twitter account - requires confirmation."""

    def test_batch_follow(self, composio_client, user_id, confirm_action):
        """Test CUSTOM_BATCH_FOLLOW follows users."""
        target = "testuser"  # Placeholder
        confirm_action(f"About to FOLLOW user '{target}' on Twitter.")

        result = execute_tool(
            composio_client,
            "TWITTER_CUSTOM_BATCH_FOLLOW",
            {"usernames": [target]},
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"

        # Cleanup best effort
        try:
            execute_tool(
                composio_client,
                "TWITTER_CUSTOM_BATCH_UNFOLLOW",
                {"usernames": [target]},
                user_id,
            )
        except Exception:
            pass

    def test_batch_unfollow(self, composio_client, user_id, confirm_action):
        """
        Test CUSTOM_BATCH_UNFOLLOW unfollows users defined in config.
        Reads keys from TWITTER_UNFOLLOW_USERS env var.
        """
        # Load targets from config
        config = get_integration_config("twitter")
        users_raw = config.get("unfollow_users")

        targets = []
        if isinstance(users_raw, list):
            targets = users_raw
        elif isinstance(users_raw, str) and users_raw:
            # Handle comma-separated string from env var
            targets = [u.strip() for u in users_raw.split(",") if u.strip()]

        if not targets:
            pytest.skip(
                "No users configured for unfollow test (set TWITTER_UNFOLLOW_USERS)"
            )

        confirm_action(f"About to UNFOLLOW these users on Twitter: {targets}")

        result = execute_tool(
            composio_client,
            "TWITTER_CUSTOM_BATCH_UNFOLLOW",
            {"usernames": targets},
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"
        print(f"\nUnfollowed: {targets}")

    def test_create_thread(self, composio_client, user_id, confirm_action):
        """Test CUSTOM_CREATE_THREAD creates a tweet thread."""

        confirm_action(
            "About to CREATE A LIVE THREAD on Twitter.\nNote: You MUST delete this manually."
        )

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tweets = [
            f"🧪 Test thread created by @trygaia (1/2)\n\nAutomated QA test {timestamp}.",
            f"Second tweet in test thread (2/2)\n\nEnd of test {timestamp}.",
        ]

        result = execute_tool(
            composio_client,
            "TWITTER_CUSTOM_CREATE_THREAD",
            {"tweets": tweets},
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"
        data = result.get("data", {})
        thread_url = data.get("thread_url") or data.get("url")

        assert thread_url, "Should return thread_url"

        print("\n\n🛑 TEST COMPLETE. PLEASE MANUALLY DELETE THE THREAD:")
        print(f"🔗 {thread_url}\n")
