"""Tests for app.agents.core.subagents.handoff_tools."""

from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.core.subagents.handoff_tools import (
    _get_subagent_by_id,
    _resolve_subagent,
    check_integration_connection,
    index_custom_mcp_as_subagent,
)
from app.agents.core.subagents.provider_subagents import SubagentUnavailableError
from app.db.repositories.user_integrations import user_integration_repository
from app.models.integration_models import Integration
from app.models.mcp_config import MCPConfig, SubAgentConfig
from app.models.subagent_models import Subagent


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
        managed_by=managed_by,  # type: ignore[arg-type]
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
                integration_id="abc123",
                name="My Tool",
                description="Does stuff",
                server_url="https://example.com/mcp",
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
        assert "no ID" in error

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
        assert "authentication" in error.lower()

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
        assert "not available" in error

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
        assert "is unavailable" in error


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
