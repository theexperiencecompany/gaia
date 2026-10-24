"""Unit tests for the integration connect prompt (card + agent copy)."""

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.integrations import ACCOUNT_NEEDS_RECONNECT_HINT, ConnectMode
from app.db.repositories.user_integrations import user_integration_repository
from app.helpers.mcp_helpers import get_mcp_oauth_redirect_uri
from app.models.mcp_config import MCPConfig
from app.services.integrations.integration_resolver import ResolvedIntegration
from app.utils.integration_checker import (
    _standalone_mcp_auth,
    request_integration_connection,
)
from tests.integration_account_factories import make_integration_account, make_integration_record

# ---------------------------------------------------------------------------
# request_integration_connection
# ---------------------------------------------------------------------------

_FAKE_FRONTEND = "https://app.example.com"
_MAGIC_LINK = "https://app.example.com/connect/abc123"
_MCP_AUTH_URL = (
    "https://mcp.example.com/authorize?client_id=gaia&state=xyz"
    "&redirect_uri=https%3A%2F%2Fapi.example.com%2Fapi%2Fv1%2Fmcp%2Foauth%2Fcallback"
)


# The identity the status lookup is expected to be asked about.
_USER = "user1"
_INTEGRATION_ID = "gmail"


def _mcp_client() -> MagicMock:
    """Return a stand-in MCP client whose provider authorization URL is known to the test."""
    client = MagicMock()
    client.build_oauth_auth_url = AsyncMock(return_value=_MCP_AUTH_URL)
    return client


def _unavailable_mcp_client() -> MagicMock:
    """Return a client whose OAuth discovery fails."""
    client = MagicMock()
    client.build_oauth_auth_url = AsyncMock(side_effect=RuntimeError("discovery failed"))
    return client


def _resolved_mcp(auth_type: str | None, integration_id: str = "posthog") -> ResolvedIntegration:
    """Return a resolvable custom MCP integration with the given auth type."""
    return ResolvedIntegration(
        integration_id=integration_id,
        name="Custom MCP",
        description="A custom MCP server",
        category="custom",
        managed_by="mcp",
        source="custom",
        requires_auth=True,
        auth_type=auth_type,
        mcp_config=MCPConfig(server_url="https://mcp.example.com/mcp", requires_auth=True),
        platform_integration=None,
        custom_doc=None,
    )


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
        patch("app.utils.integration_checker.current_stream_writer", return_value=writer),
        patch(
            "app.utils.integration_checker.build_connect_link_url",
            AsyncMock(return_value=connect_url),
        ),
        patch(
            "app.utils.integration_checker.get_mcp_client",
            AsyncMock(return_value=_mcp_client()),
        ),
        patch("app.utils.integration_checker.settings") as mock_settings,
        patch.object(user_integration_repository, "is_expired", AsyncMock(side_effect=_is_expired)),
        patch.object(user_integration_repository, "get_for_user", AsyncMock(return_value=None)),
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
        assert _MCP_AUTH_URL in ui_message
        card = self._card(writer)
        assert card["expired"] is True
        assert "reauthorize" in str(card["message"]).lower()

        with _graph_run("bot"):
            bot_message = await request_integration_connection(
                "posthog", "PostHog", "user1", mode=ConnectMode.RECONNECT
            )

        assert _MCP_AUTH_URL in bot_message
        assert _MAGIC_LINK not in bot_message
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
        assert _MCP_AUTH_URL in ui_message

        with _graph_run("bg", execution_mode="background"):
            bg_message = await request_integration_connection(
                "posthog", "PostHog", "user1", mode=ConnectMode.RECONNECT
            )
        assert "the PostHog connection needs a refresh" in bg_message


