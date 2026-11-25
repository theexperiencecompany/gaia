"""Behaviour tests for custom_crud's creator-side delete cascade."""

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.log_tags import LogTag
from app.constants.public_pages import PublicPageDomain
from app.models.integration_models import UpdateCustomIntegrationRequest
from app.services.integrations.custom_crud import (
    _delete_owned_integration,
    update_custom_integration,
)

pytestmark = pytest.mark.unit

_MODULE = "app.services.integrations.custom_crud"


@contextmanager
def _delete_seams(invalidate: AsyncMock) -> Iterator[MagicMock]:
    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    db_context = MagicMock()
    db_context.__aenter__ = AsyncMock(return_value=session)
    db_context.__aexit__ = AsyncMock(return_value=False)
    with (
        patch(f"{_MODULE}.integration_repository.delete_custom", AsyncMock(return_value=True)),
        patch(
            f"{_MODULE}.user_integration_repository.user_ids_with_integration",
            AsyncMock(return_value=[]),
        ),
        patch(f"{_MODULE}.drop_local_sessions", AsyncMock()),
        patch(f"{_MODULE}.get_db_session", return_value=db_context),
        patch(f"{_MODULE}.invalidate_mcp_tools_cache", invalidate),
        patch(f"{_MODULE}.cleanup_integration_chroma_data", AsyncMock()),
        patch(f"{_MODULE}.log") as mock_log,
    ):
        yield mock_log


@contextmanager
def _marketplace_seams(deleted: bool) -> Iterator[list[tuple[object, ...]]]:
    """Record, in order, what a creator-side delete does to the marketplace."""
    calls: list[tuple[object, ...]] = []

    def record(name: str, result: object = None) -> AsyncMock:
        async def call(*args: object) -> object:
            calls.append((name, *args))
            return result

        return AsyncMock(side_effect=call)

    with (
        _delete_seams(AsyncMock()),
        patch(f"{_MODULE}.integration_repository.delete_custom", record("delete", deleted)),
        patch(f"{_MODULE}.remove_public_integration", AsyncMock()),
        patch(f"{_MODULE}.invalidate_public_pages", record("invalidate_public_pages")),
    ):
        yield calls


class TestDeleteOwnedIntegration:
    async def test_tools_cache_invalidation_failure_is_warned_and_delete_still_succeeds(
        self,
    ) -> None:
        doc = MagicMock(is_public=False, category="custom")
        doc.mcp_config = None
        invalidate = AsyncMock(side_effect=RuntimeError("cache down"))

        with _delete_seams(invalidate) as mock_log:
            deleted = await _delete_owned_integration(doc, "user-1", "int-1")

        assert deleted is True
        mock_log.warning.assert_called_once_with(
            f"{LogTag.INTEGRATION} Failed to invalidate the MCP tools cache",
            error="cache down",
            error_type="RuntimeError",
            integration_id="int-1",
        )

    async def test_deleting_a_published_integration_clears_the_marketplace_once_it_is_gone(
        self,
    ) -> None:
        doc = MagicMock(is_public=True, category="custom")
        doc.mcp_config = None

        with _marketplace_seams(deleted=True) as calls:
            await _delete_owned_integration(doc, "user-1", "int-1")

        assert calls == [
            ("delete", "int-1", "user-1"),
            ("invalidate_public_pages", PublicPageDomain.INTEGRATIONS),
        ]

    async def test_deleting_a_private_integration_leaves_the_marketplace_alone(self) -> None:
        doc = MagicMock(is_public=False, category="custom")
        doc.mcp_config = None

        with _marketplace_seams(deleted=True) as calls:
            await _delete_owned_integration(doc, "user-1", "int-1")

        assert calls == [("delete", "int-1", "user-1")]

    async def test_a_delete_that_removed_nothing_leaves_the_marketplace_alone(self) -> None:
        doc = MagicMock(is_public=True, category="custom")
        doc.mcp_config = None

        with _marketplace_seams(deleted=False) as calls:
            deleted = await _delete_owned_integration(doc, "user-1", "int-1")

        assert deleted is False
        assert calls == [("delete", "int-1", "user-1")]


class TestUpdateCustomIntegrationClearsThePublicPages:
    @pytest.mark.parametrize(
        ("was_public", "is_public", "expected"),
        [
            pytest.param(True, True, [PublicPageDomain.INTEGRATIONS], id="published, edited"),
            pytest.param(True, False, [PublicPageDomain.INTEGRATIONS], id="made private"),
            pytest.param(False, True, [PublicPageDomain.INTEGRATIONS], id="made public"),
            pytest.param(False, False, [], id="private, edited"),
        ],
    )
    async def test_an_edit_clears_them_when_the_integration_is_or_was_published(
        self, was_public: bool, is_public: bool, expected: list[PublicPageDomain]
    ) -> None:
        with (
            patch(f"{_MODULE}.integration_repository") as repo,
            patch(
                f"{_MODULE}.user_integration_repository.user_ids_with_integration",
                AsyncMock(return_value=[]),
            ),
            patch(f"{_MODULE}.invalidate_public_pages", new_callable=AsyncMock) as invalidate_pages,
        ):
            repo.get_custom_for_user = AsyncMock(
                return_value=MagicMock(is_public=was_public, mcp_config=None)
            )
            repo.update = AsyncMock(return_value=MagicMock(is_public=is_public))
            await update_custom_integration(
                "user-1",
                "int-1",
                UpdateCustomIntegrationRequest.model_validate({"name": "Renamed"}),
            )

        assert [c.args[0] for c in invalidate_pages.await_args_list] == expected

    async def test_an_edit_that_stored_nothing_leaves_them_alone(self) -> None:
        with (
            patch(f"{_MODULE}.integration_repository") as repo,
            patch(
                f"{_MODULE}.user_integration_repository.user_ids_with_integration",
                AsyncMock(return_value=[]),
            ),
            patch(f"{_MODULE}.invalidate_public_pages", new_callable=AsyncMock) as invalidate_pages,
        ):
            repo.get_custom_for_user = AsyncMock(
                return_value=MagicMock(is_public=True, mcp_config=None)
            )
            repo.update = AsyncMock(return_value=None)
            await update_custom_integration(
                "user-1",
                "int-1",
                UpdateCustomIntegrationRequest.model_validate({"name": "Renamed"}),
            )

        invalidate_pages.assert_not_awaited()
