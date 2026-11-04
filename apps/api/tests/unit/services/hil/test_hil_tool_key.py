"""The one HIL tool key: overrides, never-auto rules and verdicts all store under it."""

import pytest

from app.services.hil.tool_key import (
    MCPToolIdentity,
    hil_tool_key,
    mcp_tool_identity,
    parse_hil_tool_key,
)

from .conftest import make_tool


@pytest.mark.unit
class TestHilToolKey:
    def test_a_registry_tool_keeps_its_bare_name(self) -> None:
        assert hil_tool_key("GMAIL_SEND_EMAIL", None) == "GMAIL_SEND_EMAIL"

    def test_an_mcp_tool_is_keyed_on_its_server_and_server_side_name(self) -> None:
        identity = MCPToolIdentity(integration_id="srv_a", server_name="delete_item")
        assert hil_tool_key("posthog_delete_item", identity) == "mcp:srv_a:delete_item"

    def test_a_scoped_key_parses_back_to_its_identity(self) -> None:
        assert parse_hil_tool_key("mcp:srv_a:ns:delete_item") == MCPToolIdentity(
            integration_id="srv_a", server_name="ns:delete_item"
        )

    def test_a_bare_key_parses_to_none(self) -> None:
        assert parse_hil_tool_key("GMAIL_SEND_EMAIL") is None


@pytest.mark.unit
class TestMcpToolIdentity:
    def test_reads_the_stamped_server_identity_not_the_gaia_name(self) -> None:
        tool = make_tool(
            name="posthog_delete_item",
            metadata={"integration_id": "srv_a", "mcp_server_name": "delete_item"},
        )
        assert mcp_tool_identity(tool) == MCPToolIdentity(
            integration_id="srv_a", server_name="delete_item"
        )

    @pytest.mark.parametrize("metadata", [None, {}, {"integration_id": ""}, {"other": "x"}])
    def test_a_non_mcp_tool_has_no_identity(self, metadata: dict[str, object] | None) -> None:
        assert mcp_tool_identity(make_tool(metadata=metadata)) is None

    def test_no_tool_has_no_identity(self) -> None:
        assert mcp_tool_identity(None) is None

    def test_an_mcp_tool_missing_its_server_name_fails_loudly(self) -> None:
        with pytest.raises(ValueError, match="mcp_server_name"):
            mcp_tool_identity(make_tool(metadata={"integration_id": "srv_a"}))
