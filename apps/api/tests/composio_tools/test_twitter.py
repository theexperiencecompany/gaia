"""
Twitter custom tool tests using pytest.

Tests Twitter tools including destructive actions (Follow/Unfollow, Thread creation).
Requires manual confirmation for destructive tests.
Unfollow targets are read from config/env (TWITTER_UNFOLLOW_USERS).

Usage:
    pytest -s tests/composio_tools/test_twitter.py -v --user-id USER_ID
"""

import logging
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from pytest_check import check

from tests.composio_tools.config_utils import get_integration_config
from tests.composio_tools.conftest import execute_tool

logger = logging.getLogger(__name__)


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

    def test_unfollow_then_follow(self, composio_client, user_id, confirm_action):
        """
        Test consolidated flow: Unfollow -> Follow for configured users.
        Reads keys from TWITTER_UNFOLLOW_USERS env var / config.
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
                "No users configured for unfollow/follow test (set TWITTER_UNFOLLOW_USERS)"
            )

        confirm_action(f"About to UNFOLLOW then FOLLOW these users: {targets}")

        # 1. Unfollow First
        # Best effort unfollow - ignore if not followed
        try:
            execute_tool(
                composio_client,
                "TWITTER_CUSTOM_BATCH_UNFOLLOW",
                {"usernames": targets},
                user_id,
            )
        except Exception:
            # Ignore errors during preliminary cleanup
            pass

        # 2. Batch Follow
        result = execute_tool(
            composio_client,
            "TWITTER_CUSTOM_BATCH_FOLLOW",
            {"usernames": targets},
            user_id,
        )
        assert result.get("successful"), f"Follow failed: {result.get('error')}"

    def test_create_thread(self, composio_client, user_id, confirm_action):
        """Test CUSTOM_CREATE_THREAD creates a tweet thread and cleans it up."""

        confirm_action(
            "About to CREATE A LIVE THREAD on Twitter.\nNote: This test attempts to AUTO-DELETE the thread after verification."
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
        logger.info(f"\nThread created successfully: {thread_url}")

        # Cleanup
        ids_to_delete = []

        if "tweet_ids" in data and isinstance(data["tweet_ids"], list):
            ids_to_delete.extend(data["tweet_ids"])

        if ids_to_delete:
            # Delete in reverse order (newest first) to minimize potential threading issues
            for tid in reversed(ids_to_delete):
                cleanup = execute_tool(
                    composio_client,
                    "TWITTER_POST_DELETE_BY_POST_ID",
                    {"id": str(tid)},
                    user_id,
                )
                if not cleanup.get("successful"):
                    logger.warning(
                        f"⚠️ Failed to delete ID {tid}: {cleanup.get('error')}"
                    )
        else:
            logger.warning(
                f"⚠️ Could not identify tweet IDs. Please manually delete: {thread_url}"
            )
