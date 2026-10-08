"""The single write save_accounts sends for a user's account set (real Mongo lives in contracts)."""

from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.repositories.user_integrations import UserIntegrationsRepository
from app.models.integration_models import IntegrationAccount

USER_ID = "user_1"
INTEGRATION_ID = "gmail"


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

    async def test_an_upsert_that_returns_nothing_fails_loud(self, collection: MagicMock) -> None:
        collection.find_one_and_update.return_value = None

        with pytest.raises(
            RuntimeError, match="^user_integrations upsert returned nothing for gmail$"
        ):
            await UserIntegrationsRepository().save_accounts(
                USER_ID, INTEGRATION_ID, accounts=[], primary_account_id=None, status="created"
            )