class TestStandaloneMcpAuthorization:
    """OAuth MCP servers hand out their provider URL; token-only servers say there is none."""

    async def test_oauth_mcp_url_is_relayed_verbatim_on_ui_and_bots(self) -> None:
        client = _mcp_client()
        with (
            _graph_run("ui"),
            patch(
                "app.utils.integration_checker.get_mcp_client",
                AsyncMock(return_value=client),
            ),
        ):
            ui_message = await request_integration_connection(
                "posthog", "PostHog", "user1", mode=ConnectMode.RECONNECT
            )

        client.build_oauth_auth_url.assert_awaited_once_with(
            integration_id="posthog",
            redirect_uri=get_mcp_oauth_redirect_uri(),
            redirect_path="/integrations",
        )
        assert _MCP_AUTH_URL in ui_message
        assert "clickable link" in ui_message

        with _graph_run("bot"):
            bot_message = await request_integration_connection(
                "posthog", "PostHog", "user1", mode=ConnectMode.RECONNECT
            )

        assert _MCP_AUTH_URL in bot_message
        assert "expires after about 10 minutes" in bot_message
        assert "1 hour" not in bot_message
        assert _MAGIC_LINK not in bot_message

    async def test_token_only_mcp_says_so_and_never_mints_a_connect_link(self) -> None:
        with (
            _graph_run("bot"),
            patch(
                "app.utils.integration_checker.IntegrationResolver.resolve",
                AsyncMock(return_value=_resolved_mcp("bearer")),
            ),
        ):
            message = await request_integration_connection(
                "posthog", "PostHog", "user1", mode=ConnectMode.RECONNECT
            )

        assert "API key" in message
        assert "no standalone authorization URL exists" in message
        assert _MAGIC_LINK not in message
        assert f"{_FAKE_FRONTEND}/integrations" in message

    async def test_token_only_mcp_still_shows_the_ui_card(self) -> None:
        with (
            _graph_run("ui") as writer,
            patch(
                "app.utils.integration_checker.IntegrationResolver.resolve",
                AsyncMock(return_value=_resolved_mcp("bearer")),
            ),
        ):
            message = await request_integration_connection(
                "posthog", "PostHog", "user1", mode=ConnectMode.RECONNECT
            )

        card = writer.call_args.args[0]["integration_connection_required"]
        assert card["expired"] is True
        assert "API key" in message
        assert "no standalone authorization URL exists" in message

    async def test_discovery_failure_falls_back_to_the_integrations_page(self) -> None:
        with (
            _graph_run("bot"),
            patch(
                "app.utils.integration_checker.get_mcp_client",
                AsyncMock(return_value=_unavailable_mcp_client()),
            ),
        ):
            message = await request_integration_connection(
                "posthog", "PostHog", "user1", mode=ConnectMode.RECONNECT
            )

        assert "No standalone authorization URL is available" in message
        assert f"{_FAKE_FRONTEND}/integrations" in message
        assert _MAGIC_LINK not in message


