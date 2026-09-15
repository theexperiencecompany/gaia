"""Unit tests for the integration connect prompt (card + agent copy)."""

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.repositories.user_integrations import user_integration_repository
from app.utils.integration_checker import request_integration_connection

# ---------------------------------------------------------------------------
# request_integration_connection
# ---------------------------------------------------------------------------

_FAKE_FRONTEND = "https://app.example.com"
_MAGIC_LINK = "https://app.example.com/connect/abc123"
# The identity the status lookup is expected to be asked about.
_USER = "user1"
_INTEGRATION_ID = "gmail"


@contextmanager
def _graph_run(
    category: str | None,
    connect_url: str | None = _MAGIC_LINK,
    *,
    expired: bool = False,
) -> Iterator[MagicMock]:
    """Run the prompt inside a graph run of category, yielding its stream writer.

    category=None simulates no runnable context; expired is the stored status
    distinguishing a dead grant from one never set up. The status stub checks
    its actual arguments so a wrong user/integration id fails loudly.
    """

    async def _is_expired(user_id: str, integration_id: str) -> bool:
        return expired and (user_id, integration_id) == (_USER, _INTEGRATION_ID)

    writer = MagicMock()
    config_patch = (
        patch(
            "app.utils.integration_checker.get_config",
            side_effect=RuntimeError("no runnable context"),
        )
        if category is None
        else patch(
            "app.utils.integration_checker.get_config",
            return_value={"configurable": {"source_category": category}},
        )
    )
    with (
        config_patch,
        patch("app.utils.integration_checker.get_stream_writer", return_value=writer),
        patch(
            "app.utils.integration_checker.build_connect_link_url",
            AsyncMock(return_value=connect_url),
        ),
        patch("app.utils.integration_checker.settings") as mock_settings,
        patch.object(user_integration_repository, "is_expired", AsyncMock(side_effect=_is_expired)),
    ):
        mock_settings.FRONTEND_URL = _FAKE_FRONTEND
        yield writer


class TestRequestIntegrationConnection:
    """The connect prompt is platform-aware: UI gets a card, non-UI embeds the connect URL inline."""

    async def test_ui_source_points_to_card_without_url(self) -> None:
        with _graph_run("ui"):
            msg = await request_integration_connection("gmail", "Gmail", "user1")
        assert "Gmail" in msg
        assert "card" in msg.lower()
        # The verb, not just the card: "connect" vs "reconnect" is the whole
        # distinction this copy exists to make.
        assert "connect button" in msg
        assert "reconnect button" not in msg
        assert "http" not in msg
        assert "/integrations" not in msg

    async def test_ui_source_emits_the_connect_card(self) -> None:
        """The UI copy promises a button was shown — so the card must be emitted."""
        with _graph_run("ui") as writer:
            await request_integration_connection("posthog", "PostHog", "user1")
        frames = [call.args[0] for call in writer.call_args_list]
        card = next(f for f in frames if "integration_connection_required" in f)
        assert card["integration_connection_required"]["integration_id"] == "posthog"
        assert "PostHog" in card["integration_connection_required"]["message"]

    @pytest.mark.parametrize("category", ["bot", "bg"])
    async def test_non_ui_prefers_login_free_connect_link(self, category: str) -> None:
        """A minted login-free link is used over the generic /integrations page, which requires GAIA login."""
        with _graph_run(category):
            msg = await request_integration_connection("gmail", "Gmail", "user1")
        assert _MAGIC_LINK in msg
        assert f"{_FAKE_FRONTEND}/integrations" not in msg

    @pytest.mark.parametrize("category", ["bot", "bg"])
    async def test_non_ui_falls_back_to_integrations_page(self, category: str) -> None:
        with _graph_run(category, connect_url=None):
            msg = await request_integration_connection("gmail", "Gmail", "user1")
        assert f"{_FAKE_FRONTEND}/integrations" in msg
        assert "connect Gmail there" in msg

    async def test_outside_runnable_context_defaults_to_url_and_skips_card(self) -> None:
        """No graph run means no stream to carry a card — the link must be inline."""
        with _graph_run(None) as writer:
            msg = await request_integration_connection("slack", "Slack", "user1")
        assert _MAGIC_LINK in msg
        assert writer.call_count == 0


class TestExpiredConnectionPrompt:
    """The prompt reads the stored status itself to tell a dead grant from one never set up."""

    async def test_expired_copy_tells_the_agent_not_to_offer_a_first_time_connect(self) -> None:
        with _graph_run("ui", expired=True):
            expired = await request_integration_connection("gmail", "Gmail", "user1")
        with _graph_run("ui", expired=False):
            never = await request_integration_connection("gmail", "Gmail", "user1")

        assert "EXPIRED" in expired
        assert "sign in again" in expired
        assert "EXPIRED" not in never
        assert "sign in again" not in never

    async def test_expired_on_ui_says_reconnect_and_still_holds_the_url_back(self) -> None:
        with _graph_run("ui", expired=True):
            msg = await request_integration_connection("gmail", "Gmail", "user1")
        assert "reconnect button" in msg
        assert "http" not in msg

    async def test_expired_on_a_bot_without_a_link_says_reconnect_not_connect(self) -> None:
        with _graph_run("bot", connect_url=None, expired=True):
            msg = await request_integration_connection("gmail", "Gmail", "user1")
        assert "reconnect Gmail there" in msg

    @staticmethod
    def _card(writer: MagicMock) -> dict[str, object]:
        payload = writer.call_args.args[0]["integration_connection_required"]
        assert isinstance(payload, dict)
        return payload

    async def test_card_carries_the_expired_flag_both_ways(self) -> None:
        """The streamed payload's expired flag is what lets the card read as re-login vs first-time connect."""
        with _graph_run("ui", expired=True) as writer:
            await request_integration_connection("gmail", "Gmail", "user1")
        assert self._card(writer)["expired"] is True

        with _graph_run("ui", expired=False) as writer:
            await request_integration_connection("gmail", "Gmail", "user1")
        assert self._card(writer)["expired"] is False

    async def test_expired_card_copy_asks_the_user_to_sign_in_again(self) -> None:
        with _graph_run("ui", expired=True) as writer:
            await request_integration_connection("gmail", "Gmail", "user1")
        assert self._card(writer)["message"] == (
            "Your Gmail connection expired. Sign in again to keep using it."
        )

        with _graph_run("ui", expired=False) as writer:
            await request_integration_connection("gmail", "Gmail", "user1")
        assert self._card(writer)["message"] == (
            "To use Gmail features, please connect your account first."
        )
