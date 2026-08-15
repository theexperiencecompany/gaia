"""Tests for the MCP proxy response schemas."""

from __future__ import annotations

from pydantic import ValidationError
import pytest

from app.schemas.mcp.responses import (
    MCPConnectionTestResponse,
    MCPProxyPromptsListResponse,
    MCPProxyResourceReadResponse,
    MCPProxyResourcesListResponse,
    MCPProxyResourceTemplatesListResponse,
    MCPProxyToolCallResponse,
)


class TestMCPConnectionTestResponse:
    @pytest.mark.parametrize(
        ("status", "kwargs", "expected"),
        [
            (
                "connected",
                {"tools_count": 3},
                {"tools_count": 3, "oauth_url": None, "error": None},
            ),
            (
                "requires_oauth",
                {"oauth_url": "https://oauth.example.com/start"},
                {
                    "tools_count": None,
                    "oauth_url": "https://oauth.example.com/start",
                    "error": None,
                },
            ),
            (
                "failed",
                {"error": "connection refused"},
                {"tools_count": None, "oauth_url": None, "error": "connection refused"},
            ),
        ],
    )
    def test_each_status_parses_with_its_own_payload(
        self, status: str, kwargs: dict, expected: dict
    ) -> None:
        response = MCPConnectionTestResponse(status=status, **kwargs)
        assert response.status == status
        assert response.tools_count == expected["tools_count"]
        assert response.oauth_url == expected["oauth_url"]
        assert response.error == expected["error"]

    def test_optional_fields_default_to_none(self) -> None:
        response = MCPConnectionTestResponse(status="connected")
        assert response.tools_count is None
        assert response.oauth_url is None
        assert response.error is None

    def test_unknown_status_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            MCPConnectionTestResponse(status="maybe")


class TestMCPProxyToolCallResponse:
    def test_full_payload_parses(self) -> None:
        response = MCPProxyToolCallResponse(content=[{"type": "text", "text": "ok"}], is_error=True)
        assert response.content == [{"type": "text", "text": "ok"}]
        assert response.is_error is True

    def test_is_error_defaults_to_false(self) -> None:
        assert MCPProxyToolCallResponse(content=[]).is_error is False

    def test_content_is_required(self) -> None:
        with pytest.raises(ValidationError):
            MCPProxyToolCallResponse()

    def test_content_elements_must_be_dicts(self) -> None:
        with pytest.raises(ValidationError):
            MCPProxyToolCallResponse(content=["not a dict"])


class TestListResponses:
    @pytest.mark.parametrize(
        ("model_cls", "field"),
        [
            (MCPProxyResourcesListResponse, "resources"),
            (MCPProxyResourceTemplatesListResponse, "resource_templates"),
            (MCPProxyPromptsListResponse, "prompts"),
        ],
    )
    def test_list_field_is_required(self, model_cls: type, field: str) -> None:
        with pytest.raises(ValidationError):
            model_cls()

    @pytest.mark.parametrize(
        ("model_cls", "field"),
        [
            (MCPProxyResourcesListResponse, "resources"),
            (MCPProxyResourceTemplatesListResponse, "resource_templates"),
            (MCPProxyPromptsListResponse, "prompts"),
        ],
    )
    def test_next_cursor_defaults_to_none(self, model_cls: type, field: str) -> None:
        response = model_cls(**{field: [{"name": "x"}]})
        assert response.next_cursor is None

    @pytest.mark.parametrize(
        ("model_cls", "field"),
        [
            (MCPProxyResourcesListResponse, "resources"),
            (MCPProxyResourceTemplatesListResponse, "resource_templates"),
            (MCPProxyPromptsListResponse, "prompts"),
        ],
    )
    def test_next_cursor_accepts_a_string(self, model_cls: type, field: str) -> None:
        response = model_cls(**{field: [{"name": "x"}], "next_cursor": "page2"})
        assert response.next_cursor == "page2"


class TestMCPProxyResourceReadResponse:
    def test_full_payload_parses(self) -> None:
        response = MCPProxyResourceReadResponse(
            contents=[{"uri": "file:///a.txt", "mimeType": "text/plain", "text": "hello"}]
        )
        assert response.contents[0]["uri"] == "file:///a.txt"

    def test_contents_is_required(self) -> None:
        with pytest.raises(ValidationError):
            MCPProxyResourceReadResponse()
