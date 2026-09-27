"""Tests for app.agents.core.subagents.handoff_tools."""

from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, ToolMessage
import pytest

from app.agents.core.subagents.handoff_tools import (
    CustomMcpIndexRequest,
    CustomMcpSubagent,
    _get_subagent_by_id,
    _handoff_rejection,
    _resolve_subagent,
    build_handoff_delegation,
    check_integration_connection,
    handoff,
    index_custom_mcp_as_subagent,
)
from app.agents.core.subagents.provider_subagents import SubagentUnavailableError
from app.agents.core.subagents.subagent_runner import SubagentOutcome, subagent_row_id
from app.constants.cache import SUBAGENT_CACHE_PREFIX, SUBAGENT_CACHE_TTL
from app.constants.hil import HIL_RESUME_CONFIG_KEY
from app.db.repositories.user_integrations import user_integration_repository
from app.models.agent_models import SubagentKind
from app.models.integration_models import Integration
from app.models.mcp_config import MCPConfig, SubAgentConfig
from app.models.subagent_models import Subagent
from app.utils.agent_utils import IntegrationMetadata
from tests.helpers import captured_wide_event

HANDOFF = "app.agents.core.subagents.handoff_tools"
DELEGATION = "app.agents.core.subagents.delegation"


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

    expired is the stored connection status the prompt reads to tell a dead
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
    """Return the integration id of every connect card pushed to the user's stream."""
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
        """check_integration_status only says "not usable" — the stored record stops a died connection reading as first-time."""
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
            ) as mock_get_cache,
        ):
            result = await _get_subagent_by_id("abc123")
        assert result == CustomMcpSubagent(id="abc123", name="Custom MCP")
        mock_get_cache.assert_awaited_once_with(f"{SUBAGENT_CACHE_PREFIX}:abc123")

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
            ) as mock_set_cache,
        ):
            mock_repo.find_by_id_prefix_or_name = AsyncMock(return_value=custom)
            result = await _get_subagent_by_id("abc")

        expected = CustomMcpSubagent(
            id="abc",
            name="My MCP",
            source="custom",
            managed_by="mcp",
            mcp_config=MCPConfig(server_url="https://example.com").model_dump(),
            icon_url="https://example.com/icon.png",
        )
        assert result == expected
        mock_set_cache.assert_awaited_once_with(
            f"{SUBAGENT_CACHE_PREFIX}:abc", expected.model_dump(), ttl=SUBAGENT_CACHE_TTL
        )

    async def test_fallback_to_integration_resolver(self):
        resolved_doc = {
            "integration_id": "res_id",
            "name": "Resolved",
            "mcp_config": {"server_url": "https://resolved.example.com"},
            "icon_url": "https://resolved.example.com/icon.png",
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
            ) as mock_set_cache,
        ):
            mock_repo.find_by_id_prefix_or_name = AsyncMock(return_value=None)
            mock_resolver.resolve = AsyncMock(return_value=resolved)
            result = await _get_subagent_by_id("res_id")

        expected = CustomMcpSubagent(
            id="res_id",
            name="Resolved",
            source="user_integrations",
            managed_by="mcp",
            mcp_config={"server_url": "https://resolved.example.com"},
            icon_url="https://resolved.example.com/icon.png",
        )
        assert result == expected
        mock_set_cache.assert_awaited_once_with(
            f"{SUBAGENT_CACHE_PREFIX}:res_id", expected.model_dump(), ttl=SUBAGENT_CACHE_TTL
        )


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
        with patch(
            "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
            new_callable=AsyncMock,
            return_value=None,
        ):
            graph, name, error, is_custom = await _resolve_subagent("unknown", "user1")
        assert graph is None
        assert "Unknown integration" in error

    async def test_a_known_integration_that_is_not_a_target_is_pointed_at_activation(self):
        with (
            patch(f"{HANDOFF}._get_subagent_by_id", new_callable=AsyncMock, return_value=None),
            patch(f"{HANDOFF}.get_subagent_by_id", return_value=SimpleNamespace(id="gmail")),
        ):
            _, _, error, _ = await _resolve_subagent("subagent:gmail", "user1")

        assert error == (
            "'subagent:gmail' is not a handoff target. Use "
            "activate_integration(integration_id='gmail') to load it "
            "in-context, then act on it yourself."
        )

    @pytest.mark.parametrize(
        ("known_ids", "examples"),
        [
            (["a", "b", "c", "d", "e", "f"], "a, b, c, d, e..."),
            (["a", "b"], "a, b"),
        ],
        ids=["more_than_five_are_elided", "a_short_list_is_complete"],
    )
    async def test_an_unknown_id_is_answered_with_up_to_five_examples(
        self, known_ids: list[str], examples: str
    ):
        with (
            patch(f"{HANDOFF}._get_subagent_by_id", new_callable=AsyncMock, return_value=None),
            patch(f"{HANDOFF}.get_subagent_by_id", return_value=None),
            patch(
                f"{HANDOFF}.all_subagents",
                return_value=[SimpleNamespace(id=known) for known in known_ids],
            ),
        ):
            _, _, error, _ = await _resolve_subagent("nope", "user1")

        assert error == f"Unknown integration 'nope'. Examples: {examples}"

    async def test_resolves_custom_mcp(self):
        custom_dict = {"id": "abc", "name": "Custom"}
        mock_graph = MagicMock()
        with (
            patch(
                "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
                new_callable=AsyncMock,
                return_value=CustomMcpSubagent.model_validate(custom_dict),
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
            return_value=CustomMcpSubagent.model_validate(custom_dict),
        ):
            graph, name, error, is_custom = await _resolve_subagent("abc", None)
        assert graph is None
        assert "authentication" in error.lower()

    async def test_custom_mcp_no_id_field(self):
        custom_dict = {"id": "", "name": "Broken"}
        with patch(
            "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
            new_callable=AsyncMock,
            return_value=CustomMcpSubagent.model_validate(custom_dict),
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
                return_value=CustomMcpSubagent.model_validate(custom_dict),
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
        """An unconnected auth'd MCP must show the connect card, not just promise one (managed_by="mcp", requires_auth=True)."""
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

    async def test_platform_non_mcp_redirects_to_activation(self):
        subagent = _make_subagent(
            "gcal",
            "gcal",
            "Google Calendar",
            managed_by="internal",
            agent_name="calendar_agent",
        )
        with patch(
            "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
            new_callable=AsyncMock,
            return_value=subagent,
        ):
            graph, name, error, is_custom = await _resolve_subagent("gcal", "user1")
        assert graph is None
        assert error == (
            "'gcal' is not a handoff target. Load it in-context with "
            "activate_integration(integration_id='gcal'), then act on "
            "it yourself with its tools."
        )

    async def test_a_redirect_to_activation_is_recorded_on_the_wide_event(self):
        subagent = _make_subagent("gcal", "gcal", "Google Calendar", managed_by="internal")
        with patch(f"{HANDOFF}._get_subagent_by_id", new_callable=AsyncMock, return_value=subagent):
            async with captured_wide_event() as event:
                await _resolve_subagent("gcal", "user1")

        assert event["handoff"] == {"integration": "gcal", "routed_to_activation": True}

    async def test_platform_composio_redirects_without_connection_check(self):
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
            ) as check,
        ):
            graph, name, error, is_custom = await _resolve_subagent("composio", "user1")
        assert graph is None
        assert "activate_integration" in error
        check.assert_not_awaited()

    async def test_platform_provider_redirects_to_activation(self):
        subagent = _make_subagent("x", "x", "X", managed_by="internal", agent_name="missing_agent")
        with patch(
            "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
            new_callable=AsyncMock,
            return_value=subagent,
        ):
            graph, name, error, is_custom = await _resolve_subagent("x", "user1")
        assert graph is None
        assert "activate_integration" in error
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
    """Make the connect prompt believe it runs on a text-only client, where the login-free link is minted instead of a UI card."""
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
    """The branch tests above mock fixed return values, so an argument-passing mutation could survive undetected.

    These fakes answer based on what they are handed, so a dropped or
    swapped argument changes the outcome instead of going unnoticed.
    """

    @staticmethod
    @contextmanager
    def _lookup_only(integration_id: str, subagent: Subagent) -> Iterator[None]:
        """get_subagent_by_id that recognises exactly one id."""
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
        """Checking the wrong user's or integration's connection could nag a connected user or wave through one who isn't."""
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
        """The prompt reads "None needs to be connected" if the display name is lost on the way there."""
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
        """On a text-only client, minting the login-free link for the wrong user hands one person another's connect flow."""
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
def _resolved_subagent(agent_name: str, integration_id: str) -> Iterator[AsyncMock]:
    """Stand up everything a handoff needs past resolution; yield the runner it hands off to."""
    ctx = SimpleNamespace(agent_name=agent_name, integration_id=integration_id)
    with (
        patch(
            f"{HANDOFF}.prepare_subagent_execution",
            new_callable=AsyncMock,
            return_value=(ctx, None, None),
        ),
        patch(f"{HANDOFF}._has_parked_subagent", new_callable=AsyncMock, return_value=False),
        patch(f"{HANDOFF}.delegate", new_callable=AsyncMock, return_value="subagent ran") as run,
    ):
        yield run


