"""Contract tests for EmailSuppressionsRepository: one opt-out per address, read back in bulk."""

from __future__ import annotations

import pytest

from app.db.repositories.email_suppressions import EmailSuppressionsRepository


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
        assert await repo.suppressed_among(["gone@x.com", "here@x.com"]) == {"gone@x.com"}
        assert await repo.suppressed_among([]) == set()
