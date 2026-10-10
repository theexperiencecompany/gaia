"""Hermetic unit tests for UserIntegrationsRepository: the account-set write and the connected-before read.

The driver is mocked at app.db.repositories.base.get_async_collection (real Mongo
lives in contracts); the reconnect flag on integration:connected rests on
has_connected_before.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId
import pytest

from app.db.repositories.user_integrations import UserIntegrationsRepository
from app.models.integration_models import IntegrationAccount

USER_ID = "user_1"
INTEGRATION_ID = "gmail"
CONNECTED_AT = datetime(2026, 9, 1, tzinfo=UTC)


@pytest.fixture
def collection() -> Iterator[MagicMock]:
    driver = MagicMock()
    driver.find_one_and_update = AsyncMock(
        return_value={"user_id": USER_ID, "integration_id": INTEGRATION_ID, "status": "connected"}
    )
    with patch("app.db.repositories.base.get_async_collection", return_value=driver):
        yield driver


def _account() -> IntegrationAccount:
    return IntegrationAccount(
        connected_account_id="ca_1",
        label="ada@acme.com",
        connected_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


class TestSaveAccounts:
    async def test_it_upserts_the_account_set_on_the_users_record(
        self, collection: MagicMock
    ) -> None:
        account = _account()

        doc = await UserIntegrationsRepository().save_accounts(
            USER_ID,
            INTEGRATION_ID,
            accounts=[account],
            primary_account_id="ca_1",
            status="connected",
        )

        assert doc.integration_id == INTEGRATION_ID
        (filter_, update), kwargs = collection.find_one_and_update.await_args
        assert filter_ == {"user_id": USER_ID, "integration_id": INTEGRATION_ID}
        assert kwargs["upsert"] is True
        now = update["$setOnInsert"]["created_at"]
        assert now.tzinfo is UTC
        assert update == {
            "$set": {
                "user_id": USER_ID,
                "integration_id": INTEGRATION_ID,
                "accounts": [account.model_dump()],
                "primary_account_id": "ca_1",
                "status": "connected",
                "connected_at": now,
                "expired_at": None,
                "expired_reason": None,
            },
            "$setOnInsert": {"created_at": now},
        }

    async def test_a_save_invalidates_only_that_users_cache_scope(
        self, collection: MagicMock
    ) -> None:
        with patch.object(UserIntegrationsRepository, "_invalidate", AsyncMock()) as invalidate:
            await UserIntegrationsRepository().save_accounts(
                USER_ID, INTEGRATION_ID, accounts=[], primary_account_id=None, status="created"
            )

        invalidate.assert_awaited_once_with(USER_ID)

    async def test_an_upsert_that_returns_nothing_fails_loud(self, collection: MagicMock) -> None:
        collection.find_one_and_update.return_value = None

        with pytest.raises(
            RuntimeError, match="^user_integrations upsert returned nothing for gmail$"
        ):
            await UserIntegrationsRepository().save_accounts(
                USER_ID, INTEGRATION_ID, accounts=[], primary_account_id=None, status="created"
            )


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
