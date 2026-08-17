"""Unit tests for app/services/integrations/marketplace.py.

Covers:
- get_all_integrations: category filtering, custom integrations, tool hydration, sorting
- get_integration_details: platform, custom, not found, creator info, stored tools
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.user_models import UserDocument
from app.services.integrations.marketplace import assemble_integration_response

MODULE = "app.services.integrations.marketplace"


def _make_oauth_integration(
    id: str = "gmail",
    name: str = "Gmail",
    category: str = "communication",
    available: bool = True,
    is_featured: bool = False,
    display_priority: int = 0,
) -> MagicMock:
    """Build a mock OAuthIntegration."""
    oauth = MagicMock()
    oauth.id = id
    oauth.name = name
    oauth.description = "Test integration"
    oauth.category = category
    oauth.available = available
    oauth.is_featured = is_featured
    oauth.display_priority = display_priority
    oauth.managed_by = "composio"
    oauth.mcp_config = None
    oauth.composio_config = MagicMock()
    return oauth


@pytest.fixture(autouse=True)
def _patch_log():
    with patch(f"{MODULE}.log"):
        yield


class TestGetAllIntegrations:
    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_all_mcp_tools", new_callable=AsyncMock)
    @patch(f"{MODULE}.integration_repository")
    @patch(f"{MODULE}.OAUTH_INTEGRATIONS", [])
    async def test_empty_marketplace(self, mock_repo: MagicMock, mock_get_all: AsyncMock) -> None:
        mock_get_all.return_value = {}

        # Empty cursor
        mock_repo.list_public_custom = AsyncMock(return_value=[])

        from app.services.integrations.marketplace import get_all_integrations

        result = await get_all_integrations()
        assert result.total == 0
        assert result.integrations == []
        assert result.featured == []

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_all_mcp_tools", new_callable=AsyncMock)
    @patch(f"{MODULE}.integration_repository")
    @patch(f"{MODULE}.OAUTH_INTEGRATIONS")
    async def test_platform_integrations_returned(
        self,
        mock_oauth_list: MagicMock,
        mock_repo: MagicMock,
        mock_get_all: AsyncMock,
    ) -> None:
        mock_get_all.return_value = {}

        mock_repo.list_public_custom = AsyncMock(return_value=[])

        oauth = _make_oauth_integration()
        mock_oauth_list.__iter__ = MagicMock(return_value=iter([oauth]))

        from app.services.integrations.marketplace import get_all_integrations

        result = await get_all_integrations()
        assert result.total == 1
        assert result.integrations[0].name == "Gmail"

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_all_mcp_tools", new_callable=AsyncMock)
    @patch(f"{MODULE}.integration_repository")
    @patch(f"{MODULE}.OAUTH_INTEGRATIONS")
    async def test_unavailable_integration_excluded(
        self,
        mock_oauth_list: MagicMock,
        mock_repo: MagicMock,
        mock_get_all: AsyncMock,
    ) -> None:
        mock_get_all.return_value = {}

        mock_repo.list_public_custom = AsyncMock(return_value=[])

        oauth = _make_oauth_integration(available=False)
        mock_oauth_list.__iter__ = MagicMock(return_value=iter([oauth]))

        from app.services.integrations.marketplace import get_all_integrations

        result = await get_all_integrations()
        assert result.total == 0

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_all_mcp_tools", new_callable=AsyncMock)
    @patch(f"{MODULE}.integration_repository")
    @patch(f"{MODULE}.OAUTH_INTEGRATIONS")
    async def test_category_filter(
        self,
        mock_oauth_list: MagicMock,
        mock_repo: MagicMock,
        mock_get_all: AsyncMock,
    ) -> None:
        mock_get_all.return_value = {}

        mock_repo.list_public_custom = AsyncMock(return_value=[])

        gmail = _make_oauth_integration("gmail", "Gmail", "communication")
        github = _make_oauth_integration("github", "GitHub", "developer")
        mock_oauth_list.__iter__ = MagicMock(return_value=iter([gmail, github]))

        from app.services.integrations.marketplace import get_all_integrations

        result = await get_all_integrations(category="developer")
        assert result.total == 1
        assert result.integrations[0].name == "GitHub"

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_all_mcp_tools", new_callable=AsyncMock)
    @patch(f"{MODULE}.integration_repository")
    @patch(f"{MODULE}.OAUTH_INTEGRATIONS")
    async def test_tool_hydration_from_store(
        self,
        mock_oauth_list: MagicMock,
        mock_repo: MagicMock,
        mock_get_all: AsyncMock,
    ) -> None:
        mock_get_all.return_value = {
            "gmail": {
                "tools": [{"name": "send_email", "description": "Send an email"}],
                "name": "Gmail",
            }
        }

        mock_repo.list_public_custom = AsyncMock(return_value=[])

        oauth = _make_oauth_integration("gmail", "Gmail")
        mock_oauth_list.__iter__ = MagicMock(return_value=iter([oauth]))

        from app.services.integrations.marketplace import get_all_integrations

        result = await get_all_integrations()
        assert len(result.integrations[0].tools) == 1
        assert result.integrations[0].tools[0].name == "send_email"

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_all_mcp_tools", new_callable=AsyncMock)
    @patch(f"{MODULE}.integration_repository")
    @patch(f"{MODULE}.OAUTH_INTEGRATIONS")
    async def test_featured_sorted(
        self,
        mock_oauth_list: MagicMock,
        mock_repo: MagicMock,
        mock_get_all: AsyncMock,
    ) -> None:
        mock_get_all.return_value = {}

        mock_repo.list_public_custom = AsyncMock(return_value=[])

        gmail = _make_oauth_integration("gmail", "Gmail", is_featured=True, display_priority=5)
        github = _make_oauth_integration("github", "GitHub", is_featured=True, display_priority=10)
        mock_oauth_list.__iter__ = MagicMock(return_value=iter([gmail, github]))

        from app.services.integrations.marketplace import get_all_integrations

        result = await get_all_integrations()
        assert len(result.featured) == 2
        # Higher priority first
        assert result.featured[0].name == "GitHub"

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_all_mcp_tools", new_callable=AsyncMock)
    @patch(f"{MODULE}.integration_repository")
    @patch(f"{MODULE}.OAUTH_INTEGRATIONS", [])
    async def test_exclude_custom_public(
        self, mock_repo: MagicMock, mock_get_all: AsyncMock
    ) -> None:
        mock_get_all.return_value = {}

        from app.services.integrations.marketplace import get_all_integrations

        result = await get_all_integrations(include_custom_public=False)
        # list_public_custom should NOT be called when include_custom_public=False
        # (fetch_custom_integrations returns early)
        mock_repo.list_public_custom.assert_not_called()
        assert result.total == 0


class TestAssembleIntegrationResponse:
    def test_custom_doc_fields_flow_into_the_assembled_response(self) -> None:
        """With no platform integration, the response carries the custom doc's own fields."""
        custom_doc = {
            "integration_id": "distinctive-custom-id",
            "name": "Distinctive Custom Name",
            "description": "Distinctive custom description",
            "category": "productivity",
            "managed_by": "mcp",
        }

        result = assemble_integration_response(
            platform_integration=None,
            custom_doc=custom_doc,
            stored_tools=None,
            creator_doc=None,
        )

        assert result is not None
        assert result.integration_id == "distinctive-custom-id"
        assert result.name == "Distinctive Custom Name"
        assert result.description == "Distinctive custom description"

    def test_stored_tools_hydrate_both_name_and_description(self) -> None:
        """A stored tool keeps both its name and its description on the assembled response."""
        oauth = _make_oauth_integration("gmail", "Gmail")
        stored_tools = [
            {"name": "distinctive_tool_name", "description": "distinctive tool description"}
        ]

        result = assemble_integration_response(
            platform_integration=oauth,
            custom_doc=None,
            stored_tools=stored_tools,
            creator_doc=None,
        )

        assert result is not None
        assert len(result.tools) == 1
        assert result.tools[0].name == "distinctive_tool_name"
        assert result.tools[0].description == "distinctive tool description"