@pytest.mark.unit
class TestHandoffRejectsAForeignProviderInTheTask:
    """A task that names one provider while being routed to another produces a result claiming work the target never did — eight GAIA todos were reported to the user as "8 tasks created (Todoist)" from exactly this input."""

    PROD_TASK = (
        "Create these 8 separate tasks on Aryan's todo list (Todoist). Each one is its "
        "own task. Use clear, actionable titles:\n\n1. Buy Resend Pro to send emails"
    )

    async def test_the_prod_task_is_rejected_before_the_subagent_runs(self) -> None:
        with _resolved_subagent("todo_agent", "todos") as run:
            result = await handoff.coroutine(
                subagent_id="todos",
                task=self.PROD_TASK,
                config={"configurable": {"user_id": "u1", "thread_id": "t1"}},
            )

        run.assert_not_awaited()
        assert "Todoist" in result
        assert "activate_integration" in result
        assert "subagent:todoist" not in result

    async def test_the_same_task_without_the_provider_name_dispatches(self) -> None:
        with _resolved_subagent("todo_agent", "todos") as run:
            result = await handoff.coroutine(
                subagent_id="todos",
                task="Create these 8 separate tasks on Aryan's todo list.",
                config={"configurable": {"user_id": "u1", "thread_id": "t1"}},
            )

        run.assert_awaited_once()
        assert result == "subagent ran"

    async def test_the_provider_named_is_free_to_be_the_target(self) -> None:
        with _resolved_subagent("todoist_agent", "todoist") as run:
            result = await handoff.coroutine(
                subagent_id="todoist",
                task="Create 8 tasks in Todoist.",
                config={"configurable": {"user_id": "u1", "thread_id": "t1"}},
            )

        run.assert_awaited_once()
        assert result == "subagent ran"


