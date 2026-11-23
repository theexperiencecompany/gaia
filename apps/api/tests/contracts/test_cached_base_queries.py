"""cached_query against real Mongo + Redis: what a finder caches, under which key, until which write."""

from __future__ import annotations

from bson import ObjectId
import pytest

from app.db.redis import redis_cache
from app.db.repositories.cache import query_arg_hash
from app.db.repositories.cached_base import cached_query
from tests.contracts.cached_repos import (
    GLOBAL_POLICY,
    QUERY_TTL,
    USER_POLICY,
    CacheItemUpdate,
    GlobalItem,
    generation,
    global_repository_with_finders,
    make_item,
    user_repository_with_finders,
)


@pytest.fixture
async def repo(raw_collection):
    return user_repository_with_finders()


def _named_key(generation: int, **args: object) -> str:
    return USER_POLICY.query_key("u1", generation, "named", query_arg_hash(args))


async def test_a_finders_result_is_cached_under_its_scopes_generation_and_arguments(
    repo, redis
) -> None:
    created = await repo.create(make_item(name="a"))
    key = _named_key(1, user_id="u1", name="a", limit=10)

    assert await repo.named("u1", "a") == [created]

    assert await redis.exists(key) == 1
    assert QUERY_TTL - 60 < await redis.ttl(key) <= QUERY_TTL


async def test_a_cached_finder_is_served_without_running_or_asking_mongo(
    repo, raw_collection
) -> None:
    created = await repo.create(make_item(name="a"))
    await repo.named("u1", "a")
    await raw_collection.update_one({"_id": ObjectId(created.id)}, {"$set": {"name": "behind"}})

    served = await repo.named("u1", "a")

    assert served == [created]
    assert repo.finder_runs == 1


async def test_defaulted_positional_and_keyword_calls_share_one_cache_entry(repo) -> None:
    await repo.create(make_item(name="a"))

    await repo.named("u1", "a")
    await repo.named("u1", "a", 10)
    await repo.named(user_id="u1", name="a", limit=10)

    assert repo.finder_runs == 1


async def test_different_arguments_are_cached_apart(repo) -> None:
    await repo.create(make_item(name="a"))
    await repo.create(make_item(name="a"))

    assert len(await repo.named("u1", "a", limit=1)) == 1
    assert len(await repo.named("u1", "a", limit=2)) == 2
    assert repo.finder_runs == 2


async def test_a_write_to_the_scope_orphans_its_cached_finders(repo, redis) -> None:
    created = await repo.create(make_item(name="a"))
    await repo.named("u1", "a")

    await repo.update(created.id, user_id="u1", update=CacheItemUpdate(name="b"))

    assert await repo.named("u1", "a") == []
    assert repo.finder_runs == 2
    assert await generation(redis, USER_POLICY, "u1") == 2


async def test_a_write_to_one_users_scope_leaves_another_users_finders_cached(repo) -> None:
    await repo.create(make_item("u2", name="a"))
    await repo.named("u2", "a")

    await repo.create(make_item("u1", name="a"))

    await repo.named("u2", "a")
    assert repo.finder_runs == 1


async def test_a_miss_is_never_cached(repo, raw_collection) -> None:
    assert await repo.first_named("u1", "a") is None
    await raw_collection.insert_one(
        {"user_id": "u1", "name": "a", "slug": "behind-the-repositorys-back"}
    )

    found = await repo.first_named("u1", "a")

    assert found is not None
    assert found.slug == "behind-the-repositorys-back"
    assert repo.finder_runs == 2


async def test_a_found_document_is_cached_and_served_as_the_model(repo) -> None:
    created = await repo.create(make_item(name="a"))

    first = await repo.first_named("u1", "a")
    second = await repo.first_named("u1", "a")

    assert first == created
    assert second == created
    assert repo.finder_runs == 1


async def test_with_redis_unavailable_the_finder_runs_every_time(repo, monkeypatch) -> None:
    created = await repo.create(make_item(name="a"))
    monkeypatch.setattr(redis_cache, "redis", None)

    assert await repo.named("u1", "a") == [created]
    assert await repo.named(user_id="u1", name="a") == [created]

    assert repo.finder_runs == 2


async def test_a_global_finder_caches_under_the_global_scope(raw_collection, redis) -> None:
    repo = global_repository_with_finders()
    created = await repo.create(GlobalItem(name="a"))

    assert await repo.named("a") == [created]
    assert await repo.named("a") == [created]

    key = GLOBAL_POLICY.query_key("global", 1, "named", query_arg_hash({"name": "a"}))
    assert await redis.exists(key) == 1
    assert repo.finder_runs == 1


def test_a_cached_finder_keeps_its_name_and_docstring() -> None:
    @cached_query(list)
    async def named(self: object) -> list[object]:
        """Items with this name."""
        return []

    assert named.__name__ == "named"
    assert named.__doc__ == "Items with this name."
