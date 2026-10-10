"""Unit tests for the integration connect prompt (card + agent copy)."""

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.integrations import ConnectMode
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
    execution_mode: str | None = None,
    frontend: str = _FAKE_FRONTEND,
) -> Iterator[MagicMock]:
    """Run the prompt inside a graph run of category, yielding its stream writer.

    category=None simulates no runnable context; expired is the stored status
    distinguishing a dead grant from one never set up. The status stub checks
    its actual arguments so a wrong user/integration id fails loudly.
    """

    async def _is_expired(user_id: str, integration_id: str) -> bool:
        return expired and (user_id, integration_id) == (_USER, _INTEGRATION_ID)

    writer = MagicMock()
    configurable = {"source_category": category}
    if execution_mode is not None:
        configurable["execution_mode"] = execution_mode
    config_patch = (
        patch(
            "app.utils.integration_checker.get_config",
            side_effect=RuntimeError("no runnable context"),
        )
        if category is None
        else patch(
            "app.utils.integration_checker.get_config",
            return_value={"configurable": configurable},
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
        mock_settings.FRONTEND_URL = frontend
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

    @pytest.mark.regression
    async def test_forced_reauthorization_is_presented_as_reconnect_and_mints_a_fresh_link(
        self,
    ) -> None:
        with _graph_run("ui") as writer:
            ui_message = await request_integration_connection(
                "posthog", "PostHog", "user1", mode=ConnectMode.RECONNECT
            )

        assert "reconnect button" in ui_message
        card = self._card(writer)
        assert card["expired"] is True
        assert "reauthorize" in str(card["message"]).lower()

        with _graph_run("bot"):
            bot_message = await request_integration_connection(
                "posthog", "PostHog", "user1", mode=ConnectMode.RECONNECT
            )

        assert _MAGIC_LINK in bot_message
        assert "reconnect" in bot_message.lower()

    @pytest.mark.regression
    async def test_forced_reauthorization_copy_is_exact(self) -> None:
        """The reconnect wording is user-facing copy; pin it verbatim."""
        with _graph_run("ui") as writer:
            ui_message = await request_integration_connection(
                "posthog", "PostHog", "user1", mode=ConnectMode.RECONNECT
            )
        card = self._card(writer)
        assert card["message"] == (
            "Your PostHog connection needs fresh authorization. Reauthorize to keep using it."
        )
        assert (
            "The user's PostHog connection needs fresh authorization; "
            "they need to reconnect to refresh access. A reconnect button has been shown"
        ) in ui_message

        with _graph_run("bg", execution_mode="background"):
            bg_message = await request_integration_connection(
                "posthog", "PostHog", "user1", mode=ConnectMode.RECONNECT
            )
        assert "the PostHog connection needs a refresh" in bg_message


class TestAddAccountPrompt:
    """Adding an account asks for another sign-in while the current accounts stay connected."""

    @staticmethod
    def _card(writer: MagicMock) -> dict[str, object]:
        payload = writer.call_args.args[0]["integration_connection_required"]
        assert isinstance(payload, dict)
        return payload

    @pytest.mark.parametrize("expired", [False, True], ids=["live", "all_expired"])
    async def test_the_card_asks_to_add_an_account_and_is_never_a_reconnect(
        self, expired: bool
    ) -> None:
        with _graph_run("ui", expired=expired) as writer:
            msg = await request_integration_connection(
                "gmail", "Gmail", "user1", mode=ConnectMode.ADD_ACCOUNT
            )

        assert self._card(writer) == {
            "integration_id": "gmail",
            "integration_name": "Gmail",
            "expired": False,
            "add_account": True,
            "message": "Add another Gmail account. Sign in with the account you want to add.",
        }
        assert msg == (
            "The user wants to add another Gmail account; their current accounts stay "
            "connected. A button to add the account has been shown to the user, so do NOT "
            "include any URL in your reply, the UI card handles it. Ask the user to click it, "
            "then try again."
        )

    async def test_a_bot_gets_the_single_use_link(self) -> None:
        with _graph_run("bot"):
            msg = await request_integration_connection(
                "gmail", "Gmail", "user1", mode=ConnectMode.ADD_ACCOUNT
            )

        assert msg.startswith("The user wants to add another Gmail account;")
        assert msg.endswith(f"valid for 1 hour: {_MAGIC_LINK}")

    async def test_a_bot_without_a_link_is_sent_to_the_integrations_page(self) -> None:
        with _graph_run("bot", connect_url=None):
            msg = await request_integration_connection(
                "gmail", "Gmail", "user1", mode=ConnectMode.ADD_ACCOUNT
            )

        assert msg.endswith(
            f"Ask them to open {_FAKE_FRONTEND}/integrations and add another account to Gmail there."
        )

    async def test_other_modes_stream_no_add_account_flag(self) -> None:
        with _graph_run("ui") as writer:
            await request_integration_connection("gmail", "Gmail", "user1")
        assert self._card(writer)["add_account"] is False

        with _graph_run("ui") as writer:
            await request_integration_connection(
                "gmail", "Gmail", "user1", mode=ConnectMode.RECONNECT
            )
        assert self._card(writer)["add_account"] is False


class TestBackgroundRunPrompt:
    """A background run has nobody to click a card or a link, so it must not wait to retry."""

    @pytest.mark.regression
    async def test_background_copy_says_carry_on_and_never_asks_to_retry(self) -> None:
        with _graph_run("bg", execution_mode="background"):
            msg = await request_integration_connection("gmail", "Gmail", "user1")

        assert "Gmail needs to be connected" in msg
        assert "no user is present" in msg
        assert "carry on with the rest of the task" in msg
        assert "try again" not in msg
        # The single-use link dies within the hour; the result is read later.
        assert _MAGIC_LINK not in msg
        assert f"{_FAKE_FRONTEND}/integrations" in msg

    @pytest.mark.regression
    async def test_background_copy_for_an_expired_grant_says_sign_in_again(self) -> None:
        with _graph_run("bg", execution_mode="background", expired=True):
            msg = await request_integration_connection("gmail", "Gmail", "user1")

        assert "EXPIRED" in msg
        assert "carry on with the rest of the task" in msg

    async def test_background_copy_names_the_gap_and_where_to_connect(self) -> None:
        # A host ending in X shows only the trailing slash is stripped.
        with _graph_run("bg", execution_mode="background", frontend="https://GAIA.BOX/"):
            msg = await request_integration_connection("gmail", "Gmail", "user1")

        assert msg == (
            "Gmail needs to be connected. This is a background run and no user is present to "
            "connect it, so retrying Gmail this run cannot succeed. Record in your result that "
            "Gmail is not connected (the user can connect it at "
            "https://GAIA.BOX/integrations), then carry on with the rest of the task."
        )

    async def test_background_copy_for_an_expired_grant_names_the_expired_connection(
        self,
    ) -> None:
        with _graph_run("bg", execution_mode="background", expired=True):
            msg = await request_integration_connection("gmail", "Gmail", "user1")

        assert msg.endswith(
            "This is a background run and no user is present to reconnect it, so retrying "
            "Gmail this run cannot succeed. Record in your result that the Gmail connection "
            "expired (the user can reconnect it at https://app.example.com/integrations), then "
            "carry on with the rest of the task."
        )