@pytest.mark.unit
class TestHandoffRunsOnTheSharedRunner:
    """handoff decides nothing about how it runs: it hands the delegation and the caller's choice to the one runner spawn_subagent also uses."""

    async def test_it_defaults_to_the_background(self) -> None:
        with _resolved_subagent("mcp_agent", "my-mcp") as run:
            await handoff.coroutine(
                subagent_id="my-mcp",
                task="Fetch the rows.",
                config={"configurable": {"user_id": "u1", "thread_id": "t1"}},
            )

        assert run.await_args.kwargs == {"background": True, "probe_parked": False}

    async def test_the_delegation_is_keyed_by_the_calling_tool_call(self) -> None:
        with _resolved_subagent("mcp_agent", "my-mcp") as run:
            await handoff.coroutine(
                subagent_id="my-mcp",
                task="Fetch the rows.",
                config={"configurable": {"user_id": "u1", "thread_id": "t1"}},
                tool_call_id="tc9",
            )

        delegation = run.await_args.args[0]
        assert delegation.tool_call_id == "tc9"
        assert delegation.subagent_id == subagent_row_id("tc9")

    async def test_background_false_waits_for_the_result(self) -> None:
        with _resolved_subagent("mcp_agent", "my-mcp") as run:
            await handoff.coroutine(
                subagent_id="my-mcp",
                task="Fetch the rows.",
                background=False,
                config={"configurable": {"user_id": "u1", "thread_id": "t1"}},
            )

        assert run.await_args.kwargs["background"] is False

    async def test_a_resume_replay_arms_the_checkpoint_probe(self) -> None:
        with _resolved_subagent("mcp_agent", "my-mcp") as run:
            await handoff.coroutine(
                subagent_id="my-mcp",
                task="Fetch the rows.",
                config={
                    "configurable": {
                        "user_id": "u1",
                        "thread_id": "t1",
                        HIL_RESUME_CONFIG_KEY: True,
                    }
                },
            )

        assert run.await_args.kwargs["probe_parked"] is True

    async def test_a_user_id_only_in_run_metadata_is_the_one_the_subagent_runs_for(self) -> None:
        with patch(
            f"{HANDOFF}.prepare_subagent_execution",
            new_callable=AsyncMock,
            return_value=(None, None, "stop here"),
        ) as prepare:
            result = await handoff.coroutine(
                subagent_id="gmail",
                task="Fetch the unread messages.",
                config={"configurable": {"thread_id": "t1"}, "metadata": {"user_id": "u-meta"}},
                tool_call_id="tc1",
            )

        assert result == "stop here"
        assert prepare.call_args.kwargs["configurable"]["user_id"] == "u-meta"


