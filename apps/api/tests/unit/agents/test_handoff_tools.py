"""Tests for app.agents.core.subagents.handoff_tools."""

from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, ToolMessage
import pytest

from app.agents.core.subagents.handoff_tools import (
    CustomMcpIndexRequest,
    _get_subagent_by_id,
    _handoff_rejection,
    _HandoffDispatch,
    _resolve_subagent,
    _run_blocking_handoff,
    check_integration_connection,
    handoff,
    index_custom_mcp_as_subagent,
)
from app.agents.core.subagents.provider_subagents import SubagentUnavailableError
from app.agents.core.subagents.subagent_runner import SubagentOutcome, subagent_row_id
from app.constants.hil import HIL_RESUME_CONFIG_KEY
from app.db.repositories.user_integrations import user_integration_repository
from app.models.integration_models import Integration
from app.models.mcp_config import MCPConfig, SubAgentConfig
from app.models.subagent_models import Subagent
from app.utils.agent_utils import IntegrationMetadata


def _integration(integration_id: str, name: str, **overrides: object) -> Integration:
    data: dict[str, object] = {
        "integration_id": integration_id,
        "name": name,
        "description": "",
        "category": "custom",
        "managed_by": "mcp",
        "source": "custom",
    }
    data.update(overrides)
    return Integration.model_validate(data)


def _make_subagent_config(agent_name: str = "gmail_agent") -> SubAgentConfig:
    return SubAgentConfig(
        has_subagent=True,
        agent_name=agent_name,
        tool_space="gmail_space",
        handoff_tool_name="call_gmail",
        domain="gmail",
        capabilities="email",
        use_cases="emails",
        system_prompt="You are gmail.",
    )


def _make_subagent(
    subagent_id: str = "gmail",
    short_name: str | None = "gmail",
    name: str = "Gmail",
    managed_by: str = "internal",
    mcp_config: MCPConfig | None = None,
    agent_name: str = "gmail_agent",
) -> Subagent:
    """Real Subagent for tests of handoff_tools (post-refactor)."""
    return Subagent(
        id=subagent_id,
        name=name,
        provider=subagent_id,
        managed_by=managed_by,  # type: ignore[arg-type]  # fixture uses a plain string for the managed_by Literal
        config=_make_subagent_config(agent_name=agent_name),
        short_name=short_name,
        mcp_config=mcp_config,
    )


@contextmanager
def _ui_graph_run(writer: MagicMock, *, expired: bool = False) -> Iterator[None]:
    """Make the connect prompt believe it is running inside a UI chat turn.

    ``expired`` is the stored connection status the prompt reads to tell a dead
    grant from one that was never set up.
    """
    with (
        patch(
            "app.utils.integration_checker.get_config",
            return_value={"configurable": {"source_category": "ui"}},
        ),
        patch("app.utils.integration_checker.get_stream_writer", return_value=writer),
        patch.object(user_integration_repository, "is_expired", AsyncMock(return_value=expired)),
    ):
        yield


def _connect_card_ids(writer: MagicMock) -> list[str]:
    """The integration id of every connect card pushed to the user's stream."""
    return [
        call.args[0]["integration_connection_required"]["integration_id"]
        for call in writer.call_args_list
        if "integration_connection_required" in call.args[0]
    ]


