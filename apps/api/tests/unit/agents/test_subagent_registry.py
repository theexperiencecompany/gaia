"""Unit tests for the subagent registry (`app.agents.core.subagents.registry`).

These tests cover `all_subagents()` (OAuth-derived + builtins) and
`get_subagent_by_id()`. Moved here from `test_subagent_runner.py` after the
refactor that introduced the `Subagent` dataclass and centralized lookups in
the registry module.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.agents.core.subagents.builtin_subagents import BUILTIN_SUBAGENTS
from app.agents.core.subagents.registry import (
    _from_oauth,
    all_subagents,
    get_subagent_by_id,
)
from app.models.mcp_config import ComposioConfig, MCPConfig, SubAgentConfig
from app.models.oauth_models import OAuthIntegration
from app.models.subagent_models import Subagent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_subagent_config(
    integration_id: str = "github",
    agent_name: str = "github_agent",
) -> SubAgentConfig:
    return SubAgentConfig(
        has_subagent=True,
        agent_name=agent_name,
        tool_space=f"{integration_id}_space",
        handoff_tool_name=f"call_{integration_id}",
        domain=integration_id,
        capabilities=f"{integration_id} capabilities",
        use_cases=f"{integration_id} use cases",
        system_prompt=f"You are the {integration_id} agent.",
    )


def _make_real_oauth_integration(
    integration_id: str = "github",
    short_name: str | None = "gh",
    has_subagent: bool = True,
    agent_name: str = "github_agent",
    provider: str = "github",
    mcp_config: MCPConfig | None = None,
) -> OAuthIntegration:
    """Build a real `OAuthIntegration` instance (not a MagicMock).

    Used in `_from_oauth` and identity-check tests where a real Pydantic
    model is required so attribute access goes through field validation.
    """
    return OAuthIntegration(
        id=integration_id,
        name=integration_id.title(),
        description=f"{integration_id} integration",
        category="productivity",
        provider=provider,
        scopes=[],
        short_name=short_name,
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id=f"auth_{integration_id}",
            toolkit=integration_id,
        ),
        subagent_config=(
            _make_subagent_config(integration_id, agent_name) if has_subagent else None
        ),
        mcp_config=mcp_config,
    )


def _make_integration(
    integration_id: str = "github",
    short_name: str = "gh",
    has_subagent: bool = True,
    agent_name: str = "github_agent",
    provider: str = "github",
) -> MagicMock:
    """Build a mock OAuthIntegration that the registry's _from_oauth can adapt."""

    if has_subagent:
        subagent_cfg = SubAgentConfig(
            has_subagent=True,
            agent_name=agent_name,
            tool_space=f"{integration_id}_space",
            handoff_tool_name=f"call_{integration_id}",
            domain=integration_id,
            capabilities=f"{integration_id} capabilities",
            use_cases=f"{integration_id} use cases",
            system_prompt=f"You are the {integration_id} agent.",
        )
    else:
        subagent_cfg = None  # type: ignore[assignment]

    integration = MagicMock()
    integration.id = integration_id
    integration.name = integration_id.title()
    integration.short_name = short_name
    integration.provider = provider
    integration.managed_by = "composio"
    integration.subagent_config = subagent_cfg
    integration.mcp_config = None
    return integration


def _make_integration_no_subagent(integration_id: str = "stripe") -> MagicMock:
    return _make_integration(
        integration_id=integration_id,
        short_name=None,  # type: ignore[arg-type]
        has_subagent=False,
    )


FAKE_INTEGRATIONS = [
    _make_integration("github", "gh", True, "github_agent"),
    _make_integration("gmail", "gmail", True, "gmail_agent"),
    _make_integration_no_subagent("stripe"),
]


def _clear_registry_cache() -> None:
    """`all_subagents()` is `@functools.cache`d. Tests that patch
    OAUTH_INTEGRATIONS or BUILTIN_SUBAGENTS must clear the cache first."""
    all_subagents.cache_clear()


# ---------------------------------------------------------------------------
# all_subagents — OAuth-derived filtering
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAllSubagents:
    def test_filters_integrations_with_subagent(self):
        _clear_registry_cache()
        with (
            patch(
                "app.agents.core.subagents.registry.OAUTH_INTEGRATIONS",
                FAKE_INTEGRATIONS,
            ),
            patch("app.agents.core.subagents.registry.BUILTIN_SUBAGENTS", ()),
        ):
            result = all_subagents()

        assert len(result) == 2
        ids = [s.id for s in result]
        assert "github" in ids
        assert "gmail" in ids
        assert "stripe" not in ids

    def test_empty_integrations(self):
        _clear_registry_cache()
        with (
            patch("app.agents.core.subagents.registry.OAUTH_INTEGRATIONS", []),
            patch("app.agents.core.subagents.registry.BUILTIN_SUBAGENTS", ()),
        ):
            assert all_subagents() == ()


