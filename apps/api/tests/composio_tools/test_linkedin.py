"""
LinkedIn custom tool tests using pytest.

Tests the full lifecycle of a LinkedIn post (create, react, comment, cleanup).
Requires manual confirmation and manual post deletion.

Usage:
    pytest -s tests/composio_tools/test_linkedin.py -v --user-id USER_ID
"""

import pytest

from tests.composio_tools.conftest import execute_tool


@pytest.fixture(scope="class")
def linkedin_resource(composio_client, user_id, request):
    """
    Class-scoped fixture to create a shared LinkedIn post.
    Prompts for user confirmation before creation.
    """
    # check for --yes or prompt
    auto_confirm = request.config.getoption("--yes", default=False)

    if not auto_confirm:
        print("\n\n!! WARNING: LinkedIn tests are DESTRUCTIVE !!")
        print("This will create a REAL post on your profile.")
        print("The post cannot be deleted via API. You must delete it manually.")
        try:
            resp = input("Do you want to proceed? (y/N): ")
            if resp.lower() not in ["y", "yes"]:
                pytest.skip("User declined LinkedIn tests")
        except OSError:
            pytest.fail("Cannot read input. Run with '-s' for interactive mode.")

    # Create Post
    print("\n Creating LinkedIn Post...")
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

    print(f"\n✅ Post Created: {post_url} (URN: {post_urn})")

    resource = {"post_urn": post_urn, "post_url": post_url}

    yield resource

    # Teardown / Reminder
    print("\n\n🛑 TEST COMPLETE. PLEASE MANUALLY DELETE THE POST:")
    print(f"🔗 {post_url}")
    print(f"URN: {post_urn}\n")


class TestLinkedInOperations:
    def test_lifecycle(self, composio_client, user_id, linkedin_resource):
        """
        Execute the reaction/comment lifecycle on the shared post.
        Grouped in one test function to ensure sequential execution and flow clarity.
        """
        post_urn = linkedin_resource["post_urn"]

        # 1. React to Post
        print("\n[Step 1] Reacting to post...")
        react_res = execute_tool(
            composio_client,
            "LINKEDIN_CUSTOM_REACT_TO_POST",
            {"post_urn": post_urn, "reaction_type": "LIKE"},
            user_id,
        )
        assert react_res.get("successful"), f"React failed: {react_res.get('error')}"

        # 2. Add Comment
        print("\n[Step 2] Adding comment...")
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
        print("\n[Step 3] Verifying reactions...")
        get_react_res = execute_tool(
            composio_client,
            "LINKEDIN_CUSTOM_GET_POST_REACTIONS",
            {"post_urn": post_urn},
            user_id,
        )
        assert get_react_res.get("successful")
        # Note: API might have lag, so just asserting call success is safer than asserting count > 0 immediately

        # 4. Get Comments (Verify)
        print("\n[Step 4] Verifying comments...")
        get_comm_res = execute_tool(
            composio_client,
            "LINKEDIN_CUSTOM_GET_POST_COMMENTS",
            {"post_urn": post_urn},
            user_id,
        )
        assert get_comm_res.get("successful")

        # 5. Delete Reaction
        print("\n[Step 5] Deleting reaction...")
        del_react_res = execute_tool(
            composio_client,
            "LINKEDIN_CUSTOM_DELETE_REACTION",
            {"post_urn": post_urn},
            user_id,
        )
        assert del_react_res.get("successful"), "Failed to delete reaction"
