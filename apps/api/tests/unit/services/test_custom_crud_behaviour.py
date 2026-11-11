"""Behaviour tests for custom_crud's creator-side delete cascade."""

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.log_tags import LogTag
from app.services.integrations.custom_crud import _delete_owned_integration

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