# ---------------------------------------------------------------------------
# get_subagent_by_id
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetSubagentById:
    def test_find_by_id(self):
        _clear_registry_cache()
        with (
            patch(
                "app.agents.core.subagents.registry.OAUTH_INTEGRATIONS",
                FAKE_INTEGRATIONS,
            ),
            patch("app.agents.core.subagents.registry.BUILTIN_SUBAGENTS", ()),
        ):
            result = get_subagent_by_id("github")
        assert result is not None
        assert result.id == "github"

    def test_find_by_short_name(self):
        _clear_registry_cache()
        with (
            patch(
                "app.agents.core.subagents.registry.OAUTH_INTEGRATIONS",
                FAKE_INTEGRATIONS,
            ),
            patch("app.agents.core.subagents.registry.BUILTIN_SUBAGENTS", ()),
        ):
            result = get_subagent_by_id("gh")
        assert result is not None
        assert result.id == "github"

    def test_case_insensitive(self):
        _clear_registry_cache()
        with (
            patch(
                "app.agents.core.subagents.registry.OAUTH_INTEGRATIONS",
                FAKE_INTEGRATIONS,
            ),
            patch("app.agents.core.subagents.registry.BUILTIN_SUBAGENTS", ()),
        ):
            result = get_subagent_by_id("GITHUB")
        assert result is not None

    def test_not_found(self):
        _clear_registry_cache()
        with (
            patch(
                "app.agents.core.subagents.registry.OAUTH_INTEGRATIONS",
                FAKE_INTEGRATIONS,
            ),
            patch("app.agents.core.subagents.registry.BUILTIN_SUBAGENTS", ()),
        ):
            result = get_subagent_by_id("nonexistent")
        assert result is None

    def test_integration_without_subagent_not_returned(self):
        _clear_registry_cache()
        with (
            patch(
                "app.agents.core.subagents.registry.OAUTH_INTEGRATIONS",
                FAKE_INTEGRATIONS,
            ),
            patch("app.agents.core.subagents.registry.BUILTIN_SUBAGENTS", ()),
        ):
            result = get_subagent_by_id("stripe")
        assert result is None

    def test_strips_whitespace(self):
        _clear_registry_cache()
        with (
            patch(
                "app.agents.core.subagents.registry.OAUTH_INTEGRATIONS",
                FAKE_INTEGRATIONS,
            ),
            patch("app.agents.core.subagents.registry.BUILTIN_SUBAGENTS", ()),
        ):
            result = get_subagent_by_id("  github  ")
        assert result is not None


# ---------------------------------------------------------------------------
# _from_oauth — adapter from OAuthIntegration to Subagent
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFromOauth:
    def test_raises_when_subagent_config_is_none(self) -> None:
        integ = _make_real_oauth_integration(
            integration_id="stripe", short_name=None, has_subagent=False
        )

        with pytest.raises(ValueError, match="without subagent_config"):
            _from_oauth(integ)

    def test_returns_subagent_with_field_for_field_correspondence(self) -> None:
        mcp_config = MCPConfig(server_url="https://example.com/mcp")
        integ = _make_real_oauth_integration(
            integration_id="github",
            short_name="gh",
            agent_name="github_agent",
            provider="github",
            mcp_config=mcp_config,
        )

        result = _from_oauth(integ)

        assert isinstance(result, Subagent)
        assert result.id == integ.id
        assert result.name == integ.name
        assert result.provider == integ.provider
        assert result.managed_by == integ.managed_by
        assert result.short_name == integ.short_name
        assert result.mcp_config is integ.mcp_config

    def test_config_is_same_object_as_integration_subagent_config(self) -> None:
        # Identity check (not equality): the registry MUST pass through the
        # integration's SubAgentConfig instance unchanged. Re-instantiating it
        # would be a wasted allocation and make tests that mutate config
        # behave inconsistently.
        integ = _make_real_oauth_integration(integration_id="github")

        result = _from_oauth(integ)

        assert result.config is integ.subagent_config


