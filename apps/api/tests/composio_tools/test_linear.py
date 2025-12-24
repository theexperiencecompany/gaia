"""
Linear custom tool tests using pytest.

Tests 12 Linear tools:
- 6 read-only: GET_WORKSPACE_CONTEXT, RESOLVE_CONTEXT, GET_MY_TASKS,
               SEARCH_ISSUES, GET_ACTIVE_SPRINT, GET_NOTIFICATIONS
- 6 destructive (IRREVERSIBLE - Linear has no delete API):
               CREATE_ISSUE, GET_ISSUE_FULL_CONTEXT, GET_ISSUE_ACTIVITY,
               CREATE_SUB_ISSUES, CREATE_ISSUE_RELATION, BULK_UPDATE_ISSUES

Usage:
    pytest tests/composio_tools/test_linear_pytest.py -v --user-id USER_ID

NOTE: Linear has no delete issue API. Created issues must be manually archived.
"""

import pytest
from pytest_check import check

from tests.composio_tools.conftest import execute_tool


class TestLinearReadOperations:
    """Tests for read-only Linear operations."""

    def test_get_workspace_context(self, composio_client, user_id):
        """Test CUSTOM_GET_WORKSPACE_CONTEXT returns workspace info."""
        result = execute_tool(
            composio_client,
            "LINEAR_CUSTOM_GET_WORKSPACE_CONTEXT",
            {},
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"
        data = result.get("data", {})

        # Validate structure
        with check:
            assert "teams" in data, "Should have 'teams' in response"
            assert isinstance(data.get("teams"), list), "teams should be a list"
            assert "users" in data, "Should have 'users' in response"

    def test_resolve_context(self, composio_client, user_id):
        """Test CUSTOM_RESOLVE_CONTEXT resolves fuzzy names to IDs."""
        result = execute_tool(
            composio_client,
            "LINEAR_CUSTOM_RESOLVE_CONTEXT",
            {"team_name": "eng"},  # Fuzzy match
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"
        data = result.get("data", {})
        assert data, "Expected response data"

    def test_get_my_tasks(self, composio_client, user_id):
        """Test CUSTOM_GET_MY_TASKS returns assigned issues."""
        result = execute_tool(
            composio_client,
            "LINEAR_CUSTOM_GET_MY_TASKS",
            {
                "filter": "all",
                "limit": 10,
                "include_completed": False,
            },
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"
        data = result.get("data", {})

        with check:
            assert "issues" in data or "tasks" in data, "Should have issues/tasks"

    def test_search_issues(self, composio_client, user_id):
        """Test CUSTOM_SEARCH_ISSUES searches for issues."""
        result = execute_tool(
            composio_client,
            "LINEAR_CUSTOM_SEARCH_ISSUES",
            {
                "query": "bug",
                "limit": 5,
            },
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"
        data = result.get("data", {})

        # Search may return empty results but should have structure
        assert isinstance(data, dict), "Expected dict response"

    def test_get_active_sprint(self, composio_client, user_id):
        """Test CUSTOM_GET_ACTIVE_SPRINT returns sprint info."""
        result = execute_tool(
            composio_client,
            "LINEAR_CUSTOM_GET_ACTIVE_SPRINT",
            {"issues_per_state_limit": 5},
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"
        data = result.get("data", {})
        assert isinstance(data, dict), "Expected dict response"

    def test_get_notifications(self, composio_client, user_id):
        """Test CUSTOM_GET_NOTIFICATIONS returns notifications."""
        result = execute_tool(
            composio_client,
            "LINEAR_CUSTOM_GET_NOTIFICATIONS",
            {
                "limit": 10,
                "include_read": False,
            },
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"
        data = result.get("data", {})

        with check:
            assert "notifications" in data, "Should have 'notifications' field"
            assert isinstance(data.get("notifications"), list), (
                "notifications should be a list"
            )


class TestLinearDestructiveOperations:
    """Tests for destructive operations - IRREVERSIBLE (Linear has no delete API).

    These tests are skipped by default. Run manually with extreme caution.
    Created issues CANNOT be deleted - only archived/closed manually.
    """

    @pytest.mark.skip(reason="IRREVERSIBLE: Linear has no delete API. Run manually.")
    def test_create_issue(self, composio_client, user_id):
        """Test CUSTOM_CREATE_ISSUE creates an issue.

        WARNING: This issue CANNOT be deleted via API.
        Must be manually archived after testing.
        """
        # First get a team ID
        context_result = execute_tool(
            composio_client,
            "LINEAR_CUSTOM_GET_WORKSPACE_CONTEXT",
            {},
            user_id,
        )
        teams = context_result.get("data", {}).get("teams", [])
        if not teams:
            pytest.skip("No teams found in workspace")

        team_id = teams[0].get("id")

        result = execute_tool(
            composio_client,
            "LINEAR_CUSTOM_CREATE_ISSUE",
            {
                "team_id": team_id,
                "title": "[TEST] Pytest Issue - Please Archive",
                "description": "Test issue created by pytest. Please archive after testing.",
                "priority": 4,  # Low priority
            },
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"
        data = result.get("data", {})

        issue = data.get("issue", {})
        assert issue.get("id"), "Created issue should have 'id'"
        assert issue.get("identifier"), "Created issue should have 'identifier'"

    @pytest.mark.skip(reason="Depends on CREATE_ISSUE. Run manually.")
    def test_get_issue_full_context(self, composio_client, user_id):
        """Test CUSTOM_GET_ISSUE_FULL_CONTEXT - requires existing issue ID."""
        # Requires issue_id from test_create_issue
        pytest.skip("Requires issue_id from create_issue test")

    @pytest.mark.skip(reason="Depends on CREATE_ISSUE. Run manually.")
    def test_get_issue_activity(self, composio_client, user_id):
        """Test CUSTOM_GET_ISSUE_ACTIVITY - requires existing issue ID."""
        pytest.skip("Requires issue_id from create_issue test")

    @pytest.mark.skip(reason="IRREVERSIBLE: Creates sub-issues. Run manually.")
    def test_create_sub_issues(self, composio_client, user_id):
        """Test CUSTOM_CREATE_SUB_ISSUES - creates sub-issues (irreversible)."""
        pytest.skip("Requires parent_issue_id from create_issue test")

    @pytest.mark.skip(reason="Modifies issues. Run manually.")
    def test_create_issue_relation(self, composio_client, user_id):
        """Test CUSTOM_CREATE_ISSUE_RELATION - creates relation between issues."""
        pytest.skip("Requires two issue IDs")

    @pytest.mark.skip(reason="Modifies issues. Run manually.")
    def test_bulk_update_issues(self, composio_client, user_id):
        """Test CUSTOM_BULK_UPDATE_ISSUES - bulk updates issues."""
        pytest.skip("Requires issue IDs")
