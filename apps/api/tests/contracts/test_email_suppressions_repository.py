"""Contract tests for EmailSuppressionsRepository: one opt-out per address, read back in bulk."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.db.repositories.email_suppressions import EmailSuppressionsRepository
from tests.helpers import local_timezone


@pytest.fixture
async def repo(raw_collection) -> EmailSuppressionsRepository:
    await raw_collection.create_index("email", unique=True)
    return EmailSuppressionsRepository()


class TestEmailSuppressionsRepository:
    async def test_suppressing_twice_keeps_one_record(self, repo, raw_collection):
        await repo.suppress("friend@x.com")
        await repo.suppress("friend@x.com")
        assert await raw_collection.count_documents({"email": "friend@x.com"}) == 1

    async def test_suppressed_among_returns_only_the_opted_out(self, repo):
        await repo.suppress("gone@x.com")
        await repo.suppress("unasked@x.com")
        assert await repo.suppressed_among(["gone@x.com", "here@x.com"]) == {"gone@x.com"}
        assert await repo.suppressed_among([]) == set()

    async def test_a_suppression_is_stamped_in_utc_whatever_the_servers_zone(
        self, repo, raw_collection
    ):
        with local_timezone("Asia/Kolkata"):
            await repo.suppress("friend@x.com")

        stored = await raw_collection.find_one({"email": "friend@x.com"})
        assert abs(stored["created_at"].replace(tzinfo=UTC) - datetime.now(UTC)) < timedelta(
            minutes=1
        )
