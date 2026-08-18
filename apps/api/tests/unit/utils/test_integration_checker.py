"""Unit tests for the integration connect prompt (card + agent copy)."""

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.utils.integration_checker import request_integration_connection

# ---------------------------------------------------------------------------
# request_integration_connection
# ---------------------------------------------------------------------------

_FAKE_FRONTEND = "https://app.example.com"
_MAGIC_LINK = "https://app.example.com/connect/abc123"


@contextmanager
def _graph_run(category: str | None, connect_url: str | None = _MAGIC_LINK) -> Iterator[MagicMock]:
    """Run the prompt as if inside a graph run of ``category``, yielding its stream writer.

    ``category=None`` simulates no runnable context at all (get_config raises).
    """
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
    ):
        mock_settings.FRONTEND_URL = _FAKE_FRONTEND
        yield writer


class TestRequestIntegrationConnection:
    """The connect prompt is platform-aware: UI gets a card and URL-free copy,
    non-UI embeds the connect URL inline so bot users can act on it."""

    async def test_ui_source_points_to_card_without_url(self) -> None:
        with _graph_run("ui"):
            msg = await request_integration_connection("gmail", "Gmail", "user1")
        assert "Gmail" in msg
        assert "card" in msg.lower()
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
        """When a login-free link is minted, the bot reply uses THAT — not the
        generic /integrations page (which requires a GAIA login)."""
        with _graph_run(category):
            msg = await request_integration_connection("gmail", "Gmail", "user1")
        assert _MAGIC_LINK in msg
        assert f"{_FAKE_FRONTEND}/integrations" not in msg

    @pytest.mark.parametrize("category", ["bot", "bg"])
    async def test_non_ui_falls_back_to_integrations_page(self, category: str) -> None:
        with _graph_run(category, connect_url=None):
            msg = await request_integration_connection("gmail", "Gmail", "user1")
        assert f"{_FAKE_FRONTEND}/integrations" in msg
        assert "Gmail" in msg

    async def test_outside_runnable_context_defaults_to_url_and_skips_card(self) -> None:
        """No graph run means no stream to carry a card — the link must be inline."""
        with _graph_run(None) as writer:
            msg = await request_integration_connection("slack", "Slack", "user1")
        assert _MAGIC_LINK in msg
        assert writer.call_count == 0
