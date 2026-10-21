"""Unit tests for app.db.chroma.chroma_cleanup."""

from unittest.mock import AsyncMock, patch

import pytest

from app.constants.cache import HANDOFF_NAME_CACHE_PREFIX, SUBAGENT_CACHE_PREFIX
from app.constants.chroma import CHROMA_TOOLS_STORE_COLLECTION
from app.db.chroma.chroma_cleanup import cleanup_integration_chroma_data
from tests.helpers import captured_wide_event

MODULE = "app.db.chroma.chroma_cleanup"


@pytest.mark.unit
class TestCleanupIntegrationChromaData:
    async def test_it_deletes_the_subagent_entry_the_tools_and_the_caches(self) -> None:
        store = AsyncMock()
        with (
            patch(f"{MODULE}.providers.aget", AsyncMock(return_value=store)),
            patch(f"{MODULE}.derive_integration_namespace", return_value="mcp_example_com"),
            patch(f"{MODULE}.delete_tools_by_namespace", AsyncMock(return_value=3)) as tools,
            patch(f"{MODULE}.delete_cache", AsyncMock()) as cache,
        ):
            async with captured_wide_event() as event:
                results = await cleanup_integration_chroma_data("int-1", "https://example.com")

        assert results == {"subagent": True, "tools": True, "cache": True}
        store.adelete.assert_awaited_once_with(namespace=("subagents",), key="int-1")
        tools.assert_awaited_once_with("mcp_example_com")
        assert [c.args[0] for c in cache.await_args_list] == [
            "chroma:indexed:mcp_example_com",
            f"{SUBAGENT_CACHE_PREFIX}:int-1",
            f"{HANDOFF_NAME_CACHE_PREFIX}:int-1",
        ]
        # The wide event names the collection the tools actually live in, suffix included.
        assert event["vector"] == {
            "operation": "delete",
            "collection": CHROMA_TOOLS_STORE_COLLECTION,
        }
