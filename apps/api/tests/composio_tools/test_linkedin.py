"""
LinkedIn custom tool tests using pytest.

Tests 6 LinkedIn tools (ALL DESTRUCTIVE - posts can't be deleted via API):
- CUSTOM_CREATE_POST (IRREVERSIBLE)
- CUSTOM_ADD_COMMENT
- CUSTOM_REACT_TO_POST
- CUSTOM_DELETE_REACTION
- CUSTOM_GET_POST_COMMENTS (read-only, but needs post_urn)
- CUSTOM_GET_POST_REACTIONS (read-only, but needs post_urn)

Usage:
    pytest tests/composio_tools/test_linkedin_pytest.py -v --user-id USER_ID

WARNING: LinkedIn posts CANNOT be deleted via API. All tests are skipped by default.
"""

import pytest

from tests.composio_tools.conftest import execute_tool


class TestLinkedInOperations:
    """All LinkedIn tests are destructive - marked as skip by default.

    LinkedIn posts CANNOT be deleted via API.
    Run these tests only on test accounts or when you understand the consequences.
    """

    @pytest.mark.skip(reason="IRREVERSIBLE: LinkedIn posts cannot be deleted via API.")
    def test_create_post(self, composio_client, user_id):
        """Test CUSTOM_CREATE_POST creates a LinkedIn post.

        WARNING: This post CANNOT be deleted via API.
        Must be manually deleted from LinkedIn website.
        """
        result = execute_tool(
            composio_client,
            "LINKEDIN_CUSTOM_CREATE_POST",
            {
                "commentary": "🧪 Test post from pytest. Please ignore - will be deleted.",
                "visibility": "PUBLIC",
            },
            user_id,
        )

        assert result.get("successful"), f"API call failed: {result.get('error')}"
        data = result.get("data", {})
        assert data.get("post_id"), "Should return post_id"
        assert data.get("url"), "Should return post URL"

    @pytest.mark.skip(reason="Depends on CREATE_POST. Run manually.")
    def test_react_to_post(self, composio_client, user_id):
        """Test CUSTOM_REACT_TO_POST adds a reaction."""
        # Requires post_urn from create_post
        pytest.skip("Requires post_urn from create_post test")

    @pytest.mark.skip(reason="Depends on CREATE_POST. Run manually.")
    def test_get_post_reactions(self, composio_client, user_id):
        """Test CUSTOM_GET_POST_REACTIONS fetches reactions."""
        pytest.skip("Requires post_urn from create_post test")

    @pytest.mark.skip(reason="Depends on CREATE_POST. Run manually.")
    def test_add_comment(self, composio_client, user_id):
        """Test CUSTOM_ADD_COMMENT adds a comment to a post."""
        pytest.skip("Requires post_urn from create_post test")

    @pytest.mark.skip(reason="Depends on CREATE_POST. Run manually.")
    def test_get_post_comments(self, composio_client, user_id):
        """Test CUSTOM_GET_POST_COMMENTS fetches comments."""
        pytest.skip("Requires post_urn from create_post test")

    @pytest.mark.skip(reason="Depends on REACT_TO_POST. Run manually.")
    def test_delete_reaction(self, composio_client, user_id):
        """Test CUSTOM_DELETE_REACTION removes a reaction."""
        pytest.skip("Requires post_urn and existing reaction")
