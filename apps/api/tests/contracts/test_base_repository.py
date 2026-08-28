"""Base repository verification against real Mongo + Redis.

A test-only ``_FixtureRepository`` (its own tiny document/update models and a
throwaway collection) drives the whole base:
- ``TestFixtureRepository`` runs the full ``UserScopedRepositoryContract``.
- ``TestBasePrimitives`` covers the subclass-only primitives.
- ``TestGlobalRepository`` proves the non-user-scoped ``MongoRepository`` surface.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from pydantic import BaseModel, ConfigDict
import pytest

from app.constants.cache import REPO_ENTITY_TTL, REPO_QUERY_TTL
from app.db.repositories.base import (
    MongoDocument,
    MongoRepository,
    UserScopedDocument,
    UserScopedRepository,
    cached_query,
)
from app.db.repositories.cache import CachePolicy
from tests.contracts.base_contract import UserScopedRepositoryContract


class _FixtureDocument(UserScopedDocument):
    title: str
    count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class _FixtureUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    count: int | None = None


class _CountResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    total: int


class _FixtureRepository(UserScopedRepository[_FixtureDocument, _FixtureUpdate]):
    collection_name = "contract_fixture"
    document_model = _FixtureDocument
    update_model = _FixtureUpdate
    uses_object_id = True
    cache_policy = CachePolicy(
        prefix="contractfix", entity_ttl=REPO_ENTITY_TTL, query_ttl=REPO_QUERY_TTL
    )

    @cached_query(list[str])
    async def list_titles(self, *, user_id: str) -> list[str]:
        docs = await self._find({"user_id": user_id})
        return [doc.title for doc in docs]


@pytest.fixture
def repo(raw_collection) -> _FixtureRepository:
    return _FixtureRepository()


@pytest.fixture
def make_doc() -> Callable[..., _FixtureDocument]:
    def _make(**overrides: object) -> _FixtureDocument:
        return _FixtureDocument.model_validate({"user_id": "user-1", "title": "hello", **overrides})

    return _make


@pytest.fixture
def make_update() -> Callable[..., _FixtureUpdate]:
    def _make(**fields: object) -> _FixtureUpdate:
        return _FixtureUpdate.model_validate(fields or {"title": "updated-title"})

    return _make


class TestFixtureRepository(UserScopedRepositoryContract):
    """Runs every inherited contract test against the fixture repository."""

    async def list_via_cache(self, repo, user_id: str) -> list:
        return await repo.list_titles(user_id=user_id)


class TestMalformedObjectId:
    """A malformed id on an ObjectId-keyed repository reads as not-found instead
    of raising ``bson.InvalidId`` — the empty-``todo_id`` agent-turn crash."""

    @pytest.mark.parametrize("malformed", ["", "not-an-objectid"])
    async def test_get_returns_none(self, repo, malformed):
        assert await repo.get(malformed, user_id="u") is None

    async def test_update_returns_none(self, repo, make_update):
        assert await repo.update("", user_id="u", update=make_update()) is None

    async def test_delete_returns_false(self, repo):
        assert await repo.delete("", user_id="u") is False

    async def test_global_repo_get_returns_none(self, global_repo):
        assert await global_repo.get("") is None


class TestBasePrimitives:
    async def test_find_filters_sorts_and_paginates(self, repo, make_doc):
        for i, title in enumerate(["a", "b", "c"]):
            await repo.create(make_doc(user_id="u", title=title, count=i))
        found = await repo._find({"user_id": "u"}, sort=[("count", -1)], limit=2)
        assert [doc.title for doc in found] == ["c", "b"]

    async def test_list_for_user_isolated(self, repo, make_doc):
        await repo.create(make_doc(user_id="mine", title="x"))
        await repo.create(make_doc(user_id="theirs", title="y"))
        mine = await repo.list_for_user("mine")
        assert [doc.title for doc in mine] == ["x"]

    async def test_count_for_user(self, repo, make_doc):
        await repo.create(make_doc(user_id="c", title="a"))
        await repo.create(make_doc(user_id="c", title="b"))
        await repo.create(make_doc(user_id="other", title="c"))
        assert await repo.count_for_user("c") == 2

    async def test_increment_updates_value_and_bumps_generation(self, repo, make_doc, redis):
        created = await repo.create(make_doc(user_id="u", count=5))
        gen_key = repo.cache_policy.generation_key("u")
        gen_before = int(await redis.get(gen_key))
        updated = await repo._increment(
            created.id, "count", 3, scope="u", extra_filter={"user_id": "u"}
        )
        assert updated is not None
        assert updated.count == 8
        assert int(await redis.get(gen_key)) == gen_before + 1

    async def test_bulk_set_updates_many(self, repo, make_doc):
        a = await repo.create(make_doc(user_id="u", title="a"))
        b = await repo.create(make_doc(user_id="u", title="b"))
        modified = await repo._bulk_set(
            [(a.id, _FixtureUpdate(title="A")), (b.id, _FixtureUpdate(title="B"))],
            scope="u",
        )
        assert modified == 2
        after_a = await repo.get(a.id, user_id="u")
        after_b = await repo.get(b.id, user_id="u")
        assert after_a is not None and after_a.title == "A"
        assert after_b is not None and after_b.title == "B"

    async def test_update_fields_no_invalidate_leaves_cache_and_generation(
        self, repo, make_doc, redis
    ):
        created = await repo.create(make_doc(user_id="u", title="orig"))
        await repo.get(created.id, user_id="u")  # populate entity cache
        gen_key = repo.cache_policy.generation_key("u")
        gen_before = int(await redis.get(gen_key))
        await repo._update_fields_no_invalidate(
            {"_id": repo._id_value(created.id)}, {"title": "hot"}
        )
        assert int(await redis.get(gen_key)) == gen_before  # generation untouched
        still = await repo.get(created.id, user_id="u")
        assert still is not None and still.title == "orig"  # served stale from cache

    async def test_delete_many_evicts_entity_cache_no_stale_read(self, repo, make_doc, redis):
        # On a CACHE-ENABLED repository _delete_many must evict each removed doc's
        # entity key, not just bump the generation (which only orphans query caches).
        a = await repo.create(make_doc(user_id="u", title="a"))
        b = await repo.create(make_doc(user_id="u", title="b"))
        await repo.get(a.id, user_id="u")  # populate entity cache
        await repo.get(b.id, user_id="u")
        assert await redis.get(repo.cache_policy.entity_key("u", a.id)) is not None

        deleted = await repo._delete_many({"user_id": "u"}, scope="u")
        assert deleted == 2
        # Entity keys evicted — a by-id read can't be served the deleted doc.
        assert await redis.get(repo.cache_policy.entity_key("u", a.id)) is None
        assert await redis.get(repo.cache_policy.entity_key("u", b.id)) is None
        assert await repo.get(a.id, user_id="u") is None

    async def test_aggregate_returns_typed_results(self, repo, make_doc):
        await repo.create(make_doc(user_id="u", count=2))
        await repo.create(make_doc(user_id="u", count=3))
        results = await repo._aggregate(
            [
                {"$match": {"user_id": "u"}},
                {"$group": {"_id": None, "total": {"$sum": "$count"}}},
            ],
            _CountResult,
        )
        assert len(results) == 1
        assert results[0].total == 5

    async def test_apply_raw_update_sets_and_keeps_cache_coherent(self, repo, make_doc, redis):
        created = await repo.create(make_doc(user_id="u", count=1))
        gen_key = repo.cache_policy.generation_key("u")
        gen_before = int(await redis.get(gen_key))
        updated = await repo._apply_raw_update(
            {"_id": repo._id_value(created.id)}, {"$set": {"count": 9}}, scope="u"
        )
        assert updated is not None and updated.count == 9
        ent = await redis.get(repo.cache_policy.entity_key("u", created.id))
        assert repo.document_model.model_validate_json(ent).count == 9  # cache refreshed
        assert int(await redis.get(gen_key)) == gen_before + 1  # generation bumped

    async def test_apply_raw_update_unset_and_gate_miss(self, repo, make_doc):
        created = await repo.create(make_doc(user_id="u", count=5))
        unset = await repo._apply_raw_update(
            {"_id": repo._id_value(created.id)}, {"$unset": {"count": ""}}, scope="u"
        )
        assert unset is not None and unset.count == 0  # field removed → model default
        missed = await repo._apply_raw_update(
            {"_id": repo._id_value(created.id)},
            {"$set": {"count": 1}},
            scope="u",
            extra_filter={"count": 999},
        )
        assert missed is None  # extra_filter gate did not match


class _GlobalDocument(MongoDocument):
    name: str


class _GlobalUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None


class _GlobalRepository(MongoRepository[_GlobalDocument, _GlobalUpdate]):
    collection_name = "contract_fixture"
    document_model = _GlobalDocument
    update_model = _GlobalUpdate
    uses_object_id = True
    cache_policy = CachePolicy(prefix="globalfix")


@pytest.fixture
def global_repo(raw_collection) -> _GlobalRepository:
    return _GlobalRepository()


class TestGlobalRepository:
    async def test_create_get_roundtrip(self, global_repo):
        created = await global_repo.create(_GlobalDocument(name="widget"))
        fetched = await global_repo.get(created.id)
        assert fetched == created

    async def test_update_and_delete(self, global_repo):
        created = await global_repo.create(_GlobalDocument(name="before"))
        updated = await global_repo.update(created.id, _GlobalUpdate(name="after"))
        assert updated is not None and updated.name == "after"
        assert await global_repo.delete(created.id) is True
        assert await global_repo.get(created.id) is None

    async def test_count(self, global_repo):
        await global_repo.create(_GlobalDocument(name="a"))
        await global_repo.create(_GlobalDocument(name="b"))
        assert await global_repo.count() == 2


class _KeyedDocument(MongoDocument):
    ref: str
    label: str = ""


class _KeyedUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = None


class _KeyedRepository(MongoRepository[_KeyedDocument, _KeyedUpdate]):
    """Identity is a business field (``ref``), not ``_id`` — the Wave-D shape."""

    collection_name = "contract_fixture"
    document_model = _KeyedDocument
    update_model = _KeyedUpdate
    uses_object_id = True
    identity_field = "ref"
    cache_policy = None


@pytest.fixture
def keyed_repo(raw_collection) -> _KeyedRepository:
    return _KeyedRepository()


class TestBusinessKeyIdentity:
    async def test_get_update_delete_by_business_key(self, keyed_repo, raw_collection):
        created = await keyed_repo.create(_KeyedDocument(ref="abc", label="first"))
        assert created.ref == "abc"
        # get keys on ``ref``, not ``_id`` — the incidental ObjectId is dropped.
        fetched = await keyed_repo.get("abc")
        assert fetched is not None and fetched.ref == "abc" and fetched.label == "first"
        # the stored doc really does carry a distinct ObjectId _id
        raw = await raw_collection.find_one({"ref": "abc"})
        assert raw["_id"] != "abc"

        updated = await keyed_repo.update("abc", _KeyedUpdate(label="second"))
        assert updated is not None and updated.label == "second"
        assert await keyed_repo.delete("abc") is True
        assert await keyed_repo.get("abc") is None

    async def test_business_key_is_not_clobbered_by_object_id(self, keyed_repo):
        created = await keyed_repo.create(_KeyedDocument(ref="uuid-xyz"))
        # MongoDocument.id must remain the model default, not str(_id).
        assert created.ref == "uuid-xyz"
        assert (await keyed_repo.get("uuid-xyz")).ref == "uuid-xyz"