class TestExactCopyPerBranch:
    """Pin the whole instruction per channel and auth kind, not just a substring.

    The agent acts on these sentences, so a mutation that swaps one clause for a
    similar one must fail here rather than reach a user.
    """

    async def test_background_token_only(self) -> None:
        with (
            _graph_run("bg", execution_mode="background"),
            patch(
                "app.utils.integration_checker.IntegrationResolver.resolve",
                AsyncMock(return_value=_resolved_mcp("bearer")),
            ),
        ):
            msg = await request_integration_connection(
                "posthog", "PostHog", "user1", mode=ConnectMode.RECONNECT
            )
        assert msg == (
            "The user's PostHog connection needs fresh authorization; they need to reconnect "
            "to refresh access. This integration authenticates with an API key, so no "
            "standalone authorization URL exists. This is a background run and no user is "
            "present to enter it, so retrying PostHog this run cannot succeed. Record in your "
            "result that the PostHog connection needs a refresh and that the user must enter "
            f"the API key at {_FAKE_FRONTEND}/integrations, then carry on with the rest of the "
            "task."
        )

    async def test_background_classification_failure(self) -> None:
        with (
            _graph_run("bg", execution_mode="background"),
            patch(
                "app.utils.integration_checker.IntegrationResolver.resolve",
                AsyncMock(side_effect=RuntimeError("discovery failed")),
            ),
        ):
            msg = await request_integration_connection(
                "posthog", "PostHog", "user1", mode=ConnectMode.RECONNECT
            )
        assert msg == (
            "The user's PostHog connection needs fresh authorization; they need to reconnect "
            "to refresh access. No standalone authorization URL is available for this "
            "integration. This is a background run and no user is present, so retrying PostHog "
            "this run cannot succeed. Record in your result that the PostHog connection needs "
            f"a refresh (the user can reconnect it at {_FAKE_FRONTEND}/integrations), then "
            "carry on with the rest of the task."
        )

    async def test_ui_oauth(self) -> None:
        with _graph_run("ui"):
            msg = await request_integration_connection(
                "posthog", "PostHog", "user1", mode=ConnectMode.RECONNECT
            )
        assert msg == (
            "The user's PostHog connection needs fresh authorization; they need to reconnect "
            "to refresh access. A reconnect button has been shown to the user, and a "
            f"standalone authorization URL is available: {_MCP_AUTH_URL}. Relay that URL "
            "verbatim as a clickable link so the user can reconnect even if the card is not "
            "visible, then try again."
        )

    async def test_ui_token_only(self) -> None:
        with (
            _graph_run("ui"),
            patch(
                "app.utils.integration_checker.IntegrationResolver.resolve",
                AsyncMock(return_value=_resolved_mcp("bearer")),
            ),
        ):
            msg = await request_integration_connection(
                "posthog", "PostHog", "user1", mode=ConnectMode.RECONNECT
            )
        assert msg == (
            "The user's PostHog connection needs fresh authorization; they need to reconnect "
            "to refresh access. This integration authenticates with an API key, so no "
            "standalone authorization URL exists. A reconnect button has been shown to the "
            "user; ask them to enter the API key there."
        )

    async def test_ui_unavailable(self) -> None:
        with (
            _graph_run("ui"),
            patch(
                "app.utils.integration_checker.get_mcp_client",
                AsyncMock(return_value=_unavailable_mcp_client()),
            ),
        ):
            msg = await request_integration_connection(
                "posthog", "PostHog", "user1", mode=ConnectMode.RECONNECT
            )
        assert msg == (
            "The user's PostHog connection needs fresh authorization; they need to reconnect "
            "to refresh access. A reconnect button has been shown to the user, but no "
            "standalone authorization URL is available right now. Ask the user to click it, "
            "then try again."
        )

    async def test_bot_oauth(self) -> None:
        with _graph_run("bot"):
            msg = await request_integration_connection(
                "posthog", "PostHog", "user1", mode=ConnectMode.RECONNECT
            )
        assert msg == (
            "The user's PostHog connection needs fresh authorization; they need to reconnect "
            "to refresh access. The user is on a text-only platform (no UI). Include this "
            "standalone authorization URL verbatim in your result so the comms agent can relay "
            "it to the user, and tell them to open it soon because it expires after about 10 "
            f"minutes: {_MCP_AUTH_URL}"
        )

    async def test_bot_token_only(self) -> None:
        with (
            _graph_run("bot"),
            patch(
                "app.utils.integration_checker.IntegrationResolver.resolve",
                AsyncMock(return_value=_resolved_mcp("bearer")),
            ),
        ):
            msg = await request_integration_connection(
                "posthog", "PostHog", "user1", mode=ConnectMode.RECONNECT
            )
        assert msg == (
            "The user's PostHog connection needs fresh authorization; they need to reconnect "
            "to refresh access. This integration authenticates with an API key, so no "
            "standalone authorization URL exists. The user is on a text-only platform (no UI); "
            f"ask them to open {_FAKE_FRONTEND}/integrations and enter the API key to connect "
            "PostHog there."
        )

    async def test_bot_unavailable(self) -> None:
        with (
            _graph_run("bot"),
            patch(
                "app.utils.integration_checker.get_mcp_client",
                AsyncMock(return_value=_unavailable_mcp_client()),
            ),
        ):
            msg = await request_integration_connection(
                "posthog", "PostHog", "user1", mode=ConnectMode.RECONNECT
            )
        assert msg == (
            "The user's PostHog connection needs fresh authorization; they need to reconnect "
            "to refresh access. No standalone authorization URL is available for this "
            "integration. The user is on a text-only platform (no UI); ask them to open "
            f"{_FAKE_FRONTEND}/integrations and reconnect PostHog there."
        )

    async def test_bot_falls_back_to_a_connect_link_when_oauth_url_is_missing(self) -> None:
        client = MagicMock()
        client.build_oauth_auth_url = AsyncMock(return_value=None)
        with (
            _graph_run("bot"),
            patch("app.utils.integration_checker.get_mcp_client", AsyncMock(return_value=client)),
        ):
            msg = await request_integration_connection(
                "posthog", "PostHog", "user1", mode=ConnectMode.RECONNECT
            )
        assert msg == (
            "The user's PostHog connection needs fresh authorization; they need to reconnect "
            "to refresh access. The user is on a text-only platform (no UI). Include this URL "
            "verbatim in your result so the comms agent can relay it to the user, and tell "
            f"them it is valid for 1 hour: {_MAGIC_LINK}"
        )

    async def test_ui_treats_a_missing_oauth_url_as_no_url(self) -> None:
        client = MagicMock()
        client.build_oauth_auth_url = AsyncMock(return_value=None)
        with (
            _graph_run("ui"),
            patch("app.utils.integration_checker.get_mcp_client", AsyncMock(return_value=client)),
        ):
            msg = await request_integration_connection(
                "posthog", "PostHog", "user1", mode=ConnectMode.RECONNECT
            )
        assert msg == (
            "The user's PostHog connection needs fresh authorization; they need to reconnect "
            "to refresh access. A reconnect button has been shown to the user, so do NOT "
            "include any URL in your reply, the UI card handles it. Ask the user to click it, "
            "then try again."
        )


