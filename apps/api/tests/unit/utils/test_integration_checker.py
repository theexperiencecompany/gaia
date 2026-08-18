"""Unit tests for the integration connection message builder."""

from unittest.mock import MagicMock, patch

import pytest

from app.utils.integration_checker import (
    build_integration_connection_message,
    emit_integration_connection_required,
)

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
            msg = build_integration_connection_message("Gmail", expired=False)
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
            msg = build_integration_connection_message("Gmail", expired=False)
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
            msg = build_integration_connection_message("Slack", expired=False)
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
            msg = build_integration_connection_message("Gmail", magic, expired=False)
        assert magic in msg
        assert f"{_FAKE_FRONTEND}/integrations" not in msg

    def test_ui_ignores_connect_link_even_when_supplied(self) -> None:
        """On UI the card carries the link; the agent text stays URL-free."""
        with patch(
            "app.utils.integration_checker.get_config",
            return_value={"configurable": {"source_category": "ui"}},
        ):
            msg = build_integration_connection_message(
                "Gmail",
                "https://api.example.com/api/v1/integrations/connect-link?t=abc",
                expired=False,
            )
        assert "http" not in msg
        assert "card" in msg.lower()


class TestExpiredConnectionMessage:
    """A dead connection and one that was never set up need different copy — the
    agent must not tell a user to "connect" something they already connected."""

    @pytest.mark.parametrize("category", ["ui", "bot"])
    def test_expired_tells_the_agent_the_connection_died(self, category: str) -> None:
        with (
            patch(
                "app.utils.integration_checker.get_config",
                return_value={"configurable": {"source_category": category}},
            ),
            patch("app.utils.integration_checker.settings") as mock_settings,
        ):
            mock_settings.FRONTEND_URL = _FAKE_FRONTEND
            expired = build_integration_connection_message("Gmail", expired=True)
            never = build_integration_connection_message("Gmail", expired=False)

        assert "EXPIRED" in expired
        assert "sign in again" in expired
        assert "EXPIRED" not in never
        assert "sign in again" not in never

    def test_expired_on_ui_says_reconnect_and_still_holds_the_url_back(self) -> None:
        with patch(
            "app.utils.integration_checker.get_config",
            return_value={"configurable": {"source_category": "ui"}},
        ):
            msg = build_integration_connection_message(
                "Gmail", "https://api.example.com/connect-link?t=abc", expired=True
            )
        assert "reconnect button" in msg
        assert "http" not in msg

    def test_expired_on_a_bot_without_a_link_says_reconnect_not_connect(self) -> None:
        with (
            patch(
                "app.utils.integration_checker.get_config",
                return_value={"configurable": {"source_category": "bot"}},
            ),
            patch("app.utils.integration_checker.settings") as mock_settings,
        ):
            mock_settings.FRONTEND_URL = _FAKE_FRONTEND
            msg = build_integration_connection_message("Gmail", expired=True)
        assert "reconnect Gmail there" in msg


# ---------------------------------------------------------------------------
# emit_integration_connection_required
# ---------------------------------------------------------------------------


class TestEmitIntegrationConnectionRequired:
    """The streamed payload is the renderers' contract — `expired` is what lets
    the card read as a re-login instead of a first-time connect."""

    @staticmethod
    def _card(*, expired: bool) -> dict[str, object]:
        writer = MagicMock()
        with patch("app.utils.integration_checker.get_stream_writer", return_value=writer):
            emit_integration_connection_required("gmail", "Gmail", expired=expired)
        payload = writer.call_args.args[0]["integration_connection_required"]
        assert isinstance(payload, dict)
        return payload

    def test_carries_the_expired_flag_both_ways(self) -> None:
        assert self._card(expired=True)["expired"] is True
        assert self._card(expired=False)["expired"] is False

    def test_expired_card_copy_asks_the_user_to_sign_in_again(self) -> None:
        assert self._card(expired=True)["message"] == (
            "Your Gmail connection expired. Sign in again to keep using it."
        )
        assert self._card(expired=False)["message"] == (
            "To use Gmail features, please connect your account first."
        )
