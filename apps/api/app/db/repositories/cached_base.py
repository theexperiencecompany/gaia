"""The cached repository bases: the only repositories that know a cache, or its scope, exists.

A cached repository declares its CachePolicy and picks the base whose scope rule it
follows: CachedMongoRepository caches under the one global scope, and
CachedUserScopedRepository under the user_id of the document or of the write's filter.
Every write primitive refreshes or evicts the entity key and bumps the scope's
generation, which orphans that scope's query caches. See CLAUDE.md in this directory.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
import functools
import inspect
from typing import Any, ClassVar, TypeVar, cast

from pydantic import BaseModel
from pymongo.errors import BulkWriteError

from app.constants.cache import REPO_GLOBAL_SCOPE
from app.db.redis import delete_cache, get_cache, set_cache
from app.db.repositories.base import (
    MongoDocument,
    MongoRepository,
    TDoc,
    TUpdate,
    TUserDoc,
    UserScopedRepository,
    _BaseRepository,
)
from app.db.repositories.cache import CachePolicy, bump_generation, query_arg_hash, read_generation
from app.utils.errors import RepositoryMisconfiguredError

# Bound to the decorated finder itself so cached_query preserves its exact
# signature — parameter list and return type, | None included.
_TFinder = TypeVar("_TFinder", bound=Callable[..., Awaitable[Any]])


class _CachedRepository(_BaseRepository[TDoc, TUpdate], abstract=True):
    """Entity cache and generation bumps around every write; subclass a scope-rule base, not this."""

    cache_policy: ClassVar[CachePolicy]

    def __init_subclass__(cls, abstract: bool = False, **kwargs: object) -> None:
        super().__init_subclass__(abstract=abstract, **kwargs)
        if not abstract and not isinstance(getattr(cls, "cache_policy", None), CachePolicy):
            raise RepositoryMisconfiguredError(
                message=f"{cls.__name__} is a cached repository without a cache_policy",
                fix=f"set cache_policy = CachePolicy(...) on {cls.__name__}",
            )

    def _doc_scope(self, doc: TDoc) -> str:
        raise NotImplementedError

    def _filter_scope(self, filter_: Mapping[str, object]) -> str:
        raise NotImplementedError

    async def _cache_store(self, scope: str, doc: TDoc) -> None:
        policy = self.cache_policy
        await set_cache(
            policy.entity_key(scope, self._doc_identity(doc)),
            doc,
            ttl=policy.entity_ttl,
            model=self.document_model,
        )

    async def _cache_evict(self, scope: str, doc_id: str) -> None:
        await delete_cache(self.cache_policy.entity_key(scope, doc_id))

    async def _invalidate(self, scope: str) -> None:
        await bump_generation(self.cache_policy, scope)

    async def _evict_many(self, scope: str, doc_ids: Sequence[str]) -> None:
        for doc_id in doc_ids:
            await self._cache_evict(scope, doc_id)
        await self._invalidate(scope)

    async def _stored(self, scope: str, doc: TDoc) -> TDoc:
        await self._cache_store(scope, doc)
        await self._invalidate(scope)
        return doc

    async def _insert(self, doc: TDoc) -> TDoc:
        return await self._stored(self._doc_scope(doc), await super()._insert(doc))

    async def _fetch(self, doc_id: str, extra_filter: Mapping[str, object]) -> TDoc | None:
        policy = self.cache_policy
        key = policy.entity_key(self._filter_scope(extra_filter), doc_id)
        cached = await get_cache(key, model=self.document_model)
        if cached is not None:
            return cast(TDoc, cached)
        doc = await super()._fetch(doc_id, extra_filter)
        if doc is not None:
            await set_cache(key, doc, ttl=policy.entity_ttl, model=self.document_model)
        return doc

    async def _apply_update(
        self,
        doc_id: str,
        extra_filter: Mapping[str, object],
        update: TUpdate,
        *,
        touch: bool = True,
    ) -> TDoc | None:
        scope = self._filter_scope(extra_filter)
        doc = await super()._apply_update(doc_id, extra_filter, update, touch=touch)
        if doc is None:
            # A refused compare-and-set may mean the cached copy is stale; the retry must read Mongo.
            await self._cache_evict(scope, doc_id)
            return None
        return await self._stored(scope, doc)

    async def _remove(self, doc_id: str, extra_filter: Mapping[str, object]) -> bool:
        deleted = await super()._remove(doc_id, extra_filter)
        if deleted:
            await self._evict_many(self._filter_scope(extra_filter), [doc_id])
        return deleted

    async def _delete_many(self, filter_: Mapping[str, object]) -> int:
        """Delete every match, evicting each one's entity key; ids are read before the delete."""
        scope = self._filter_scope(filter_)
        ids = [self._doc_identity(doc) for doc in await self._find(filter_)]
        deleted = await super()._delete_many(filter_)
        if deleted:
            await self._evict_many(scope, ids)
        return deleted

    async def _apply_raw_update(
        self,
        filter_: Mapping[str, object],
        update: Mapping[str, Mapping[str, object]],
        *,
        extra_filter: Mapping[str, object] | None = None,
        return_document: bool = True,
        array_filters: Sequence[Mapping[str, object]] | None = None,
        upsert: bool = False,
    ) -> TDoc | None:
        """Apply the raw update, then store the AFTER image or evict on a BEFORE image or a miss."""
        scope = self._filter_scope({**filter_, **(extra_filter or {})})
        doc = await super()._apply_raw_update(
            filter_,
            update,
            extra_filter=extra_filter,
            return_document=return_document,
            array_filters=array_filters,
            upsert=upsert,
        )
        if doc is None:
            await self._evict_targeted(scope, filter_)
            return None
        if return_document:
            return await self._stored(scope, doc)
        # The BEFORE image would re-seed the cache with the pre-write document.
        await self._evict_many(scope, [self._doc_identity(doc)])
        return doc

    async def _evict_targeted(self, scope: str, filter_: Mapping[str, object]) -> None:
        # A miss on a by-identity filter evicts, so a deleted document is never served from cache.
        targeted = self._filter_doc_id(filter_)
        if targeted is not None:
            await self._cache_evict(scope, targeted)

    async def _apply_raw_update_unfetched(
        self,
        filter_: Mapping[str, object],
        update: Mapping[str, Mapping[str, object]],
        *,
        extra_filter: Mapping[str, object] | None = None,
        array_filters: Sequence[Mapping[str, object]] | None = None,
        upsert: bool = False,
    ) -> int:
        result = await self._update_one(
            filter_, update, extra_filter=extra_filter, array_filters=array_filters, upsert=upsert
        )
        if result.matched_count or (upsert and result.upserted_id is not None):
            await self._evict_filtered(
                self._filter_scope({**filter_, **(extra_filter or {})}), filter_
            )
        return result.matched_count

    async def _evict_filtered(self, scope: str, filter_: Mapping[str, object]) -> None:
        await self._evict_targeted(scope, filter_)
        await self._invalidate(scope)

    async def _apply_pipeline_update(
        self,
        filter_: Mapping[str, object],
        pipeline: Sequence[Mapping[str, object]],
    ) -> TDoc | None:
        scope = self._filter_scope(filter_)
        doc = await super()._apply_pipeline_update(filter_, pipeline)
        if doc is None:
            await self._evict_targeted(scope, filter_)
            return None
        return await self._stored(scope, doc)

    async def _apply_pipeline_update_unfetched(
        self,
        filter_: Mapping[str, object],
        pipeline: Sequence[Mapping[str, object]],
        *,
        extra_filter: Mapping[str, object] | None = None,
    ) -> int:
        matched = await super()._apply_pipeline_update_unfetched(
            filter_, pipeline, extra_filter=extra_filter
        )
        if matched:
            await self._evict_filtered(
                self._filter_scope({**filter_, **(extra_filter or {})}), filter_
            )
        return matched

    async def _increment(
        self,
        doc_id: str,
        field: str,
        by: int,
        *,
        extra_filter: Mapping[str, object] | None = None,
    ) -> TDoc | None:
        doc = await super()._increment(doc_id, field, by, extra_filter=extra_filter)
        if doc is None:
            return None
        return await self._stored(self._filter_scope(extra_filter or {}), doc)

    async def _update_fields_no_invalidate(
        self, filter_: Mapping[str, object], fields: Mapping[str, object]
    ) -> None:
        """Write hot fields without touching the cache or bumping the generation.

        A deliberate hole in the invalidation guarantee — only for fields whose
        staleness is harmless (e.g. last_active_at). Justify every use in the
        calling method's docstring; if unsure, use the normal update path.
        """
        await self._raw_collection().update_one(dict(filter_), {"$set": dict(fields)})


