"""Contract tests for the HIL tool-risk cache: one verdict per tool and description, overwritten in place."""

from __future__ import annotations

import pytest

from app.db.repositories.hil import HilToolRiskRepository
from app.models.hil_models import HILToolRiskRecord


@pytest.fixture
def risk_repo(raw_collection) -> HilToolRiskRepository:
    return HilToolRiskRepository()


class TestHilToolRiskRepository:
    async def test_upsert_then_find_roundtrip(self, risk_repo):
        await risk_repo.upsert_classification(
            HILToolRiskRecord(tool_name="t", description_hash="h1", is_destructive=True)
        )

        got = await risk_repo.find_classification("t", "h1")

        assert got is not None and got.is_destructive is True
        assert await risk_repo.find_classification("t", "other-hash") is None

    async def test_upsert_overwrites_the_same_key_in_place(self, risk_repo):
        await risk_repo.upsert_classification(
            HILToolRiskRecord(tool_name="t", description_hash="h1", is_destructive=True)
        )
        await risk_repo.upsert_classification(
            HILToolRiskRecord(tool_name="t", description_hash="h1", is_destructive=False)
        )

        got = await risk_repo.find_classification("t", "h1")

        assert got is not None and got.is_destructive is False