@pytest.mark.unit
class TestHandoffBuildsItsDelegation:
    """build_handoff_delegation is also how a parked MCP subagent is rebuilt, so every field it sets is load-bearing twice."""

    @staticmethod
    def _prepared(metadata: IntegrationMetadata | None) -> Any:
        ctx = SimpleNamespace(agent_name="custom_mcp_ab12", integration_id="ab12")
        return patch(
            f"{HANDOFF}.prepare_subagent_execution",
            new_callable=AsyncMock,
            return_value=(ctx, metadata, None),
        )

    async def test_the_row_takes_the_integrations_display_metadata(self) -> None:
        metadata = IntegrationMetadata(
            icon_url="https://cdn.test/mcp.png", integration_id="ab12", name="Team Wiki"
        )
        parent = {"user_id": "u1", "thread_id": "executor_c1"}
        with self._prepared(metadata):
            delegation = await build_handoff_delegation("ab12", "find the doc", parent, "tc1")

        assert not isinstance(delegation, str)
        assert delegation.kind is SubagentKind.MCP
        assert delegation.subagent_id == subagent_row_id("tc1")
        assert delegation.integration_id == "ab12"
        assert delegation.parent_configurable is parent
        assert delegation.integration_metadata is metadata
        assert (delegation.display.name, delegation.display.icon_url) == (
            "Team Wiki",
            "https://cdn.test/mcp.png",
        )
        assert delegation.display.agent_type == "handoff"

    async def test_without_metadata_the_row_falls_back_to_the_agent_and_integration(self) -> None:
        with self._prepared(None):
            delegation = await build_handoff_delegation("ab12", "find the doc", {}, "tc1")

        assert not isinstance(delegation, str)
        assert delegation.display.name == "custom_mcp_ab12"
        assert delegation.display.tool_category == "ab12"
        assert delegation.display.icon_url is None

    async def test_an_unresolvable_subagent_returns_the_reason(self) -> None:
        with patch(
            f"{HANDOFF}.prepare_subagent_execution",
            new_callable=AsyncMock,
            return_value=(None, None, "not connected"),
        ):
            assert await build_handoff_delegation("ab12", "t", {}, "tc1") == "not connected"

    async def test_an_unresolvable_subagent_with_no_reason_still_says_so(self) -> None:
        with patch(
            f"{HANDOFF}.prepare_subagent_execution",
            new_callable=AsyncMock,
            return_value=(None, None, None),
        ):
            reason = await build_handoff_delegation("ab12", "t", {}, "tc1")

        assert reason == "Unknown error resolving subagent"

    async def test_the_task_runs_on_the_parents_stream_under_its_tool_call(self) -> None:
        parent = {"user_id": "u1", "stream_id": "parent-stream"}
        with self._prepared(None) as prepare:
            delegation = await build_handoff_delegation("ab12", "find the doc", parent, "tc1")

        assert prepare.await_args.kwargs == {
            "subagent_id": "ab12",
            "task": "find the doc",
            "configurable": parent,
            "stream_id": "parent-stream",
        }
        assert not isinstance(delegation, str)
        assert delegation.tool_call_id == "tc1"
        assert delegation.display.integration == "ab12"


