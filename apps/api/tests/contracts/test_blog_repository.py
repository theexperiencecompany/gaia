"""Contract tests for BlogsRepository (global, read-through with a team join).

The author ``$lookup`` resolves to the real ``gaia_test.team`` collection (a
``$lookup`` binds by collection name at the database level, not through the
patched accessor), so these tests seed a uniquely-identified team member there
and assert membership — robust to the shared collection under parallel xdist.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
import uuid

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorCollection
import pytest

from app.db.repositories.blog import BlogsRepository


@pytest.fixture
def repo(raw_collection) -> BlogsRepository:
    return BlogsRepository()


@pytest.fixture
async def team(raw_collection) -> AsyncIterator[AsyncIOMotorCollection]:
    """The shared ``gaia_test.team`` collection, with per-test ids cleaned up."""
    coll = raw_collection.database["team"]
    inserted: list[ObjectId] = []

    yield _TrackingTeam(coll, inserted)

    if inserted:
        await coll.delete_many({"_id": {"$in": inserted}})


class _TrackingTeam:
    """Thin wrapper that records inserted team ids for teardown."""

    def __init__(self, coll: AsyncIOMotorCollection, inserted: list[ObjectId]) -> None:
        self._coll = coll
        self._inserted = inserted

    async def add_member(self, *, name: str, role: str = "Engineer") -> str:
        member_id = ObjectId()
        self._inserted.append(member_id)
        await self._coll.insert_one({"_id": member_id, "name": name, "role": role})
        return str(member_id)


def _blog(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "slug": f"post-{uuid.uuid4().hex}",
        "title": "A Post",
        "date": "2026-01-01",
        "authors": [],
        "category": "eng",
        "content": "Body text",
    }
    data.update(overrides)
    return data


class TestBlogsRepository:
    async def test_count_is_isolated(self, repo, raw_collection):
        await raw_collection.insert_many([_blog(), _blog(), _blog()])
        assert await repo.count() == 3

    async def test_get_by_slug_populates_author_details(self, repo, raw_collection, team):
        author_id = await team.add_member(name="Ada Lovelace", role="Author")
        slug = f"post-{uuid.uuid4().hex}"
        await raw_collection.insert_one(_blog(slug=slug, authors=[author_id], content="Full body"))

        post = await repo.get_by_slug(slug)
        assert post is not None
        assert post.slug == slug
        assert post.content == "Full body"
        assert isinstance(post.id, str) and len(post.id) == 24
        assert post.author_details is not None
        assert "Ada Lovelace" in {a.name for a in post.author_details}

    async def test_get_by_slug_missing_returns_none(self, repo, raw_collection):
        assert await repo.get_by_slug(f"missing-{uuid.uuid4().hex}") is None

    async def test_author_fallback_when_no_team_match(self, repo, raw_collection):
        slug = f"post-{uuid.uuid4().hex}"
        await raw_collection.insert_one(_blog(slug=slug, authors=["ghost-author"]))

        post = await repo.get_by_slug(slug)
        assert post is not None
        assert post.author_details is not None and len(post.author_details) == 1
        assert post.author_details[0].name == "ghost-author"
        assert post.author_details[0].role == "Author"

    async def test_list_page_orders_newest_first_and_drops_content(self, repo, raw_collection):
        await raw_collection.insert_one(_blog(slug="old", date="2026-01-01", content="old body"))
        await raw_collection.insert_one(_blog(slug="new", date="2026-02-01", content="new body"))

        posts = await repo.list_page(skip=0, limit=10, include_content=False)
        assert [p.slug for p in posts] == ["new", "old"]  # date descending
        assert all(p.content == "" for p in posts)  # content omitted from list view

    async def test_search_matches_title(self, repo, raw_collection):
        # No index setup: search must plan on a bare collection, exactly as it
        # does in production (`create_blog_indexes` declares no `title` index).
        await raw_collection.insert_one(_blog(slug="a", title="Rust ownership model"))
        await raw_collection.insert_one(_blog(slug="b", title="Cooking pasta"))

        results = await repo.search("Rust", skip=0, limit=10)
        assert {p.slug for p in results} == {"a"}

    async def test_search_matches_category_and_content(self, repo, raw_collection):
        await raw_collection.insert_one(_blog(slug="by-category", category="rustaceans"))
        await raw_collection.insert_one(
            _blog(slug="by-content", category="eng", content="a deep dive into Rust internals")
        )
        await raw_collection.insert_one(_blog(slug="miss", category="food", content="Pasta"))

        results = await repo.search("rust", skip=0, limit=10)
        assert {p.slug for p in results} == {"by-category", "by-content"}

    async def test_search_treats_the_query_as_a_literal(self, repo, raw_collection):
        await raw_collection.insert_one(_blog(slug="literal", title="C++ (a.k.a. cpp)"))
        await raw_collection.insert_one(_blog(slug="other", title="Plain title"))

        results = await repo.search("C++ (a.k.a.", skip=0, limit=10)
        assert {p.slug for p in results} == {"literal"}

    async def test_search_orders_newest_first_and_paginates(self, repo, raw_collection):
        await raw_collection.insert_one(_blog(slug="mid", title="Rust two", date="2026-02-01"))
        await raw_collection.insert_one(_blog(slug="new", title="Rust three", date="2026-03-01"))
        await raw_collection.insert_one(_blog(slug="old", title="Rust one", date="2026-01-01"))

        assert [p.slug for p in await repo.search("Rust", skip=0, limit=2)] == ["new", "mid"]
        assert [p.slug for p in await repo.search("Rust", skip=2, limit=2)] == ["old"]
