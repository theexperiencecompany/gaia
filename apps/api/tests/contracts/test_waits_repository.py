"""Contract tests for WaitsRepository: waiters kept until the user does what GAIA asked, on real Mongo.

The fixture builds the production indexes on the throwaway collection, so the unique key and
the TTL anchor are what the assertions read.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TypeAlias

from motor.motor_asyncio import AsyncIOMotorCollection
import pytest

from app.constants.waits import RESUME_WAITER_LEASE, WAIT_TTL_SECONDS, WaitCondition, WaiterKind
from app.db.repositories.waits import WaitsRepository
from app.models.wait_models import WaitDocument, WaitKey, WaitUpdate

USER = "6812f0b3c9a14e2b7d5a91cc"
OTHER = "6812f0b3c9a14e2b7d5a91cd"
CONNECTED = WaitCondition.INTEGRATION_CONNECTED
CONFIGURED = WaitCondition.WORKFLOW_TRIGGER_CONFIGURED
# A raw handle on the waits collection; documents are read only through the repository.
WaitsCollection: TypeAlias = "AsyncIOMotorCollection[dict[str, object]]"


@pytest.fixture
async def repo(raw_collection: WaitsCollection) -> WaitsRepository:
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


async def _take_all(repo: WaitsRepository, user_id: str = USER) -> list[WaitDocument]:
    """Find the live waits and claim each, as report_wait_met and one resume job per wait do."""
    found = await repo.find_met(user_id, CONNECTED, "gmail")
    claimed = [await repo.claim(w.id, user_id=user_id, job_id=f"job-{w.id}") for w in found]
    return [w for w in claimed if w is not None]


class TestWaitsRepository:
    async def test_a_kept_wait_is_found_and_claimed_with_its_waiter_run_and_ttl_anchor(
        self, repo: WaitsRepository
    ) -> None:
        before = datetime.now(UTC)
        await _keep(repo, _key(waiter=WaiterKind.TODO, waiter_id="todo-1"))

        [taken] = await _take_all(repo)

        assert (taken.waiter, taken.waiter_id, taken.stream_id, taken.subject_name) == (
            WaiterKind.TODO,
            "todo-1",
            "stream-1",
            "Gmail",
        )
        assert taken.created_at >= before.replace(microsecond=0)

    async def test_a_repeat_ask_keeps_one_wait_with_the_newest_run_and_time(
        self, repo: WaitsRepository, raw_collection: WaitsCollection
    ) -> None:
        await _keep(repo, stream_id="stream-old")
        await raw_collection.update_many(
            {}, {"$set": {"created_at": datetime.now(UTC) - timedelta(days=3)}}
        )
        await _keep(repo, stream_id="stream-new")

        [taken] = await _take_all(repo)

        assert taken.stream_id == "stream-new"
        assert datetime.now(UTC) - taken.created_at < timedelta(minutes=1)

    async def test_finding_leaves_the_waits_until_each_is_claimed(
        self, repo: WaitsRepository
    ) -> None:
        await _keep(repo, _key(waiter=WaiterKind.CHAT, waiter_id="conv-1"))
        await _keep(repo, _key(waiter=WaiterKind.TODO, waiter_id="todo-1"))
        await _keep(repo, _key(waiter=WaiterKind.WORKFLOW, waiter_id="wf-1"))

        found = await repo.find_met(USER, CONNECTED, "gmail")
        found_again = await repo.find_met(USER, CONNECTED, "gmail")
        first = [await repo.claim(w.id, user_id=USER, job_id="job-a") for w in found]
        second = [await repo.claim(w.id, user_id=USER, job_id="job-b") for w in found]

        assert sorted(w.waiter_id for w in found) == ["conv-1", "todo-1", "wf-1"]
        assert sorted(w.id for w in found_again) == sorted(w.id for w in found)
        assert all(w is not None for w in first)
        assert second == [None, None, None]

    async def test_an_expired_wait_the_ttl_sweep_has_not_removed_is_neither_found_nor_claimed(
        self, repo: WaitsRepository, raw_collection: WaitsCollection
    ) -> None:
        await _keep(repo)
        [wait] = await repo.find_met(USER, CONNECTED, "gmail")
        await raw_collection.update_many(
            {}, {"$set": {"created_at": datetime.now(UTC) - timedelta(days=7, minutes=1)}}
        )

        assert await repo.find_met(USER, CONNECTED, "gmail") == []
        assert await repo.claim(wait.id, user_id=USER, job_id="job-a") is None

    async def test_another_users_claim_takes_nothing(self, repo: WaitsRepository) -> None:
        await _keep(repo)
        [wait] = await repo.find_met(USER, CONNECTED, "gmail")

        assert await repo.claim(wait.id, user_id=OTHER, job_id="job-a") is None
        assert await repo.claim(wait.id, user_id=USER, job_id="job-a") is not None

    async def test_finding_skips_other_subjects_conditions_and_users(
        self, repo: WaitsRepository
    ) -> None:
        await _keep(repo)
        await _keep(repo, _key(subject_id="slack"))
        await _keep(repo, _key(condition=CONFIGURED, subject_id="gmail"))
        await _keep(repo, _key(user_id=OTHER))

        found = await repo.find_met(USER, CONNECTED, "gmail")

        assert [(w.user_id, w.condition, w.subject_id) for w in found] == [
            (USER, CONNECTED, "gmail")
        ]

    async def test_concurrent_claims_hand_each_waiter_to_one_job(
        self, repo: WaitsRepository
    ) -> None:
        for n in range(5):
            await _keep(repo, _key(waiter_id=f"conv-{n}"))
        found = await repo.find_met(USER, CONNECTED, "gmail")

        results = await asyncio.gather(
            *(repo.claim(w.id, user_id=USER, job_id=f"job-{n}") for w in found for n in range(4))
        )

        claimed = [w.waiter_id for w in results if w is not None]
        assert sorted(claimed) == [f"conv-{n}" for n in range(5)]

    async def test_racing_first_asks_from_one_waiter_leave_one_document(
        self, repo: WaitsRepository, raw_collection: WaitsCollection
    ) -> None:
        await asyncio.gather(*(_keep(repo) for _ in range(5)))

        assert await raw_collection.count_documents({"user_id": USER}) == 1

    async def test_a_rerun_of_the_same_job_takes_its_wait_again(
        self, repo: WaitsRepository
    ) -> None:
        await _keep(repo)
        [wait] = await repo.find_met(USER, CONNECTED, "gmail")
        assert await repo.claim(wait.id, user_id=USER, job_id="job-a") is not None

        again = await repo.claim(wait.id, user_id=USER, job_id="job-a")

        assert again is not None
        assert again.id == wait.id

    async def test_a_lease_past_its_time_goes_to_the_next_job(
        self, repo: WaitsRepository, raw_collection: WaitsCollection
    ) -> None:
        await _keep(repo)
        [wait] = await repo.find_met(USER, CONNECTED, "gmail")
        assert await repo.claim(wait.id, user_id=USER, job_id="job-a") is not None
        assert await repo.claim(wait.id, user_id=USER, job_id="job-b") is None
        await raw_collection.update_many(
            {},
            {
                "$set": {
                    "claimed_at": datetime.now(UTC) - RESUME_WAITER_LEASE - timedelta(minutes=1)
                }
            },
        )

        assert await repo.claim(wait.id, user_id=USER, job_id="job-b") is not None

    async def test_a_settled_wait_is_gone(
        self, repo: WaitsRepository, raw_collection: WaitsCollection
    ) -> None:
        await _keep(repo)
        [wait] = await repo.find_met(USER, CONNECTED, "gmail")
        await repo.claim(wait.id, user_id=USER, job_id="job-a")

        await repo.settle(wait.id, job_id="job-a")

        assert await raw_collection.count_documents({}) == 0

    async def test_settling_never_drops_a_newer_ask(self, repo: WaitsRepository) -> None:
        await _keep(repo, stream_id="stream-old")
        [wait] = await repo.find_met(USER, CONNECTED, "gmail")
        await repo.claim(wait.id, user_id=USER, job_id="job-a")
        await _keep(repo, stream_id="stream-new")

        await repo.settle(wait.id, job_id="job-a")

        [kept] = await _take_all(repo)
        assert kept.stream_id == "stream-new"

    async def test_a_released_wait_goes_to_the_next_job_with_its_original_ask_time(
        self, repo: WaitsRepository, raw_collection: WaitsCollection
    ) -> None:
        await _keep(repo)
        asked_at = datetime.now(UTC) - timedelta(hours=3)
        await raw_collection.update_many({}, {"$set": {"created_at": asked_at}})
        [wait] = await repo.find_met(USER, CONNECTED, "gmail")
        await repo.claim(wait.id, user_id=USER, job_id="job-a")

        await repo.release(wait.id, job_id="job-a")

        again = await repo.claim(wait.id, user_id=USER, job_id="job-b")
        assert again is not None
        # Mongo keeps milliseconds, so the stored time is the original to within one.
        assert abs(again.created_at - asked_at) < timedelta(milliseconds=1)

    async def test_another_jobs_settle_or_release_touches_nothing(
        self, repo: WaitsRepository
    ) -> None:
        await _keep(repo)
        [wait] = await repo.find_met(USER, CONNECTED, "gmail")
        await repo.claim(wait.id, user_id=USER, job_id="job-a")

        await repo.settle(wait.id, job_id="job-b")
        await repo.release(wait.id, job_id="job-b")

        assert await repo.claim(wait.id, user_id=USER, job_id="job-b") is None
        assert await repo.claim(wait.id, user_id=USER, job_id="job-a") is not None
