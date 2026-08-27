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
from typing import Any, ClassVar, Generic, TypeVar, cast

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorCollection
from pydantic import BaseModel, ConfigDict, ValidationError
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
from app.utils.errors import AppError, EmptyUpdateError, RepositoryMisconfiguredError
from shared.py.wide_events import log


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
# Bound to the decorated finder itself so ``cached_query`` preserves its exact
# signature — parameter list and return type, ``| None`` included.
_TFinder = TypeVar("_TFinder", bound=Callable[..., Awaitable[Any]])

_REQUIRED_CLASSVARS = ("collection_name", "document_model", "update_model", "uses_object_id")


def cached_query(result_model: type[Any]) -> Callable[[_TFinder], _TFinder]:
    """Cache a named finder's result under its scope's current generation.

    Key is ``{method}:{hash(args)}`` under the scope (its ``user_id`` argument,
    or ``"global"``). A write to that scope bumps the generation and orphans the
    entry.

    ``result_model`` is the shape stored under the key: the finder's return type
    (e.g. ``list[NoteDocument]``), or — for a finder that may return ``None`` —
    its non-``None`` part, since ``None`` is never cached. The decorator preserves
    the finder's own signature, so an ``X | None`` finder stays ``X | None``.
    """

    def decorator(fn: _TFinder) -> _TFinder:
        signature = inspect.signature(fn)

        @functools.wraps(fn)
        async def wrapper(
            self: _BaseRepository[MongoDocument, BaseModel], *args: object, **kwargs: object
        ) -> object:
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
                return cached
            result = await fn(self, *args, **kwargs)
            if result is not None:
                await set_cache(key, result, ttl=policy.query_ttl, model=result_model)
            return result

        return cast(_TFinder, wrapper)

    return decorator


