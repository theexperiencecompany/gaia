"""Unit tests for the integration connection message builder."""

from unittest.mock import patch

import pytest

from app.utils.integration_checker import build_integration_connection_message

# ---------------------------------------------------------------------------
# build_integration_connection_message
# ---------------------------------------------------------------------------

_FAKE_FRONTEND = "https://app.example.com"


class TestBuildIntegrationConnectionMessage:
    """The connect message is platform-aware: UI points at the card, non-UI
    embeds the connect URL inline so bot users can act on it."""

    def test_ui_source_points_to_card_without_url(self) -> None:
        with patch(
            "app.utils.integration_checker.get_config",
            return_value={"configurable": {"source_category": "ui"}},
        ):
            msg = build_integration_connection_message("Gmail")
        assert "Gmail" in msg
        assert "card" in msg.lower()
        assert "http" not in msg
        assert "/integrations" not in msg

    @pytest.mark.parametrize("category", ["bot", "bg"])
    def test_non_ui_source_includes_connect_url(self, category: str) -> None:
        with (
            patch(
                "app.utils.integration_checker.get_config",
                return_value={"configurable": {"source_category": category}},
            ),
            patch("app.utils.integration_checker.settings") as mock_settings,
        ):
            mock_settings.FRONTEND_URL = _FAKE_FRONTEND
            msg = build_integration_connection_message("Gmail")
        assert f"{_FAKE_FRONTEND}/integrations" in msg
        assert "Gmail" in msg

    def test_outside_runnable_context_defaults_to_url(self) -> None:
        # get_config raises RuntimeError outside a graph run -> treat as non-UI.
        with (
            patch(
                "app.utils.integration_checker.get_config",
                side_effect=RuntimeError("no runnable context"),
            ),
            patch("app.utils.integration_checker.settings") as mock_settings,
        ):
            mock_settings.FRONTEND_URL = _FAKE_FRONTEND
            msg = build_integration_connection_message("Slack")
        assert f"{_FAKE_FRONTEND}/integrations" in msg

    @pytest.mark.parametrize("category", ["bot", "bg"])
    def test_non_ui_prefers_login_free_connect_link(self, category: str) -> None:
        """When a minted login-free link is supplied, the bot reply uses THAT —
        not the generic /integrations page (which requires a GAIA login)."""
        magic = "https://api.example.com/api/v1/integrations/connect-link?t=abc.def.ghi"
        with (
            patch(
                "app.utils.integration_checker.get_config",
                return_value={"configurable": {"source_category": category}},
            ),
            patch("app.utils.integration_checker.settings") as mock_settings,
        ):
            mock_settings.FRONTEND_URL = _FAKE_FRONTEND
            msg = build_integration_connection_message("Gmail", magic)
        assert magic in msg
        assert f"{_FAKE_FRONTEND}/integrations" not in msg

    def test_ui_ignores_connect_link_even_when_supplied(self) -> None:
        """On UI the card carries the link; the agent text stays URL-free."""
        with patch(
            "app.utils.integration_checker.get_config",
            return_value={"configurable": {"source_category": "ui"}},
        ):
            msg = build_integration_connection_message(
                "Gmail", "https://api.example.com/api/v1/integrations/connect-link?t=abc"
            )
        assert "http" not in msg
        assert "card" in msg.lower()
