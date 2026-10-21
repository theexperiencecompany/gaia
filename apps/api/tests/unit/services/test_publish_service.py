"""Unit tests for integration publishing (publish_service + publish_validator).

Publishing runs a gauntlet of ownership/connection/validation checks before
writing — each guard must produce its PublishError, and the happy path must
return the marketplace URL contract.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.models.integration_models import Integration, StoredIntegrationTool
from app.models.mcp_config import MCPConfig
from app.models.oauth_models import IntegrationContent
from app.services.integrations.publish_service import (
    PublishError,
    publish_custom_integration,
    unpublish_custom_integration,
)

_MOD = "app.services.integrations.publish_service"
USER_ID = "507f1f77bcf86cd799439011"
INTEGRATION_ID = "my-integration-123"


def _integration(**overrides: object) -> Integration:
    data: dict[str, object] = {
        "integration_id": INTEGRATION_ID,
        "name": "My Integration",
        "description": "A handy tool",
        "category": "custom",
        "managed_by": "mcp",
        "source": "custom",
        "created_by": USER_ID,
        "is_public": False,
        "tools": [StoredIntegrationTool(name="lookup", description="Look things up")],
        "mcp_config": None,
    }
    data.update(overrides)
    return Integration(**data)


@pytest.fixture
def mock_deps():
    with (
        patch(f"{_MOD}.integration_repository") as m_repo,
        patch(f"{_MOD}.user_integration_repository") as m_user,
        patch(
            f"{_MOD}.PublishIntegrationValidator.validate_for_publish", new_callable=AsyncMock
        ) as m_validate,
        patch(f"{_MOD}.infer_integration_category", new_callable=AsyncMock) as m_category,
        patch(f"{_MOD}.infer_integration_content", new_callable=AsyncMock) as m_content,
        patch(f"{_MOD}.index_public_integration", new_callable=AsyncMock) as m_index,
        patch(f"{_MOD}.remove_public_integration", new_callable=AsyncMock) as m_remove,
        patch(f"{_MOD}.delete_cache_by_pattern", new_callable=AsyncMock) as m_clear,
        patch(f"{_MOD}.invalidate_user_integration_caches", new_callable=AsyncMock) as m_invalidate,
    ):
        m_repo.get = AsyncMock(return_value=None)
        m_repo.ensure_unique_slug = AsyncMock(return_value="my-integration")
        m_repo.publish = AsyncMock(return_value=True)
        m_repo.get_by_creator = AsyncMock(return_value=None)
        m_repo.unpublish = AsyncMock(return_value=True)
        m_user.is_connected = AsyncMock(return_value=True)
        m_validate.return_value = []
        m_category.return_value = "productivity"
        m_content.return_value = IntegrationContent(
            use_cases=["a"] * 5,
            how_it_works=[{"title": "t", "body": "b"}] * 3,
            faqs=[{"question": "q", "answer": "a"}] * 4,
        )
        yield SimpleNamespace(
            repo=m_repo,
            user=m_user,
            validate=m_validate,
            category=m_category,
            content=m_content,
            index=m_index,
            remove=m_remove,
            clear=m_clear,
            invalidate=m_invalidate,
        )


class TestPublishCustomIntegration:
    async def test_publishes_and_returns_marketplace_url(self, mock_deps):
        mock_deps.repo.get.return_value = _integration()

        result = await publish_custom_integration(INTEGRATION_ID, USER_ID)

        assert result == "/marketplace/my-integration"
        assert mock_deps.repo.ensure_unique_slug.await_args.kwargs == {
            "name": "My Integration",
            "category": "productivity",
            "integration_id": INTEGRATION_ID,
        }
        assert mock_deps.repo.publish.await_args.kwargs["created_by"] == USER_ID
        assert mock_deps.repo.publish.await_args.kwargs["slug"] == "my-integration"
        # The validator and the Chroma index take the dumped tools, not the
        # models: a None here publishes an integration whose tools are
        # unsearchable and unvalidated, with nothing else going wrong.
        dumped = [{"name": "lookup", "description": "Look things up"}]
        assert mock_deps.validate.await_args.kwargs["tools"] == dumped
        assert mock_deps.index.await_args.kwargs["tools"] == dumped
        mock_deps.clear.assert_awaited_once_with("marketplace:community:*")
        mock_deps.invalidate.assert_awaited_once_with(USER_ID)

    async def test_404_when_integration_missing(self, mock_deps):
        with pytest.raises(PublishError) as exc_info:
            await publish_custom_integration(INTEGRATION_ID, USER_ID)

        assert exc_info.value.status_code == 404
        assert "not found" in exc_info.value.message

    async def test_403_when_not_creator(self, mock_deps):
        mock_deps.repo.get.return_value = _integration(created_by="someone-else")

        with pytest.raises(PublishError) as exc_info:
            await publish_custom_integration(INTEGRATION_ID, USER_ID)

        assert exc_info.value.status_code == 403
        assert "you created" in exc_info.value.message

    async def test_rejects_platform_integrations(self, mock_deps):
        mock_deps.repo.get.return_value = _integration(source="platform")

        with pytest.raises(PublishError) as exc_info:
            await publish_custom_integration(INTEGRATION_ID, USER_ID)

        assert exc_info.value.status_code == 400
        assert "Only custom integrations" in exc_info.value.message

    async def test_requires_connected(self, mock_deps):
        mock_deps.repo.get.return_value = _integration()
        mock_deps.user.is_connected.return_value = False

        with pytest.raises(PublishError) as exc_info:
            await publish_custom_integration(INTEGRATION_ID, USER_ID)

        assert "must be connected" in exc_info.value.message

    async def test_requires_tools(self, mock_deps):
        mock_deps.repo.get.return_value = _integration(tools=[])

        with pytest.raises(PublishError) as exc_info:
            await publish_custom_integration(INTEGRATION_ID, USER_ID)

        assert "tools" in exc_info.value.message
        mock_deps.repo.publish.assert_not_awaited()

    async def test_surfaces_validation_errors(self, mock_deps):
        mock_deps.repo.get.return_value = _integration()
        mock_deps.validate.return_value = ["Name must be at least 3 characters", "Bad words"]

        with pytest.raises(PublishError) as exc_info:
            await publish_custom_integration(INTEGRATION_ID, USER_ID)

        assert exc_info.value.message == "Name must be at least 3 characters; Bad words"
        mock_deps.repo.publish.assert_not_awaited()

    async def test_already_published_detected(self, mock_deps):
        mock_deps.repo.get.return_value = _integration()
        mock_deps.repo.publish.return_value = False
        mock_deps.repo.get_by_creator.return_value = _integration(is_public=True)

        with pytest.raises(PublishError) as exc_info:
            await publish_custom_integration(INTEGRATION_ID, USER_ID)

        assert "already published" in exc_info.value.message

    async def test_publish_failure_without_creator_doc_is_404(self, mock_deps):
        mock_deps.repo.get.return_value = _integration()
        mock_deps.repo.publish.return_value = False

        with pytest.raises(PublishError) as exc_info:
            await publish_custom_integration(INTEGRATION_ID, USER_ID)

        assert exc_info.value.status_code == 404

    async def test_llm_failure_falls_back_to_deterministic_content(
        self, mock_deps: SimpleNamespace
    ) -> None:
        """When the LLM returns None, publish still stores tool-grounded content."""
        mock_deps.repo.get.return_value = _integration()
        mock_deps.content.return_value = None

        result = await publish_custom_integration(INTEGRATION_ID, USER_ID)

        assert result == "/marketplace/my-integration"
        content = mock_deps.repo.publish.await_args.kwargs["content"]
        assert content is not None
        assert len(content.use_cases) == 5
        assert len(content.how_it_works) == 3
        assert len(content.faqs) == 4
        # Grounded in the integration's real tools, not the generic template.
        assert any("lookup" in uc for uc in content.use_cases)
        assert "lookup" in content.faqs[1].answer
        # The fallback carries this integration's identity, not blanks.
        assert content.faqs[0].question == "How do I connect My Integration to GAIA?"
        assert content.faqs[1].answer.startswith("A handy tool")
        assert "productivity stack" in content.how_it_works[2].body
        # No auth configured anywhere: the generic connect copy.
        assert "if asked" in content.how_it_works[0].body

    async def test_fallback_prefers_mcp_config_auth(self, mock_deps: SimpleNamespace) -> None:
        """mcp_config.auth_type wins over the legacy top-level mirror."""
        mock_deps.repo.get.return_value = _integration(
            mcp_config=MCPConfig(server_url="https://mcp.example.com", auth_type="oauth"),
            auth_type="bearer",
        )
        mock_deps.content.return_value = None

        await publish_custom_integration(INTEGRATION_ID, USER_ID)

        content = mock_deps.repo.publish.await_args.kwargs["content"]
        assert "OAuth consent" in content.how_it_works[0].body
        assert "OAuth consent" in content.faqs[0].answer

    async def test_fallback_uses_legacy_auth_without_mcp_config(
        self, mock_deps: SimpleNamespace
    ) -> None:
        """Older documents without mcp_config still resolve auth from the mirror."""
        mock_deps.repo.get.return_value = _integration(mcp_config=None, auth_type="bearer")
        mock_deps.content.return_value = None

        await publish_custom_integration(INTEGRATION_ID, USER_ID)

        content = mock_deps.repo.publish.await_args.kwargs["content"]
        assert "API token" in content.how_it_works[0].body


class TestUnpublishCustomIntegration:
    async def test_unpublishes_and_cleans_marketplace(self, mock_deps):
        mock_deps.repo.get.return_value = _integration(is_public=True)

        await unpublish_custom_integration(INTEGRATION_ID, USER_ID)

        mock_deps.repo.unpublish.assert_awaited_once_with(INTEGRATION_ID)
        mock_deps.remove.assert_awaited_once_with(INTEGRATION_ID)
        mock_deps.clear.assert_awaited_once_with("marketplace:community:*")
        mock_deps.invalidate.assert_awaited_once_with(USER_ID)

    async def test_404_when_integration_missing(self, mock_deps):
        with pytest.raises(PublishError) as exc_info:
            await unpublish_custom_integration(INTEGRATION_ID, USER_ID)

        assert exc_info.value.status_code == 404

    async def test_403_when_not_creator(self, mock_deps):
        mock_deps.repo.get.return_value = _integration(created_by="someone-else", is_public=True)

        with pytest.raises(PublishError) as exc_info:
            await unpublish_custom_integration(INTEGRATION_ID, USER_ID)

        assert exc_info.value.status_code == 403

    async def test_rejects_unpublished_integration(self, mock_deps):
        mock_deps.repo.get.return_value = _integration(is_public=False)

        with pytest.raises(PublishError) as exc_info:
            await unpublish_custom_integration(INTEGRATION_ID, USER_ID)

        assert "not currently published" in exc_info.value.message
        mock_deps.repo.unpublish.assert_not_awaited()

    async def test_500_when_update_fails(self, mock_deps):
        mock_deps.repo.get.return_value = _integration(is_public=True)
        mock_deps.repo.unpublish.return_value = False

        with pytest.raises(PublishError) as exc_info:
            await unpublish_custom_integration(INTEGRATION_ID, USER_ID)

        assert exc_info.value.status_code == 500
        mock_deps.remove.assert_not_awaited()
