"""Contract + finder tests for ProjectsRepository against real Mongo + Redis."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from app.db.repositories.projects import ProjectsRepository
from app.models.todo_models import ProjectDocument, ProjectUpdate
from tests.contracts.base_contract import UserScopedRepositoryContract


@pytest.fixture
def repo(raw_collection) -> ProjectsRepository:
    return ProjectsRepository()


@pytest.fixture
def make_doc() -> Callable[..., ProjectDocument]:
    def _make(**overrides: object) -> ProjectDocument:
        return ProjectDocument.model_validate({"user_id": "user-1", "name": "Work", **overrides})

    return _make


@pytest.fixture
def make_update() -> Callable[..., ProjectUpdate]:
    def _make(**fields: object) -> ProjectUpdate:
        return ProjectUpdate.model_validate(fields or {"name": "Renamed"})

    return _make


class TestProjectsRepository(UserScopedRepositoryContract):
    """Runs the full user-scoped contract against the real projects repository."""

    async def list_via_cache(self, repo, user_id: str) -> list:
        return await repo.list_with_counts(user_id=user_id)

    # ProjectDocument has no `title` field — the two base cache tests that use
    # `title` as the sample mutable string are re-expressed here against `name`.

    async def test_second_get_serves_from_cache(self, repo, make_doc, raw_collection, redis):
        created = await repo.create(make_doc(name="original"))
        await repo.get(created.id, user_id=created.user_id)
        await raw_collection.update_one(
            {"_id": repo._id_value(created.id)}, {"$set": {"name": "mutated-in-db"}}
        )
        again = await repo.get(created.id, user_id=created.user_id)
        assert again is not None
        assert again.name == "original"  # served stale from cache, proving the hit

    async def test_redis_down_degrades_to_mongo_not_error(self, repo, make_doc, monkeypatch):
        from app.db.redis import redis_cache

        monkeypatch.setattr(redis_cache, "redis", None)
        created = await repo.create(make_doc(name="no-redis"))
        fetched = await repo.get(created.id, user_id=created.user_id)
        assert fetched is not None
        assert fetched.name == "no-redis"

    # ---- finder tests ------------------------------------------------------

    async def test_get_or_create_inbox_is_idempotent(self, repo):
        first = await repo.get_or_create_inbox("owner")
        assert first.is_default is True
        assert first.name == "Inbox"
        second = await repo.get_or_create_inbox("owner")
        assert second.id == first.id  # not re-created
        assert await repo.count_for_user("owner") == 1

    async def test_get_default_inbox_returns_none_before_creation(self, repo):
        assert await repo.get_default_inbox("owner") is None
        created = await repo.get_or_create_inbox("owner")
        found = await repo.get_default_inbox("owner")
        assert found is not None
        assert found.id == created.id

    async def test_list_with_counts_returns_only_the_users_projects(self, repo, make_doc):
        await repo.create(make_doc(user_id="owner", name="A"))
        await repo.create(make_doc(user_id="owner", name="B"))
        await repo.create(make_doc(user_id="other", name="C"))
        projects = await repo.list_with_counts(user_id="owner")
        assert sorted(p.name for p in projects) == ["A", "B"]
        assert all(p.user_id == "owner" for p in projects)
        assert all(p.todo_count == 0 for p in projects)


class TestProjectDeletes:
    async def test_delete_all_for_user_is_scoped(self, repo, make_doc):
        await repo.create(make_doc(user_id="u1", name="p1"))
        await repo.create(make_doc(user_id="u1", name="p2"))
        await repo.create(make_doc(user_id="u2", name="p3"))
        assert await repo.delete_all_for_user("u1") == 2
        assert await repo.delete_all_for_user("u2") == 1
