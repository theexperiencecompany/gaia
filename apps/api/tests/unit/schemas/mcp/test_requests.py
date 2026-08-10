"""Tests for the MCP proxy request schemas."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError
import pytest

from app.schemas.mcp.requests import (
    MCPProxyPromptsListRequest,
    MCPProxyResourceReadRequest,
    MCPProxyResourcesListRequest,
    MCPProxyResourceTemplatesListRequest,
    MCPProxyToolCallRequest,
)


class TestMCPProxyToolCallRequest:
    def test_full_payload_parses(self) -> None:
        request = MCPProxyToolCallRequest(
            server_url="https://mcp.example.com", tool_name="read", arguments={"path": "/a"}
        )
        assert request.server_url == "https://mcp.example.com"
        assert request.tool_name == "read"
        assert request.arguments == {"path": "/a"}

    def test_arguments_defaults_to_empty_dict(self) -> None:
        request = MCPProxyToolCallRequest(server_url="u", tool_name="t")
        assert request.arguments == {}

    def test_arguments_default_is_not_shared_across_instances(self) -> None:
        first = MCPProxyToolCallRequest(server_url="u", tool_name="t")
        second = MCPProxyToolCallRequest(server_url="u", tool_name="t")
        first.arguments["polluted"] = True
        assert second.arguments == {}

    def test_arguments_accepts_arbitrary_nested_values(self) -> None:
        arguments: dict[str, Any] = {
            "nested": {"list": [1, True, None, "x"]},
            "scalar": 3.5,
        }
        request = MCPProxyToolCallRequest(server_url="u", tool_name="t", arguments=arguments)
        assert request.arguments == arguments

    def test_server_url_is_required(self) -> None:
        with pytest.raises(ValidationError):
            MCPProxyToolCallRequest(tool_name="t")

    def test_tool_name_is_required(self) -> None:
        with pytest.raises(ValidationError):
            MCPProxyToolCallRequest(server_url="u")

    def test_arguments_must_be_a_dict(self) -> None:
        with pytest.raises(ValidationError):
            MCPProxyToolCallRequest(server_url="u", tool_name="t", arguments="nope")


class TestListRequests:
    @pytest.mark.parametrize(
        ("model_cls", "expected"),
        [
            (MCPProxyResourcesListRequest, "resources"),
            (MCPProxyResourceTemplatesListRequest, "resource_templates"),
            (MCPProxyPromptsListRequest, "prompts"),
        ],
    )
    def test_cursor_defaults_to_none(self, model_cls: type, expected: str) -> None:
        request = model_cls(server_url="u")
        assert request.server_url == "u"
        assert request.cursor is None

    @pytest.mark.parametrize(
        "model_cls",
        [
            MCPProxyResourcesListRequest,
            MCPProxyResourceTemplatesListRequest,
            MCPProxyPromptsListRequest,
        ],
    )
    def test_cursor_accepts_a_string(self, model_cls: type) -> None:
        request = model_cls(server_url="u", cursor="next_page")
        assert request.cursor == "next_page"

    @pytest.mark.parametrize(
        "model_cls",
        [
            MCPProxyResourcesListRequest,
            MCPProxyResourceTemplatesListRequest,
            MCPProxyPromptsListRequest,
        ],
    )
    def test_server_url_is_required(self, model_cls: type) -> None:
        with pytest.raises(ValidationError):
            model_cls()


class TestMCPProxyResourceReadRequest:
    def test_full_payload_parses(self) -> None:
        request = MCPProxyResourceReadRequest(server_url="u", uri="file:///a.txt")
        assert request.uri == "file:///a.txt"

    def test_server_url_is_required(self) -> None:
        with pytest.raises(ValidationError):
            MCPProxyResourceReadRequest(uri="file:///a.txt")

    def test_uri_is_required(self) -> None:
        with pytest.raises(ValidationError):
            MCPProxyResourceReadRequest(server_url="u")