class TestGetIntegrationDetails:
    @pytest.mark.asyncio
    @patch(f"{MODULE}.user_repository")
    @patch(f"{MODULE}.IntegrationResolver")
    @patch(f"{MODULE}.get_integration_tools", new_callable=AsyncMock)
    async def test_not_found(
        self,
        mock_get_tools: AsyncMock,
        mock_resolver: MagicMock,
        mock_users: MagicMock,
    ) -> None:
        mock_get_tools.return_value = []
        mock_resolver.resolve = AsyncMock(return_value=None)

        from app.services.integrations.marketplace import get_integration_details

        result = await get_integration_details("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    @patch(f"{MODULE}.user_repository")
    @patch(f"{MODULE}.IntegrationResolver")
    @patch(f"{MODULE}.get_integration_tools", new_callable=AsyncMock)
    async def test_platform_integration(
        self,
        mock_get_tools: AsyncMock,
        mock_resolver: MagicMock,
        mock_users: MagicMock,
    ) -> None:
        mock_get_tools.return_value = []

        resolved = MagicMock()
        resolved.platform_integration = _make_oauth_integration("gmail", "Gmail")
        resolved.custom_doc = None
        mock_resolver.resolve = AsyncMock(return_value=resolved)

        from app.services.integrations.marketplace import get_integration_details

        result = await get_integration_details("gmail")
        assert result is not None
        assert result.name == "Gmail"

    @pytest.mark.asyncio
    @patch(f"{MODULE}.user_repository")
    @patch(f"{MODULE}.IntegrationResolver")
    @patch(f"{MODULE}.get_integration_tools", new_callable=AsyncMock)
    async def test_stored_tools_hydrated(
        self,
        mock_get_tools: AsyncMock,
        mock_resolver: MagicMock,
        mock_users: MagicMock,
    ) -> None:
        stored = [{"name": "tool1", "description": "desc1"}]
        mock_get_tools.return_value = stored

        resolved = MagicMock()
        resolved.platform_integration = _make_oauth_integration("gmail", "Gmail")
        resolved.custom_doc = None
        mock_resolver.resolve = AsyncMock(return_value=resolved)

        from app.services.integrations.marketplace import get_integration_details

        result = await get_integration_details("gmail")
        assert result is not None
        assert len(result.tools) == 1
        assert result.tools[0].name == "tool1"

    @pytest.mark.asyncio
    @patch(f"{MODULE}.user_repository")
    @patch(f"{MODULE}.IntegrationResolver")
    @patch(f"{MODULE}.get_integration_tools", new_callable=AsyncMock)
    async def test_creator_info_populated(
        self,
        mock_get_tools: AsyncMock,
        mock_resolver: MagicMock,
        mock_users: MagicMock,
    ) -> None:
        mock_get_tools.return_value = []

        resolved = MagicMock()
        resolved.platform_integration = _make_oauth_integration("gmail", "Gmail")
        # custom_doc must be a dict with 'created_by' so the code fetches creator info
        resolved.custom_doc = {"created_by": "507f1f77bcf86cd799439011"}  # pragma: allowlist secret
        mock_resolver.resolve = AsyncMock(return_value=resolved)

        from app.services.integrations.marketplace import get_integration_details

        with patch(f"{MODULE}.IntegrationResponse.from_oauth_integration") as mock_from_oauth:
            resp = MagicMock()
            resp.tools = []
            mock_from_oauth.return_value = resp
            mock_users.get = AsyncMock(
                return_value=UserDocument(name="Creator", picture="https://pic.com")
            )

            result = await get_integration_details("gmail")

        assert result.creator == {"name": "Creator", "picture": "https://pic.com"}  # type: ignore[union-attr]

    @pytest.mark.asyncio
    @patch(f"{MODULE}.user_repository")
    @patch(f"{MODULE}.IntegrationResolver")
    @patch(f"{MODULE}.get_integration_tools", new_callable=AsyncMock)
    async def test_resolved_no_platform_no_custom(
        self,
        mock_get_tools: AsyncMock,
        mock_resolver: MagicMock,
        mock_users: MagicMock,
    ) -> None:
        mock_get_tools.return_value = []

        resolved = MagicMock()
        resolved.platform_integration = None
        resolved.custom_doc = None
        mock_resolver.resolve = AsyncMock(return_value=resolved)

        from app.services.integrations.marketplace import get_integration_details

        result = await get_integration_details("unknown")
        assert result is None
