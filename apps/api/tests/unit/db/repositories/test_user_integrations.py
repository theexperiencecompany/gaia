"""Hermetic unit tests for UserIntegrationsRepository.has_connected_before.

The driver is mocked at app.db.repositories.base.get_async_collection; the
reconnect flag on integration:connected rests on this read.
"""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId
import pytest

from app.db.repositories.user_integrations import UserIntegrationsRepository

USER_ID = "6812f0b3c9a14e2b7d5a91cc"
CONNECTED_AT = datetime(2026, 9, 1, tzinfo=UTC)


def _row(status: str, connected_at: datetime | None) -> dict[str, Any]:
    return {
        "_id": ObjectId(),
        "user_id": USER_ID,
        "integration_id": "gmail",
        "status": status,
        "connected_at": connected_at,
    }


async def _connected_before(row: dict[str, Any] | None) -> tuple[bool, MagicMock]:
    collection = MagicMock()
    collection.find_one = AsyncMock(return_value=row)
    with patch("app.db.repositories.base.get_async_collection", return_value=collection):
        result = await UserIntegrationsRepository().has_connected_before(USER_ID, "gmail")
    return result, collection


@pytest.mark.parametrize("status", ["connected", "expired", "created"])
async def test_a_record_that_was_ever_connected_counts_whatever_its_status_now(
    status: str,
) -> None:
    connected, _ = await _connected_before(_row(status, CONNECTED_AT))

    assert connected is True


async def test_a_record_never_connected_does_not_count() -> None:
    connected, _ = await _connected_before(_row("created", None))

    assert connected is False


async def test_no_record_does_not_count_and_reads_only_this_users_integration() -> None:
    connected, collection = await _connected_before(None)

    assert connected is False
    (filter_,), _ = collection.find_one.await_args
    assert filter_ == {"user_id": USER_ID, "integration_id": "gmail"}
