"""Contract tests for LinkReportsRepository over real Mongo: one report per reporter per link."""

from __future__ import annotations

from collections.abc import AsyncIterator

from motor.motor_asyncio import AsyncIOMotorCollection
import pytest

from app.db.mongodb.indexes import create_short_link_indexes
from app.db.repositories.link_reports import LinkReportsRepository
from app.models.short_link_models import LinkReport, ReportReason


def _report(slug: str, reporter_key: str, *, signed_in: bool = True) -> LinkReport:
    return LinkReport(
        slug=slug, reason=ReportReason.PHISHING, reporter_key=reporter_key, signed_in=signed_in
    )


@pytest.fixture
async def repo(
    raw_collection: AsyncIOMotorCollection, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[LinkReportsRepository]:
    """Return the repository over a collection carrying the real link_reports unique index."""
    # The builder also indexes short_links (slug unique), which must land on a collection of its own.
    short_links = raw_collection.database[f"{raw_collection.name}_short_links"]

    def collection(name: str) -> AsyncIOMotorCollection:
        return raw_collection if name == "link_reports" else short_links

    monkeypatch.setattr("app.db.mongodb.indexes.get_async_collection", collection)
    await create_short_link_indexes()
    yield LinkReportsRepository()
    await short_links.drop()


async def test_a_first_report_is_recorded(
    repo: LinkReportsRepository, raw_collection: AsyncIOMotorCollection
) -> None:
    assert await repo.add(_report("s1", "user-a")) is True
    assert await raw_collection.count_documents({"slug": "s1", "reporter_key": "user-a"}) == 1


async def test_a_reporter_counts_once_per_link(
    repo: LinkReportsRepository, raw_collection: AsyncIOMotorCollection
) -> None:
    await repo.add(_report("s1", "user-a"))

    assert await repo.add(_report("s1", "user-a")) is False
    assert await raw_collection.count_documents({"slug": "s1"}) == 1
    assert await repo.add(_report("s2", "user-a")) is True


async def test_only_signed_in_reporters_of_that_link_are_counted(
    repo: LinkReportsRepository,
) -> None:
    await repo.add(_report("s1", "user-a"))
    await repo.add(_report("s1", "user-b"))
    await repo.add(_report("s1", "address-hash", signed_in=False))
    await repo.add(_report("s2", "user-c"))

    assert await repo.signed_in_reporters("s1") == 2
    assert await repo.signed_in_reporters("unreported") == 0
