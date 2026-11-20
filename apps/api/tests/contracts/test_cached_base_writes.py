"""Cached repository write paths against real Mongo + Redis: what each write leaves in the cache."""

from __future__ import annotations

from typing import cast

from bson import ObjectId
from pymongo.errors import BulkWriteError
import pytest
from redis.asyncio import Redis

from app.db.redis import set_cache
from app.db.repositories.cache import CachePolicy
from app.db.repositories.cached_base import CachedUserScopedRepository
from app.utils.errors import RepositoryMisconfiguredError
from tests.contracts.cached_repos import (
    ENTITY_TTL,
    GLOBAL_POLICY,
    USER_POLICY,
    CacheItem,
    CacheItemUpdate,
    GlobalCacheRepository,
    GlobalItem,
    GlobalItemUpdate,
    UserCacheRepository,
    by_id,
    cached_entity,
    entity_ttl,
    generation,
    make_item,
)


@pytest.fixture
async def repo(raw_collection) -> UserCacheRepository:
    await raw_collection.create_index("slug", unique=True)
    return UserCacheRepository()


async def _cold(redis: Redis, repo: UserCacheRepository, item: CacheItem) -> None:
    """Drop the entity key create just wrote, so the next read starts from Mongo."""
    await redis.delete(repo.cache_policy.entity_key(item.user_id, item.id))


# --- misconfiguration -------------------------------------------------------


def test_a_cached_repository_without_a_policy_is_refused_at_class_creation() -> None:
    with pytest.raises(RepositoryMisconfiguredError) as refused:

        class Unpolicied(CachedUserScopedRepository[CacheItem, CacheItemUpdate]):
            collection_name = "x"
            document_model = CacheItem
            update_model = CacheItemUpdate
            uses_object_id = True

    assert refused.value.message == "Unpolicied is a cached repository without a cache_policy"
    assert refused.value.fix == "set cache_policy = CachePolicy(...) on Unpolicied"


def test_a_policy_that_is_not_a_cache_policy_is_refused() -> None:
    with pytest.raises(RepositoryMisconfiguredError):

        class WrongPolicy(CachedUserScopedRepository[CacheItem, CacheItemUpdate]):
            collection_name = "x"
            document_model = CacheItem
            update_model = CacheItemUpdate
            uses_object_id = True
            cache_policy = cast(CachePolicy, "not a policy")


def test_an_abstract_cached_repository_needs_no_policy() -> None:
    class Shared(CachedUserScopedRepository[CacheItem, CacheItemUpdate], abstract=True):
        pass

    class Concrete(Shared):
        collection_name = "x"
        document_model = CacheItem
        update_model = CacheItemUpdate
        uses_object_id = True
        cache_policy = CachePolicy(prefix="x")

    assert Concrete.cache_policy.prefix == "x"


def test_an_unknown_class_keyword_is_refused() -> None:
    with pytest.raises(TypeError):

        class Odd(CachedUserScopedRepository[CacheItem, CacheItemUpdate], abstract=True, bogus=1):
            pass


async def test_a_cached_user_write_whose_filter_names_no_user_is_refused(repo) -> None:
    with pytest.raises(RepositoryMisconfiguredError) as refused:
        await repo._fetch("0" * 24, {})

    assert refused.value.message == "UserCacheRepository write names no user_id in its filter"
    assert refused.value.why == "a cached user-scoped write must say whose cache it invalidates"
    assert refused.value.fix == 'put "user_id": user_id in the filter'


async def test_a_filter_whose_user_is_an_operator_is_refused(repo) -> None:
    with pytest.raises(RepositoryMisconfiguredError):
        await repo._fetch("0" * 24, {"user_id": {"$ne": "u1"}})


# --- create / read ----------------------------------------------------------


async def test_create_caches_the_document_under_its_owner_and_bumps_only_that_owners_generation(
    repo, redis
) -> None:
    created = await repo.create(make_item("u1"))

    assert await cached_entity(repo, "u1", created.id) == created
    assert ENTITY_TTL - 60 < await entity_ttl(redis, repo, "u1", created.id) <= ENTITY_TTL
    assert await generation(redis, USER_POLICY, "u1") == 1
    assert await generation(redis, USER_POLICY, "u2") == 0


async def test_a_read_miss_caches_what_mongo_returned(repo, redis) -> None:
    created = await repo.create(make_item())
    await _cold(redis, repo, created)

    assert await repo.get(created.id, user_id="u1") == created

    assert await cached_entity(repo, "u1", created.id) == created
    assert ENTITY_TTL - 60 < await entity_ttl(redis, repo, "u1", created.id) <= ENTITY_TTL


