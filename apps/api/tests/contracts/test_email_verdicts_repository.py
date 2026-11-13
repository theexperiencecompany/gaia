"""Contract tests for EmailVerdictsRepository: one verdict per user and Gmail message, on real Mongo.

The fixture builds the production indexes on the throwaway collection, so the unique key and
the TTL anchor are what the assertions read.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from app.constants.desk_buckets import EMAIL_VERDICT_TTL_SECONDS, DeskBucket, Judgment
from app.db.repositories.email_verdicts import EmailVerdictsRepository
from app.models.email_verdict_models import EmailVerdictDocument

USER = "6812f0b3c9a14e2b7d5a91cc"
OTHER = "6812f0b3c9a14e2b7d5a91cd"


@pytest.fixture
async def repo(raw_collection) -> EmailVerdictsRepository:
    await raw_collection.create_index([("user_id", 1), ("message_id", 1)], unique=True)
    await raw_collection.create_index("created_at", expireAfterSeconds=EMAIL_VERDICT_TTL_SECONDS)
    return EmailVerdictsRepository()


def _verdict(
    user_id: str = USER, bucket: DeskBucket | None = DeskBucket.ACT, issue: float = 0.9
) -> EmailVerdictDocument:
    return EmailVerdictDocument(
        user_id=user_id,
        message_id="m1",
        answers={Judgment.REPORTS_ISSUE: issue, Judgment.IS_PERSON: 0.1},
        bucket=bucket,
    )


class TestEmailVerdictsRepository:
    async def test_a_kept_verdict_reads_back_with_its_answers_and_a_ttl_anchor(self, repo):
        before = datetime.now(UTC)
        await repo.keep(_verdict())

        kept = await repo.get("m1", user_id=USER)

        assert kept is not None
        assert (kept.message_id, kept.bucket) == ("m1", DeskBucket.ACT)
        assert kept.answers == {Judgment.REPORTS_ISSUE: 0.9, Judgment.IS_PERSON: 0.1}
        assert kept.created_at is not None and kept.created_at >= before.replace(microsecond=0)

    async def test_keeping_again_replaces_the_verdict_and_leaves_one_document(
        self, repo, raw_collection
    ):
        await repo.keep(_verdict())
        await repo.keep(_verdict(bucket=None, issue=0.5))

        kept = await repo.get("m1", user_id=USER)

        assert kept is not None and kept.bucket is None
        assert kept.answers[Judgment.REPORTS_ISSUE] == 0.5
        assert await raw_collection.count_documents({"message_id": "m1"}) == 1

    async def test_a_verdict_is_only_ever_read_by_its_own_user(self, repo, raw_collection):
        await repo.keep(_verdict())
        await repo.keep(_verdict(user_id=OTHER, bucket=DeskBucket.JUNK))

        mine, theirs = await repo.get("m1", user_id=USER), await repo.get("m1", user_id=OTHER)

        assert mine is not None and mine.bucket is DeskBucket.ACT
        assert theirs is not None and theirs.bucket is DeskBucket.JUNK
        assert await raw_collection.count_documents({}) == 2

    async def test_racing_first_keeps_of_one_message_leave_one_document(self, repo, raw_collection):
        await asyncio.gather(*(repo.keep(_verdict()) for _ in range(5)))

        assert await raw_collection.count_documents({"user_id": USER, "message_id": "m1"}) == 1

    async def test_an_unknown_message_reads_none(self, repo):
        assert await repo.get("never", user_id=USER) is None