@pytest.mark.unit
class TestWorkflowHandoffCarriesTheSubagentsCallRecord:
    """A workflow executor transcribes playbook steps from the handoff result; without the call record it guesses names and args.

    E.g. invented max_results for GMAIL_FETCH_MESSAGES whose real arg is
    max_messages. A chat run must stay byte-identical to the plain
    subagent text: no extra text, no extra tokens.
    """

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
        """Run the real runner over a faked subagent stream; the record append under test lives inside it."""
        ctx = SimpleNamespace(
            agent_name="gmail_agent",
            integration_id="gmail",
            configurable={},
            config={},
            stream_id=None,
        )
        registry = MagicMock(claim=AsyncMock(return_value=True), deregister=AsyncMock())
        with (
            patch(
                f"{HANDOFF}.prepare_subagent_execution",
                new_callable=AsyncMock,
                return_value=(ctx, None, None),
            ),
            patch(f"{HANDOFF}._has_parked_subagent", new_callable=AsyncMock, return_value=False),
            patch(f"{DELEGATION}.RunningSubagents", return_value=registry),
            patch(f"{DELEGATION}.get_stream_writer", return_value=MagicMock()),
            patch(
                f"{DELEGATION}.execute_subagent_stream",
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
                        "execution_mode": "background",
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
                background=False,
                config={"configurable": {"user_id": "u1", "thread_id": "t1"}},
            )

        assert result == "subagent ran"


# ---------------------------------------------------------------------------
# index_custom_mcp_as_subagent — the indexed document
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestIndexedCustomMcpDocument:
    """The indexed value IS the semantic-search document.

    Losing the description or tool summaries leaves the subagent ranking
    on just its own name, so a "meetings" query never surfaces the MCP
    that has get_meetings.
    """

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
    """Every return of the custom-MCP path is read out to the user verbatim.

    The is_custom flag decides whether the caller looks the integration's
    display metadata up in Mongo — a failure must never claim to be custom.
    """

    @staticmethod
    @contextmanager
    def _mongo_doc(doc: dict[str, object]) -> Iterator[None]:
        with patch(
            "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
            new_callable=AsyncMock,
            return_value=CustomMcpSubagent.model_validate(doc),
        ):
            yield

    async def test_a_document_with_no_id_key_is_rejected(self):
        """.get("id") without the "" default resolves a missing key to None, whose str() is the truthy "None"."""
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
        """A nulled or dropped argument here builds somebody else's subagent, with their tokens, under this user's handoff."""
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
    """The token store, connection probe and per-user graph all key on (integration_id, user_id); a nulled one reads another account's tokens."""

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


# ---------------------------------------------------------------------------
# _handoff_rejection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestHandoffRejectionMessages:
    """A refusal is the executor's only instruction on what to do instead, so the wording is behaviour, not decoration.

    Dropping the name gives the model "the None subagent is paused" to act on.
    """

    async def test_a_parked_subagent_refuses_new_work_and_says_its_result_is_coming(self):
        ctx = SimpleNamespace(agent_name="gmail_agent", integration_id="gmail")
        probed: list[object] = []

        async def _parked(candidate: object) -> bool:
            probed.append(candidate)
            return candidate is ctx

        with patch(f"{HANDOFF}._has_parked_subagent", new=_parked):
            rejection = await _handoff_rejection(ctx, "do the work")

        assert rejection == (
            "The gmail_agent subagent is paused waiting for the user's approval. "
            "It resumes on its own once the user decides and its result arrives in your "
            "inbox; send it nothing meanwhile."
        )
        assert probed == [ctx]

    async def test_an_unparked_subagent_with_a_clean_task_may_run(self):
        ctx = SimpleNamespace(agent_name="gmail_agent", integration_id="gmail")
        with patch(f"{HANDOFF}._has_parked_subagent", new_callable=AsyncMock, return_value=False):
            assert await _handoff_rejection(ctx, "do the work") is None


class TestHandoffRefusesProviderIds:
    """Provider and built-in integrations are not handoff targets: the tool redirects to activate_integration instead of building a graph.

    Only per-user MCP integrations proceed to dispatch.
    """

    async def test_provider_id_redirects_to_activation(self):
        subagent = _make_subagent("gmail", "gmail", "Gmail", managed_by="composio")
        with patch(
            "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
            new_callable=AsyncMock,
            return_value=subagent,
        ):
            result = await handoff.coroutine(
                subagent_id="gmail",
                task="Summarize the inbox.",
                config={"configurable": {"user_id": "u1", "thread_id": "t1"}},
            )
        assert "not a handoff target" in result
        assert "activate_integration(integration_id='gmail')" in result

    async def test_unknown_id_reports_unknown(self):
        with patch(
            "app.agents.core.subagents.handoff_tools._get_subagent_by_id",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await handoff.coroutine(
                subagent_id="nope",
                task="Do it.",
                config={"configurable": {"user_id": "u1", "thread_id": "t1"}},
            )
        assert "Unknown integration" in result
