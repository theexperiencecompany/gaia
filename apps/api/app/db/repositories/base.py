"""Generic MongoDB repository base with automatic, generation-based caching.

Public methods accept and return typed Pydantic models only — raw dicts,
``ObjectId``, Mongo filters, and cache calls never cross this boundary. The
subclass primitives (leading underscore) are the internal seam where dict-shaped
Mongo data is allowed. See ``app/db/repositories/CLAUDE.md``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
import functools
import inspect
from typing import ClassVar, Generic, TypeVar, cast

from bson import ObjectId
from pydantic import BaseModel, ConfigDict
from pymongo import ReturnDocument, UpdateOne

from app.constants.cache import REPO_GLOBAL_SCOPE
from app.db.mongodb.collections import get_async_collection
from app.db.redis import delete_cache, get_cache, set_cache
from app.db.repositories.cache import (
    CachePolicy,
    bump_generation,
    query_arg_hash,
    read_generation,
)
from app.utils.errors import AppError, EmptyUpdateError, RepositoryMisconfigured


class MongoDocument(BaseModel):
    """Base for every repository document model — carries the string id.

    ``extra="ignore"`` so a legacy document with stray fields still reads (the
    write side is fully controlled by the update model's ``extra="forbid"``).
    """

    model_config = ConfigDict(extra="ignore")

    id: str = ""


class UserScopedDocument(MongoDocument):
    """A document owned by a user — the base for user-scoped repositories."""

    user_id: str


TDoc = TypeVar("TDoc", bound=MongoDocument)
TUserDoc = TypeVar("TUserDoc", bound=UserScopedDocument)
TUpdate = TypeVar("TUpdate", bound=BaseModel)
TResult = TypeVar("TResult", bound=BaseModel)
_TReturn = TypeVar("_TReturn")

_REQUIRED_CLASSVARS = ("collection_name", "document_model", "update_model", "uses_object_id")


def cached_query(
    result_model: type[_TReturn],
) -> Callable[[Callable[..., Awaitable[_TReturn]]], Callable[..., Awaitable[_TReturn]]]:
    """Cache a named finder's result under its scope's current generation.

    Key is ``{method}:{hash(args)}`` under the scope (its ``user_id`` argument,
    or ``"global"``). A write to that scope bumps the generation and orphans the
    entry. ``result_model`` is the finder's return type (e.g. ``list[NoteDocument]``).
    """

    def decorator(fn: Callable[..., Awaitable[_TReturn]]) -> Callable[..., Awaitable[_TReturn]]:
        signature = inspect.signature(fn)

        @functools.wraps(fn)
        async def wrapper(
            self: _BaseRepository[MongoDocument, BaseModel], *args: object, **kwargs: object
        ) -> _TReturn:
            policy = self.cache_policy
            if policy is None:
                return await fn(self, *args, **kwargs)
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
                return cast(_TReturn, cached)
            result = await fn(self, *args, **kwargs)
            if result is not None:
                await set_cache(key, result, ttl=policy.query_ttl, model=result_model)
            return result

        return wrapper

    return decorator


class _BaseRepository(Generic[TDoc, TUpdate]):
    """Shared CRUD + cache machinery. Do not subclass directly — use one of the
    two public bases (``MongoRepository`` / ``UserScopedRepository``)."""

    collection_name: ClassVar[str]
    document_model: type[TDoc]
    update_model: type[TUpdate]
    uses_object_id: ClassVar[bool]
    cache_policy: ClassVar[CachePolicy | None] = None

    def __init_subclass__(cls, abstract: bool = False, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if abstract:
            return
        missing = [name for name in _REQUIRED_CLASSVARS if getattr(cls, name, None) is None]
        if missing:
            raise RepositoryMisconfigured(
                message=f"{cls.__name__} is missing repository ClassVars: {', '.join(missing)}",
                why="a concrete repository must declare its collection and its models",
                fix=f"set {', '.join(missing)} on {cls.__name__}",
            )
        for attr in ("document_model", "update_model"):
            model = getattr(cls, attr)
            if not (isinstance(model, type) and issubclass(model, BaseModel)):
                raise RepositoryMisconfigured(
                    message=f"{cls.__name__}.{attr} must be a pydantic BaseModel subclass"
                )

    # ---- id / model conversion (the one place ObjectId and _id are handled) ----

    def _id_value(self, doc_id: str) -> object:
        return ObjectId(doc_id) if self.uses_object_id else doc_id

    def _to_model(self, raw: Mapping[str, object]) -> TDoc:
        data = dict(raw)
        identifier = data.pop("_id", None)
        if identifier is not None:
            data["id"] = str(identifier) if self.uses_object_id else identifier
        return self.document_model.model_validate(data)

    def _doc_scope(self, doc: TDoc) -> str:
        return REPO_GLOBAL_SCOPE

    # ---- cache helpers ----

    async def _cache_store(self, scope: str, doc: TDoc) -> None:
        policy = self.cache_policy
        if policy is not None:
            await set_cache(
                policy.entity_key(scope, doc.id),
                doc,
                ttl=policy.entity_ttl,
                model=self.document_model,
            )

    async def _cache_evict(self, scope: str, doc_id: str) -> None:
        policy = self.cache_policy
        if policy is not None:
            await delete_cache(policy.entity_key(scope, doc_id))

    async def _invalidate(self, scope: str) -> None:
        policy = self.cache_policy
        if policy is not None:
            await bump_generation(policy, scope)

    # ---- write/read cores (public methods below are thin scope wrappers) ----

    async def create(self, doc: TDoc) -> TDoc:
        return await self._insert(doc, self._doc_scope(doc))

    async def _insert(self, doc: TDoc, scope: str) -> TDoc:
        data = doc.model_dump(exclude={"id"})
        now = datetime.now(UTC)
        fields = self.document_model.model_fields
        if "created_at" in fields:
            data["created_at"] = now
        if "updated_at" in fields:
            data["updated_at"] = now
        if not self.uses_object_id and doc.id:
            data["_id"] = doc.id
        collection = get_async_collection(self.collection_name)
        result = await collection.insert_one(data)
        stored = await collection.find_one({"_id": result.inserted_id})
        if stored is None:
            raise AppError(message="inserted document could not be read back")
        created = self._to_model(stored)
        await self._cache_store(scope, created)
        await self._invalidate(scope)
        return created

    async def _fetch(
        self, doc_id: str, scope: str, extra_filter: Mapping[str, object]
    ) -> TDoc | None:
        policy = self.cache_policy
        if policy is not None:
            cached = await get_cache(policy.entity_key(scope, doc_id), model=self.document_model)
            if cached is not None:
                return cast(TDoc, cached)
        collection = get_async_collection(self.collection_name)
        raw = await collection.find_one({"_id": self._id_value(doc_id), **extra_filter})
        if raw is None:
            return None
        doc = self._to_model(raw)
        if policy is not None:
            await set_cache(
                policy.entity_key(scope, doc_id),
                doc,
                ttl=policy.entity_ttl,
                model=self.document_model,
            )
        return doc

    async def _apply_update(
        self, doc_id: str, scope: str, extra_filter: Mapping[str, object], update: TUpdate
    ) -> TDoc | None:
        set_fields = update.model_dump(exclude_unset=True)
        if not set_fields:
            raise EmptyUpdateError(
                message="update contains no fields to set",
                why="a write that changes nothing is a bug (a typo'd or empty update)",
                fix="set at least one field on the update model",
            )
        if "updated_at" in self.document_model.model_fields:
            set_fields["updated_at"] = datetime.now(UTC)
        raw = await get_async_collection(self.collection_name).find_one_and_update(
            {"_id": self._id_value(doc_id), **extra_filter},
            {"$set": set_fields},
            return_document=ReturnDocument.AFTER,
        )
        if raw is None:
            return None
        doc = self._to_model(raw)
        await self._cache_store(scope, doc)
        await self._invalidate(scope)
        return doc

    async def _remove(self, doc_id: str, scope: str, extra_filter: Mapping[str, object]) -> bool:
        result = await get_async_collection(self.collection_name).delete_one(
            {"_id": self._id_value(doc_id), **extra_filter}
        )
        deleted = result.deleted_count > 0
        if deleted:
            await self._cache_evict(scope, doc_id)
            await self._invalidate(scope)
        return deleted

    async def _count(self, filter_: Mapping[str, object]) -> int:
        return await get_async_collection(self.collection_name).count_documents(dict(filter_))

    # ---- subclass-only primitives (never called outside a repository) ----

    async def _find(
        self,
        filter_: Mapping[str, object],
        *,
        sort: Sequence[tuple[str, int]] | None = None,
        limit: int = 0,
        skip: int = 0,
    ) -> list[TDoc]:
        cursor = get_async_collection(self.collection_name).find(dict(filter_))
        if sort is not None:
            cursor = cursor.sort(list(sort))
        if skip:
            cursor = cursor.skip(skip)
        if limit:
            cursor = cursor.limit(limit)
        raw_docs = await cursor.to_list(length=limit or None)
        return [self._to_model(raw) for raw in raw_docs]

    async def _aggregate(
        self, pipeline: Sequence[Mapping[str, object]], result_model: type[TResult]
    ) -> list[TResult]:
        cursor = get_async_collection(self.collection_name).aggregate(
            [dict(stage) for stage in pipeline]
        )
        raw_results = await cursor.to_list(length=None)
        return [result_model.model_validate(raw) for raw in raw_results]

    async def _bulk_set(self, updates: Sequence[tuple[str, TUpdate]], *, scope: str) -> int:
        """Apply many typed ``$set`` updates in one round trip. All ids must share
        ``scope`` (the caller's user) so one generation bump invalidates them."""
        if not updates:
            return 0
        stamp_updated_at = "updated_at" in self.document_model.model_fields
        now = datetime.now(UTC)
        operations: list[UpdateOne] = []
        for doc_id, update in updates:
            set_fields = update.model_dump(exclude_unset=True)
            if not set_fields:
                raise EmptyUpdateError(message=f"bulk update for {doc_id} has no fields to set")
            if stamp_updated_at:
                set_fields["updated_at"] = now
            operations.append(UpdateOne({"_id": self._id_value(doc_id)}, {"$set": set_fields}))
        result = await get_async_collection(self.collection_name).bulk_write(operations)
        modified = result.modified_count
        if modified:
            for doc_id, _ in updates:
                await self._cache_evict(scope, doc_id)
            await self._invalidate(scope)
        return modified

    async def _increment(
        self,
        doc_id: str,
        field: str,
        by: int,
        *,
        scope: str,
        extra_filter: Mapping[str, object] | None = None,
    ) -> TDoc | None:
        raw = await get_async_collection(self.collection_name).find_one_and_update(
            {"_id": self._id_value(doc_id), **(extra_filter or {})},
            {"$inc": {field: by}},
            return_document=ReturnDocument.AFTER,
        )
        if raw is None:
            return None
        doc = self._to_model(raw)
        await self._cache_store(scope, doc)
        await self._invalidate(scope)
        return doc

    async def _update_fields_no_invalidate(
        self, filter_: Mapping[str, object], fields: Mapping[str, object]
    ) -> None:
        """Write hot fields without touching the cache or bumping the generation.

        A deliberate hole in the invalidation guarantee — only for fields whose
        staleness is harmless (e.g. ``last_active_at``). Justify every use in the
        calling method's docstring; if unsure, use the normal update path.
        """
        await get_async_collection(self.collection_name).update_one(
            dict(filter_), {"$set": dict(fields)}
        )


class MongoRepository(_BaseRepository[TDoc, TUpdate], abstract=True):
    """Global (non-user-scoped) repository. Every operation is keyed by id alone."""

    async def get(self, doc_id: str) -> TDoc | None:
        return await self._fetch(doc_id, REPO_GLOBAL_SCOPE, {})

    async def update(self, doc_id: str, update: TUpdate) -> TDoc | None:
        return await self._apply_update(doc_id, REPO_GLOBAL_SCOPE, {}, update)

    async def delete(self, doc_id: str) -> bool:
        return await self._remove(doc_id, REPO_GLOBAL_SCOPE, {})

    async def count(self) -> int:
        return await self._count({})


class UserScopedRepository(_BaseRepository[TUserDoc, TUpdate], abstract=True):
    """User-scoped repository. Every public method requires ``user_id`` and every
    Mongo filter includes ``{"user_id": user_id}`` — cross-user access returns
    ``None``/``False``, never another user's data."""

    def _doc_scope(self, doc: TUserDoc) -> str:
        return doc.user_id

    async def get(self, doc_id: str, *, user_id: str) -> TUserDoc | None:
        return await self._fetch(doc_id, user_id, {"user_id": user_id})

    async def update(self, doc_id: str, *, user_id: str, update: TUpdate) -> TUserDoc | None:
        return await self._apply_update(doc_id, user_id, {"user_id": user_id}, update)

    async def delete(self, doc_id: str, *, user_id: str) -> bool:
        return await self._remove(doc_id, user_id, {"user_id": user_id})

    async def list_for_user(
        self,
        user_id: str,
        *,
        sort: Sequence[tuple[str, int]] | None = None,
        limit: int = 0,
        skip: int = 0,
    ) -> list[TUserDoc]:
        return await self._find({"user_id": user_id}, sort=sort, limit=limit, skip=skip)

    async def count_for_user(self, user_id: str) -> int:
        return await self._count({"user_id": user_id})
