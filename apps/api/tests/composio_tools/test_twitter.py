"""
Twitter custom tool tests using pytest.

Tests 5 Twitter tools:
- CUSTOM_SEARCH_USERS (read-only)
- CUSTOM_SCHEDULE_TWEET (creates draft only)
- CUSTOM_BATCH_FOLLOW (affects account)
- CUSTOM_BATCH_UNFOLLOW (cleanup)
- CUSTOM_CREATE_THREAD (IRREVERSIBLE - tweets can't be deleted via API)

Usage:
    pytest tests/composio_tools/test_twitter_pytest.py -v --user-id USER_ID

WARNING: Creating tweets affects your real Twitter account.
"""

from datetime import datetime, timedelta

import pytest
from pytest_check import check

from tests.composio_tools.conftest import execute_tool


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
    """Tests that affect real Twitter account - run manually."""

    @pytest.mark.skip(reason="Affects real account. Run manually.")
    def test_batch_follow(self, composio_client, user_id):
        """Test CUSTOM_BATCH_FOLLOW follows users.

        NOTE: This will actually follow users on your account.
        """
        # Test follows a specific user
        result = execute_tool(
            composio_client,
            "TWITTER_CUSTOM_BATCH_FOLLOW",
            {"usernames": ["testuser"]},  # Replace with real username
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"

    @pytest.mark.skip(reason="Depends on BATCH_FOLLOW. Run manually.")
    def test_batch_unfollow(self, composio_client, user_id):
        """Test CUSTOM_BATCH_UNFOLLOW unfollows users."""
        pytest.skip("Requires users to be followed first")

    @pytest.mark.skip(reason="IRREVERSIBLE: Tweets cannot be deleted via API.")
    def test_create_thread(self, composio_client, user_id):
        """Test CUSTOM_CREATE_THREAD creates a tweet thread.

        WARNING: Tweets CANNOT be deleted via this API.
        Must be manually deleted from Twitter website.
        """
        result = execute_tool(
            composio_client,
            "TWITTER_CUSTOM_CREATE_THREAD",
            {
                "tweets": [
                    "🧪 Test thread from pytest (1/2)",
                    "Second tweet in test thread (2/2)",
                ],
            },
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"
        data = result.get("data", {})
        assert data.get("thread_url"), "Should return thread_url"
