"""Contract tests for PendingPlatformRegistrationsRepository.

The registry of Photon numbers registered but not yet linked. The unique index
on ``(platform, platform_user_id)`` is what stops two accounts from claiming the
same number, so the fixture creates it to mirror production.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.db.repositories.pending_platform_registrations import (
    PendingPlatformRegistrationsRepository,
)

NOW = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


@pytest.fixture
async def repo(raw_collection) -> PendingPlatformRegistrationsRepository:
    await raw_collection.create_index([("platform", 1), ("platform_user_id", 1)], unique=True)
    return PendingPlatformRegistrationsRepository()


class TestPendingPlatformRegistrationsRepository:
    async def test_record_then_get_for_user(self, repo):
        assert await repo.get_for_user("u1", "imessage") is None

        recorded = await repo.record(
            user_id="u1", platform="imessage", platform_user_id="+15550000001", created_at=NOW
        )

        assert recorded is not None
        found = await repo.get_for_user("u1", "imessage")
        assert found is not None
        assert found.platform_user_id == "+15550000001"
        assert found.created_at == NOW
        assert await repo.get_for_user("u1", "discord") is None
        assert await repo.get_for_user("u2", "imessage") is None

    async def test_record_stores_exactly_the_documented_fields(self, repo, raw_collection):
        """A stray or misspelled field reads back fine but is invisible to every finder."""
        await repo.record(
            user_id="u1", platform="imessage", platform_user_id="+15550000001", created_at=NOW
        )

        raw = await raw_collection.find_one({"user_id": "u1"})
        assert raw is not None
        assert set(raw) == {"_id", "user_id", "platform", "platform_user_id", "created_at"}
        assert raw["platform"] == "imessage"
        assert raw["platform_user_id"] == "+15550000001"

    async def test_record_replaces_the_users_previous_number(self, repo, raw_collection):
        await repo.record(
            user_id="u1", platform="imessage", platform_user_id="+15550000001", created_at=NOW
        )
        await repo.record(
            user_id="u1",
            platform="imessage",
            platform_user_id="+15550000002",
            created_at=NOW + timedelta(minutes=5),
        )

        assert await raw_collection.count_documents({"user_id": "u1"}) == 1
        found = await repo.get_for_user("u1", "imessage")
        assert found is not None
        assert found.platform_user_id == "+15550000002"

    async def test_a_number_pending_on_another_account_is_refused(self, repo):
        await repo.record(
            user_id="u1", platform="imessage", platform_user_id="+15550000001", created_at=NOW
        )

        refused = await repo.record(
            user_id="u2", platform="imessage", platform_user_id="+15550000001", created_at=NOW
        )

        assert refused is None
        assert await repo.get_for_user("u2", "imessage") is None

    async def test_find_older_than_returns_expired_records_of_that_platform_oldest_first(
        self, repo
    ):
        # Inserted newest-first so insertion order cannot pass for sorted order.
        await repo.record(
            user_id="newer",
            platform="imessage",
            platform_user_id="+15550000001",
            created_at=NOW - timedelta(days=2),
        )
        await repo.record(
            user_id="oldest",
            platform="imessage",
            platform_user_id="+15550000002",
            created_at=NOW - timedelta(days=9),
        )
        await repo.record(
            user_id="fresh", platform="imessage", platform_user_id="+15550000003", created_at=NOW
        )
        await repo.record(
            user_id="other",
            platform="discord",
            platform_user_id="+15550000004",
            created_at=NOW - timedelta(days=2),
        )

        expired = await repo.find_older_than("imessage", NOW - timedelta(days=1))

        # Oldest first: a partially-drained sweep releases the longest-held seats.
        assert [record.user_id for record in expired] == ["oldest", "newer"]

    async def test_delete_for_user_removes_only_that_users_platform_record(self, repo):
        await repo.record(
            user_id="u1", platform="imessage", platform_user_id="+15550000001", created_at=NOW
        )
        await repo.record(
            user_id="u2", platform="imessage", platform_user_id="+15550000002", created_at=NOW
        )

        deleted = await repo.delete_for_user("u1", "imessage")

        assert deleted == 1
        assert await repo.get_for_user("u1", "imessage") is None
        assert await repo.get_for_user("u2", "imessage") is not None

    async def test_delete_by_platform_user_id(self, repo):
        await repo.record(
            user_id="u1", platform="imessage", platform_user_id="+15550000001", created_at=NOW
        )

        deleted = await repo.delete_by_platform_user_id("imessage", "+15550000001")

        assert deleted == 1
        assert await repo.get_for_user("u1", "imessage") is None
        assert await repo.delete_by_platform_user_id("imessage", "+15550000001") == 0
