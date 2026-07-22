"""Contract tests for UserRepository against real Mongo + Redis.

UserRepository is a global MongoRepository with cache_policy=None (caching is
deferred until every user writer is migrated), so it does not inherit the
user-scoped cache contract. These tests exercise its reads, the debounced
cache-exempt touch_last_active, the gated onboarding writes, and the platform /
background-job named methods.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from app.db.repositories.users import UserRepository
from app.models.user_models import UserDocument


@pytest.fixture
def repo(raw_collection) -> UserRepository:
    return UserRepository()


@pytest.fixture
def make_user() -> Callable[..., UserDocument]:
    def _make(**overrides: object) -> UserDocument:
        return UserDocument.model_validate({"email": "a@b.com", "name": "A", **overrides})

    return _make


class TestUserReads:
    async def test_get_by_id_and_email_roundtrip(self, repo, make_user):
        created = await repo.create(make_user(email="x@y.com"))
        assert await repo.get(created.id) == created
        assert await repo.get_by_email("x@y.com") == created
        assert await repo.get_by_email("missing@y.com") is None

    async def test_extra_allow_preserves_undeclared_fields(self, repo, make_user):
        # build_user_context spreads the whole doc, so undeclared fields must survive.
        created = await repo.create(make_user(custom_flag=True, nested={"k": "v"}))
        dump = (await repo.get(created.id)).model_dump()
        assert dump["custom_flag"] is True
        assert dump["nested"] == {"k": "v"}


class TestTouchLastActive:
    async def test_writes_then_debounces_within_window(self, repo, make_user, raw_collection):
        await repo.create(make_user(email="t@u.com"))
        await repo.touch_last_active("t@u.com")
        first = (await raw_collection.find_one({"email": "t@u.com"}))["last_active_at"]
        assert first is not None
        # Second touch inside the debounce window: the SETNX gate blocks the write.
        await repo.touch_last_active("t@u.com")
        second = (await raw_collection.find_one({"email": "t@u.com"}))["last_active_at"]
        assert second == first

    async def test_never_raises_when_redis_unavailable(self, repo, make_user, monkeypatch):
        await repo.create(make_user(email="r@s.com"))
        from app.db.redis import redis_cache

        monkeypatch.setattr(redis_cache, "redis", None)
        await repo.touch_last_active("r@s.com")  # no gate; must write and not raise
        assert (await repo.get_by_email("r@s.com")).last_active_at is not None

    async def test_touch_failure_is_swallowed_not_raised(self, repo, monkeypatch):
        # A touch on a missing user still must not raise into the auth caller.
        await repo.touch_last_active("nobody@nowhere.com")


class TestOnboardingWrites:
    async def test_complete_onboarding_is_gated_and_idempotent(self, repo, make_user):
        created = await repo.create(make_user())
        first = await repo.complete_onboarding(
            created.id,
            name="New Name",
            phase="done",
            bio_status="ready",
            pipeline_mode="split",
            preferences={"profession": "eng"},
        )
        assert first is not None
        assert first.name == "New Name"
        assert first.onboarding["completed"] is True
        assert first.onboarding["phase"] == "done"
        # Gate misses on replay (onboarding already exists) → None, original untouched.
        second = await repo.complete_onboarding(
            created.id, phase="x", bio_status="y", pipeline_mode="z", preferences={}
        )
        assert second is None
        assert (await repo.get(created.id)).onboarding["phase"] == "done"

    async def test_update_preferences_patches_only_given_keys(self, repo, make_user):
        created = await repo.create(make_user())
        await repo.complete_onboarding(
            created.id,
            phase="p",
            bio_status="b",
            pipeline_mode="m",
            preferences={"profession": "eng", "response_style": "brief"},
        )
        updated = await repo.update_onboarding_preferences(created.id, {"profession": "designer"})
        assert updated is not None
        prefs = updated.onboarding["preferences"]
        assert prefs["profession"] == "designer"
        assert prefs["response_style"] == "brief"

    async def test_reset_onboarding_removes_subdocument(self, repo, make_user):
        created = await repo.create(make_user())
        await repo.complete_onboarding(
            created.id, phase="p", bio_status="b", pipeline_mode="m", preferences={}
        )
        await repo.reset_onboarding(created.id)
        assert (await repo.get(created.id)).onboarding is None

    async def test_social_profiles_written_once_then_guarded(self, repo, make_user):
        created = await repo.create(make_user())
        await repo.set_social_profiles_if_unset(created.id, [{"platform": "x"}])
        first = (await repo.get(created.id)).onboarding["social_profiles"]
        assert len(first) == 1
        await repo.set_social_profiles_if_unset(created.id, [{"platform": "y"}, {"platform": "z"}])
        assert (await repo.get(created.id)).onboarding["social_profiles"] == first


class TestSettingsWrites:
    async def test_set_channel_preferences_patches_only_given_channels(self, repo, make_user):
        created = await repo.create(make_user())
        await repo.set_channel_preferences(created.id, telegram=True, slack=False)
        prefs = (await repo.get(created.id)).notification_channel_prefs
        assert prefs == {"telegram": True, "slack": False}
        # A second call leaves unspecified channels untouched and updates given ones.
        await repo.set_channel_preferences(created.id, telegram=False, discord=True)
        prefs = (await repo.get(created.id)).notification_channel_prefs
        assert prefs == {"telegram": False, "slack": False, "discord": True}

    async def test_set_channel_preferences_no_args_is_noop(self, repo, make_user):
        created = await repo.create(make_user())
        await repo.set_channel_preferences(created.id)
        assert (await repo.get(created.id)).notification_channel_prefs is None

    async def test_set_selected_and_starred_voices(self, repo, make_user):
        created = await repo.create(make_user())
        await repo.set_selected_voice(created.id, "voice-1")
        await repo.set_starred_voices(created.id, ["voice-1", "voice-2"])
        stored = await repo.get(created.id)
        assert stored.selected_voice_id == "voice-1"
        assert stored.starred_voice_ids == ["voice-1", "voice-2"]

    async def test_set_provider_metadata_roundtrip_and_missing_user(self, repo, make_user):
        created = await repo.create(make_user())
        assert await repo.set_provider_metadata(created.id, "github", {"username": "octocat"})
        stored = await repo.get(created.id)
        assert stored.provider_metadata == {"github": {"username": "octocat"}}
        # A second provider merges rather than replacing.
        await repo.set_provider_metadata(created.id, "twitter", {"handle": "cat"})
        stored = await repo.get(created.id)
        assert set(stored.provider_metadata) == {"github", "twitter"}
        # Missing user → write did not land.
        assert await repo.set_provider_metadata("0" * 24, "github", {"x": "y"}) is False

    async def test_set_holo_card_colors_and_missing_user(self, repo, make_user):
        created = await repo.create(make_user())
        assert await repo.set_holo_card_colors(created.id, "rgba(1,2,3,1)", 55)
        onboarding = (await repo.get(created.id)).onboarding
        assert onboarding["overlay_color"] == "rgba(1,2,3,1)"
        assert onboarding["overlay_opacity"] == 55
        assert await repo.set_holo_card_colors("0" * 24, "x", 1) is False


class TestUserCounts:
    async def test_count_created_before(self, repo, make_user):
        from datetime import UTC, datetime

        cutoff = datetime(2025, 6, 1, tzinfo=UTC)
        await repo.create(make_user(created_at=datetime(2025, 1, 1, tzinfo=UTC)))
        await repo.create(make_user(created_at=datetime(2025, 3, 1, tzinfo=UTC)))
        await repo.create(make_user(created_at=datetime(2025, 12, 1, tzinfo=UTC)))
        assert await repo.count_created_before(cutoff) == 2


class TestBackgroundJobMarkers:
    async def test_set_and_compare_and_clear(self, repo, make_user):
        created = await repo.create(make_user())
        field = "onboarding.intelligence_job_id"
        await repo.set_active_job(created.id, field, "job1")
        assert (await repo.get(created.id)).onboarding["intelligence_job_id"] == "job1"
        # Wrong id → no-op.
        await repo.clear_active_job_if_matches(created.id, field, "other")
        assert (await repo.get(created.id)).onboarding["intelligence_job_id"] == "job1"
        # Right id → cleared.
        await repo.clear_active_job_if_matches(created.id, field, "job1")
        assert "intelligence_job_id" not in ((await repo.get(created.id)).onboarding or {})


class TestPlatformLinking:
    async def test_link_lookup_and_unlink(self, repo, make_user):
        created = await repo.create(make_user())
        linked = await repo.link_platform(
            created.id, "telegram", {"id": "tg123", "username": "u"}, "2026-01-01T00:00:00Z"
        )
        assert linked is not None
        assert linked.platform_links["telegram"]["id"] == "tg123"
        found = await repo.get_by_platform_id("telegram", "tg123")
        assert found is not None and found.id == created.id
        assert "tg123" in await repo.list_platform_user_ids("telegram")
        await repo.unlink_platform(created.id, "telegram")
        assert await repo.get_by_platform_id("telegram", "tg123") is None

    async def test_link_missing_user_returns_none(self, repo):
        assert await repo.link_platform("0" * 24, "telegram", {"id": "x"}, "t") is None