# ---------------------------------------------------------------------------
# all_subagents — caching, ordering, builtins inclusion
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAllSubagentsCachingAndOrdering:
    def test_includes_oauth_and_builtins_in_order(self) -> None:
        _clear_registry_cache()
        oauth_integ = _make_real_oauth_integration(integration_id="github")
        invalid_integ = _make_real_oauth_integration(
            integration_id="stripe", short_name=None, has_subagent=False
        )
        builtin = Subagent(
            id="builtin_one",
            name="Builtin One",
            provider="builtin_one",
            managed_by="internal",
            config=_make_subagent_config("builtin_one", "builtin_one_agent"),
        )

        with (
            patch(
                "app.agents.core.subagents.registry.OAUTH_INTEGRATIONS",
                [oauth_integ, invalid_integ],
            ),
            patch(
                "app.agents.core.subagents.registry.BUILTIN_SUBAGENTS",
                (builtin,),
            ),
        ):
            result = all_subagents()

        # Only the valid OAuth integration + the builtin — invalid one is
        # filtered out by the `i.subagent_config and i.subagent_config.has_subagent`
        # guard in registry.all_subagents.
        assert len(result) == 2
        assert result[0].id == "github"
        assert result[1].id == "builtin_one"

    def test_result_is_cached_by_identity(self) -> None:
        _clear_registry_cache()
        with (
            patch("app.agents.core.subagents.registry.OAUTH_INTEGRATIONS", []),
            patch("app.agents.core.subagents.registry.BUILTIN_SUBAGENTS", ()),
        ):
            first = all_subagents()
            second = all_subagents()

        assert first is second

    def test_cache_clear_returns_fresh_tuple(self) -> None:
        # Use both an OAuth-derived AND a builtin entry so the result is
        # `tuple(...) + (builtin,)` — a freshly allocated tuple each call.
        # CPython optimizes `() + non_empty_tuple` to return the non-empty
        # tuple itself, which would break identity-inequality assertions.
        builtin = Subagent(
            id="builtin_for_cache_test",
            name="Builtin",
            provider="builtin_for_cache_test",
            managed_by="internal",
            config=_make_subagent_config("builtin_for_cache_test", "builtin_for_cache_test_agent"),
        )
        _clear_registry_cache()
        with (
            patch(
                "app.agents.core.subagents.registry.OAUTH_INTEGRATIONS",
                [_make_integration("github")],
            ),
            patch(
                "app.agents.core.subagents.registry.BUILTIN_SUBAGENTS",
                (builtin,),
            ),
        ):
            first = all_subagents()
            all_subagents.cache_clear()
            second = all_subagents()

        # After cache_clear the call re-executes and produces a fresh tuple
        # object with equal contents.
        assert first == second
        assert first is not second


# ---------------------------------------------------------------------------
# get_subagent_by_id — additional coverage with builtins and edge keys
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetSubagentByIdExtended:
    def test_finds_real_gaia_builtin(self) -> None:
        _clear_registry_cache()
        # Patch out OAuth integrations but keep the real BUILTIN_SUBAGENTS.
        with patch("app.agents.core.subagents.registry.OAUTH_INTEGRATIONS", []):
            result = get_subagent_by_id("gaia_knowledge_guide")

        assert result is not None
        assert result.id == "gaia_knowledge_guide"
        assert result is BUILTIN_SUBAGENTS[0]

    def test_finds_real_gaia_builtin_uppercase(self) -> None:
        _clear_registry_cache()
        with patch("app.agents.core.subagents.registry.OAUTH_INTEGRATIONS", []):
            result = get_subagent_by_id("GAIA_KNOWLEDGE_GUIDE")

        assert result is not None
        assert result.id == "gaia_knowledge_guide"

    def test_finds_real_gaia_builtin_with_whitespace(self) -> None:
        _clear_registry_cache()
        with patch("app.agents.core.subagents.registry.OAUTH_INTEGRATIONS", []):
            result = get_subagent_by_id("  gaia_knowledge_guide  ")

        assert result is not None
        assert result.id == "gaia_knowledge_guide"

    def test_unknown_id_returns_none_without_raising(self) -> None:
        _clear_registry_cache()
        with (
            patch("app.agents.core.subagents.registry.OAUTH_INTEGRATIONS", []),
            patch("app.agents.core.subagents.registry.BUILTIN_SUBAGENTS", ()),
        ):
            assert get_subagent_by_id("does_not_exist") is None

    def test_short_name_lookup_with_real_integration(self) -> None:
        _clear_registry_cache()
        oauth_integ = _make_real_oauth_integration(integration_id="github", short_name="gh")

        with (
            patch(
                "app.agents.core.subagents.registry.OAUTH_INTEGRATIONS",
                [oauth_integ],
            ),
            patch("app.agents.core.subagents.registry.BUILTIN_SUBAGENTS", ()),
        ):
            result = get_subagent_by_id("gh")

        assert result is not None
        assert result.id == "github"

    def test_does_not_match_by_agent_name(self) -> None:
        # `agent_name` lives in a separate key space — it's the LangGraph
        # provider name, not a lookup key. Looking up by it must return None.
        _clear_registry_cache()
        with patch("app.agents.core.subagents.registry.OAUTH_INTEGRATIONS", []):
            assert get_subagent_by_id("gaia_knowledge_guide_agent") is None
