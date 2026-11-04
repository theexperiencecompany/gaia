"""Which stored MCP tool entries the restore rewrites back to the server's own name."""

import pytest
from scripts.restore_mcp_server_tool_names import restored_tools

from app.constants.mcp import MCP_RENAMED_TOOL_NOTE
from app.models.integration_models import StoredIntegrationTool


def _master_renamed(original: str, renamed: str, description: str) -> StoredIntegrationTool:
    """Build an entry as master stored it: the GAIA rename, its description led by the rename note."""
    return StoredIntegrationTool(
        name=renamed,
        description=MCP_RENAMED_TOOL_NOTE.format(original=original, renamed=renamed) + description,
    )


@pytest.mark.unit
class TestRestoredTools:
    def test_a_master_renamed_entry_gets_back_its_server_name_and_description(self) -> None:
        """Seen on this branch: master stored posthog_execute, so the gate key mcp:posthog:execute never matched."""
        restored = restored_tools(
            [
                _master_renamed("execute", "posthog_execute", "Run a HogQL query."),
                StoredIntegrationTool(name="query", description="Query events."),
            ]
        )

        assert restored == [
            StoredIntegrationTool(name="execute", description="Run a HogQL query."),
            StoredIntegrationTool(name="query", description="Query events."),
        ]

    def test_a_list_already_holding_server_names_needs_no_rewrite(self) -> None:
        assert restored_tools([StoredIntegrationTool(name="query", description="Q.")]) is None

    def test_a_note_naming_another_tool_is_left_alone(self) -> None:
        """Only a note that names this entry as the rename is master's; anything else is the server's own text."""
        note = MCP_RENAMED_TOOL_NOTE.format(original="execute", renamed="other_name")
        tool = StoredIntegrationTool(name="posthog_execute", description=note + "Run.")

        assert restored_tools([tool]) is None
