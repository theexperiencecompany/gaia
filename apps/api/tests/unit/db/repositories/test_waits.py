"""Hermetic unit tests for WaitsRepository: the exact writes and filters it hands the driver.

The real-Mongo proof lives in tests/contracts/test_waits_repository.py. The driver is mocked at
app.db.repositories.base.get_async_collection, the seam every read and write goes through.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId
from pymongo.errors import DuplicateKeyError
import pytest
import time_machine

from app.constants.waits import WaitCondition, WaiterKind
from app.db.repositories.waits import WaitsRepository
from app.models.wait_models import WaitKey, WaitUpdate

USER = "6812f0b3c9a14e2b7d5a91cc"
WAIT_ID = "6812f0b3c9a14e2b7d5a91ff"
NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
OLDEST_LIVE = NOW - timedelta(days=7)
KEY = WaitKey(
    user_id=USER,
    condition=WaitCondition.INTEGRATION_CONNECTED,
    subject_id="gmail",
    waiter=WaiterKind.CHAT,
    waiter_id="conv-1",
)
KEY_FILTER = {
    "user_id": USER,
    "condition": "integration_connected",
    "subject_id": "gmail",
    "waiter": "chat",
    "waiter_id": "conv-1",
}


def _raw() -> dict[str, object]:
    return {
        "_id": ObjectId(WAIT_ID),
        **KEY_FILTER,
        "subject_name": "Gmail",
        "stream_id": "stream-1",
        "created_at": NOW,
    }


@pytest.fixture
def collection() -> Iterator[MagicMock]:
    mock = MagicMock()
    mock.find_one_and_update = AsyncMock(return_value=_raw())
    mock.find_one_and_delete = AsyncMock(return_value=_raw())
    cursor = MagicMock()
    cursor.to_list = AsyncMock(return_value=[_raw()])
    mock.find = MagicMock(return_value=cursor)
    with (
        time_machine.travel(NOW, tick=False),
        patch("app.db.repositories.base.get_async_collection", return_value=mock),
    ):
        yield mock


class TestKeep:
    async def test_an_ask_upserts_the_waiter_with_its_run_and_a_fresh_seven_days(
        self, collection: MagicMock
    ) -> None:
        await WaitsRepository().keep(KEY, WaitUpdate(subject_name="Gmail", stream_id="stream-1"))

        collection.find_one_and_update.assert_awaited_once_with(
            KEY_FILTER,
            {"$set": {"subject_name": "Gmail", "stream_id": "stream-1", "created_at": NOW}},
            array_filters=None,
            return_document=True,
            upsert=True,
        )

    async def test_the_loser_of_two_first_asks_retries_onto_the_winner(
        self, collection: MagicMock
    ) -> None:
        collection.find_one_and_update.side_effect = [DuplicateKeyError("dup"), _raw()]

        await WaitsRepository().keep(KEY, WaitUpdate(subject_name="Gmail", stream_id=None))

        assert collection.find_one_and_update.await_count == 2
        retry = collection.find_one_and_update.await_args_list[1]
        assert retry.args[0] == KEY_FILTER
        assert retry.kwargs["upsert"] is True


class TestFindMet:
    async def test_reads_only_live_waits_on_the_subject(self, collection: MagicMock) -> None:
        waits = await WaitsRepository().find_met(USER, WaitCondition.INTEGRATION_CONNECTED, "gmail")

        collection.find.assert_called_once_with(
            {
                "user_id": USER,
                "condition": "integration_connected",
                "subject_id": "gmail",
                "created_at": {"$gte": OLDEST_LIVE},
            }
        )
        assert [w.id for w in waits] == [WAIT_ID]


class TestClaim:
    async def test_takes_the_users_live_wait_by_id(self, collection: MagicMock) -> None:
        wait = await WaitsRepository().claim(WAIT_ID, user_id=USER)

        collection.find_one_and_delete.assert_awaited_once_with(
            {"_id": ObjectId(WAIT_ID), "user_id": USER, "created_at": {"$gte": OLDEST_LIVE}}
        )
        assert wait is not None
        assert (wait.id, wait.waiter_id) == (WAIT_ID, "conv-1")

    async def test_a_wait_already_taken_claims_nothing(self, collection: MagicMock) -> None:
        collection.find_one_and_delete.return_value = None

        assert await WaitsRepository().claim(WAIT_ID, user_id=USER) is None


class TestRestore:
    async def test_a_failed_resume_puts_its_wait_back_unless_a_newer_ask_is_there(
        self, collection: MagicMock
    ) -> None:
        repo = WaitsRepository()
        wait = await repo.claim(WAIT_ID, user_id=USER)
        assert wait is not None

        await repo.restore(wait)

        collection.find_one_and_update.assert_awaited_once_with(
            KEY_FILTER,
            {
                "$setOnInsert": {
                    "subject_name": "Gmail",
                    "stream_id": "stream-1",
                    "created_at": NOW,
                }
            },
            array_filters=None,
            return_document=True,
            upsert=True,
        )