async def test_a_cached_read_is_served_without_asking_mongo(repo, raw_collection) -> None:
    created = await repo.create(make_item(name="cached"))
    await raw_collection.update_one({"_id": ObjectId(created.id)}, {"$set": {"name": "behind"}})

    served = await repo.get(created.id, user_id="u1")

    assert served is not None
    assert served.name == "cached"


async def test_a_missing_document_is_not_cached_and_reads_none(repo, redis) -> None:
    missing = str(ObjectId())

    assert await repo.get(missing, user_id="u1") is None
    assert await redis.exists(repo.cache_policy.entity_key("u1", missing)) == 0


async def test_another_users_cached_copy_is_never_served(repo) -> None:
    created = await repo.create(make_item("owner"))

    assert await repo.get(created.id, user_id="attacker") is None


# --- update / remove --------------------------------------------------------


async def test_update_replaces_the_cached_copy_and_bumps_the_generation(repo, redis) -> None:
    created = await repo.create(make_item(name="old"))

    updated = await repo.update(created.id, user_id="u1", update=CacheItemUpdate(name="new"))

    assert updated is not None
    assert await cached_entity(repo, "u1", created.id) == updated
    assert updated.name == "new"
    assert await generation(redis, USER_POLICY, "u1") == 2


async def test_a_refused_update_evicts_the_possibly_stale_copy_without_bumping(
    repo, raw_collection, redis
) -> None:
    created = await repo.create(make_item(name="old"))
    await raw_collection.update_one({"_id": ObjectId(created.id)}, {"$set": {"name": "behind"}})

    refused = await repo._apply_update(
        created.id, {"user_id": "u1", "name": "expected"}, CacheItemUpdate(name="x")
    )

    assert refused is None
    assert await cached_entity(repo, "u1", created.id) is None
    assert await generation(redis, USER_POLICY, "u1") == 1
    assert (await repo.get(created.id, user_id="u1")).name == "behind"


async def test_an_untouched_update_keeps_updated_at(repo) -> None:
    created = await repo.create(make_item())

    kept = await repo._apply_update(
        created.id, {"user_id": "u1"}, CacheItemUpdate(name="quiet"), touch=False
    )

    assert kept is not None
    assert kept.name == "quiet"
    assert kept.updated_at == created.updated_at


async def test_a_delete_evicts_the_copy_and_bumps_the_generation(repo, redis) -> None:
    created = await repo.create(make_item())

    assert await repo.delete(created.id, user_id="u1") is True

    assert await cached_entity(repo, "u1", created.id) is None
    assert await generation(redis, USER_POLICY, "u1") == 2


async def test_a_delete_that_removes_nothing_leaves_the_cache_alone(repo, redis) -> None:
    created = await repo.create(make_item("owner"))

    assert await repo.delete(created.id, user_id="attacker") is False

    assert await cached_entity(repo, "owner", created.id) == created
    assert await generation(redis, USER_POLICY, "attacker") == 0
    assert await generation(redis, USER_POLICY, "owner") == 1


async def test_delete_many_evicts_every_deleted_copy_and_bumps_once(repo, redis) -> None:
    gone_a = await repo.create(make_item(name="gone"))
    gone_b = await repo.create(make_item(name="gone"))
    kept = await repo.create(make_item(name="kept"))

    deleted = await repo._delete_many({"user_id": "u1", "name": "gone"})

    assert deleted == 2
    assert await cached_entity(repo, "u1", gone_a.id) is None
    assert await cached_entity(repo, "u1", gone_b.id) is None
    assert await cached_entity(repo, "u1", kept.id) == kept
    assert await generation(redis, USER_POLICY, "u1") == 4


async def test_delete_many_that_matches_nothing_leaves_the_cache_alone(repo, redis) -> None:
    created = await repo.create(make_item(name="kept"))

    assert await repo._delete_many({"user_id": "u1", "name": "nothing"}) == 0

    assert await cached_entity(repo, "u1", created.id) == created
    assert await generation(redis, USER_POLICY, "u1") == 1


# --- raw updates ------------------------------------------------------------