# ---------------------------------------------------------------------------
# check_integration_connection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCheckIntegrationConnection:
    async def test_returns_none_when_integration_not_found(self):
        with patch(
            "app.agents.core.subagents.handoff_tools.get_subagent_by_id",
            return_value=None,
        ):
            result = await check_integration_connection("bogus", "user1")
        assert result is None

    async def test_returns_none_when_connected(self):
        subagent = _make_subagent("gmail")
        with (
            patch(
                "app.agents.core.subagents.handoff_tools.get_subagent_by_id",
                return_value=subagent,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.check_integration_status",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            result = await check_integration_connection("gmail", "user1")
        assert result is None

    async def test_returns_error_when_not_connected(self):
        subagent = _make_subagent("gmail")
        mock_writer = MagicMock()
        with (
            patch(
                "app.agents.core.subagents.handoff_tools.get_subagent_by_id",
                return_value=subagent,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.check_integration_status",
                new_callable=AsyncMock,
                return_value=False,
            ),
            _ui_graph_run(mock_writer),
        ):
            result = await check_integration_connection("gmail", "user1")

        assert result is not None
        assert "needs to be connected" in result
        assert _connect_card_ids(mock_writer) == ["gmail"]

    async def test_a_dead_connection_asks_the_user_to_sign_in_again(self):
        """`check_integration_status` only says "not usable" — the stored record
        is what stops a died-on-us connection reading as a first-time connect."""
        mock_writer = MagicMock()
        with (
            patch(
                "app.agents.core.subagents.handoff_tools.get_subagent_by_id",
                return_value=_make_subagent("gmail"),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.check_integration_status",
                new_callable=AsyncMock,
                return_value=False,
            ),
            _ui_graph_run(mock_writer, expired=True),
        ):
            result = await check_integration_connection("gmail", "user1")

        assert result is not None
        assert "EXPIRED" in result
        assert "sign in again" in result
        assert "needs to be connected" not in result
        card = next(
            call.args[0]["integration_connection_required"]
            for call in mock_writer.call_args_list
            if "integration_connection_required" in call.args[0]
        )
        assert card["expired"] is True
        assert card["message"] == "Your Gmail connection expired. Sign in again to keep using it."

    async def test_status_check_failure_propagates(self):
        """A failed status check must not be swallowed into "connected"."""
        with (
            patch(
                "app.agents.core.subagents.handoff_tools.get_subagent_by_id",
                return_value=_make_subagent("gmail"),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.check_integration_status",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            ),
            pytest.raises(RuntimeError, match="boom"),
        ):
            await check_integration_connection("gmail", "user1")


# ---------------------------------------------------------------------------
# _get_subagent_by_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetSubagentById:
    async def test_finds_platform_integration_by_id(self):
        subagent = _make_subagent("gmail")
        with patch(
            "app.agents.core.subagents.handoff_tools.get_subagent_by_id",
            return_value=subagent,
        ):
            result = await _get_subagent_by_id("gmail")
        assert result is subagent

    async def test_finds_platform_integration_by_short_name(self):
        subagent = _make_subagent("google_calendar", short_name="gcal")
        # Registry's get_subagent_by_id resolves the short_name lookup itself —
        # the mock returns the same subagent regardless of the input string.
        with patch(
            "app.agents.core.subagents.handoff_tools.get_subagent_by_id",
            return_value=subagent,
        ):
            result = await _get_subagent_by_id("gcal")
        assert result is subagent

    async def test_skips_platform_without_subagent_config(self):
        # Registry never returns subagents without a config; falls through to
        # cache/MongoDB. Slack is not a registered subagent, so the lookup
        # returns None and we exercise the custom-MCP fallback path.
        with (
            patch(
                "app.agents.core.subagents.handoff_tools.get_subagent_by_id",
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.get_cache",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("app.agents.core.subagents.handoff_tools.integration_repository") as mock_repo,
            patch("app.agents.core.subagents.handoff_tools.IntegrationResolver") as mock_resolver,
            patch(
                "app.agents.core.subagents.handoff_tools.set_cache",
                new_callable=AsyncMock,
            ),
        ):
            mock_repo.find_by_id_prefix_or_name = AsyncMock(return_value=None)
            mock_resolver.resolve = AsyncMock(return_value=None)
            result = await _get_subagent_by_id("slack")
        assert result is None

    async def test_returns_cached_custom_integration(self):
        cached = {"id": "abc123", "name": "Custom MCP"}
        with (
            patch(
                "app.agents.core.subagents.handoff_tools.get_subagent_by_id",
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.get_cache",
                new_callable=AsyncMock,
                return_value=cached,
            ),
        ):
            result = await _get_subagent_by_id("abc123")
        assert result == cached

    async def test_returns_none_for_negative_cache(self):
        with (
            patch(
                "app.agents.core.subagents.handoff_tools.get_subagent_by_id",
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.get_cache",
                new_callable=AsyncMock,
                return_value={},
            ),
        ):
            result = await _get_subagent_by_id("missing")
        assert result is None

    async def test_finds_custom_from_mongodb(self):
        custom = _integration(
            "abc",
            "My MCP",
            mcp_config=MCPConfig(server_url="https://example.com"),
            icon_url="https://example.com/icon.png",
        )
        with (
            patch(
                "app.agents.core.subagents.handoff_tools.get_subagent_by_id",
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.get_cache",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("app.agents.core.subagents.handoff_tools.integration_repository") as mock_repo,
            patch(
                "app.agents.core.subagents.handoff_tools.set_cache",
                new_callable=AsyncMock,
            ),
        ):
            mock_repo.find_by_id_prefix_or_name = AsyncMock(return_value=custom)
            result = await _get_subagent_by_id("abc")

        assert result["id"] == "abc"
        assert result["name"] == "My MCP"

    async def test_fallback_to_integration_resolver(self):
        resolved_doc = {
            "integration_id": "res_id",
            "name": "Resolved",
            "mcp_config": {},
            "icon_url": None,
        }
        resolved = SimpleNamespace(custom_doc=resolved_doc, source="user_integrations")
        with (
            patch(
                "app.agents.core.subagents.handoff_tools.get_subagent_by_id",
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.get_cache",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("app.agents.core.subagents.handoff_tools.integration_repository") as mock_repo,
            patch("app.agents.core.subagents.handoff_tools.IntegrationResolver") as mock_resolver,
            patch(
                "app.agents.core.subagents.handoff_tools.set_cache",
                new_callable=AsyncMock,
            ),
        ):
            mock_repo.find_by_id_prefix_or_name = AsyncMock(return_value=None)
            mock_resolver.resolve = AsyncMock(return_value=resolved)
            result = await _get_subagent_by_id("res_id")

        assert result["id"] == "res_id"
        assert result["source"] == "user_integrations"


# ---------------------------------------------------------------------------
# index_custom_mcp_as_subagent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestIndexCustomMcpAsSubagent:
    async def test_indexes_mcp(self):
        mock_store = AsyncMock()
        with patch(
            "app.agents.core.subagents.handoff_tools.derive_integration_namespace",
            return_value="example.com",
        ):
            await index_custom_mcp_as_subagent(
                store=mock_store,
                request=CustomMcpIndexRequest(
                    integration_id="abc123",
                    name="My Tool",
                    description="Does stuff",
                    server_url="https://example.com/mcp",
                ),
            )
        mock_store.abatch.assert_awaited_once()
        put_op = mock_store.abatch.call_args[0][0][0]
        assert put_op.key == "abc123"
        assert put_op.value["name"] == "My Tool"
        assert put_op.value["tool_namespace"] == "example.com"


# ---------------------------------------------------------------------------
# _resolve_subagent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestResolveSubagent:
    async def test_returns_error_when_not_found(self):
        with (
            patch(
                "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.all_subagents",
                return_value=(
                    _make_subagent("gmail"),
                    _make_subagent("slack"),
                ),
            ),
        ):
            graph, name, error, is_custom = await _resolve_subagent("unknown", "user1")
        assert graph is None
        assert "not found" in error

    async def test_resolves_custom_mcp(self):
        custom_dict = {"id": "abc", "name": "Custom"}
        mock_graph = MagicMock()
        with (
            patch(
                "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=custom_dict,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.create_subagent_for_user",
                new_callable=AsyncMock,
                return_value=mock_graph,
            ),
        ):
            graph, name, int_id, is_custom = await _resolve_subagent("abc", "user1")
        assert graph is mock_graph
        assert is_custom is True
        assert int_id == "abc"

    async def test_custom_mcp_no_user_id(self):
        custom_dict = {"id": "abc", "name": "Custom"}
        with patch(
            "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
            new_callable=AsyncMock,
            return_value=custom_dict,
        ):
            graph, name, error, is_custom = await _resolve_subagent("abc", None)
        assert graph is None
        assert "authentication" in error.lower()

    async def test_custom_mcp_no_id_field(self):
        custom_dict = {"id": "", "name": "Broken"}
        with patch(
            "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
            new_callable=AsyncMock,
            return_value=custom_dict,
        ):
            graph, name, error, is_custom = await _resolve_subagent("broken", "user1")
        assert graph is None
        assert error == "Error: Custom integration has no ID"
        assert is_custom is False

    async def test_custom_mcp_graph_creation_fails(self):
        custom_dict = {"id": "abc", "name": "Custom"}
        with (
            patch(
                "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=custom_dict,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.create_subagent_for_user",
                new_callable=AsyncMock,
                side_effect=SubagentUnavailableError("connection failed"),
            ),
        ):
            graph, name, error, is_custom = await _resolve_subagent("abc", "user1")
        assert graph is None
        assert "is unavailable" in error

    async def test_platform_mcp_requires_auth_connected(self):
        mcp_cfg = MCPConfig(server_url="https://example.com", requires_auth=True)
        subagent = _make_subagent("gmail", "gmail", "Gmail", managed_by="mcp", mcp_config=mcp_cfg)
        mock_graph = MagicMock()
        with (
            patch(
                "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=subagent,
            ),
            patch("app.agents.core.subagents.handoff_tools.MCPTokenStore") as mock_ts_cls,
            patch(
                "app.agents.core.subagents.handoff_tools.create_subagent_for_user",
                new_callable=AsyncMock,
                return_value=mock_graph,
            ),
        ):
            mock_ts = AsyncMock()
            mock_ts.is_connected.return_value = True
            mock_ts_cls.return_value = mock_ts
            graph, name, int_id, is_custom = await _resolve_subagent("subagent:gmail", "user1")
        assert graph is mock_graph
        assert is_custom is False

    @pytest.mark.regression
    async def test_platform_mcp_requires_auth_not_connected(self):
        """An unconnected auth'd MCP must show the connect card, not just promise one.

        The UI copy tells the agent "a connect button has been shown to the user",
        so a text-only return here leaves the user hunting a button that never
        rendered (PostHog: managed_by="mcp", requires_auth=True).
        """
        mcp_cfg = MCPConfig(server_url="https://example.com", requires_auth=True)
        subagent = _make_subagent(
            "posthog", "posthog", "PostHog", managed_by="mcp", mcp_config=mcp_cfg
        )
        mock_writer = MagicMock()
        with (
            patch(
                "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=subagent,
            ),
            patch("app.agents.core.subagents.handoff_tools.MCPTokenStore") as mock_ts_cls,
            _ui_graph_run(mock_writer),
        ):
            mock_ts = AsyncMock()
            mock_ts.is_connected.return_value = False
            mock_ts_cls.return_value = mock_ts
            graph, name, error, is_custom = await _resolve_subagent("posthog", "user1")
        assert graph is None
        assert "needs to be connected" in error
        assert _connect_card_ids(mock_writer) == ["posthog"]

    async def test_platform_mcp_requires_auth_no_user(self):
        mcp_cfg = MCPConfig(server_url="https://example.com", requires_auth=True)
        subagent = _make_subagent("gmail", "gmail", "Gmail", managed_by="mcp", mcp_config=mcp_cfg)
        with patch(
            "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
            new_callable=AsyncMock,
            return_value=subagent,
        ):
            graph, name, error, is_custom = await _resolve_subagent("gmail", None)
        assert graph is None
        assert error == "Error: gmail_agent requires authentication. Please sign in first."
        assert is_custom is False

    async def test_platform_non_mcp_uses_provider(self):
        subagent = _make_subagent(
            "gcal",
            "gcal",
            "Google Calendar",
            managed_by="internal",
            agent_name="calendar_agent",
        )
        mock_graph = MagicMock()
        with (
            patch(
                "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=subagent,
            ),
            patch("app.agents.core.subagents.handoff_tools.providers") as mock_providers,
        ):
            mock_providers.aget = AsyncMock(return_value=mock_graph)
            graph, name, int_id, is_custom = await _resolve_subagent("gcal", "user1")
        assert graph is mock_graph
        assert name == "calendar_agent"

    async def test_platform_composio_checks_connection(self):
        subagent = _make_subagent(
            "composio",
            "composio",
            "Composio",
            managed_by="composio",
            agent_name="composio_agent",
        )
        with (
            patch(
                "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=subagent,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.check_integration_connection",
                new_callable=AsyncMock,
                return_value="Not connected",
            ),
        ):
            graph, name, error, is_custom = await _resolve_subagent("composio", "user1")
        assert graph is None
        assert error == "Not connected"

    async def test_platform_provider_not_available(self):
        subagent = _make_subagent("x", "x", "X", managed_by="internal", agent_name="missing_agent")
        with (
            patch(
                "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=subagent,
            ),
            patch("app.agents.core.subagents.handoff_tools.providers") as mock_providers,
        ):
            mock_providers.aget = AsyncMock(return_value=None)
            graph, name, error, is_custom = await _resolve_subagent("x", "user1")
        assert graph is None
        assert error == "Error: missing_agent not available"
        assert is_custom is False

    async def test_platform_mcp_graph_creation_fails(self):
        mcp_cfg = MCPConfig(server_url="https://example.com", requires_auth=True)
        subagent = _make_subagent(
            "mcp_int",
            "mcp_int",
            "MCP Int",
            managed_by="mcp",
            mcp_config=mcp_cfg,
            agent_name="mcp_agent",
        )
        with (
            patch(
                "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=subagent,
            ),
            patch("app.agents.core.subagents.handoff_tools.MCPTokenStore") as mock_ts_cls,
            patch(
                "app.agents.core.subagents.handoff_tools.create_subagent_for_user",
                new_callable=AsyncMock,
                side_effect=SubagentUnavailableError("server error"),
            ),
        ):
            mock_ts = AsyncMock()
            mock_ts.is_connected.return_value = True
            mock_ts_cls.return_value = mock_ts
            graph, name, error, is_custom = await _resolve_subagent("mcp_int", "user1")
        assert graph is None
        assert error == "Error: mcp_agent is unavailable: server error"
        assert is_custom is False


# ---------------------------------------------------------------------------
# check_integration_connection / _resolve_subagent — argument passing
# ---------------------------------------------------------------------------


@contextmanager
def _bot_graph_run() -> Iterator[None]:
    """Make the connect prompt believe it is running on a text-only client, where
    the login-free link is minted instead of a UI card."""
    with (
        patch(
            "app.utils.integration_checker.get_config",
            return_value={"configurable": {"source_category": "bot"}},
        ),
        patch("app.utils.integration_checker.get_stream_writer", return_value=MagicMock()),
        patch.object(user_integration_repository, "is_expired", AsyncMock(return_value=False)),
    ):
        yield


@pytest.mark.asyncio
class TestConnectionChecksUseTheirArguments:
    """The branch tests above mock with fixed return values, which cannot tell a
    correct argument from a nulled one — every argument-passing mutation in these
    two functions survived them. These fakes answer based on what they are handed,
    so a dropped or swapped argument changes the outcome instead of going
    unnoticed."""

    @staticmethod
    @contextmanager
    def _lookup_only(integration_id: str, subagent: Subagent) -> Iterator[None]:
        """``get_subagent_by_id`` that recognises exactly one id."""
        with patch(
            "app.agents.core.subagents.handoff_tools.get_subagent_by_id",
            side_effect=lambda requested: subagent if requested == integration_id else None,
        ):
            yield

    async def test_the_integration_asked_about_is_the_one_looked_up(self):
        subagent = _make_subagent("gmail")
        with (
            self._lookup_only("gmail", subagent),
            patch(
                "app.agents.core.subagents.handoff_tools.check_integration_status",
                new_callable=AsyncMock,
                return_value=False,
            ),
            _ui_graph_run(MagicMock()),
        ):
            result = await check_integration_connection("gmail", "user1")

        assert result is not None

    async def test_the_connection_check_is_scoped_to_this_user_and_integration(self):
        """Checking the wrong user's connection, or the wrong integration's, would
        nag a user who is already connected — or worse, wave through one who is
        not."""
        subagent = _make_subagent("gmail")

        async def _status(integration_id: str, user_id: str) -> bool:
            return (integration_id, user_id) == ("gmail", "user1")

        with (
            self._lookup_only("gmail", subagent),
            patch(
                "app.agents.core.subagents.handoff_tools.check_integration_status",
                new=AsyncMock(side_effect=_status),
            ),
        ):
            assert await check_integration_connection("gmail", "user1") is None

    async def test_the_prompt_names_the_subagent_being_connected(self):
        """ "None needs to be connected" is what the agent would read out to the
        user if the display name were lost on the way to the prompt."""
        subagent = _make_subagent("gmail", name="Gmail")
        with (
            self._lookup_only("gmail", subagent),
            patch(
                "app.agents.core.subagents.handoff_tools.check_integration_status",
                new_callable=AsyncMock,
                return_value=False,
            ),
            _ui_graph_run(MagicMock()),
        ):
            result = await check_integration_connection("gmail", "user1")

        assert result is not None and result.startswith("Gmail needs to be connected")

    async def test_the_connect_link_is_minted_for_the_asking_user(self):
        """On a text-only client the prompt carries a single-use login-free link.
        Minting it for the wrong user hands one person another's connect flow."""
        subagent = _make_subagent("gmail")

        async def _link(user_id: str, integration_id: str) -> str | None:
            if (user_id, integration_id) == ("user1", "gmail"):
                return "https://gaia.test/connect/abc"
            return None

        with (
            self._lookup_only("gmail", subagent),
            patch(
                "app.agents.core.subagents.handoff_tools.check_integration_status",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.utils.integration_checker.build_connect_link_url",
                new=AsyncMock(side_effect=_link),
            ),
            _bot_graph_run(),
        ):
            result = await check_integration_connection("gmail", "user1")

        assert result is not None and "https://gaia.test/connect/abc" in result

    async def test_the_mcp_connect_prompt_names_the_subagent(self):
        mcp_cfg = MCPConfig(server_url="https://example.com", requires_auth=True)
        subagent = _make_subagent(
            "posthog", "posthog", "PostHog", managed_by="mcp", mcp_config=mcp_cfg
        )
        with (
            patch(
                "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=subagent,
            ),
            patch("app.agents.core.subagents.handoff_tools.MCPTokenStore") as mock_ts_cls,
            _ui_graph_run(MagicMock()),
        ):
            mock_ts = AsyncMock()
            mock_ts.is_connected.return_value = False
            mock_ts_cls.return_value = mock_ts
            _graph, _name, error, _is_custom = await _resolve_subagent("posthog", "user1")

        assert error.startswith("PostHog needs to be connected")

    async def test_the_mcp_connect_link_is_minted_for_the_asking_user(self):
        mcp_cfg = MCPConfig(server_url="https://example.com", requires_auth=True)
        subagent = _make_subagent(
            "posthog", "posthog", "PostHog", managed_by="mcp", mcp_config=mcp_cfg
        )

        async def _link(user_id: str, integration_id: str) -> str | None:
            if (user_id, integration_id) == ("user1", "posthog"):
                return "https://gaia.test/connect/xyz"
            return None

        with (
            patch(
                "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=subagent,
            ),
            patch("app.agents.core.subagents.handoff_tools.MCPTokenStore") as mock_ts_cls,
            patch(
                "app.utils.integration_checker.build_connect_link_url",
                new=AsyncMock(side_effect=_link),
            ),
            _bot_graph_run(),
        ):
            mock_ts = AsyncMock()
            mock_ts.is_connected.return_value = False
            mock_ts_cls.return_value = mock_ts
            _graph, _name, error, _is_custom = await _resolve_subagent("posthog", "user1")

        assert "https://gaia.test/connect/xyz" in error


@contextmanager
def _resolved_subagent(agent_name: str, integration_id: str) -> Iterator[MagicMock]:
    """Stand every collaborator `handoff` needs past resolution, so the only
    thing under test is what it does with the task text it was handed."""
    ctx = SimpleNamespace(agent_name=agent_name, integration_id=integration_id)
    with (
        patch(
            "app.agents.core.subagents.handoff_tools.prepare_subagent_execution",
            new_callable=AsyncMock,
            return_value=(ctx, None, None),
        ),
        patch(
            "app.agents.core.subagents.handoff_tools._has_parked_subagent",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "app.agents.core.subagents.handoff_tools._run_blocking_handoff",
            new_callable=AsyncMock,
            return_value="subagent ran",
        ) as dispatch,
    ):
        yield dispatch


@pytest.mark.unit
class TestHandoffRejectsAForeignProviderInTheTask:
    """A task that names one provider while being routed to another produces a
    result claiming work the target never did — eight GAIA todos were reported
    to the user as "8 tasks created (Todoist)" from exactly this input."""

    PROD_TASK = (
        "Create these 8 separate tasks on Aryan's todo list (Todoist). Each one is its "
        "own task. Use clear, actionable titles:\n\n1. Buy Resend Pro to send emails"
    )

    async def test_the_prod_task_is_rejected_before_the_subagent_runs(self) -> None:
        with _resolved_subagent("todo_agent", "todos") as dispatch:
            result = await handoff.coroutine(
                subagent_id="todos",
                task=self.PROD_TASK,
                config={"configurable": {"user_id": "u1", "thread_id": "t1"}},
            )

        dispatch.assert_not_awaited()
        assert "Todoist" in result
        assert "subagent:todoist" in result

    async def test_the_same_task_without_the_provider_name_dispatches(self) -> None:
        with _resolved_subagent("todo_agent", "todos") as dispatch:
            result = await handoff.coroutine(
                subagent_id="todos",
                task="Create these 8 separate tasks on Aryan's todo list.",
                config={"configurable": {"user_id": "u1", "thread_id": "t1"}},
            )

        dispatch.assert_awaited_once()
        assert result == "subagent ran"

    async def test_the_provider_named_is_free_to_be_the_target(self) -> None:
        with _resolved_subagent("todoist_agent", "todoist") as dispatch:
            result = await handoff.coroutine(
                subagent_id="todoist",
                task="Create 8 tasks in Todoist.",
                config={"configurable": {"user_id": "u1", "thread_id": "t1"}},
            )

        dispatch.assert_awaited_once()
        assert result == "subagent ran"


@pytest.mark.unit
class TestBackgroundHandoffWithoutAStream:
    """``background=True`` needs a stream_id to route the result back. Without
    one the handoff still runs, but blocking — and the executor has to be told,
    or it calls ``wait_for_subagents()`` for a result that already arrived and
    waits on nothing."""

    async def test_the_result_is_prefixed_with_the_fallback_warning(self) -> None:
        with _resolved_subagent("todo_agent", "todos") as dispatch:
            result = await handoff.coroutine(
                subagent_id="todos",
                task="Create a task.",
                background=True,
                config={"configurable": {"user_id": "u1", "thread_id": "t1"}},
            )

        dispatch.assert_awaited_once()
        assert result == (
            "[WARNING: background handoff fell back to blocking: "
            "stream_id not propagated into executor configurable] subagent ran"
        )


@pytest.mark.unit
class TestWorkflowHandoffCarriesTheSubagentsCallRecord:
    """A workflow run's executor transcribes playbook steps from the handoff
    result — it never sees the subagent's own tool calls, so without the record
    it guesses names and args (invented ``max_results`` for GMAIL_FETCH_MESSAGES
    whose real arg is ``max_messages``). A chat run must stay byte-identical to
    the plain subagent text: no extra text, no extra tokens."""

    @staticmethod
    def _outcome() -> SubagentOutcome:
        return SubagentOutcome(
            text="subagent ran",
            run_messages=(
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "GMAIL_FETCH_MESSAGES",
                            "args": {"max_messages": 5},
                            "id": "tc1",
                        }
                    ],
                ),
                ToolMessage(content="ok", tool_call_id="tc1"),
            ),
        )

    @contextmanager
    def _running_subagent(self) -> Iterator[None]:
        """Real ``_run_blocking_handoff`` over a faked subagent stream — the
        record append under test lives inside it, so it must not be mocked."""
        ctx = SimpleNamespace(
            agent_name="gmail_agent",
            integration_id="gmail",
            configurable={},
            config={},
        )
        with (
            patch(
                "app.agents.core.subagents.handoff_tools.prepare_subagent_execution",
                new_callable=AsyncMock,
                return_value=(ctx, None, None),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools._has_parked_subagent",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.get_stream_writer",
                return_value=MagicMock(),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.execute_subagent_stream",
                new_callable=AsyncMock,
                return_value=self._outcome(),
            ),
        ):
            yield

    async def test_a_workflow_run_gets_the_record_appended(self) -> None:
        with self._running_subagent():
            result = await handoff.coroutine(
                subagent_id="gmail",
                task="Fetch the unread messages.",
                config={
                    "configurable": {
                        "user_id": "u1",
                        "thread_id": "t1",
                        "workflow_id": "wf1",
                    }
                },
            )

        assert result.startswith("subagent ran")
        assert "<subagent_call_record>" in result
        assert 'GMAIL_FETCH_MESSAGES({"max_messages":5})' in result

    async def test_a_chat_run_result_is_untouched(self) -> None:
        with self._running_subagent():
            result = await handoff.coroutine(
                subagent_id="gmail",
                task="Fetch the unread messages.",
                config={"configurable": {"user_id": "u1", "thread_id": "t1"}},
            )

        assert result == "subagent ran"


# ---------------------------------------------------------------------------
# index_custom_mcp_as_subagent — the indexed document
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestIndexedCustomMcpDocument:
    """The indexed value IS the semantic-search document. Losing the description
    or the tool summaries leaves the subagent ranking for nothing but its own
    name, so a "meetings" query never surfaces the MCP that has get_meetings."""

    async def test_the_description_and_every_tool_summary_are_indexed(self):
        store = AsyncMock()
        with patch(
            "app.agents.core.subagents.handoff_tools.derive_integration_namespace",
            side_effect=lambda integration_id, server_url, is_custom: (
                f"{integration_id}|{server_url}|{is_custom}"
            ),
        ):
            await index_custom_mcp_as_subagent(
                store=store,
                request=CustomMcpIndexRequest(
                    integration_id="abc123",
                    name="My Tool",
                    description="Does stuff",
                    server_url="https://example.com/mcp",
                    tools=[
                        SimpleNamespace(
                            name="get_meetings",
                            description="List upcoming meetings\nlonger prose",
                        ),
                        SimpleNamespace(name="ping", description=""),
                    ],
                ),
            )

        put_op = store.abatch.call_args[0][0][0]
        assert put_op.namespace == ("subagents",)
        assert put_op.index == ["description"]
        assert put_op.value == {
            "id": "abc123",
            "name": "My Tool",
            "description": (
                "My Tool. Does stuff. Available tools: get_meetings: List upcoming meetings; ping."
            ),
            "source": "custom",
            "tool_namespace": "abc123|https://example.com/mcp|True",
        }


# ---------------------------------------------------------------------------
# _resolve_subagent — custom MCP failures and argument passing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCustomMcpResolution:
    """Every return of the custom-MCP path is read out to the user verbatim, and
    the ``is_custom`` flag decides whether the caller looks the integration's
    display metadata up in Mongo — a failure must never claim to be custom."""

    @staticmethod
    @contextmanager
    def _mongo_doc(doc: dict[str, object]) -> Iterator[None]:
        with patch(
            "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
            new_callable=AsyncMock,
            return_value=doc,
        ):
            yield

    async def test_a_document_with_no_id_key_is_rejected(self):
        """``.get("id")`` without the empty-string default resolves a missing key
        to ``None``, whose ``str()`` is the truthy "None" — and the run proceeds
        against an integration id that does not exist."""
        with self._mongo_doc({"name": "Custom"}):
            graph, name, error, is_custom = await _resolve_subagent("abc", "user1")

        assert (graph, name) == (None, None)
        assert error == "Error: Custom integration has no ID"
        assert is_custom is False

    async def test_an_unauthenticated_custom_mcp_is_named_in_the_refusal(self):
        with self._mongo_doc({"id": "abc", "name": "Custom"}):
            graph, name, error, is_custom = await _resolve_subagent("abc", None)

        assert (graph, name) == (None, None)
        assert error == "Error: Custom requires authentication. Please sign in first."
        assert is_custom is False

    async def test_a_nameless_custom_mcp_falls_back_to_its_id(self):
        with self._mongo_doc({"id": "abc"}):
            _graph, _name, error, _is_custom = await _resolve_subagent("abc", None)

        assert error == "Error: abc requires authentication. Please sign in first."

    async def test_an_unavailable_custom_mcp_reports_the_servers_reason(self):
        with (
            self._mongo_doc({"id": "abc", "name": "Custom"}),
            patch(
                "app.agents.core.subagents.handoff_tools.create_subagent_for_user",
                new_callable=AsyncMock,
                side_effect=SubagentUnavailableError("server returned 402"),
            ),
        ):
            graph, name, error, is_custom = await _resolve_subagent("abc", "user1")

        assert (graph, name) == (None, None)
        assert error == "Error: Custom is unavailable: server returned 402"
        assert is_custom is False

    async def test_the_graph_is_built_for_this_integration_and_this_user(self):
        """A nulled or dropped argument here builds somebody else's subagent —
        with their tokens — under this user's handoff."""
        graph_for_abc = MagicMock()

        async def _create(integration_id: str, user_id: str) -> MagicMock:
            if (integration_id, user_id) != ("abc", "user1"):
                raise SubagentUnavailableError(f"wrong args: {integration_id!r}, {user_id!r}")
            return graph_for_abc

        with (
            self._mongo_doc({"id": "abc", "name": "Custom"}),
            patch(
                "app.agents.core.subagents.handoff_tools.create_subagent_for_user",
                new=_create,
            ),
        ):
            graph, name, int_id, is_custom = await _resolve_subagent("abc", "user1")

        assert graph is graph_for_abc
        assert name == "custom_mcp_abc"
        assert int_id == "abc"
        assert is_custom is True


@pytest.mark.asyncio
class TestAuthMcpResolutionUsesItsArguments:
    """The token store, the connection probe and the per-user graph all key on
    (integration_id, user_id). A nulled one reads another account's tokens."""

    @staticmethod
    def _subagent() -> Subagent:
        return _make_subagent(
            "posthog",
            "posthog",
            "PostHog",
            managed_by="mcp",
            mcp_config=MCPConfig(server_url="https://example.com", requires_auth=True),
            agent_name="posthog_agent",
        )

    async def test_the_token_store_and_graph_are_scoped_to_this_user(self):
        graph_for_posthog = MagicMock()
        seen: dict[str, object] = {}

        class _TokenStore:
            def __init__(self, user_id: str) -> None:
                seen["token_store_user"] = user_id

            async def is_connected(self, integration_id: str) -> bool:
                seen["is_connected_arg"] = integration_id
                return integration_id == "posthog"

        async def _create(integration_id: str, user_id: str) -> MagicMock:
            if (integration_id, user_id) != ("posthog", "user1"):
                raise SubagentUnavailableError(f"wrong args: {integration_id!r}, {user_id!r}")
            return graph_for_posthog

        with (
            patch(
                "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=self._subagent(),
            ),
            patch("app.agents.core.subagents.handoff_tools.MCPTokenStore", _TokenStore),
            patch("app.agents.core.subagents.handoff_tools.create_subagent_for_user", new=_create),
            patch(
                "app.agents.core.subagents.handoff_tools.request_integration_connection",
                new_callable=AsyncMock,
                return_value="connect PostHog",
            ),
        ):
            graph, name, int_id, is_custom = await _resolve_subagent("posthog", "user1")

        assert graph is graph_for_posthog
        assert seen == {"token_store_user": "user1", "is_connected_arg": "posthog"}
        assert (name, int_id, is_custom) == ("posthog_agent", "posthog", False)


@pytest.mark.asyncio
class TestPlainSubagentGraphResolution:
    """The connection check is skipped for integrations that are always
    available. Running it anyway hides every builtin behind a connect card the
    user can never satisfy; skipping it for a real OAuth integration dispatches
    a subagent with no credentials."""

    @staticmethod
    @contextmanager
    def _resolves(subagent: Subagent) -> Iterator[None]:
        with patch(
            "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
            new_callable=AsyncMock,
            return_value=subagent,
        ):
            yield

    async def test_an_internal_subagent_skips_the_connection_check(self):
        subagent = _make_subagent(
            "gcal", "gcal", "Google Calendar", managed_by="internal", agent_name="calendar_agent"
        )
        mock_graph = MagicMock()
        with (
            self._resolves(subagent),
            patch(
                "app.agents.core.subagents.handoff_tools.check_integration_connection",
                new_callable=AsyncMock,
                return_value="Not connected",
            ),
            patch("app.agents.core.subagents.handoff_tools.providers") as mock_providers,
        ):
            mock_providers.aget = AsyncMock(return_value=mock_graph)
            graph, name, int_id, is_custom = await _resolve_subagent("gcal", "user1")

        assert graph is mock_graph
        assert (name, int_id, is_custom) == ("calendar_agent", "gcal", False)

    async def test_an_mcp_subagent_that_needs_no_auth_skips_the_connection_check(self):
        subagent = _make_subagent(
            "docs", "docs", "Docs", managed_by="mcp", mcp_config=None, agent_name="docs_agent"
        )
        mock_graph = MagicMock()
        with (
            self._resolves(subagent),
            patch(
                "app.agents.core.subagents.handoff_tools.check_integration_connection",
                new_callable=AsyncMock,
                return_value="Not connected",
            ),
            patch("app.agents.core.subagents.handoff_tools.providers") as mock_providers,
        ):
            mock_providers.aget = AsyncMock(return_value=mock_graph)
            graph, _name, _int_id, _is_custom = await _resolve_subagent("docs", "user1")

        assert graph is mock_graph

    async def test_the_connection_check_is_scoped_to_the_asking_user_and_integration(self):
        subagent = _make_subagent(
            "composio", "composio", "Composio", managed_by="composio", agent_name="composio_agent"
        )
        mock_graph = MagicMock()

        async def _check(integration_id: str, user_id: str) -> str | None:
            if (integration_id, user_id) == ("composio", "user1"):
                return None
            return f"wrong args: {integration_id!r}, {user_id!r}"

        with (
            self._resolves(subagent),
            patch(
                "app.agents.core.subagents.handoff_tools.check_integration_connection", new=_check
            ),
            patch("app.agents.core.subagents.handoff_tools.providers") as mock_providers,
        ):
            mock_providers.aget = AsyncMock(return_value=mock_graph)
            graph, name, _int_id, _is_custom = await _resolve_subagent("composio", "user1")

        assert graph is mock_graph
        assert name == "composio_agent"

    async def test_the_graph_is_fetched_under_the_configured_agent_name(self):
        """``agent_name`` is the provider-registry key — asking for the wrong one
        (or for ``None``) resolves to no graph and the handoff dies as "not
        available" on an integration that is connected and fine."""
        subagent = _make_subagent(
            "gcal", "gcal", "Google Calendar", managed_by="internal", agent_name="calendar_agent"
        )
        mock_graph = MagicMock()

        async def _aget(name: str) -> MagicMock | None:
            return mock_graph if name == "calendar_agent" else None

        with (
            self._resolves(subagent),
            patch("app.agents.core.subagents.handoff_tools.providers") as mock_providers,
        ):
            mock_providers.aget = _aget
            graph, name, _int_id, _is_custom = await _resolve_subagent("gcal", "user1")

        assert graph is mock_graph
        assert name == "calendar_agent"


# ---------------------------------------------------------------------------
# _run_blocking_handoff
# ---------------------------------------------------------------------------


def _blocking_ctx() -> SimpleNamespace:
    """The parts of a SubagentExecutionContext `_run_blocking_handoff` touches."""
    return SimpleNamespace(
        agent_name="gmail_agent",
        integration_id="gmail",
        configurable={},
        config={},
    )


def _stream_event(writer: MagicMock, key: str) -> dict[str, object]:
    return next(call.args[0][key] for call in writer.call_args_list if key in call.args[0])


@pytest.mark.asyncio
class TestBlockingHandoffLifecycleEvents:
    """``subagent_start`` is the UI row for the run: its name, icon and category
    are the resolved integration's, and its id must be the replay-stable row id
    or an approval pause orphans a spinner and opens a duplicate on resume."""

    @staticmethod
    @contextmanager
    def _subagent_run(writer: MagicMock, outcome: SubagentOutcome) -> Iterator[None]:
        with (
            patch("app.agents.core.subagents.handoff_tools.get_stream_writer", return_value=writer),
            patch(
                "app.agents.core.subagents.handoff_tools.execute_subagent_stream",
                new_callable=AsyncMock,
                return_value=outcome,
            ),
        ):
            yield

    async def test_the_start_event_carries_the_integrations_display_metadata(self):
        writer = MagicMock()
        dispatch = _HandoffDispatch(
            metadata=IntegrationMetadata(
                icon_url="https://cdn.test/gmail.png",
                integration_id="gmail_custom",
                name="Gmail Inbox",
            ),
            agent_name="gmail_agent",
            integration_id="gmail",
            tool_call_id="tc1",
        )
        with self._subagent_run(writer, SubagentOutcome(text="done")):
            result = await _run_blocking_handoff(_blocking_ctx(), dispatch)

        start = _stream_event(writer, "subagent_start")
        assert result == "done"
        assert start["subagent_name"] == "Gmail Inbox"
        assert start["icon_url"] == "https://cdn.test/gmail.png"
        assert start["tool_category"] == "gmail_custom"
        assert start["subagent_id"] == subagent_row_id("tc1")
        assert _stream_event(writer, "subagent_end")["subagent_id"] == subagent_row_id("tc1")

    async def test_a_subagent_without_metadata_falls_back_to_its_agent_and_integration(self):
        writer = MagicMock()
        dispatch = _HandoffDispatch(
            metadata=None,
            agent_name="gmail_agent",
            integration_id="gmail",
            tool_call_id="tc1",
        )
        with self._subagent_run(writer, SubagentOutcome(text="done")):
            await _run_blocking_handoff(_blocking_ctx(), dispatch)

        start = _stream_event(writer, "subagent_start")
        assert start["subagent_name"] == "gmail_agent"
        assert start["tool_category"] == "gmail"
        assert "icon_url" not in start

    async def test_a_resume_replay_recovers_the_parked_thread_instead_of_rerunning_it(self):
        """Re-invoking a thread that already holds work redoes every side effect
        it performed before the pause — the emails go out twice."""
        writer = MagicMock()
        dispatch = _HandoffDispatch(
            metadata=None,
            agent_name="gmail_agent",
            integration_id="gmail",
            tool_call_id="tc1",
            probe_parked=True,
        )
        with (
            patch("app.agents.core.subagents.handoff_tools.get_stream_writer", return_value=writer),
            patch(
                "app.agents.core.subagents.handoff_tools.recover_from_checkpoint",
                new_callable=AsyncMock,
                return_value=SubagentOutcome(text="recovered"),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.execute_subagent_stream",
                new_callable=AsyncMock,
            ) as rerun,
        ):
            result = await _run_blocking_handoff(_blocking_ctx(), dispatch)

        assert result == "recovered"
        rerun.assert_not_awaited()

    async def test_every_run_across_an_approval_pause_reaches_the_call_record(self):
        """One task can gate several destructive calls in sequence, so the run
        that resumes is a second run — dropping its messages loses the call the
        user actually approved from the playbook the executor writes."""
        writer = MagicMock()
        paused = SubagentOutcome(
            text="",
            interrupt={"approval_id": "a1"},
            run_messages=(
                AIMessage(
                    content="",
                    tool_calls=[{"name": "GMAIL_SEND", "args": {"to": "a@b.c"}, "id": "tc_a"}],
                ),
                ToolMessage(content="sent", tool_call_id="tc_a"),
            ),
        )
        finished = SubagentOutcome(
            text="both sent",
            run_messages=(
                AIMessage(
                    content="",
                    tool_calls=[{"name": "GMAIL_SEND", "args": {"to": "d@e.f"}, "id": "tc_b"}],
                ),
                ToolMessage(content="sent", tool_call_id="tc_b"),
            ),
        )
        dispatch = _HandoffDispatch(
            metadata=None,
            agent_name="gmail_agent",
            integration_id="gmail",
            tool_call_id="tc1",
            record_calls=True,
        )
        with (
            patch("app.agents.core.subagents.handoff_tools.get_stream_writer", return_value=writer),
            patch(
                "app.agents.core.subagents.handoff_tools.resume_for_gate",
                return_value={"status": "approved"},
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.execute_subagent_stream",
                new_callable=AsyncMock,
                side_effect=[paused, finished],
            ),
        ):
            result = await _run_blocking_handoff(_blocking_ctx(), dispatch)

        assert result.startswith("both sent")
        assert 'GMAIL_SEND({"to":"a@b.c"})' in result
        assert 'GMAIL_SEND({"to":"d@e.f"})' in result


# ---------------------------------------------------------------------------
# _handoff_rejection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestHandoffRejectionMessages:
    """A refusal is the executor's only instruction on what to do instead —
    ``wait_for_subagents()`` — so the wording and the named subagent are
    behaviour, not decoration. Dropping the name gives the model "the None
    subagent is paused" to act on."""

    @staticmethod
    @contextmanager
    def _no_foreign_provider() -> Iterator[None]:
        with patch(
            "app.agents.core.subagents.handoff_tools.foreign_provider_named_in", return_value=None
        ):
            yield

    async def test_a_parked_subagent_refuses_new_work_with_the_collect_instruction(self):
        ctx = SimpleNamespace(agent_name="gmail_agent", integration_id="gmail")
        probed: list[object] = []

        async def _parked(candidate: object) -> bool:
            probed.append(candidate)
            return candidate is ctx

        with (
            self._no_foreign_provider(),
            patch("app.agents.core.subagents.handoff_tools._has_parked_subagent", new=_parked),
        ):
            rejection = await _handoff_rejection(ctx, "Fetch the unread messages.", False, "s1")

        assert rejection == (
            "The gmail_agent subagent is paused waiting for the user's approval. "
            "Call wait_for_subagents() to collect its outcome before sending it "
            "new tasks."
        )
        assert probed == [ctx]

    async def test_a_blocking_handoff_refuses_to_collide_with_a_live_background_run(self):
        """The slot is keyed by (stream_id, integration_id); a nulled or blanked
        key checks a slot nobody holds and lets two runs share one checkpoint
        thread. A run with no stream_id checks the empty-string stream."""
        ctx = SimpleNamespace(agent_name="gmail_agent", integration_id="gmail")

        def _has_bg(stream_id: str, integration_id: str) -> bool:
            return (stream_id, integration_id) == ("", "gmail")

        with (
            self._no_foreign_provider(),
            patch(
                "app.agents.core.subagents.handoff_tools._has_parked_subagent",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.has_bg_integration", side_effect=_has_bg
            ),
        ):
            rejection = await _handoff_rejection(ctx, "Fetch the unread messages.", False, None)

        assert rejection == (
            "A background gmail_agent subagent is already running on this "
            "integration. Call wait_for_subagents() to collect it first."
        )

    async def test_a_background_handoff_is_left_to_the_session_slot_claim(self):
        """The background branch enforces one-per-integration itself via
        ``claim_bg_integration``. Refusing here as well would fail every parallel
        dispatch that follows a live one, instead of falling back cleanly."""
        ctx = SimpleNamespace(agent_name="gmail_agent", integration_id="gmail")
        with (
            self._no_foreign_provider(),
            patch(
                "app.agents.core.subagents.handoff_tools._has_parked_subagent",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch("app.agents.core.subagents.handoff_tools.has_bg_integration", return_value=True),
        ):
            assert await _handoff_rejection(ctx, "Fetch the unread messages.", True, "s1") is None


# ---------------------------------------------------------------------------
# handoff — what it hands to the runners
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandoffBuildsItsDispatch:
    """Everything past resolution travels in one ``_HandoffDispatch``. A nulled
    or dropped field silently downgrades the run: no metadata on the UI row, no
    checkpoint probe on a resume replay, no call record for a workflow."""

    @staticmethod
    @contextmanager
    def _blocking_run(metadata: IntegrationMetadata | None) -> Iterator[dict[str, object]]:
        ctx = SimpleNamespace(agent_name="gmail_agent", integration_id="gmail")
        seen: dict[str, object] = {"ctx": ctx, "calls": []}

        async def _run(run_ctx: object, dispatch: object) -> str:
            seen["calls"].append((run_ctx, dispatch))  # type: ignore[attr-defined]  # the seen bag holds mixed value types; mypy narrows to the first
            return "subagent ran"

        with (
            patch(
                "app.agents.core.subagents.handoff_tools.prepare_subagent_execution",
                new_callable=AsyncMock,
                return_value=(ctx, metadata, None),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools._has_parked_subagent",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch("app.agents.core.subagents.handoff_tools._run_blocking_handoff", new=_run),
        ):
            yield seen

    async def test_the_dispatch_carries_the_metadata_ids_and_run_mode_flags(self) -> None:
        metadata = IntegrationMetadata(icon_url=None, integration_id="gmail", name="Gmail")
        with self._blocking_run(metadata) as seen:
            result = await handoff.coroutine(
                subagent_id="gmail",
                task="Fetch the unread messages.",
                config={
                    "configurable": {
                        "user_id": "u1",
                        "thread_id": "t1",
                        "workflow_id": "wf1",
                        HIL_RESUME_CONFIG_KEY: "replay",
                    }
                },
                tool_call_id="tc1",
            )

        assert result == "subagent ran"
        (run_ctx, dispatch) = seen["calls"][0]  # type: ignore[index]  # the seen bag holds mixed value types; mypy narrows to the first
        assert run_ctx is seen["ctx"]
        assert dispatch == _HandoffDispatch(
            metadata=metadata,
            agent_name="gmail_agent",
            integration_id="gmail",
            tool_call_id="tc1",
            probe_parked=True,
            record_calls=True,
        )

    async def test_the_background_fallback_runs_the_very_same_context_and_dispatch(self) -> None:
        with self._blocking_run(None) as seen:
            result = await handoff.coroutine(
                subagent_id="gmail",
                task="Fetch the unread messages.",
                background=True,
                config={"configurable": {"user_id": "u1", "thread_id": "t1"}},
                tool_call_id="tc1",
            )

        (run_ctx, dispatch) = seen["calls"][0]  # type: ignore[index]  # the seen bag holds mixed value types; mypy narrows to the first
        assert run_ctx is seen["ctx"]
        assert dispatch == _HandoffDispatch(
            metadata=None,
            agent_name="gmail_agent",
            integration_id="gmail",
            tool_call_id="tc1",
        )
        assert result == (
            "[WARNING: background handoff fell back to blocking: "
            "stream_id not propagated into executor configurable] subagent ran"
        )

    async def test_a_background_dispatch_is_handed_the_runs_stream_id(self) -> None:
        """``sid`` routes the detached result back to this conversation's bucket
        and keys its integration slot — the wrong one strands the result."""
        ctx = SimpleNamespace(agent_name="gmail_agent", integration_id="gmail")
        calls: list[tuple[object, object, object]] = []

        async def _dispatch(run_ctx: object, dispatch: object, sid: object) -> str:
            calls.append((run_ctx, dispatch, sid))
            return "started"

        with (
            patch(
                "app.agents.core.subagents.handoff_tools.prepare_subagent_execution",
                new_callable=AsyncMock,
                return_value=(ctx, None, None),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools._has_parked_subagent",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools._dispatch_background_handoff",
                new=_dispatch,
            ),
        ):
            result = await handoff.coroutine(
                subagent_id="gmail",
                task="Fetch the unread messages.",
                background=True,
                config={"configurable": {"user_id": "u1", "thread_id": "t1", "stream_id": "s1"}},
                tool_call_id="tc1",
            )

        assert result == "started"
        assert calls == [
            (
                ctx,
                _HandoffDispatch(
                    metadata=None,
                    agent_name="gmail_agent",
                    integration_id="gmail",
                    tool_call_id="tc1",
                ),
                "s1",
            )
        ]


@pytest.mark.unit
class TestHandoffPassesTheRunModeToTheRejectionCheck:
    """``background`` and ``stream_id`` decide which collision the pre-dispatch
    check is even looking for. Losing either turns the check on its head: a
    blocking run stops colliding with a live background task, or a background
    run starts refusing itself."""

    @staticmethod
    @contextmanager
    def _live_background_run_on(stream_id: str) -> Iterator[None]:
        ctx = SimpleNamespace(agent_name="gmail_agent", integration_id="gmail")

        def _has_bg(seen_stream_id: str, integration_id: str) -> bool:
            return (seen_stream_id, integration_id) == (stream_id, "gmail")

        async def _dispatch(_ctx: object, _handoff: object, _sid: object) -> str:
            return "started"

        with (
            patch(
                "app.agents.core.subagents.handoff_tools.prepare_subagent_execution",
                new_callable=AsyncMock,
                return_value=(ctx, None, None),
            ),
            patch(
                "app.agents.core.subagents.handoff_tools._has_parked_subagent",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.agents.core.subagents.handoff_tools.has_bg_integration", side_effect=_has_bg
            ),
            patch(
                "app.agents.core.subagents.handoff_tools._run_blocking_handoff",
                new_callable=AsyncMock,
                return_value="subagent ran",
            ),
            patch(
                "app.agents.core.subagents.handoff_tools._dispatch_background_handoff",
                new=_dispatch,
            ),
        ):
            yield

    async def test_a_blocking_handoff_checks_this_streams_background_slot(self) -> None:
        with self._live_background_run_on("s1"):
            result = await handoff.coroutine(
                subagent_id="gmail",
                task="Fetch the unread messages.",
                config={"configurable": {"user_id": "u1", "thread_id": "t1", "stream_id": "s1"}},
            )

        assert result == (
            "A background gmail_agent subagent is already running on this "
            "integration. Call wait_for_subagents() to collect it first."
        )

    async def test_a_background_handoff_is_not_refused_by_that_same_slot(self) -> None:
        with self._live_background_run_on("s1"):
            result = await handoff.coroutine(
                subagent_id="gmail",
                task="Fetch the unread messages.",
                background=True,
                config={"configurable": {"user_id": "u1", "thread_id": "t1", "stream_id": "s1"}},
            )

        assert result == "started"
