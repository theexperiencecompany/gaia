"""The write/edit refusal for ``account/**`` paths.

The account files are read-only projections: an attempted edit must be answered
with the mutation tool that performs the change, and must never reach the
sandbox filesystem.
"""

from unittest.mock import patch

import pytest

from app.agents.tools.coding import edit_tool, write_tool

CONFIG = {"metadata": {"user_id": "user-1", "conversation_id": "conv-1"}}


@pytest.mark.unit
@pytest.mark.parametrize(
    ("path", "expected_tool"),
    [
        ("/workspace/account/preferences.json", "update_preferences"),
        ("/workspace/account/voices/selected.json", "set_selected_voice"),
    ],
)
async def test_write_to_an_account_file_refuses_and_never_touches_the_sandbox(
    path, expected_tool
) -> None:
    with (
        patch("app.agents.tools.coding.write_tool.acquire_sandbox") as sandbox,
        patch("app.agents.tools.coding.write_tool.log"),
    ):
        result = await write_tool.write.ainvoke(
            {"path": path, "content": "tampered"}, config=CONFIG
        )

    assert "read-only projection" in result
    # The refusal must name exactly the tool that owns this file — a wrong
    # pointer sends the agent (and the user) to the wrong action.
    assert expected_tool in result
    sandbox.assert_not_called()


async def test_edit_to_an_account_file_refuses_with_the_right_tool() -> None:
    with patch("app.agents.tools.coding.edit_tool.acquire_sandbox") as sandbox:
        result = await edit_tool.edit.ainvoke(
            {
                "path": "/workspace/account/custom-instructions.json",
                "old_string": "old",
                "new_string": "new",
            },
            config=CONFIG,
        )

    assert "update_custom_instructions" in result
    sandbox.assert_not_called()


@pytest.mark.unit
async def test_subscription_refusal_names_no_tool_because_none_exists() -> None:
    with (
        patch("app.agents.tools.coding.write_tool.acquire_sandbox") as sandbox,
        patch("app.agents.tools.coding.write_tool.log"),
    ):
        result = await write_tool.write.ainvoke(
            {"path": "/workspace/account/subscription.json", "content": "{}"},
            config=CONFIG,
        )

    assert "read-only" in result
    assert "update_" not in result and "set_selected_voice" not in result
    sandbox.assert_not_called()
