"""Hermetic unit tests for IntegrationsRepository.find_custom_by_server_url.

Dedup matches on the stored normalized key, so https://host/mcp/ finds a
row stored as https://host/mcp no matter which creation path wrote it.
The driver is mocked at app.db.repositories.base.get_async_collection;
the real-Mongo proof (including the partial unique index) belongs in the
contracts tier.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from app.db.repositories.integrations import IntegrationsRepository

USER_ID = "user_1"


def _row(server_url: str, normalized: str | None) -> dict[str, Any]:
    mcp_config: dict[str, Any] = {"server_url": server_url}
    if normalized is not None:
        mcp_config["server_url_normalized"] = normalized
    return {
        "integration_id": "int-1",
        "name": "Slash MCP",
        "description": "d",
        "category": "custom",
        "managed_by": "mcp",
        "source": "custom",
        "created_by": USER_ID,
        "mcp_config": mcp_config,
    }


async def _find(collection: MagicMock, url: str) -> Any:
    repo = IntegrationsRepository()
    with patch("app.db.repositories.base.get_async_collection", return_value=collection):
        return await repo.find_custom_by_server_url(url, USER_ID)


async def test_lookup_matches_normalized_key_not_stored_spelling():
    """A trailing-slash query finds the slashless row (and vice versa)."""
    collection = MagicMock()
    collection.find_one = AsyncMock(return_value=_row("https://host/mcp", "https://host/mcp"))

    result = await _find(collection, "https://host/mcp/")

    assert result is not None
    assert result.integration_id == "int-1"
    (filter_,), _ = collection.find_one.await_args
    assert filter_ == {
        "source": "custom",
        "created_by": USER_ID,
        "mcp_config.server_url_normalized": "https://host/mcp",
    }


async def test_lookup_normalizes_case_variants():
    collection = MagicMock()
    collection.find_one = AsyncMock(return_value=_row("https://host/mcp", "https://host/mcp"))

    await _find(collection, "HTTPS://HOST/mcp")

    (filter_,), _ = collection.find_one.await_args
    assert filter_["mcp_config.server_url_normalized"] == "https://host/mcp"


async def test_community_browse_unknown_sort_falls_back_to_popular_order():
    collection = MagicMock()
    collection.aggregate.return_value.to_list = AsyncMock(return_value=[])
    repo = IntegrationsRepository()

    with patch("app.db.repositories.base.get_async_collection", return_value=collection):
        await repo.community_browse("trending", "all", offset=0, limit=10)

    (pipeline,), _ = collection.aggregate.call_args
    assert pipeline[1] == {"$sort": {"clone_count": -1, "published_at": -1}}


async def test_unusable_url_matches_nothing_without_querying():
    """A blank URL can never be a dedup key — match nothing, don't raise."""
    collection = MagicMock()
    collection.find_one = AsyncMock()

    assert await _find(collection, "   ") is None
    collection.find_one.assert_not_awaited()
