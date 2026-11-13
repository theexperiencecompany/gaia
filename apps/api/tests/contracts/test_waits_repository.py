"""Contract tests for WaitsRepository: waiters kept until the user does what GAIA asked, on real Mongo.

The fixture builds the production indexes on the throwaway collection, so the unique key and
the TTL anchor are what the assertions read.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.constants.waits import WAIT_TTL_SECONDS, WaitCondition, WaiterKind
from app.db.repositories.waits import WaitsRepository
from app.models.wait_models import WaitKey, WaitUpdate

USER = "6812f0b3c9a14e2b7d5a91cc"
OTHER = "6812f0b3c9a14e2b7d5a91cd"
CONNECTED = WaitCondition.INTEGRATION_CONNECTED
CONFIGURED = WaitCondition.WORKFLOW_TRIGGER_CONFIGURED


@pytest.fixture
async def repo(raw_collection) -> WaitsRepository:
    await raw_collection.create_index(
        [("user_id", 1), ("condition", 1), ("subject_id", 1), ("waiter", 1), ("waiter_id", 1)],
        unique=True,
    )
    await raw_collection.create_index("created_at", expireAfterSeconds=WAIT_TTL_SECONDS)
    return WaitsRepository()


def _key(
    *,
    user_id: str = USER,
    condition: WaitCondition = CONNECTED,
    subject_id: str = "gmail",
    waiter: WaiterKind = WaiterKind.CHAT,
    waiter_id: str = "conv-1",
) -> WaitKey:
    return WaitKey(
        user_id=user_id,
        condition=condition,
        subject_id=subject_id,
        waiter=waiter,
        waiter_id=waiter_id,
    )


async def _keep(
    repo: WaitsRepository, key: WaitKey | None = None, stream_id: str = "stream-1"
) -> None:
    await repo.keep(key or _key(), WaitUpdate(subject_name="Gmail", stream_id=stream_id))


class TestWaitsRepository:
    async def test_a_kept_wait_is_taken_with_its_waiter_run_and_ttl_anchor(self, repo):
        before = datetime.now(UTC)
        await _keep(repo, _key(waiter=WaiterKind.TODO, waiter_id="todo-1"))

        [taken] = await repo.take_met(USER, CONNECTED, "gmail")

        assert (taken.waiter, taken.waiter_id, taken.stream_id, taken.subject_name) == (
            WaiterKind.TODO,
            "todo-1",
            "stream-1",
            "Gmail",
        )
        assert taken.created_at >= before.replace(microsecond=0)

    async def test_a_repeat_ask_keeps_one_wait_with_the_newest_run_and_time(
        self, repo, raw_collection
    ):
        await _keep(repo, stream_id="stream-old")
        await raw_collection.update_many(
            {}, {"$set": {"created_at": datetime.now(UTC) - timedelta(days=3)}}
        )
        await _keep(repo, stream_id="stream-new")

        [taken] = await repo.take_met(USER, CONNECTED, "gmail")

        assert taken.stream_id == "stream-new"
        assert datetime.now(UTC) - taken.created_at < timedelta(minutes=1)

    async def test_every_waiter_on_the_subject_is_taken_exactly_once(self, repo):
        await _keep(repo, _key(waiter=WaiterKind.CHAT, waiter_id="conv-1"))
        await _keep(repo, _key(waiter=WaiterKind.TODO, waiter_id="todo-1"))
        await _keep(repo, _key(waiter=WaiterKind.WORKFLOW, waiter_id="wf-1"))

        first = await repo.take_met(USER, CONNECTED, "gmail")
        second = await repo.take_met(USER, CONNECTED, "gmail")

        assert sorted(w.waiter_id for w in first) == ["conv-1", "todo-1", "wf-1"]
        assert second == []

    async def test_take_leaves_other_subjects_conditions_and_users_waiting(
        self, repo, raw_collection
    ):
        await _keep(repo)
        await _keep(repo, _key(subject_id="slack"))
        await _keep(repo, _key(condition=CONFIGURED, subject_id="gmail"))
        await _keep(repo, _key(user_id=OTHER))

        await repo.take_met(USER, CONNECTED, "gmail")

        left = await raw_collection.find(
            {}, {"_id": 0, "user_id": 1, "condition": 1, "subject_id": 1}
        ).to_list(None)
        assert sorted((d["user_id"], d["condition"], d["subject_id"]) for d in left) == sorted(
            [
                (USER, CONNECTED.value, "slack"),
                (USER, CONFIGURED.value, "gmail"),
                (OTHER, CONNECTED.value, "gmail"),
            ]
        )

    async def test_concurrent_takes_hand_each_waiter_to_one_caller(self, repo):
        for n in range(5):
            await _keep(repo, _key(waiter_id=f"conv-{n}"))

        results = await asyncio.gather(*(repo.take_met(USER, CONNECTED, "gmail") for _ in range(4)))

        claimed = [w.waiter_id for batch in results for w in batch]
        assert sorted(claimed) == [f"conv-{n}" for n in range(5)]

    async def test_racing_first_asks_from_one_waiter_leave_one_document(self, repo, raw_collection):
        await asyncio.gather(*(_keep(repo) for _ in range(5)))

        assert await raw_collection.count_documents({"user_id": USER}) == 1