class TestStandaloneMcpAuthClassification:
    """_standalone_mcp_auth decides the auth kind without touching the network when it can."""

    async def test_a_composio_integration_is_not_mcp_even_with_a_config(self) -> None:
        resolved = _resolved_mcp("oauth")
        resolved.managed_by = "composio"
        with patch(
            "app.utils.integration_checker.IntegrationResolver.resolve",
            AsyncMock(return_value=resolved),
        ):
            auth = await _standalone_mcp_auth("user1", "posthog", build_url=True)
        assert auth.kind == "not_mcp"
        assert auth.url is None

    async def test_unknown_integration_is_not_mcp(self) -> None:
        with patch(
            "app.utils.integration_checker.IntegrationResolver.resolve",
            AsyncMock(return_value=None),
        ):
            auth = await _standalone_mcp_auth("user1", "posthog", build_url=True)
        assert auth.kind == "not_mcp"

    async def test_mcp_without_a_config_is_not_mcp(self) -> None:
        resolved = _resolved_mcp("oauth")
        resolved.mcp_config = None
        with patch(
            "app.utils.integration_checker.IntegrationResolver.resolve",
            AsyncMock(return_value=resolved),
        ):
            auth = await _standalone_mcp_auth("user1", "posthog", build_url=True)
        assert auth.kind == "not_mcp"

    async def test_mcp_that_needs_no_auth_is_not_mcp(self) -> None:
        resolved = _resolved_mcp("oauth")
        resolved.requires_auth = False
        with patch(
            "app.utils.integration_checker.IntegrationResolver.resolve",
            AsyncMock(return_value=resolved),
        ):
            auth = await _standalone_mcp_auth("user1", "posthog", build_url=True)
        assert auth.kind == "not_mcp"

    async def test_bearer_server_is_token_only(self) -> None:
        with (
            patch(
                "app.utils.integration_checker.IntegrationResolver.resolve",
                AsyncMock(return_value=_resolved_mcp("bearer")),
            ),
            patch("app.utils.integration_checker.get_mcp_client") as get_client,
        ):
            auth = await _standalone_mcp_auth("user1", "posthog", build_url=True)
        assert auth.kind == "token_only"
        get_client.assert_not_awaited()

    async def test_oauth_without_building_the_url_stays_oauth(self) -> None:
        with (
            patch(
                "app.utils.integration_checker.IntegrationResolver.resolve",
                AsyncMock(return_value=_resolved_mcp("oauth")),
            ),
            patch("app.utils.integration_checker.get_mcp_client") as get_client,
        ):
            auth = await _standalone_mcp_auth("user1", "posthog", build_url=False)
        assert auth.kind == "oauth"
        assert auth.url is None
        get_client.assert_not_awaited()

    async def test_discovery_failure_is_unavailable_and_logged(self) -> None:
        with (
            patch(
                "app.utils.integration_checker.IntegrationResolver.resolve",
                AsyncMock(side_effect=RuntimeError("boom")),
            ),
            patch("app.utils.integration_checker.log.warning") as warning,
        ):
            auth = await _standalone_mcp_auth("user1", "posthog", build_url=True)
        assert auth.kind == "unavailable"
        warning.assert_called_once_with(
            "MCP standalone authorization URL unavailable",
            integration_id="posthog",
            error_type="RuntimeError",
            error="boom",
        )


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
        record = make_integration_record(
            make_integration_account("ca_1", label="me@gmail.com"),
            make_integration_account("ca_2", label="work@acme.com", nickname="Work"),
            user_id=_USER,
            primary="ca_2",
        )
        with (
            _graph_run("ui", expired=expired) as writer,
            patch.object(
                user_integration_repository, "get_for_user", AsyncMock(return_value=record)
            ) as lookup,
        ):
            msg = await request_integration_connection(
                "gmail", "Gmail", "user1", mode=ConnectMode.ADD_ACCOUNT
            )

        assert self._card(writer) == {
            "integration_id": "gmail",
            "integration_name": "Gmail",
            "expired": False,
            "add_account": True,
            "message": "Add another Gmail account. Sign in with the account you want to add.",
            # The primary first, so the card reads the way the user thinks of them.
            "connected_accounts": ["Work", "me@gmail.com"],
            "reconnect_account": None,
        }
        lookup.assert_awaited_once_with(_USER, _INTEGRATION_ID)
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
        assert self._card(writer)["connected_accounts"] == []

        with _graph_run("ui") as writer:
            await request_integration_connection(
                "gmail", "Gmail", "user1", mode=ConnectMode.RECONNECT
            )
        assert self._card(writer)["add_account"] is False