class _BaseRepository(Generic[TDoc, TUpdate]):
    """Shared CRUD + cache machinery. Do not subclass directly — use one of the
    two public bases (``MongoRepository`` / ``UserScopedRepository``)."""

    collection_name: ClassVar[str]
    document_model: type[TDoc]
    update_model: type[TUpdate]
    uses_object_id: ClassVar[bool]
    cache_policy: ClassVar[CachePolicy | None] = None
    # The document's identity field. Defaults to Mongo's ``_id``; a domain keyed
    # by a business field (e.g. ``conversation_id``, a UUID ``id``) sets this so
    # get/update/delete filter on it and ``_id`` stays incidental.
    identity_field: ClassVar[str] = "_id"
    # Whether the base auto-stamps ``created_at``/``updated_at`` on writes. A
    # domain that stores its timestamps in a shape the base must not touch — e.g.
    # legacy ISO-format strings, or a field it wants left unset on insert — turns
    # this off and writes those fields itself. See the timestamp-normalization
    # follow-up before flipping any existing collection.
    auto_stamp_timestamps: ClassVar[bool] = True

    def __init_subclass__(cls, abstract: bool = False, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if abstract:
            return
        missing = [name for name in _REQUIRED_CLASSVARS if getattr(cls, name, None) is None]
        if missing:
            raise RepositoryMisconfiguredError(
                message=f"{cls.__name__} is missing repository ClassVars: {', '.join(missing)}",
                why="a concrete repository must declare its collection and its models",
                fix=f"set {', '.join(missing)} on {cls.__name__}",
            )
        for attr in ("document_model", "update_model"):
            model = getattr(cls, attr)
            if not (isinstance(model, type) and issubclass(model, BaseModel)):
                raise RepositoryMisconfiguredError(
                    message=f"{cls.__name__}.{attr} must be a pydantic BaseModel subclass"
                )

    # ---- id / model conversion (the one place ObjectId and _id are handled) ----

    def _id_value(self, doc_id: str) -> object:
        # Only the Mongo ``_id`` identity is wrapped as an ObjectId; a business-key
        # identity (conversation_id, a UUID id) is matched as the plain string.
        if self.identity_field == "_id" and self.uses_object_id:
            return ObjectId(doc_id)
        return doc_id

    def _identity_filter(self, doc_id: str) -> dict[str, object]:
        return {self.identity_field: self._id_value(doc_id)}

    def _doc_identity(self, doc: TDoc) -> str:
        return doc.id if self.identity_field == "_id" else str(getattr(doc, self.identity_field))

    def _to_model(self, raw: Mapping[str, object]) -> TDoc:
        data = dict(raw)
        identifier = data.pop("_id", None)
        # Map ``_id`` onto the model's ``id`` only when ``_id`` is the identity;
        # for a business-key identity the model already carries its own id field
        # and the incidental ObjectId is dropped.
        if self.identity_field == "_id" and identifier is not None:
            data["id"] = str(identifier) if self.uses_object_id else identifier
        return self.document_model.model_validate(data)

    def _doc_scope(self, _doc: TDoc) -> str:
        return REPO_GLOBAL_SCOPE

    def _scope_filter(self, _scope: str) -> dict[str, object]:
        """Extra Mongo filter constraining an operation to ``scope``.

        Empty for a global repository; ``{"user_id": scope}`` for a user-scoped
        one, so the multi-document primitives (``_bulk_set``, ``_bulk_delete``)
        never reach across users the way a raw ``{"_id": ...}`` filter would.
        """
        return {}

    # ---- cache helpers ----

    async def _cache_store(self, scope: str, doc: TDoc) -> None:
        policy = self.cache_policy
        if policy is not None:
            await set_cache(
                policy.entity_key(scope, self._doc_identity(doc)),
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
        # Drop the placeholder ``id`` (it mirrors ``_id``) — but keep it when ``id``
        # is itself the business identity (a caller-provided UUID). exclude_none so
        # an unset optional field is absent, not stored as null: a later nested
        # `$set` (onboarding.x) or `{$exists: false}` gate needs the container field
        # absent, and absent reads back identically to null anyway.
        exclude = set() if self.identity_field == "id" else {"id"}
        data = doc.model_dump(exclude=exclude, exclude_none=True)
        now = datetime.now(UTC)
        fields = self.document_model.model_fields
        # Stamp created_at only when the caller didn't provide it (some domains,
        # e.g. notifications, set their own creation time); always stamp updated_at.
        if self.auto_stamp_timestamps and "created_at" in fields and data.get("created_at") is None:
            data["created_at"] = now
        if self.auto_stamp_timestamps and "updated_at" in fields:
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
        raw = await collection.find_one({**self._identity_filter(doc_id), **extra_filter})
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
        if self.auto_stamp_timestamps and "updated_at" in self.document_model.model_fields:
            set_fields["updated_at"] = datetime.now(UTC)
        raw = await get_async_collection(self.collection_name).find_one_and_update(
            {**self._identity_filter(doc_id), **extra_filter},
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
            {**self._identity_filter(doc_id), **extra_filter}
        )
        deleted = result.deleted_count > 0
        if deleted:
            await self._cache_evict(scope, doc_id)
            await self._invalidate(scope)
        return deleted

    async def _count(self, filter_: Mapping[str, object]) -> int:
        return await get_async_collection(self.collection_name).count_documents(dict(filter_))

    async def _delete_many(self, filter_: Mapping[str, object], *, scope: str) -> int:
        """Delete every document matching ``filter_`` in one round trip, then evict
        each removed doc's entity-cache key and bump ``scope``'s generation. The
        filter-based sibling of ``_bulk_delete`` (which deletes by id list) — for the
        global-collection-with-a-guard case (e.g. ``{_id: {$in}, user_id}``) and
        domain-level wipes like "all of a user's conversations".

        Structurally cache-safe on any repository: when an entity cache exists, the
        matched ids are resolved first, then deleted, then their entity keys evicted
        — so the generation bump (which only orphans query caches) can't leave a
        stale by-id read served from the entity cache. Evict happens AFTER the delete
        so a concurrent read-through can't re-populate an entity we then leave stale
        (a post-delete get misses Mongo and never re-caches). When ``cache_policy is
        None`` there is no entity cache and no id pre-fetch: a single ``delete_many``.
        Returns the deleted count."""
        collection = get_async_collection(self.collection_name)
        ids: list[str] = []
        if self.cache_policy is not None:
            async for raw in collection.find(dict(filter_)):
                ids.append(self._doc_identity(self._to_model(raw)))
        result = await collection.delete_many(dict(filter_))
        if result.deleted_count:
            for doc_id in ids:
                await self._cache_evict(scope, doc_id)
            await self._invalidate(scope)
        return int(result.deleted_count)

    async def _distinct(self, field: str, filter_: Mapping[str, object] | None = None) -> list[str]:
        """Distinct string values of a field. Read-only (no cache interaction)."""
        values = await get_async_collection(self.collection_name).distinct(
            field, dict(filter_) if filter_ is not None else None
        )
        return [str(value) for value in values]

    # ---- subclass-only primitives (never called outside a repository) ----

    def _raw_collection(self) -> AsyncIOMotorCollection[dict[str, Any]]:
        """The repository's own Motor handle, for the rare operator no base
        primitive expresses (e.g. an aggregation-pipeline update or a filter
        upsert). Resolves through this module's ``get_async_collection`` binding —
        the seam the contract and service fixtures patch — so a subclass's raw
        call can never drift off the test wiring the way a direct import would.
        The caller owns any cache eviction the write implies."""
        return get_async_collection(self.collection_name)

    async def _find_one(self, filter_: Mapping[str, object]) -> TDoc | None:
        raw = await get_async_collection(self.collection_name).find_one(dict(filter_))
        return None if raw is None else self._to_model(raw)

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

    async def _find_lenient(
        self,
        filter_: Mapping[str, object],
        *,
        sort: Sequence[tuple[str, int]] | None = None,
        limit: int = 0,
        skip: int = 0,
    ) -> list[TDoc]:
        """Like ``_find``, but a single row that fails model validation is skipped
        and logged loudly rather than failing the whole read.

        For user-facing LIST reads where one corrupt legacy document must not blank
        the entire result. ``_find`` stays the strict default so single-document and
        internal reads still fail loud — a validation error there surfaces the
        corruption instead of hiding it.
        """
        cursor = get_async_collection(self.collection_name).find(dict(filter_))
        if sort is not None:
            cursor = cursor.sort(list(sort))
        if skip:
            cursor = cursor.skip(skip)
        if limit:
            cursor = cursor.limit(limit)
        docs: list[TDoc] = []
        async for raw in cursor:
            try:
                docs.append(self._to_model(raw))
            except ValidationError as exc:
                log.warning(
                    "[repository] skipping malformed document in lenient list read",
                    collection=self.collection_name,
                    document_id=raw.get("_id"),
                    error=str(exc),
                )
        return docs

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
        stamp_updated_at = (
            self.auto_stamp_timestamps and "updated_at" in self.document_model.model_fields
        )
        now = datetime.now(UTC)
        scope_filter = self._scope_filter(scope)
        operations: list[UpdateOne] = []
        for doc_id, update in updates:
            set_fields = update.model_dump(exclude_unset=True)
            if not set_fields:
                raise EmptyUpdateError(message=f"bulk update for {doc_id} has no fields to set")
            if stamp_updated_at:
                set_fields["updated_at"] = now
            operations.append(
                UpdateOne({**self._identity_filter(doc_id), **scope_filter}, {"$set": set_fields})
            )
        result = await get_async_collection(self.collection_name).bulk_write(operations)
        modified = result.modified_count
        if modified:
            for doc_id, _ in updates:
                await self._cache_evict(scope, doc_id)
            await self._invalidate(scope)
        return modified

    async def _bulk_delete(self, doc_ids: Sequence[str], *, scope: str) -> int:
        """Delete many documents in one round trip. All ids must share ``scope``
        (the caller's user) so one generation bump invalidates them together."""
        if not doc_ids:
            return 0
        result = await get_async_collection(self.collection_name).delete_many(
            {
                "_id": {"$in": [self._id_value(doc_id) for doc_id in doc_ids]},
                **self._scope_filter(scope),
            }
        )
        deleted = result.deleted_count
        if deleted:
            for doc_id in doc_ids:
                await self._cache_evict(scope, doc_id)
            await self._invalidate(scope)
        return deleted

    async def _apply_raw_update(
        self,
        filter_: Mapping[str, object],
        update: Mapping[str, Mapping[str, object]],
        *,
        scope: str,
        extra_filter: Mapping[str, object] | None = None,
        return_document: bool = True,
        array_filters: Sequence[Mapping[str, object]] | None = None,
        upsert: bool = False,
    ) -> TDoc | None:
        """Apply a raw Mongo update to one document, then refresh the entity cache
        and bump the generation exactly like the typed ``update`` path. With
        ``return_document=False`` the read-back is the BEFORE image, so the entity
        key is evicted rather than stored — the cache is never seeded from it.

        The typed ``$set``-from-model path (public ``update``) is preferred; this is
        the internal seam for the operators a typed model cannot express —
        ``$push``/``$pull``/``$addToSet`` on arrays, positional ``$set`` with
        ``array_filters``, and ``$unset``. ``updated_at`` is stamped into ``$set``
        automatically when the document declares it. ``scope`` names the cache scope
        (usually the owning ``user_id``); ``extra_filter`` adds guards (e.g. a
        ``vfs_path`` existence check) to ``filter_``. ``return_document`` selects the
        AFTER (default) or BEFORE image. ``upsert`` inserts the document when the
        filter matches nothing — for atomic get-or-create with ``$setOnInsert``
        (returning BEFORE on an insert yields ``None``).
        """
        ops: dict[str, dict[str, object]] = {k: dict(v) for k, v in update.items()}
        if self.auto_stamp_timestamps and "updated_at" in self.document_model.model_fields:
            ops.setdefault("$set", {})["updated_at"] = datetime.now(UTC)
        collection = get_async_collection(self.collection_name)
        raw = await collection.find_one_and_update(
            {**dict(filter_), **(extra_filter or {})},
            ops,
            array_filters=[dict(f) for f in array_filters] if array_filters is not None else None,
            return_document=ReturnDocument.AFTER if return_document else ReturnDocument.BEFORE,
            upsert=upsert,
        )
        if raw is None:
            return None
        doc = self._to_model(raw)
        if return_document:
            await self._cache_store(scope, doc)
        else:
            # ``doc`` is the BEFORE image — storing it would re-seed the entity
            # cache with the pre-write document. Evict instead.
            await self._cache_evict(scope, self._doc_identity(doc))
        await self._invalidate(scope)
        return doc

    async def _apply_raw_update_unfetched(
        self,
        filter_: Mapping[str, object],
        update: Mapping[str, Mapping[str, object]],
        *,
        scope: str,
        doc_id: str | None = None,
        extra_filter: Mapping[str, object] | None = None,
        array_filters: Sequence[Mapping[str, object]] | None = None,
        upsert: bool = False,
    ) -> int:
        """Apply a raw update via ``update_one`` WITHOUT reading the document back.

        The ``_apply_raw_update`` sibling pays a full ``find_one_and_update`` read
        on every call; this is the seam for hot write paths where the after-image
        is not needed — e.g. ``$push``-ing onto a large embedded array on every
        chat turn, where reloading the whole document each time would be wasteful.
        It is also the seam for an ``upsert`` whose inserted document must NOT be
        validated as a full ``document_model`` — e.g. a tools-only stub that only
        carries a business key and one field (``_apply_raw_update``'s read-back
        would fail model validation on such a partial doc). Refreshes the cache
        exactly like any other write: evicts the entity key when ``doc_id`` is
        given and bumps the generation. ``updated_at`` is auto-stamped into
        ``$set`` when the document declares it. Returns the matched count (0 = the
        filter matched no existing document; an upsert-insert also reports 0).
        """
        ops: dict[str, dict[str, object]] = {k: dict(v) for k, v in update.items()}
        if self.auto_stamp_timestamps and "updated_at" in self.document_model.model_fields:
            ops.setdefault("$set", {})["updated_at"] = datetime.now(UTC)
        result = await get_async_collection(self.collection_name).update_one(
            {**dict(filter_), **(extra_filter or {})},
            ops,
            array_filters=[dict(f) for f in array_filters] if array_filters is not None else None,
            upsert=upsert,
        )
        touched = result.matched_count or (upsert and result.upserted_id is not None)
        if touched:
            if doc_id is not None:
                await self._cache_evict(scope, doc_id)
            await self._invalidate(scope)
        return result.matched_count

    async def _find_one_projected(
        self,
        filter_: Mapping[str, object],
        projection: Mapping[str, object],
        result_model: type[TResult],
    ) -> TResult | None:
        """Read one document under a Mongo projection into a typed partial model.

        For reads that need only a slice of a document — a single field, or one
        positional ``messages.$`` element — so a large embedded array is never
        loaded in full. ``result_model`` describes exactly the projected shape.
        """
        raw = await get_async_collection(self.collection_name).find_one(
            dict(filter_), dict(projection)
        )
        return None if raw is None else result_model.model_validate(raw)

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
            {**self._identity_filter(doc_id), **(extra_filter or {})},
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

    def _scope_filter(self, scope: str) -> dict[str, object]:
        return {"user_id": scope}

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