async def test_a_raw_update_replaces_the_cached_copy_with_the_after_image(repo, redis) -> None:
    created = await repo.create(make_item(name="old"))

    after = await repo._apply_raw_update(by_id(created.id), {"$set": {"name": "raw"}})

    assert after is not None
    assert after.name == "raw"
    assert await cached_entity(repo, "u1", created.id) == after
    assert await generation(redis, USER_POLICY, "u1") == 2


async def test_a_raw_update_scopes_its_cache_by_the_user_in_the_extra_filter(repo) -> None:
    created = await repo.create(make_item(name="old"))

    after = await repo._apply_raw_update(
        {"_id": ObjectId(created.id)}, {"$set": {"name": "raw"}}, extra_filter={"user_id": "u1"}
    )

    assert after is not None
    assert await cached_entity(repo, "u1", created.id) == after


async def test_a_raw_update_refused_by_its_extra_filter_changes_nothing(repo) -> None:
    created = await repo.create(make_item(name="old"))

    refused = await repo._apply_raw_update(
        by_id(created.id), {"$set": {"name": "raw"}}, extra_filter={"name": "other"}
    )

    assert refused is None
    assert (await repo.get(created.id, user_id="u1")).name == "old"


async def test_a_raw_update_honours_array_filters(repo) -> None:
    created = await repo.create(
        make_item(entries=[{"key": "a", "count": 1}, {"key": "b", "count": 1}])
    )

    after = await repo._apply_raw_update(
        by_id(created.id),
        {"$set": {"entries.$[hit].count": 9}},
        array_filters=[{"hit.key": "b"}],
    )

    assert after is not None
    assert [(e.key, e.count) for e in after.entries] == [("a", 1), ("b", 9)]


async def test_a_raw_upsert_creates_the_document_and_caches_it(repo, redis) -> None:
    new_id = ObjectId()

    created = await repo._apply_raw_update(
        {"_id": new_id, "user_id": "u1"},
        {"$set": {"name": "fresh", "slug": "fresh-slug"}},
        upsert=True,
    )

    assert created is not None
    assert created.id == str(new_id)
    assert await cached_entity(repo, "u1", created.id) == created
    assert await generation(redis, USER_POLICY, "u1") == 1


async def test_a_raw_update_without_upsert_creates_nothing(repo, raw_collection) -> None:
    result = await repo._apply_raw_update(by_id(str(ObjectId())), {"$set": {"name": "x"}})

    assert result is None
    assert await raw_collection.count_documents({}) == 0


async def test_a_raw_update_returning_the_before_image_does_not_reseed_the_cache(
    repo, redis
) -> None:
    created = await repo.create(make_item(name="old"))

    before = await repo._apply_raw_update(
        by_id(created.id), {"$set": {"name": "new"}}, return_document=False
    )

    assert before is not None
    assert before.name == "old"
    assert await cached_entity(repo, "u1", created.id) is None
    assert await generation(redis, USER_POLICY, "u1") == 2
    assert (await repo.get(created.id, user_id="u1")).name == "new"


async def test_a_raw_update_that_misses_evicts_the_targeted_copy_only(repo, redis) -> None:
    gone = str(ObjectId())
    await set_cache(USER_POLICY.entity_key("u1", gone), make_item(id=gone), model=CacheItem)

    assert await repo._apply_raw_update(by_id(gone), {"$set": {"name": "x"}}) is None

    assert await cached_entity(repo, "u1", gone) is None
    assert await generation(redis, USER_POLICY, "u1") == 0


async def test_a_raw_miss_on_a_set_filter_evicts_nothing(repo, redis) -> None:
    created = await repo.create(make_item(name="kept"))

    missed = await repo._apply_raw_update(
        {"_id": {"$in": [ObjectId(created.id)]}, "user_id": "u1", "name": "other"},
        {"$set": {"name": "x"}},
    )

    assert missed is None
    assert await cached_entity(repo, "u1", created.id) == created


# --- unfetched raw updates --------------------------------------------------


async def test_an_unfetched_raw_update_evicts_the_copy_and_bumps(repo, redis) -> None:
    created = await repo.create(make_item(name="old"))

    matched = await repo._apply_raw_update_unfetched(by_id(created.id), {"$set": {"name": "new"}})

    assert matched == 1
    assert await cached_entity(repo, "u1", created.id) is None
    assert await generation(redis, USER_POLICY, "u1") == 2


async def test_an_unfetched_raw_update_scopes_by_the_user_in_the_extra_filter(repo, redis) -> None:
    created = await repo.create(make_item(name="old"))

    matched = await repo._apply_raw_update_unfetched(
        {"_id": ObjectId(created.id)}, {"$set": {"name": "new"}}, extra_filter={"user_id": "u1"}
    )

    assert matched == 1
    assert await cached_entity(repo, "u1", created.id) is None