class TestAccountReconnectPrompt:
    """One expired account is signed back in place, named on the card and in the link."""

    _DEAD = make_integration_account("ca_work", "expired", label="work@acme.com")

    async def test_the_card_names_the_account_and_carries_its_id(self) -> None:
        # The integration itself stays connected while another account works.
        with _graph_run("ui", expired=False) as writer:
            msg = await request_integration_connection(
                "gmail", "Gmail", "user1", mode=ConnectMode.RECONNECT, account=self._DEAD
            )

        assert writer.call_args.args[0]["integration_connection_required"] == {
            "integration_id": "gmail",
            "integration_name": "Gmail",
            "expired": True,
            "add_account": False,
            "message": "Your Gmail account work@acme.com lost its connection. Sign in as "
            "work@acme.com again to keep using it.",
            "connected_accounts": [],
            "reconnect_account": {"id": "ca_work", "name": "work@acme.com"},
        }
        assert msg == (
            "The user's Gmail account work@acme.com lost its connection and must be signed in "
            f"again. {ACCOUNT_NEEDS_RECONNECT_HINT} A reconnect button has been shown to the "
            "user, so do NOT include any URL in your reply, the UI card handles it. Ask the "
            "user to click it, then try again."
        )

    async def test_a_background_run_records_which_account_lost_its_connection(self) -> None:
        with _graph_run("bg", execution_mode="background"):
            msg = await request_integration_connection(
                "gmail", "Gmail", "user1", mode=ConnectMode.RECONNECT, account=self._DEAD
            )

        assert msg == (
            "The user's Gmail account work@acme.com lost its connection and must be signed in "
            f"again. {ACCOUNT_NEEDS_RECONNECT_HINT} This is a background run and no user is "
            "present to reconnect it, so retrying Gmail this run cannot succeed. Record in your "
            "result that the Gmail account work@acme.com lost its connection (the user can "
            f"reconnect it at {_FAKE_FRONTEND}/integrations), then carry on with the rest of "
            "the task."
        )

    async def test_a_bot_link_signs_that_account_back_in(self) -> None:
        mint = AsyncMock(return_value=_MAGIC_LINK)
        with (
            _graph_run("bot"),
            patch("app.utils.integration_checker.build_connect_link_url", mint),
        ):
            msg = await request_integration_connection(
                "gmail", "Gmail", "user1", mode=ConnectMode.RECONNECT, account=self._DEAD
            )

        mint.assert_awaited_once_with("user1", "gmail", "ca_work")
        assert msg.endswith(f"valid for 1 hour: {_MAGIC_LINK}")


