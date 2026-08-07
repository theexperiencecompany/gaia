"""Contract tests for SearchUrlsRepository (global, identity = business ``url``)."""

from __future__ import annotations

import uuid

import pytest

from app.db.repositories.search_urls import SearchUrlsRepository
from app.models.search_models import SearchUrlDocument


def _doc(url: str, **overrides: object) -> SearchUrlDocument:
    data: dict[str, object] = {
        "url": url,
        "title": "Example",
        "description": "An example page",
        "favicon": "https://example.com/favicon.ico",
        "website_name": "Example",
        "website_image": "https://example.com/og.png",
    }
    data.update(overrides)
    return SearchUrlDocument.model_validate(data)


@pytest.fixture
def repo(raw_collection) -> SearchUrlsRepository:
    return SearchUrlsRepository()


class TestSearchUrlsRepository:
    async def test_get_by_url_miss_then_hit(self, repo):
        url = f"https://example.com/{uuid.uuid4().hex}"
        assert await repo.get_by_url(url) is None

        await repo.create(_doc(url, title="Cached Title"))

        found = await repo.get_by_url(url)
        assert found is not None
        assert found.url == url
        assert found.title == "Cached Title"

    async def test_urls_are_isolated_by_address(self, repo):
        a = f"https://a.example/{uuid.uuid4().hex}"
        b = f"https://b.example/{uuid.uuid4().hex}"
        await repo.create(_doc(a, website_name="A"))
        await repo.create(_doc(b, website_name="B"))

        assert (await repo.get_by_url(a)).website_name == "A"
        assert (await repo.get_by_url(b)).website_name == "B"

    async def test_optional_metadata_roundtrips_none(self, repo):
        url = f"https://sparse.example/{uuid.uuid4().hex}"
        await repo.create(
            SearchUrlDocument(url=url)  # every metadata field left None
        )
        found = await repo.get_by_url(url)
        assert found is not None
        assert found.title is None and found.favicon is None
