"""Contract tests for ReferralCodesRepository: one code per user, one owner per code."""

from __future__ import annotations

from datetime import UTC, datetime

from pymongo.errors import DuplicateKeyError
import pytest

from app.db.repositories.referral_codes import ReferralCodesRepository
from app.models.referral_models import ReferralCodeDocument

NOW = datetime(2026, 10, 14, tzinfo=UTC)


@pytest.fixture
async def repo(raw_collection) -> ReferralCodesRepository:
    await raw_collection.create_index("user_id", unique=True)
    await raw_collection.create_index("code", unique=True)
    return ReferralCodesRepository()


class TestReferralCodesRepository:
    async def test_a_code_is_found_by_its_owner_and_by_itself(self, repo):
        await repo.create(ReferralCodeDocument(user_id="u1", code="aryan-k7f2", created_at=NOW))

        assert (await repo.get_for_user("u1")).code == "aryan-k7f2"
        assert (await repo.get_by_code("aryan-k7f2")).user_id == "u1"
        assert await repo.get_by_code("aryan-zzzz") is None
        assert await repo.get_for_user("u2") is None

    async def test_a_second_code_for_a_user_or_a_taken_code_is_refused(self, repo):
        await repo.create(ReferralCodeDocument(user_id="u1", code="aryan-k7f2", created_at=NOW))

        with pytest.raises(DuplicateKeyError):
            await repo.create(ReferralCodeDocument(user_id="u1", code="aryan-abcd", created_at=NOW))
        with pytest.raises(DuplicateKeyError):
            await repo.create(ReferralCodeDocument(user_id="u2", code="aryan-k7f2", created_at=NOW))