async def test_an_unfetched_raw_update_refused_by_its_extra_filter_leaves_the_cache(
    repo, redis
) -> None:
    created = await repo.create(make_item(name="old"))

    matched = await repo._apply_raw_update_unfetched(
        by_id(created.id), {"$set": {"name": "new"}}, extra_filter={"name": "other"}
    )

    assert matched == 0
    assert await cached_entity(repo, "u1", created.id) == created
    assert await generation(redis, USER_POLICY, "u1") == 1


async def test_an_unfetched_raw_update_honours_array_filters(repo) -> None:
    created = await repo.create(
        make_item(entries=[{"key": "a", "count": 1}, {"key": "b", "count": 1}])
    )

    await repo._apply_raw_update_unfetched(
        by_id(created.id),
        {"$set": {"entries.$[hit].count": 9}},
        array_filters=[{"hit.key": "b"}],
    )

    stored = await repo.get(created.id, user_id="u1")
    assert stored is not None
    assert [(e.key, e.count) for e in stored.entries] == [("a", 1), ("b", 9)]


async def test_an_unfetched_raw_update_does_not_upsert_unless_asked(repo, raw_collection) -> None:
    matched = await repo._apply_raw_update_unfetched(
        by_id(str(ObjectId())), {"$set": {"name": "x", "slug": "s"}}
    )

    assert matched == 0
    assert await raw_collection.count_documents({}) == 0


async def test_an_unfetched_upsert_that_inserts_still_invalidates_the_scope(
    repo, raw_collection, redis
) -> None:
    matched = await repo._apply_raw_update_unfetched(
        {"_id": ObjectId(), "user_id": "u1"}, {"$set": {"name": "x", "slug": "s"}}, upsert=True
    )

    assert matched == 0
    assert await raw_collection.count_documents({}) == 1
    assert await generation(redis, USER_POLICY, "u1") == 1


# --- pipeline updates -------------------------------------------------------

_APPEND_BANG = [{"$set": {"name": {"$concat": ["$name", "!"]}}}]


async def test_a_pipeline_update_replaces_the_cached_copy_with_the_after_image(repo, redis) -> None:
    created = await repo.create(make_item(name="hey"))

    after = await repo._apply_pipeline_update(by_id(created.id), _APPEND_BANG)

    assert after is not None
    assert after.name == "hey!"
    assert await cached_entity(repo, "u1", created.id) == after
    assert await generation(redis, USER_POLICY, "u1") == 2


async def test_a_pipeline_update_that_misses_evicts_the_targeted_copy(repo, redis) -> None:
    gone = str(ObjectId())
    await set_cache(USER_POLICY.entity_key("u1", gone), make_item(id=gone), model=CacheItem)

    assert await repo._apply_pipeline_update(by_id(gone), _APPEND_BANG) is None

    assert await cached_entity(repo, "u1", gone) is None
    assert await generation(redis, USER_POLICY, "u1") == 0


async def test_an_unfetched_pipeline_update_evicts_the_copy_and_bumps(repo, redis) -> None:
    created = await repo.create(make_item(name="hey"))

    matched = await repo._apply_pipeline_update_unfetched(by_id(created.id), _APPEND_BANG)

    assert matched == 1
    assert await cached_entity(repo, "u1", created.id) is None
    assert await generation(redis, USER_POLICY, "u1") == 2


async def test_an_unfetched_pipeline_update_honours_its_extra_filter(repo, redis) -> None:
    created = await repo.create(make_item(name="hey"))

    refused = await repo._apply_pipeline_update_unfetched(
        by_id(created.id), _APPEND_BANG, extra_filter={"name": "other"}
    )
    scoped = await repo._apply_pipeline_update_unfetched(
        {"_id": ObjectId(created.id)}, _APPEND_BANG, extra_filter={"user_id": "u1"}
    )

    assert refused == 0
    assert scoped == 1
    assert (await repo.get(created.id, user_id="u1")).name == "hey!"


# --- increment / no-invalidate ----------------------------------------------


async def test_an_increment_caches_the_after_image_and_bumps(repo, redis) -> None:
    created = await repo.create(make_item())

    after = await repo._increment(created.id, "hits", 3, extra_filter={"user_id": "u1"})

    assert after is not None
    assert after.hits == 3
    assert await cached_entity(repo, "u1", created.id) == after
    assert await generation(redis, USER_POLICY, "u1") == 2


