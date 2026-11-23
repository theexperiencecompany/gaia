"""Contract tests for the HIL tool caches: one verdict per tool, overwritten in place."""

from __future__ import annotations

import pytest

from app.db.repositories.hil import HilToolRiskRepository, ToolReadOnlyVerdictRepository
from app.models.hil_models import HILToolRiskRecord, ToolReadOnlyVerdict


@pytest.fixture
def risk_repo(raw_collection) -> HilToolRiskRepository:
    return HilToolRiskRepository()


@pytest.fixture
def verdict_repo(raw_collection) -> ToolReadOnlyVerdictRepository:
    return ToolReadOnlyVerdictRepository()


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


class TestToolReadOnlyVerdictRepository:
    async def test_a_stored_verdict_is_found_by_its_tool_hash_and_classifier(self, verdict_repo):
        await verdict_repo.upsert_verdict(
            ToolReadOnlyVerdict(
                tool_hash="h1", classifier="c1", tool_name="list_issues", read_only=True
            )
        )

        got = await verdict_repo.find_verdict("h1", "c1")

        assert got is not None
        assert (got.tool_hash, got.tool_name, got.read_only) == ("h1", "list_issues", True)
        assert await verdict_repo.find_verdict("other-hash", "c1") is None
        # A changed classifier (model or prompt) never reads an older classifier's verdict.
        assert await verdict_repo.find_verdict("h1", "c2") is None

    async def test_a_verdict_is_stored_as_one_document_keyed_by_tool_hash_with_no_id_field(
        self, verdict_repo, raw_collection
    ):
        await verdict_repo.upsert_verdict(
            ToolReadOnlyVerdict(tool_hash="h1", classifier="c1", tool_name="t", read_only=True)
        )

        [stored] = await raw_collection.find({}).to_list(None)

        assert set(stored) == {
            "_id",
            "tool_hash",
            "classifier",
            "tool_name",
            "read_only",
            "rationale",
            "classified_at",
        }

    async def test_a_second_verdict_on_one_hash_overwrites_the_first_in_place(self, verdict_repo):
        await verdict_repo.upsert_verdict(
            ToolReadOnlyVerdict(
                tool_hash="h1", classifier="c1", tool_name="t", read_only=True, rationale="reads"
            )
        )
        await verdict_repo.upsert_verdict(
            ToolReadOnlyVerdict(
                tool_hash="h1", classifier="c1", tool_name="t", read_only=False, rationale="writes"
            )
        )

        got = await verdict_repo.find_verdict("h1", "c1")

        assert got is not None
        assert (got.read_only, got.rationale) == (False, "writes")