class CachedMongoRepository(
    _CachedRepository[TDoc, TUpdate], MongoRepository[TDoc, TUpdate], abstract=True
):
    """A global repository whose cache has one scope, the global one."""

    def _doc_scope(self, _doc: TDoc) -> str:
        return REPO_GLOBAL_SCOPE

    def _filter_scope(self, _filter: Mapping[str, object]) -> str:
        return REPO_GLOBAL_SCOPE


class CachedUserScopedRepository(
    _CachedRepository[TUserDoc, TUpdate], UserScopedRepository[TUserDoc, TUpdate], abstract=True
):
    """A user-scoped repository whose cache scope is the user_id of the document or the write's filter.

    A write primitive takes no scope argument, so the user it touches is the user_id its
    filter pins; every cached user-scoped write names one, and one that does not is refused.
    """

    def _doc_scope(self, doc: TUserDoc) -> str:
        return doc.user_id

    def _filter_scope(self, filter_: Mapping[str, object]) -> str:
        user_id = filter_.get("user_id")
        if not isinstance(user_id, str):
            raise RepositoryMisconfiguredError(
                message=f"{type(self).__name__} write names no user_id in its filter",
                why="a cached user-scoped write must say whose cache it invalidates",
                fix='put "user_id": user_id in the filter',
            )
        return user_id

    async def _bulk_set(self, updates: Sequence[tuple[str, TUpdate]], *, user_id: str) -> int:
        doc_ids = [doc_id for doc_id, _ in updates]
        try:
            modified = await super()._bulk_set(updates, user_id=user_id)
        except BulkWriteError:
            # Ordered: the writes before the failing one landed, so their cache is stale too.
            await self._evict_many(user_id, doc_ids)
            raise
        if modified:
            await self._evict_many(user_id, doc_ids)
        return modified

    async def _bulk_delete(self, doc_ids: Sequence[str], *, user_id: str) -> int:
        deleted = await super()._bulk_delete(doc_ids, user_id=user_id)
        if deleted:
            await self._evict_many(user_id, doc_ids)
        return deleted


