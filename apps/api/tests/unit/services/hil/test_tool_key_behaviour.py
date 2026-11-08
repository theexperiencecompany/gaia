"""Boundaries of the HIL tool key: which malformed shapes are rejected, and the message."""

import pytest

from app.services.hil.tool_key import (
    MCPToolIdentity,
    hil_tool_key,
    mcp_tool_identity,
    mcp_tool_key,
    parse_hil_tool_key,
)

from .conftest import make_tool


@pytest.mark.unit
class TestMcpToolIdentityBoundaries:
    @pytest.mark.parametrize("server_name", [None, "", 7])
    def test_an_integration_without_a_usable_server_name_raises(self, server_name: object) -> None:
        tool = make_tool(
            name="t",
            metadata={"integration_id": "srv_a", "mcp_server_name": server_name},
        )
        with pytest.raises(ValueError, match="MCP tool from srv_a carries no mcp_server_name"):
            mcp_tool_identity(tool)

    def test_a_non_empty_server_name_is_accepted_without_raising(self) -> None:
        tool = make_tool(name="t", metadata={"integration_id": "srv_a", "mcp_server_name": "x"})
        identity = mcp_tool_identity(tool)
        assert identity is not None
        assert (identity.integration_id, identity.server_name) == ("srv_a", "x")


@pytest.mark.unit
class TestParseHilToolKeyBoundaries:
    @pytest.mark.parametrize("key", ["mcp:", "mcp::name", "mcp:srv_a", "mcp:srv_a:"])
    def test_a_scoped_key_missing_either_part_is_rejected_with_the_key_in_the_message(
        self, key: str
    ) -> None:
        with pytest.raises(ValueError) as excinfo:
            parse_hil_tool_key(key)
        assert str(excinfo.value) == f"Malformed HIL tool key: {key}"


@pytest.mark.unit
class TestMcpToolKey:
    def test_the_key_names_the_server_then_the_name_on_it(self) -> None:
        identity = MCPToolIdentity(integration_id="srv_a", server_name="delete_item")
        assert mcp_tool_key(identity) == "mcp:srv_a:delete_item"

    def test_the_bare_name_never_enters_a_scoped_key(self) -> None:
        identity = MCPToolIdentity(integration_id="srv_a", server_name="delete_item")
        assert hil_tool_key("posthog_delete_item", identity) == "mcp:srv_a:delete_item"
        assert hil_tool_key("posthog_delete_item", None) == "posthog_delete_item"