class TestExactCopyPerMode:
    """The agent acts on these sentences, so each mode's wording is pinned whole."""

    async def test_a_first_connect_on_ui(self) -> None:
        with _graph_run("ui"):
            msg = await request_integration_connection("gmail", "Gmail", "user1")
        assert msg == (
            "Gmail needs to be connected. A connect button has been shown to the user, so do "
            "NOT include any URL in your reply, the UI card handles it. Ask the user to click "
            "it, then try again."
        )

    async def test_an_expired_connection_on_ui(self) -> None:
        with _graph_run("ui", expired=True):
            msg = await request_integration_connection("gmail", "Gmail", "user1")
        assert msg.endswith(
            "Do NOT tell them to connect Gmail for the first time. A reconnect button has been "
            "shown to the user, so do NOT include any URL in your reply, the UI card handles "
            "it. Ask the user to click it, then try again."
        )

    async def test_a_requested_reconnect_in_the_background(self) -> None:
        with _graph_run("bg", execution_mode="background"):
            msg = await request_integration_connection(
                "posthog", "PostHog", "user1", mode=ConnectMode.RECONNECT
            )
        assert msg == (
            "The user's PostHog connection needs fresh authorization; they need to reconnect "
            "to refresh access. This is a background run and no user is present to reconnect "
            "it, so retrying PostHog this run cannot succeed. Record in your result that the "
            "PostHog connection needs a refresh (the user can reconnect it at "
            f"{_FAKE_FRONTEND}/integrations), then carry on with the rest of the task."
        )

    async def test_adding_an_account_in_the_background(self) -> None:
        with _graph_run("bg", execution_mode="background"):
            msg = await request_integration_connection(
                "gmail", "Gmail", "user1", mode=ConnectMode.ADD_ACCOUNT
            )
        assert msg == (
            "The user wants to add another Gmail account; their current accounts stay "
            "connected. This is a background run and no user is present to add another "
            "account to it, so retrying Gmail this run cannot succeed. Record in your result "
            "that another Gmail account was not added (the user can add another account to it "
            f"at {_FAKE_FRONTEND}/integrations), then carry on with the rest of the task."
        )


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