def cached_query(result_model: type[Any]) -> Callable[[_TFinder], _TFinder]:
    """Cache a named finder's result under its scope's current generation.

    Key is {method}:{hash(args)} under the scope (user_id, or "global"); a write to that
    scope bumps the generation and orphans the entry. result_model is the finder's return
    type, or its non-None part if it may return None, since None is never cached.
    """

    def decorator(fn: _TFinder) -> _TFinder:
        signature = inspect.signature(fn)

        @functools.wraps(fn)
        async def wrapper(
            self: _CachedRepository[MongoDocument, BaseModel], *args: object, **kwargs: object
        ) -> object:
            policy = self.cache_policy
            bound = signature.bind(self, *args, **kwargs)
            bound.apply_defaults()
            call_args = dict(bound.arguments)
            call_args.pop("self", None)
            scope = str(call_args.get("user_id", REPO_GLOBAL_SCOPE))
            generation = await read_generation(policy, scope)
            if generation is None:
                return await fn(self, *args, **kwargs)
            key = policy.query_key(scope, generation, fn.__name__, query_arg_hash(call_args))
            cached = await get_cache(key, model=result_model)
            if cached is not None:
                return cached
            result = await fn(self, *args, **kwargs)
            if result is not None:
                await set_cache(key, result, ttl=policy.query_ttl, model=result_model)
            return result

        return cast(_TFinder, wrapper)

    return decorator
