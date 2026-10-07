"""Invariants for Composio integrations and their auth configs.

A Composio integration is connectable only with a dashboard auth_config_id;
without one it must stay unavailable (hidden from the marketplace, refused by
connect, skipped by startup tool indexing). The model validator makes
"available with no auth config" impossible.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import ValidationError
import pytest

from app.agents.tools.core.registry import ToolRegistry
from app.config.oauth_config import (
    OAUTH_INTEGRATIONS,
    get_integration_by_id,
    get_integration_by_tool_slug,
)
from app.models.mcp_config import ComposioConfig
from app.models.oauth_models import OAuthIntegration

NEW_INTEGRATION_IDS = ("calcom", "calendly", "outlook", "jira", "dropbox")

COMPOSIO_INTEGRATIONS = [
    i for i in OAUTH_INTEGRATIONS if i.managed_by == "composio" and i.composio_config
]


def _composio_integration(*, available: bool, auth_config_id: str) -> OAuthIntegration:
    return OAuthIntegration(
        id="example",
        name="Example",
        description="Example",
        category="productivity",
        provider="example",
        scopes=[],
        available=available,
        managed_by="composio",
        composio_config=ComposioConfig(auth_config_id=auth_config_id, toolkit="EXAMPLE"),
    )


@pytest.mark.unit
class TestAuthConfigInvariant:
    def test_available_without_auth_config_id_is_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            _composio_integration(available=True, auth_config_id="")
        # Assert the exact wording (correct case, no mutmut XX-wrapper) so a
        # mutated message string is caught, not just that validation failed.
        message = str(exc_info.value)
        assert (
            "Integration 'example' is available but has no Composio auth_config_id; "
            "set it from the Composio dashboard or keep available=False." in message
        )
        assert "XX" not in message

    def test_unavailable_without_auth_config_id_is_allowed(self) -> None:
        assert _composio_integration(available=False, auth_config_id="").available is False

    def test_available_with_auth_config_id_is_allowed(self) -> None:
        assert _composio_integration(available=True, auth_config_id="ac_x").available is True


@pytest.mark.unit
@pytest.mark.parametrize("integration_id", NEW_INTEGRATION_IDS)
def test_new_integration_is_fully_configured_and_connectable(
    integration_id: str,
) -> None:
    integration = get_integration_by_id(integration_id)
    assert integration is not None
    assert integration.composio_config is not None
    assert integration.available is True
    assert integration.composio_config.auth_config_id.startswith("ac_")
    assert integration.subagent_config is not None
    assert integration.subagent_config.memory_prompt
    assert integration.content is not None
    assert integration.destructive_tools  # reviewed and non-empty


@pytest.mark.unit
@pytest.mark.parametrize(
    ("slug", "integration_id"),
    [
        # CAL is a prefix of CALENDLY's name but not of its slugs (CALENDLY_ vs
        # CAL_), so each toolkit must keep its own tools.
        ("CAL_FETCH_ALL_BOOKINGS", "calcom"),
        ("CALENDLY_LIST_SCHEDULED_EVENTS", "calendly"),
        ("OUTLOOK_SEND_EMAIL", "outlook"),
        ("JIRA_CREATE_ISSUE", "jira"),
        ("DROPBOX_READ_FILE", "dropbox"),
    ],
)
def test_tool_slugs_resolve_to_their_own_integration(slug: str, integration_id: str) -> None:
    integration = get_integration_by_tool_slug(slug)
    assert integration is not None
    assert integration.id == integration_id


@pytest.mark.unit
@pytest.mark.parametrize("integration", COMPOSIO_INTEGRATIONS, ids=lambda i: i.id)
class TestComposioConfigConsistency:
    def test_destructive_tools_belong_to_the_toolkit(self, integration: OAuthIntegration) -> None:
        prefix = f"{integration.composio_config.toolkit.upper()}_"
        for tool in integration.destructive_tools or []:
            assert tool.startswith(prefix), tool

    def test_auto_bound_tools_are_not_excluded(self, integration: OAuthIntegration) -> None:
        config = integration.subagent_config
        if config is None:
            return
        overlap = set(config.auto_bind_tools or []) & set(config.exclude_tools or [])
        assert not overlap


@pytest.mark.unit
async def test_provider_catalog_skips_unavailable_integrations() -> None:
    """Startup indexing must not fetch toolkits nobody can connect."""

    def _fake(integration_id: str, *, available: bool) -> SimpleNamespace:
        return SimpleNamespace(
            id=integration_id,
            available=available,
            managed_by="composio",
            composio_config=SimpleNamespace(toolkit=integration_id.upper()),
            subagent_config=SimpleNamespace(
                has_subagent=True,
                tool_space=integration_id,
                specific_tools=None,
                exclude_tools=None,
            ),
        )

    composio_service = MagicMock()
    composio_service.get_raw_tools_metadata = AsyncMock(
        return_value=[SimpleNamespace(slug="LIVE_TOOL", description="d")]
    )

    with (
        patch(
            "app.agents.tools.core.registry.OAUTH_INTEGRATIONS",
            [_fake("live", available=True), _fake("staged", available=False)],
        ),
        patch(
            "app.agents.tools.core.registry.get_composio_service",
            return_value=composio_service,
        ),
        patch("app.db.chroma.chroma_tools_store.index_tools_to_store", new=AsyncMock()),
        patch("app.agents.tools.core.registry.store_mcp_tools_batch", new=AsyncMock()),
    ):
        total = await ToolRegistry().populate_provider_catalog()

    assert total == 1
    composio_service.get_raw_tools_metadata.assert_awaited_once_with(
        tool_kit="LIVE", specific_tools=None
    )
