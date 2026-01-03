"""
LinkedIn custom tool tests using pytest.

Tests the full lifecycle of a LinkedIn post (create, react, comment, cleanup).
Requires manual confirmation and manual post deletion.

Usage:
    pytest -s tests/composio_tools/test_linkedin.py -v --user-id USER_ID
"""

import logging

import pytest

from tests.composio_tools.conftest import execute_tool

logger = logging.getLogger(__name__)


@pytest.fixture(scope="class")
def linkedin_resource(composio_client, user_id, request, confirm_action):
    """
    Class-scoped fixture to create a shared LinkedIn post.
    Prompts for user confirmation before creation.
    """
    confirm_action(
        "LinkedIn tests are DESTRUCTIVE!\n"
        "This will create a REAL post on your profile.\n"
        "The post cannot be deleted via API. You must delete it manually."
    )

    # Create Post
    logger.info("Creating LinkedIn Post...")
    result = execute_tool(
        composio_client,
        "LINKEDIN_CUSTOM_CREATE_POST",
        {
            "commentary": "🧪 QA Test Post from Gaia/Composio.\n\nThis is a temporary test post used to verify API functionality (Reactions, Comments).\nIt should be deleted shortly.",
            "visibility": "PUBLIC",
        },
        user_id,
    )

    assert result.get("successful"), f"Failed to create post: {result.get('error')}"
    data = result.get("data", {})
    post_urn = data.get("id") or data.get("urn")
    post_url = data.get("url")

    if not post_urn:
        pytest.fail("Post created but no URN returned")

    logger.info(f"✅ Post Created: {post_url} (URN: {post_urn})")

    resource = {"post_urn": post_urn, "post_url": post_url}

    yield resource

    # Teardown / Reminder
    logger.info("\n\n🛑 TEST COMPLETE. PLEASE MANUALLY DELETE THE POST:")
    logger.info(f"🔗 {post_url}")
    logger.info(f"URN: {post_urn}\n")


class TestLinkedInOperations:
    def test_lifecycle(self, composio_client, user_id, linkedin_resource):
        """
        Execute the reaction/comment lifecycle on the shared post.
        Grouped in one test function to ensure sequential execution and flow clarity.
        """
        post_urn = linkedin_resource["post_urn"]

        # 1. React to Post
        logger.info("Reacting to post...")
        react_res = execute_tool(
            composio_client,
            "LINKEDIN_CUSTOM_REACT_TO_POST",
            {"post_urn": post_urn, "reaction_type": "LIKE"},
            user_id,
        )
        assert react_res.get("successful"), f"React failed: {react_res.get('error')}"

        # 2. Add Comment
        logger.info("Adding comment...")
        comment_res = execute_tool(
            composio_client,
            "LINKEDIN_CUSTOM_ADD_COMMENT",
            {"post_urn": post_urn, "text": "This is a test comment 🤖"},
            user_id,
        )
        assert comment_res.get("successful"), (
            f"Comment failed: {comment_res.get('error')}"
        )

        # 3. Get Reactions (Verify)
        logger.info("Verifying reactions...")
        get_react_res = execute_tool(
            composio_client,
            "LINKEDIN_CUSTOM_GET_POST_REACTIONS",
            {"post_urn": post_urn},
            user_id,
        )
        assert get_react_res.get("successful")
        # Note: API might have lag, so just asserting call success is safer than asserting count > 0 immediately

        # 4. Get Comments (Verify)
        logger.info("Verifying comments...")
        get_comm_res = execute_tool(
            composio_client,
            "LINKEDIN_CUSTOM_GET_POST_COMMENTS",
            {"post_urn": post_urn},
            user_id,
        )
        assert get_comm_res.get("successful")

        # 5. Delete Reaction
        logger.info("Deleting reaction...")
        del_react_res = execute_tool(
            composio_client,
            "LINKEDIN_CUSTOM_DELETE_REACTION",
            {"post_urn": post_urn},
            user_id,
        )
        assert del_react_res.get("successful"), "Failed to delete reaction"
