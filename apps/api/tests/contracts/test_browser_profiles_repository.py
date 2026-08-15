"""Contract tests for BrowserProfilesRepository (one Steel profile per user+domain)."""

from __future__ import annotations

import uuid

import pytest

from app.db.repositories.browser_profiles import BrowserProfilesRepository


@pytest.fixture
def repo(raw_collection) -> BrowserProfilesRepository:
    return BrowserProfilesRepository()


class TestBrowserProfilesRepository:
    async def test_get_for_domain_is_none_before_any_write(self, repo):
        assert await repo.get_for_domain(f"u-{uuid.uuid4().hex}", "example.com") is None

    async def test_upsert_creates_then_replaces_profile_id(self, repo):
        user = f"u-{uuid.uuid4().hex}"
        await repo.upsert_steel_profile_id(user, "example.com", "prof-1")
        first = await repo.get_for_domain(user, "example.com")
        assert first is not None
        assert first.steel_profile_id == "prof-1"
        assert first.created_at is not None

        await repo.upsert_steel_profile_id(user, "example.com", "prof-2")
        second = await repo.get_for_domain(user, "example.com")
        assert second is not None
        assert second.id == first.id  # same record, not a duplicate
        assert second.steel_profile_id == "prof-2"
        assert second.created_at == first.created_at  # $setOnInsert did not overwrite it

    async def test_profiles_are_scoped_per_user_and_domain(self, repo):
        user_a = f"u-{uuid.uuid4().hex}"
        user_b = f"u-{uuid.uuid4().hex}"
        await repo.upsert_steel_profile_id(user_a, "example.com", "prof-a")
        await repo.upsert_steel_profile_id(user_a, "other.com", "prof-a-other")

        assert (await repo.get_for_domain(user_a, "other.com")).steel_profile_id == "prof-a-other"
        assert await repo.get_for_domain(user_b, "example.com") is None
