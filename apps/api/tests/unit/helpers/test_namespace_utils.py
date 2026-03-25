"""Tests for app.helpers.namespace_utils — ChromaDB namespace derivation."""

from unittest.mock import MagicMock, patch

import pytest

from app.helpers.namespace_utils import derive_integration_namespace


# ---------------------------------------------------------------------------
# derive_integration_namespace
# ---------------------------------------------------------------------------


class TestDeriveIntegrationNamespace:
    """Tests for derive_integration_namespace()."""

    # -- non-custom (platform) integrations ----------------------------------

    def test_platform_integration_returns_integration_id(self) -> None:
        """Platform (non-custom) integrations always return integration_id."""
        result = derive_integration_namespace("composio_gmail", is_custom=False)
        assert result == "composio_gmail"

    def test_platform_integration_ignores_server_url(self) -> None:
        """Even if server_url is provided, non-custom returns integration_id."""
        result = derive_integration_namespace(
            "composio_slack",
            server_url="https://api.slack.com/v1",
            is_custom=False,
        )
        assert result == "composio_slack"

    def test_platform_integration_default_is_custom_false(self) -> None:
        """Default is_custom=False means integration_id is returned."""
        result = derive_integration_namespace("my_integration")
        assert result == "my_integration"

    # -- custom integrations with server_url ---------------------------------

    @patch("app.helpers.namespace_utils.get_tool_namespace_from_url")
    def test_custom_with_url_delegates_to_namespace_from_url(
        self,
        mock_get_ns: MagicMock,
    ) -> None:
        mock_get_ns.return_value = "api.example.com/v1"
        result = derive_integration_namespace(
            "int_123",
            server_url="https://api.example.com/v1",
            is_custom=True,
        )
        assert result == "api.example.com/v1"
        mock_get_ns.assert_called_once_with(
            "https://api.example.com/v1",
            fallback="int_123",
        )

    @patch("app.helpers.namespace_utils.get_tool_namespace_from_url")
    def test_custom_url_fallback_used_on_bad_url(self, mock_get_ns: MagicMock) -> None:
        """If get_tool_namespace_from_url falls back, integration_id is returned."""
        mock_get_ns.return_value = "int_456"
        result = derive_integration_namespace(
            "int_456",
            server_url="not-a-valid-url",
            is_custom=True,
        )
        assert result == "int_456"
        mock_get_ns.assert_called_once_with("not-a-valid-url", fallback="int_456")

    @patch("app.helpers.namespace_utils.get_tool_namespace_from_url")
    def test_custom_with_different_urls_produce_different_namespaces(
        self,
        mock_get_ns: MagicMock,
    ) -> None:
        """Different URLs should yield different namespaces."""
        mock_get_ns.side_effect = lambda url, fallback: {
            "https://api.example.com/v1": "api.example.com/v1",
            "https://api.example.com/v2": "api.example.com/v2",
        }.get(url, fallback)

        ns1 = derive_integration_namespace(
            "int_1",
            server_url="https://api.example.com/v1",
            is_custom=True,
        )
        ns2 = derive_integration_namespace(
            "int_2",
            server_url="https://api.example.com/v2",
            is_custom=True,
        )
        assert ns1 != ns2
        assert ns1 == "api.example.com/v1"
        assert ns2 == "api.example.com/v2"

    # -- custom integrations without server_url ------------------------------

    def test_custom_without_url_returns_integration_id(self) -> None:
        """Custom integration with no server_url falls through to integration_id."""
        result = derive_integration_namespace(
            "int_789",
            server_url=None,
            is_custom=True,
        )
        assert result == "int_789"

    def test_custom_with_empty_string_url_returns_integration_id(self) -> None:
        """Empty string is falsy, so falls through to integration_id."""
        result = derive_integration_namespace(
            "int_abc",
            server_url="",
            is_custom=True,
        )
        assert result == "int_abc"

    # -- edge cases ----------------------------------------------------------

    def test_empty_integration_id(self) -> None:
        result = derive_integration_namespace("")
        assert result == ""

    @patch("app.helpers.namespace_utils.get_tool_namespace_from_url")
    def test_custom_with_url_and_empty_integration_id(
        self,
        mock_get_ns: MagicMock,
    ) -> None:
        mock_get_ns.return_value = "example.com"
        result = derive_integration_namespace(
            "",
            server_url="https://example.com",
            is_custom=True,
        )
        assert result == "example.com"
        mock_get_ns.assert_called_once_with("https://example.com", fallback="")

    @pytest.mark.parametrize(
        "integration_id",
        [
            "composio_gmail",
            "composio_slack",
            "custom_integration_123",
            "a",
            "very-long-integration-id-that-is-quite-descriptive",
        ],
        ids=["gmail", "slack", "custom", "single-char", "long-id"],
    )
    def test_platform_always_returns_id_parametrized(self, integration_id: str) -> None:
        assert derive_integration_namespace(integration_id) == integration_id

    @patch("app.helpers.namespace_utils.get_tool_namespace_from_url")
    def test_log_debug_called_for_custom(self, mock_get_ns: MagicMock) -> None:
        """Verify the debug log path is exercised (no assertion on log content)."""
        mock_get_ns.return_value = "mcp.example.com/tools"
        # Should not raise
        result = derive_integration_namespace(
            "int_log",
            server_url="https://mcp.example.com/tools",
            is_custom=True,
        )
        assert result == "mcp.example.com/tools"
