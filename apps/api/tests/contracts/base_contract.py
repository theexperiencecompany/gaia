"""Backend-agnostic contract every user-scoped repository inherits.

A concrete test class subclasses ``UserScopedRepositoryContract`` and provides
three fixtures: ``repo`` (the repository singleton), ``make_doc(**overrides)``
and ``make_update(**fields)``. The ``raw_collection`` and ``redis`` fixtures come
from the contract ``conftest``. Every assertion is on a concrete value — never a
spy or a "was called". This suite is the Postgres-migration certificate: the same
class will run against a Postgres repository unchanged.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from app.utils.errors import EmptyUpdateError


class UserScopedRepositoryContract:
    async def list_via_cache(self, repo, user_id: str) -> list:
        """Invoke the repository's cached list finder for a user.

        Override per repository (e.g. ``return await repo.list_notes(user_id=user_id)``)
        so the query-cache contract runs against that repository's real finder.
        """
        raise NotImplementedError("provide list_via_cache for the query-cache contract")

    # ------------------------------------------------------------------ CRUD

    async def test_create_returns_typed_document_with_string_id(self, repo, make_doc):
        created = await repo.create(make_doc())
        assert type(created) is repo.document_model
        assert isinstance(created.id, str) and created.id

    async def test_create_then_get_roundtrips_every_field(self, repo, make_doc):
        created = await repo.create(make_doc())
        fetched = await repo.get(created.id, user_id=created.user_id)
        assert fetched == created  # full-model equality, not spot checks

    async def test_get_missing_id_returns_none(self, repo):
        assert await repo.get("0" * 24, user_id="u1") is None

    async def test_cross_user_isolation_on_get_update_delete(self, repo, make_doc, make_update):
        created = await repo.create(make_doc(user_id="owner"))
        assert await repo.get(created.id, user_id="attacker") is None
        assert await repo.update(created.id, user_id="attacker", update=make_update()) is None
        assert await repo.delete(created.id, user_id="attacker") is False
        assert await repo.get(created.id, user_id="owner") == created  # untouched

    async def test_partial_update_leaves_unset_fields_untouched(self, repo, make_doc, make_update):
        created = await repo.create(make_doc())
        update = make_update()
        updated = await repo.update(created.id, user_id=created.user_id, update=update)
        assert updated is not None
        touched = set(update.model_dump(exclude_unset=True))
        for field in created.__class__.model_fields:
            if field in touched or field == "updated_at":
                continue
            assert getattr(updated, field) == getattr(created, field)

    async def test_update_returns_after_state(self, repo, make_doc, make_update):
        created = await repo.create(make_doc())
        update = make_update()
        updated = await repo.update(created.id, user_id=created.user_id, update=update)
        assert updated is not None
        for field, value in update.model_dump(exclude_unset=True).items():
            assert getattr(updated, field) == value

    async def test_empty_update_raises_empty_update_error(self, repo, make_doc):
        created = await repo.create(make_doc())
        with pytest.raises(EmptyUpdateError):
            await repo.update(created.id, user_id=created.user_id, update=repo.update_model())

    async def test_delete_returns_true_then_get_returns_none(self, repo, make_doc):
        created = await repo.create(make_doc())
        assert await repo.delete(created.id, user_id=created.user_id) is True
        assert await repo.get(created.id, user_id=created.user_id) is None

    async def test_delete_missing_returns_false(self, repo):
        assert await repo.delete("0" * 24, user_id="u1") is False

    async def test_datetimes_come_back_tz_aware_utc(self, repo, make_doc):
        created = await repo.create(make_doc())
        for value in (created.created_at, created.updated_at):
            assert value is not None
            assert value.tzinfo is not None
            assert value.utcoffset() == timedelta(0)

    async def test_updated_at_bumped_created_at_stable(self, repo, make_doc, make_update):
        created = await repo.create(make_doc())
        await asyncio.sleep(0.01)
        updated = await repo.update(created.id, user_id=created.user_id, update=make_update())
        assert updated is not None
        assert updated.created_at == created.created_at
        assert updated.updated_at > created.updated_at

    # ------------------------------------------------------- cache (real Redis)

    async def test_get_populates_entity_cache(self, repo, make_doc, redis):
        created = await repo.create(make_doc())
        key = repo.cache_policy.entity_key(created.user_id, created.id)
        await redis.delete(key)
        assert await redis.get(key) is None
        fetched = await repo.get(created.id, user_id=created.user_id)
        assert fetched == created
        assert await redis.get(key) is not None  # read-through repopulated it

    async def test_second_get_serves_from_cache(self, repo, make_doc, raw_collection, redis):
        created = await repo.create(make_doc(title="original"))
        await repo.get(created.id, user_id=created.user_id)  # ensure cached
        # Mutate Mongo directly, behind the repository's back — no cache eviction.
        await raw_collection.update_one(
            {"_id": repo._id_value(created.id)}, {"$set": {"title": "mutated-in-db"}}
        )
        again = await repo.get(created.id, user_id=created.user_id)
        assert again is not None
        assert again.title == "original"  # served stale from cache, proving the hit

    async def test_update_refreshes_entity_cache_and_bumps_generation(
        self, repo, make_doc, make_update, redis
    ):
        created = await repo.create(make_doc())
        gen_key = repo.cache_policy.generation_key(created.user_id)
        gen_before = int(await redis.get(gen_key))
        updated = await repo.update(created.id, user_id=created.user_id, update=make_update())
        ent_key = repo.cache_policy.entity_key(created.user_id, created.id)
        cached_raw = await redis.get(ent_key)
        assert cached_raw is not None
        assert repo.document_model.model_validate_json(cached_raw) == updated
        assert int(await redis.get(gen_key)) == gen_before + 1

    async def test_delete_evicts_entity_cache(self, repo, make_doc, redis):
        created = await repo.create(make_doc())
        await repo.get(created.id, user_id=created.user_id)  # ensure cached
        ent_key = repo.cache_policy.entity_key(created.user_id, created.id)
        assert await redis.get(ent_key) is not None
        await repo.delete(created.id, user_id=created.user_id)
        assert await redis.get(ent_key) is None

    async def test_write_orphans_query_caches(self, repo, make_doc, raw_collection, redis):
        user = "orphan-user"
        await repo.create(make_doc(user_id=user))
        await repo.create(make_doc(user_id=user))
        assert len(await self.list_via_cache(repo, user)) == 2
        # Direct insert, no repo write → no generation bump → stays invisible (cached).
        await raw_collection.insert_one(make_doc(user_id=user).model_dump(exclude={"id"}))
        assert len(await self.list_via_cache(repo, user)) == 2
        # A repo write bumps the generation → the query cache is orphaned, both new
        # documents (the repo one and the direct insert) become visible.
        await repo.create(make_doc(user_id=user))
        assert len(await self.list_via_cache(repo, user)) == 4

    async def test_redis_down_degrades_to_mongo_not_error(self, repo, make_doc, monkeypatch):
        from app.db.redis import redis_cache

        monkeypatch.setattr(redis_cache, "redis", None)
        created = await repo.create(make_doc(title="no-redis"))
        fetched = await repo.get(created.id, user_id=created.user_id)
        assert fetched is not None
        assert fetched.title == "no-redis"