async def test_an_increment_refused_by_its_extra_filter_changes_nothing(repo, redis) -> None:
    created = await repo.create(make_item())

    refused = await repo._increment(
        created.id, "hits", 3, extra_filter={"user_id": "u1", "name": "other"}
    )

    assert refused is None
    assert (await repo.get(created.id, user_id="u1")).hits == 0
    assert await generation(redis, USER_POLICY, "u1") == 1


async def test_a_no_invalidate_write_reaches_mongo_but_not_the_cache(
    repo, raw_collection, redis
) -> None:
    created = await repo.create(make_item(name="old"))

    await repo._update_fields_no_invalidate({"_id": ObjectId(created.id)}, {"name": "hot"})

    assert (await raw_collection.find_one({"_id": ObjectId(created.id)}))["name"] == "hot"
    assert await cached_entity(repo, "u1", created.id) == created
    assert await generation(redis, USER_POLICY, "u1") == 1


# --- bulk writes ------------------------------------------------------------


async def test_a_bulk_set_evicts_every_touched_copy_and_bumps(repo, redis) -> None:
    first = await repo.create(make_item(name="a"))
    second = await repo.create(make_item(name="b"))

    modified = await repo._bulk_set(
        [(first.id, CacheItemUpdate(name="x")), (second.id, CacheItemUpdate(name="y"))],
        user_id="u1",
    )

    assert modified == 2
    assert await cached_entity(repo, "u1", first.id) is None
    assert await cached_entity(repo, "u1", second.id) is None
    assert await generation(redis, USER_POLICY, "u1") == 3


async def test_a_bulk_set_that_modifies_nothing_leaves_the_cache(repo, redis) -> None:
    created = await repo.create(make_item("owner"))

    modified = await repo._bulk_set([(created.id, CacheItemUpdate(name="x"))], user_id="attacker")

    assert modified == 0
    assert await cached_entity(repo, "owner", created.id) == created
    assert await generation(redis, USER_POLICY, "attacker") == 0


async def test_a_bulk_set_that_fails_midway_still_evicts_what_it_may_have_written(
    repo, redis
) -> None:
    first = await repo.create(make_item(name="a"))
    second = await repo.create(make_item(name="b"))

    with pytest.raises(BulkWriteError):
        await repo._bulk_set(
            [(first.id, CacheItemUpdate(name="x")), (second.id, CacheItemUpdate(slug=first.slug))],
            user_id="u1",
        )

    assert await cached_entity(repo, "u1", first.id) is None
    assert await cached_entity(repo, "u1", second.id) is None
    assert await generation(redis, USER_POLICY, "u1") == 3
    assert (await repo.get(first.id, user_id="u1")).name == "x"


async def test_a_bulk_delete_evicts_every_deleted_copy_and_bumps(repo, redis) -> None:
    first = await repo.create(make_item())
    second = await repo.create(make_item())

    deleted = await repo._bulk_delete([first.id, second.id], user_id="u1")

    assert deleted == 2
    assert await cached_entity(repo, "u1", first.id) is None
    assert await cached_entity(repo, "u1", second.id) is None
    assert await generation(redis, USER_POLICY, "u1") == 3


async def test_a_bulk_delete_that_removes_nothing_leaves_the_cache(repo, redis) -> None:
    created = await repo.create(make_item("owner"))

    assert await repo._bulk_delete([created.id], user_id="attacker") == 0

    assert await cached_entity(repo, "owner", created.id) == created
    assert await generation(redis, USER_POLICY, "attacker") == 0


# --- the global scope -------------------------------------------------------


async def test_a_global_repository_caches_and_invalidates_under_the_one_global_scope(
    raw_collection, redis
) -> None:
    repo = GlobalCacheRepository()

    created = await repo.create(GlobalItem(name="old"))
    updated = await repo.update(created.id, GlobalItemUpdate(name="new"))

    assert updated is not None
    entity_key = GLOBAL_POLICY.entity_key("global", created.id)
    assert await redis.exists(entity_key) == 1
    assert await generation(redis, GLOBAL_POLICY, "global") == 2
    assert await repo.get(created.id) == updated

    assert await repo.delete(created.id) is True
    assert await redis.exists(entity_key) == 0
    assert await generation(redis, GLOBAL_POLICY, "global") == 3
