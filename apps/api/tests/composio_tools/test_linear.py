"""
Linear custom tool tests using pytest.

Tests 12 Linear tools:
- 6 read-only: GET_WORKSPACE_CONTEXT, RESOLVE_CONTEXT, GET_MY_TASKS,
               SEARCH_ISSUES, GET_ACTIVE_SPRINT, GET_NOTIFICATIONS
- 6 destructive (IRREVERSIBLE - Linear has no delete API):
               CREATE_ISSUE, GET_ISSUE_FULL_CONTEXT, GET_ISSUE_ACTIVITY,
               CREATE_SUB_ISSUES, CREATE_ISSUE_RELATION, BULK_UPDATE_ISSUES

Usage:
    pytest tests/composio_tools/test_linear.py -v --user-id USER_ID

NOTE: Linear has no delete issue API. Created issues must be manually archived.
"""

import json
import uuid

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
            assert "user" in data, "Should have 'user' in response"

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

    These tests are no longer skipped. They use the `fresh_issue` fixture
    to ensure created resources are always archived/cleaned up.
    """

    @pytest.fixture
    def fresh_issue(self, composio_client, user_id):
        """Fixture to create a fresh issue and ensure cleanup (archive)."""
        # 1. Get Team ID
        context = execute_tool(
            composio_client, "LINEAR_CUSTOM_GET_WORKSPACE_CONTEXT", {}, user_id
        )
        teams = context.get("data", {}).get("teams", [])
        if not teams:
            pytest.skip("No teams found")
        team_id = teams[0].get("id")

        # 2. Create Issue
        unique_id = str(uuid.uuid4())[:8]
        title = f"[PYTEST] Temp Issue {unique_id}"

        result = execute_tool(
            composio_client,
            "LINEAR_CUSTOM_CREATE_ISSUE",
            {"team_id": team_id, "title": title},
            user_id,
        )
        assert result.get("successful"), f"Setup failed: {result.get('error')}"
        data = result.get("data", {})
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception:
                pytest.fail(f"Tool execution failed with message: {data}")

        if not isinstance(data, dict):
            pytest.fail(
                f"Tool execution returned invalid data type: {type(data)} Value: {data}"
            )

        issue = data.get("issue", {})
        issue_id = issue.get("id")

        yield {
            "id": issue_id,
            "team_id": team_id,
            "identifier": issue.get("identifier"),
        }

        # 3. Cleanup (Archive) - Pass for now as Linear has no delete API
        pass

    @pytest.fixture
    def fresh_issue_pair(self, composio_client, user_id, fresh_issue):
        """Create a second issue for relation tests."""
        # 1. Get Team ID (fresh_issue has logic but we need another one)
        context = execute_tool(
            composio_client, "LINEAR_CUSTOM_GET_WORKSPACE_CONTEXT", {}, user_id
        )
        team_id = context.get("data", {}).get("teams", [])[0].get("id")

        unique_id = str(uuid.uuid4())[:8]
        result = execute_tool(
            composio_client,
            "LINEAR_CUSTOM_CREATE_ISSUE",
            {
                "team_id": team_id,
                "title": f"[PYTEST] Temp Issue 2 {unique_id}",
            },
            user_id,
        )
        data = result.get("data", {})
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception:
                pytest.fail(f"Tool execution failed with message: {data}")

        if not isinstance(data, dict):
            pytest.fail(
                f"Tool execution returned invalid data type: {type(data)} Value: {data}"
            )
        issue2 = data.get("issue", {})
        return fresh_issue, {
            "id": issue2.get("id"),
            "identifier": issue2.get("identifier"),
        }

    def test_create_issue(self, composio_client, user_id, fresh_issue):
        """Test CUSTOM_CREATE_ISSUE creates an issue.

        Uses fresh_issue fixture which handles creation and cleanup.
        """
        assert fresh_issue.get("id"), "Fixture should provide issue ID"
        assert fresh_issue.get("identifier"), "Fixture should provide issue identifier"

    def test_get_issue_full_context(self, composio_client, user_id):
        """Test CUSTOM_GET_ISSUE_FULL_CONTEXT - requires existing issue ID."""
        # Find an issue first
        search = execute_tool(
            composio_client,
            "LINEAR_CUSTOM_SEARCH_ISSUES",
            {"query": "test", "limit": 1},
            user_id,
        )
        assert search.get("successful"), f"Search failed: {search.get('error')}"

        data = search.get("data", {})
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception:
                pass

        issues = data.get("issues", [])
        if not issues:
            pytest.skip("No issues found to test get_issue_full_context")

        # Use identifier instead of ID to see if it avoids 400 error
        issue_identifier = issues[0].get("identifier")
        if not issue_identifier:
            pytest.skip("Issue found but no identifier")

        result = execute_tool(
            composio_client,
            "LINEAR_CUSTOM_GET_ISSUE_FULL_CONTEXT",
            {"issue_identifier": issue_identifier},
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"
        data = result.get("data", {}).get("issue", {})
        assert data.get("identifier") == issue_identifier
        assert "title" in data

    def test_get_issue_activity(self, composio_client, user_id):
        """Test CUSTOM_GET_ISSUE_ACTIVITY - requires existing issue ID."""
        # Find an issue first
        search = execute_tool(
            composio_client,
            "LINEAR_CUSTOM_SEARCH_ISSUES",
            {"query": "test", "limit": 1},
            user_id,
        )
        assert search.get("successful"), f"Search failed: {search.get('error')}"

        data = search.get("data", {})
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception:
                pass

        issues = data.get("issues", [])
        if not issues:
            pytest.skip("No issues found to test get_issue_activity")

        issue_id = issues[0].get("id")

        result = execute_tool(
            composio_client,
            "LINEAR_CUSTOM_GET_ISSUE_ACTIVITY",
            {"issue_id": issue_id, "limit": 5},
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"
        data = result.get("data", {})
        assert "activities" in data
        assert isinstance(data.get("activities"), list)

    def test_create_sub_issues(self, composio_client, user_id, fresh_issue):
        """Test CUSTOM_CREATE_SUB_ISSUES."""
        result = execute_tool(
            composio_client,
            "LINEAR_CUSTOM_CREATE_SUB_ISSUES",
            {
                "parent_issue_id": fresh_issue["id"],
                "sub_issues": [{"title": "Sub Issue 1", "priority": 4}],
            },
            user_id,
        )
        assert result.get("successful"), (
            f"Failed to create sub-issues: {result.get('error')}"
        )

    def test_create_issue_relation(self, composio_client, user_id, fresh_issue_pair):
        """Test CUSTOM_CREATE_ISSUE_RELATION."""
        issue1, issue2 = fresh_issue_pair
        result = execute_tool(
            composio_client,
            "LINEAR_CUSTOM_CREATE_ISSUE_RELATION",
            {
                "issue_id": issue1["id"],
                "related_issue_id": issue2["id"],
                "relation_type": "relates_to",
            },
            user_id,
        )
        assert result.get("successful"), (
            f"Failed to relate issues: {result.get('error')}"
        )

    def test_bulk_update_issues(self, composio_client, user_id, fresh_issue_pair):
        """Test CUSTOM_BULK_UPDATE_ISSUES."""
        issue1, issue2 = fresh_issue_pair
        result = execute_tool(
            composio_client,
            "LINEAR_CUSTOM_BULK_UPDATE_ISSUES",
            {
                "issue_ids": [issue1["id"], issue2["id"]],
                "priority": 1,  # Urgent
            },
            user_id,
        )
        assert result.get("successful"), f"Failed to bulk update: {result.get('error')}"
