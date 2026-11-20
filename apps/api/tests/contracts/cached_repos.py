"""Cached repositories over a throwaway collection, for the cached_base contract suites.

One user-scoped and one global repository, each with a cached finder, plus the Redis
readers the suites assert on. Every test reads the real keys the base wrote, never a spy.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from bson import ObjectId
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis

from app.db.redis import get_cache
from app.db.repositories.base import MongoDocument, UserScopedDocument
from app.db.repositories.cache import CachePolicy
from app.db.repositories.cached_base import (
    CachedMongoRepository,
    CachedUserScopedRepository,
    cached_query,
)

ENTITY_TTL = 1111
QUERY_TTL = 2222
USER_POLICY = CachePolicy(prefix="cbuser", entity_ttl=ENTITY_TTL, query_ttl=QUERY_TTL)
GLOBAL_POLICY = CachePolicy(prefix="cbglobal", entity_ttl=ENTITY_TTL, query_ttl=QUERY_TTL)


class Entry(BaseModel):
    key: str
    count: int = 0


class CacheItem(UserScopedDocument):
    name: str = ""
    slug: str
    hits: int = 0
    entries: list[Entry] = Field(default_factory=list)
    updated_at: datetime | None = None


class CacheItemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    slug: str | None = None


class GlobalItem(MongoDocument):
    name: str = ""


class GlobalItemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None


class UserCacheRepository(CachedUserScopedRepository[CacheItem, CacheItemUpdate]):
    collection_name = "cached_base_items"
    document_model = CacheItem
    update_model = CacheItemUpdate
    uses_object_id = True
    cache_policy = USER_POLICY

    def __init__(self) -> None:
        self.finder_runs = 0


class GlobalCacheRepository(CachedMongoRepository[GlobalItem, GlobalItemUpdate]):
    collection_name = "cached_base_global_items"
    document_model = GlobalItem
    update_model = GlobalItemUpdate
    uses_object_id = True
    cache_policy = GLOBAL_POLICY

    def __init__(self) -> None:
        self.finder_runs = 0


def user_repository_with_finders() -> UserCacheRepository:
    """Build the repository inside the test, so cached_query decorates under whatever mutant is active."""

    class UserFinders(UserCacheRepository):
        @cached_query(list[CacheItem])
        async def named(self, user_id: str, name: str, limit: int = 10) -> list[CacheItem]:
            """Items of a user with this name."""
            self.finder_runs += 1
            return await self._find({"user_id": user_id, "name": name}, limit=limit)

        @cached_query(CacheItem)
        async def first_named(self, user_id: str, name: str) -> CacheItem | None:
            self.finder_runs += 1
            return await self._find_one({"user_id": user_id, "name": name})

    return UserFinders()


class GlobalFinderRepository(Protocol):
    """The global repository with its cached finder, as the query tests use it."""

    finder_runs: int

    async def create(self, doc: GlobalItem) -> GlobalItem: ...

    async def named(self, name: str) -> list[GlobalItem]: ...


def global_repository_with_finders() -> GlobalFinderRepository:
    class GlobalFinders(GlobalCacheRepository):
        @cached_query(list[GlobalItem])
        async def named(self, name: str) -> list[GlobalItem]:
            self.finder_runs += 1
            return await self._find({"name": name})

    return GlobalFinders()


def make_item(user_id: str = "u1", **overrides: object) -> CacheItem:
    slug = str(ObjectId())
    return CacheItem.model_validate({"user_id": user_id, "slug": slug, **overrides})


def by_id(doc_id: str, user_id: str = "u1") -> dict[str, object]:
    return {"_id": ObjectId(doc_id), "user_id": user_id}


async def cached_entity(repo: UserCacheRepository, scope: str, doc_id: str) -> CacheItem | None:
    return await get_cache(repo.cache_policy.entity_key(scope, doc_id), model=CacheItem)


async def entity_ttl(redis: Redis, repo: UserCacheRepository, scope: str, doc_id: str) -> int:
    return await redis.ttl(repo.cache_policy.entity_key(scope, doc_id))


async def generation(redis: Redis, policy: CachePolicy, scope: str) -> int:
    return int(await redis.get(policy.generation_key(scope)) or 0)
