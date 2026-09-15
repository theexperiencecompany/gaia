"""Contract tests for UserRepository against real Mongo + Redis.

UserRepository is a global MongoRepository with entity caching enabled (every
user writer routes through it). These tests exercise its reads, the cache
freshness guarantee (a repo write can't be shadowed by a stale cached read), the
debounced cache-exempt touch_last_active, the gated onboarding writes, and the
platform / background-job named methods.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
import time

import pytest

from app.constants.email import SignupDelivery
from app.db.repositories.users import UserRepository
from app.models.onboarding_models import SocialProfile
from app.models.user_models import (
    BioStatus,
    OnboardingPhase,
    OnboardingPreferences,
    PersonalizationBundle,
    UserDocument,
    UserUpdate,
)


@pytest.fixture
def repo(raw_collection) -> UserRepository:
    return UserRepository()


@pytest.fixture
def make_user() -> Callable[..., UserDocument]:
    def _make(**overrides: object) -> UserDocument:
        return UserDocument.model_validate({"email": "a@b.com", "name": "A", **overrides})

    return _make


@pytest.fixture
def local_time_offset_from_utc(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Move the process's local timezone off UTC for the test.

    The suite pins TZ=UTC, which makes a naive ``datetime.now()`` numerically
    identical to an aware UTC one — so a timestamp that forgot its timezone
    would look correct here and be hours wrong in production.
    """
    monkeypatch.setenv("TZ", "Asia/Kolkata")  # UTC+5:30
    time.tzset()
    try:
        yield
    finally:
        monkeypatch.undo()
        time.tzset()


class TestUserReads:
    async def test_get_by_id_and_email_roundtrip(self, repo, make_user):
        created = await repo.create(make_user(email="x@y.com"))
        assert await repo.get(created.id) == created
        assert await repo.get_by_email("x@y.com") == created
        assert await repo.get_by_email("missing@y.com") is None

    async def test_find_by_ids_skips_invalid(self, repo, make_user):
        a = await repo.create(make_user(email="c1@b.com"))
        b = await repo.create(make_user(email="c2@b.com"))
        found = await repo.find_by_ids([a.id, b.id, "not-an-objectid", "0" * 24])
        assert {u.id for u in found} == {a.id, b.id}
        assert await repo.find_by_ids([]) == []

    async def test_extra_allow_preserves_undeclared_fields(self, repo, make_user):
        # build_user_context spreads the whole doc, so undeclared fields must survive.
        created = await repo.create(make_user(custom_flag=True, nested={"k": "v"}))
        dump = (await repo.get(created.id)).model_dump()
        assert dump["custom_flag"] is True
        assert dump["nested"] == {"k": "v"}


class TestCacheFreshness:
    """A cached user read must never shadow a write — a stale user is stale auth."""

    async def test_typed_update_refreshes_entity_and_query_caches(self, repo, make_user):
        created = await repo.create(make_user(email="fresh@y.com", name="Old"))
        # Warm both the entity cache (get) and the query cache (get_by_email).
        assert (await repo.get(created.id)).name == "Old"
        assert (await repo.get_by_email("fresh@y.com")).name == "Old"
        await repo.update(created.id, UserUpdate(name="New"))
        assert (await repo.get(created.id)).name == "New"
        assert (await repo.get_by_email("fresh@y.com")).name == "New"

    async def test_named_write_busts_both_caches(self, repo, make_user):
        # Named writes go through _apply_raw_update(return_document=False), whose
        # read-back is the BEFORE image — it must evict the entity key, never
        # store it, or every named write would re-seed the cache with stale data.
        created = await repo.create(make_user(email="raw@y.com"))
        assert (await repo.get(created.id)).selected_voice_id is None
        assert (await repo.get_by_email("raw@y.com")).selected_voice_id is None
        await repo.set_selected_voice(created.id, "voice-x")
        assert (await repo.get(created.id)).selected_voice_id == "voice-x"
        assert (await repo.get_by_email("raw@y.com")).selected_voice_id == "voice-x"

    async def test_delete_busts_both_caches(self, repo, make_user):
        created = await repo.create(make_user(email="gone@y.com"))
        await repo.get(created.id)
        await repo.get_by_email("gone@y.com")
        assert await repo.delete(created.id)
        assert await repo.get(created.id) is None
        assert await repo.get_by_email("gone@y.com") is None

    async def test_touch_last_active_does_not_bump_the_generation(self, repo, make_user):
        # The one cache-exempt write: it fires on every authenticated request, so
        # bumping here would invalidate the whole cache on every request.
        from app.db.repositories.cache import read_generation

        await repo.create(make_user(email="hot@y.com"))
        before = await read_generation(repo.cache_policy, "global")
        await repo.touch_last_active("hot@y.com")
        assert await read_generation(repo.cache_policy, "global") == before


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
            phase=OnboardingPhase.COMPLETED,
            bio_status=BioStatus.COMPLETED,
            preferences=OnboardingPreferences(profession="eng"),
        )
        assert first is not None
        assert first.onboarding is not None
        assert first.onboarding.completed is True
        assert first.onboarding.phase == OnboardingPhase.COMPLETED
        # Gate misses on replay (onboarding already exists) → None, original untouched.
        second = await repo.complete_onboarding(
            created.id,
            phase=OnboardingPhase.INITIAL,
            bio_status=BioStatus.PENDING,
            preferences=OnboardingPreferences(),
        )
        assert second is None
        assert (await repo.get(created.id)).onboarding.phase == OnboardingPhase.COMPLETED

    async def test_complete_onboarding_writes_timezone_at_the_document_root(
        self, repo, make_user, raw_collection
    ):
        """``user.timezone`` is the single source of truth — the wizard's answer
        must land at the root under that exact key, not on the subdocument."""
        created = await repo.create(make_user(email="tz@y.com"))
        completed = await repo.complete_onboarding(
            created.id,
            phase=OnboardingPhase.COMPLETED,
            bio_status=BioStatus.COMPLETED,
            preferences=OnboardingPreferences(profession="eng"),
            timezone="Europe/Berlin",
        )
        assert completed is not None
        assert completed.timezone == "Europe/Berlin"
        stored = await raw_collection.find_one({"email": "tz@y.com"})
        assert stored["timezone"] == "Europe/Berlin"

    async def test_complete_onboarding_without_timezone_keeps_the_stored_one(
        self, repo, make_user, raw_collection
    ):
        """Omitting the argument must not clear a timezone detected earlier."""
        created = await repo.create(make_user(email="tzkeep@y.com", timezone="Asia/Kolkata"))
        completed = await repo.complete_onboarding(
            created.id,
            phase=OnboardingPhase.COMPLETED,
            bio_status=BioStatus.COMPLETED,
            preferences=OnboardingPreferences(profession="eng"),
        )
        assert completed is not None
        assert completed.timezone == "Asia/Kolkata"
        stored = await raw_collection.find_one({"email": "tzkeep@y.com"})
        assert stored["timezone"] == "Asia/Kolkata"

    async def test_update_preferences_patches_only_given_keys(self, repo, make_user):
        created = await repo.create(make_user())
        await repo.complete_onboarding(
            created.id,
            phase=OnboardingPhase.INITIAL,
            bio_status=BioStatus.PENDING,
            preferences=OnboardingPreferences(profession="eng", response_style="brief"),
        )
        # Only `profession` is set, so exclude_unset must leave response_style alone.
        updated = await repo.update_onboarding_preferences(
            created.id, OnboardingPreferences(profession="designer")
        )
        assert updated is not None
        assert updated.onboarding is not None
        prefs = updated.onboarding.preferences
        assert prefs is not None
        assert prefs.profession == "designer"
        assert prefs.response_style == "brief"

    async def test_save_personalization_writes_bundle_and_phase(self, repo, make_user):
        created = await repo.create(make_user())
        await repo.save_personalization(
            created.id,
            PersonalizationBundle(
                house="explorer",
                personality_phrase="Creative",
                user_bio="Bio",
                bio_status=BioStatus.COMPLETED,
                account_number=42,
                member_since="Mar 2024",
                overlay_color="#ff0000",
                overlay_opacity=80,
            ),
        )
        onboarding = (await repo.get(created.id)).onboarding
        assert onboarding is not None
        assert onboarding.house == "explorer"
        assert onboarding.phase == OnboardingPhase.PERSONALIZATION_COMPLETE
        assert onboarding.account_number == 42

    async def test_mark_gmail_personalization_done_stamps_marker_and_conversation(
        self, repo, make_user
    ):
        created = await repo.create(make_user())
        await repo.mark_gmail_personalization_done(created.id, conversation_id="conv-1")

        onboarding = (await repo.get(created.id)).onboarding
        assert onboarding is not None
        assert isinstance(onboarding.gmail_personalization_at, datetime)
        assert onboarding.holo_conversation_id == "conv-1"

    async def test_mark_gmail_personalization_done_omits_missing_conversation(
        self, repo, make_user
    ):
        created = await repo.create(make_user())
        await repo.mark_gmail_personalization_done(created.id)

        onboarding = (await repo.get(created.id)).onboarding
        assert onboarding is not None
        # model_fields_set is the typed stand-in for "key present in the Mongo doc":
        # the write must stamp the marker and must not write the conversation id at all.
        assert "gmail_personalization_at" in onboarding.model_fields_set
        assert "holo_conversation_id" not in onboarding.model_fields_set

    async def test_set_social_profiles_overwrites(self, repo, make_user):
        created = await repo.create(make_user())
        await repo.set_social_profiles(created.id, [SocialProfile(platform="x", url="u/x")])
        await repo.set_social_profiles(
            created.id,
            [SocialProfile(platform="y", url="u/y"), SocialProfile(platform="z", url="u/z")],
        )
        assert len((await repo.get(created.id)).onboarding.social_profiles) == 2

    async def test_set_bio_status(self, repo, make_user):
        created = await repo.create(make_user())
        await repo.set_bio_status(created.id, "processing")
        assert (await repo.get(created.id)).onboarding.bio_status == BioStatus.PROCESSING

    async def test_set_writing_style_user_summary(self, repo, make_user):
        created = await repo.create(make_user())
        await repo.set_writing_style_user_summary(created.id, "my style")
        style = (await repo.get(created.id)).onboarding.writing_style
        assert style is not None
        assert style["user_edited_summary"] == "my style"

    async def test_reset_onboarding_removes_subdocument(self, repo, make_user):
        created = await repo.create(make_user())
        await repo.complete_onboarding(
            created.id,
            phase=OnboardingPhase.INITIAL,
            bio_status=BioStatus.PENDING,
            preferences=OnboardingPreferences(),
        )
        await repo.reset_onboarding(created.id)
        assert (await repo.get(created.id)).onboarding is None

    async def test_social_profiles_written_once_then_guarded(self, repo, make_user):
        created = await repo.create(make_user())
        await repo.set_social_profiles_if_unset(
            created.id, [SocialProfile(platform="x", url="u/x")]
        )
        first = (await repo.get(created.id)).onboarding.social_profiles
        assert len(first) == 1
        await repo.set_social_profiles_if_unset(
            created.id,
            [SocialProfile(platform="y", url="u/y"), SocialProfile(platform="z", url="u/z")],
        )
        assert (await repo.get(created.id)).onboarding.social_profiles == first


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

    async def test_mark_email_processing_complete(self, repo, make_user):
        created = await repo.create(make_user())
        await repo.mark_email_processing_complete(created.id, 42)
        stored = await repo.get(created.id)
        assert stored.email_memory_processed is True
        assert stored.email_memory_count == 42
        assert stored.email_memory_processed_at is not None

    async def test_set_gmail_scan_timestamp(self, repo, make_user):
        from datetime import datetime

        created = await repo.create(make_user())
        ts = datetime(2025, 1, 1, tzinfo=UTC)
        await repo.set_gmail_scan_timestamp(created.id, ts)
        states = (await repo.get(created.id)).integration_scan_states
        assert states["gmail"]["last_scan_timestamp"] == ts

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
        assert onboarding is not None
        assert onboarding.overlay_color == "rgba(1,2,3,1)"
        assert onboarding.overlay_opacity == 55
        assert await repo.set_holo_card_colors("0" * 24, "x", 1) is False


class TestUserCounts:
    async def test_list_all_ids(self, repo, make_user):
        a = await repo.create(make_user(email="a1@b.com"))
        b = await repo.create(make_user(email="a2@b.com"))
        assert set(await repo.list_all_ids()) == {a.id, b.id}

    async def test_count_created_before(self, repo, make_user):
        from datetime import datetime

        cutoff = datetime(2025, 6, 1, tzinfo=UTC)
        await repo.create(make_user(created_at=datetime(2025, 1, 1, tzinfo=UTC)))
        await repo.create(make_user(created_at=datetime(2025, 3, 1, tzinfo=UTC)))
        await repo.create(make_user(created_at=datetime(2025, 12, 1, tzinfo=UTC)))
        assert await repo.count_created_before(cutoff) == 2


class TestWorkerScans:
    async def test_find_stuck_personalization(self, repo, make_user, raw_collection):
        from datetime import datetime, timedelta

        from bson import ObjectId

        cutoff = datetime.now(UTC) - timedelta(minutes=30)
        old = datetime.now(UTC) - timedelta(hours=1)
        # Stuck: pending phase, updated_at backdated past the cutoff (create()
        # auto-stamps updated_at, so backdate it directly).
        stuck = await repo.create(make_user(onboarding={"phase": "personalization_pending"}))
        await raw_collection.update_one({"_id": ObjectId(stuck.id)}, {"$set": {"updated_at": old}})
        # Not stuck: pending but freshly updated (updated_at is 'now').
        await repo.create(make_user(onboarding={"phase": "personalization_pending"}))
        # Not stuck: different phase.
        await repo.create(make_user(onboarding={"phase": "completed"}))
        found = await repo.find_stuck_personalization(cutoff, limit=50)
        assert [u.id for u in found] == [stuck.id]

    async def test_find_inactive_email_candidates(self, repo, make_user):
        from datetime import datetime, timedelta

        before = datetime.now(UTC)
        long_ago = datetime.now(UTC) - timedelta(days=30)
        inactive = await repo.create(make_user(last_active_at=long_ago, is_active=True))
        # Excluded: explicitly deactivated.
        await repo.create(make_user(last_active_at=long_ago, is_active=False))
        # Excluded: recently active.
        await repo.create(make_user(last_active_at=datetime.now(UTC)))
        found = await repo.find_inactive_email_candidates(before)
        assert [u.id for u in found] == [inactive.id]

    async def test_record_inactive_email(self, repo, make_user):
        created = await repo.create(make_user())
        await repo.record_inactive_email(created.id, 2)
        stored = await repo.get(created.id)
        assert stored.inactive_email_count == 2
        assert stored.last_inactive_email_sent is not None

    async def test_backfill_candidates_by_creation_and_marker(self, repo, make_user):
        from datetime import datetime, timedelta

        active_since = datetime.now(UTC) - timedelta(days=1)
        eligible_before = datetime.now(UTC)
        # Eligible: recently active, created before cutoff (fresh ObjectId is now),
        # so use a far-future eligible_before to include it.
        eligible = await repo.create(make_user(last_active_at=datetime.now(UTC)))
        # Excluded: already backfilled.
        await repo.create(
            make_user(last_active_at=datetime.now(UTC), memory_backfilled=datetime.now(UTC))
        )
        future = eligible_before + timedelta(days=1)
        assert await repo.count_backfill_candidates(active_since, future) == 1
        ids = await repo.find_backfill_candidate_ids(active_since, future, limit=10)
        assert ids == [eligible.id]

    async def test_mark_memory_backfilled_stamps_an_utc_instant(
        self, repo, make_user, local_time_offset_from_utc
    ):
        """The marker is compared against a UTC cutoff by the daily cron, so a
        naive local ``now()`` would land hours off and re-select (or hide) the
        user."""
        created = await repo.create(make_user())
        before = datetime.now(UTC) - timedelta(milliseconds=1)  # BSON stores milliseconds
        await repo.mark_memory_backfilled(created.id)
        stamped = (await repo.get(created.id)).memory_backfilled
        assert stamped is not None
        assert before <= stamped <= datetime.now(UTC)


class TestSignupDeliveryStamps:
    """The pair the signup-delivery recovery sweep is built on.

    A missing stamp is the only durable record that a new user is still owed a
    welcome email and a place in the marketing audience, so the query that finds
    those users and the write that retires them are the whole mechanism. Both
    run against real Mongo here because both are pure query shape — an ``$or``
    over ``{$exists: false}`` and a ``$set`` of named fields — which a stubbed
    repository proves nothing about.
    """

    @staticmethod
    def _recent(ages_in_hours: int) -> datetime:
        return datetime.now(UTC) - timedelta(hours=ages_in_hours)

    async def test_only_recent_signups_missing_a_stamp_are_selected(self, repo, make_user):
        """Both halves of this matter. Missing the un-stamped users means a lost
        enqueue is never recovered; including the settled or the ancient ones
        means re-mailing people who already got the email — and every account
        predating these fields carries neither stamp, so the lookback is the
        only thing standing between the sweep and the entire user base.
        """
        lookback = datetime.now(UTC) - timedelta(days=7)
        settled = datetime.now(UTC)
        # Inserted oldest-first, so Mongo's natural order is the reverse of the
        # expected one: an unsorted query cannot accidentally pass this.
        owed_one = await repo.create(
            make_user(email="half@b.com", created_at=self._recent(2), welcome_email_sent_at=settled)
        )
        owed_both = await repo.create(make_user(email="owed@b.com", created_at=self._recent(1)))
        # Excluded: both deliveries already landed.
        await repo.create(
            make_user(
                email="done@b.com",
                created_at=self._recent(3),
                welcome_email_sent_at=settled,
                marketing_contact_added_at=settled,
            )
        )
        # Excluded: predates the lookback, so its missing stamps mean "before
        # this mechanism existed", not "still owed".
        await repo.create(
            make_user(email="ancient@b.com", created_at=datetime.now(UTC) - timedelta(days=8))
        )

        ids = await repo.find_undelivered_signup_ids(lookback, limit=10)

        # Newest first: a capped run should drain the freshest signups, whose
        # welcome email is still worth sending, before older ones.
        assert ids == [owed_both.id, owed_one.id]

    async def test_the_lookback_boundary_includes_the_user_sitting_on_it(self, repo, make_user):
        boundary = datetime.now(UTC) - timedelta(days=7)
        on_boundary = await repo.create(make_user(email="on@b.com", created_at=boundary))
        await repo.create(make_user(email="off@b.com", created_at=boundary - timedelta(seconds=1)))

        ids = await repo.find_undelivered_signup_ids(boundary, limit=10)

        assert ids == [on_boundary.id]

    async def test_the_batch_is_capped_and_takes_the_newest(self, repo, make_user):
        """The cap keeps one run from spiking the ESP; the stamps are what make
        the next run resume with whoever is left."""
        # Oldest inserted first. Natural order would hand back the two oldest,
        # which is exactly the batch a capped run must NOT take: the stalest
        # signups, whose welcome email is least worth sending.
        await repo.create(make_user(email="n3@b.com", created_at=self._recent(3)))
        middle = await repo.create(make_user(email="n2@b.com", created_at=self._recent(2)))
        newest = await repo.create(make_user(email="n1@b.com", created_at=self._recent(1)))

        ids = await repo.find_undelivered_signup_ids(self._recent(24), limit=2)

        assert ids == [newest.id, middle.id]

    async def test_stamping_one_delivery_leaves_the_other_owed(
        self, repo, make_user, local_time_offset_from_utc
    ):
        """The two deliveries fail independently, so they retire independently.
        Stamping both when only one landed loses the other with no trace.

        The instant is compared against a UTC cutoff by the sweep, so a naive
        local ``now()`` would land hours off and either re-select the user or
        hide them for good.
        """
        created = await repo.create(make_user(created_at=self._recent(1)))
        # Warm the entity cache first: a stamp shadowed by a stale cached read
        # would let the job re-send a delivery it had already made.
        assert (await repo.get(created.id)).welcome_email_sent_at is None
        before = datetime.now(UTC) - timedelta(milliseconds=1)  # BSON stores milliseconds

        assert (
            await repo.stamp_signup_deliveries(created.id, [SignupDelivery.WELCOME_EMAIL]) is True
        )

        stored = await repo.get(created.id)
        assert stored.welcome_email_sent_at is not None
        assert before <= stored.welcome_email_sent_at <= datetime.now(UTC)
        assert stored.marketing_contact_added_at is None
        # Still owed the contact, so the sweep must still find them.
        assert await repo.find_undelivered_signup_ids(self._recent(24), limit=10) == [created.id]

    async def test_stamping_both_retires_the_signup_from_the_sweep(self, repo, make_user):
        created = await repo.create(make_user(created_at=self._recent(1)))

        await repo.stamp_signup_deliveries(created.id, list(SignupDelivery))

        stored = await repo.get(created.id)
        assert stored.welcome_email_sent_at is not None
        assert stored.marketing_contact_added_at is not None
        assert await repo.find_undelivered_signup_ids(self._recent(24), limit=10) == []

    async def test_stamping_a_user_that_no_longer_exists_touches_nobody(self, repo, make_user):
        """A user deleted between the sweep's scan and the job's run. The write
        matches nothing and must not spill onto whoever is left."""
        survivor = await repo.create(make_user(created_at=self._recent(1)))

        # Reported, not swallowed: a stamp that matched nobody means the job
        # just delivered to a user who is already gone.
        assert await repo.stamp_signup_deliveries("0" * 24, list(SignupDelivery)) is False

        stored = await repo.get(survivor.id)
        assert stored.welcome_email_sent_at is None
        assert stored.marketing_contact_added_at is None
        assert await repo.find_undelivered_signup_ids(self._recent(24), limit=10) == [survivor.id]


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


class TestHilPreferenceWrites:
    """The concurrency-safe HIL preference writes. Each assertion maps to a way a
    read-modify-write (or a dotted ``$set`` path) could silently drop or bury a
    user's setting — verified against real Mongo, where the burying happens."""

    async def test_setting_an_override_touches_only_that_tools_key(self, repo, make_user):
        user = await repo.create(
            make_user(hil_preferences={"mode": "always_ask", "tool_overrides": {"other": False}})
        )

        await repo.set_hil_tool_override(user.id, "GMAIL_SEND_EMAIL", True)

        got = await repo.get(user.id)
        assert got is not None
        assert got.hil_preferences == {
            "mode": "always_ask",
            "tool_overrides": {"other": False, "GMAIL_SEND_EMAIL": True},
        }

    async def test_a_dotted_mcp_tool_name_stays_a_flat_key(self, repo, make_user):
        # A dotted `$set` path would make Mongo nest {"server": {"action": true}},
        # which the flat-map read path never finds — the toggle would appear to do
        # nothing.
        user = await repo.create(make_user())

        await repo.set_hil_tool_override(user.id, "server.action", True)

        got = await repo.get(user.id)
        assert got is not None
        assert (got.hil_preferences or {})["tool_overrides"] == {"server.action": True}

    async def test_a_dollar_prefixed_tool_name_is_a_literal_not_an_expression(
        self, repo, make_user
    ):
        user = await repo.create(make_user())

        await repo.set_hil_tool_override(user.id, "$weird_tool", True)

        got = await repo.get(user.id)
        assert got is not None
        assert (got.hil_preferences or {})["tool_overrides"] == {"$weird_tool": True}

    async def test_false_is_a_real_setting_and_none_clears(self, repo, make_user):
        # False means "always allow this tool" — coercing it to a clear would
        # silently re-gate a tool the user disarmed.
        user = await repo.create(make_user())

        await repo.set_hil_tool_override(user.id, "t1", False)
        await repo.set_hil_tool_override(user.id, "t2", True)
        await repo.set_hil_tool_override(user.id, "t2", None)

        got = await repo.get(user.id)
        assert got is not None
        assert (got.hil_preferences or {})["tool_overrides"] == {"t1": False}

    async def test_partial_field_updates_leave_the_other_field_alone(self, repo, make_user):
        user = await repo.create(
            make_user(hil_preferences={"mode": "always_ask", "tool_overrides": {"send": True}})
        )

        await repo.set_hil_preference_fields(user.id, mode="auto")

        got = await repo.get(user.id)
        assert got is not None
        assert got.hil_preferences == {"mode": "auto", "tool_overrides": {"send": True}}

    async def test_an_empty_override_map_clears_rather_than_being_ignored(self, repo, make_user):
        user = await repo.create(
            make_user(hil_preferences={"mode": "auto", "tool_overrides": {"send": True}})
        )

        await repo.set_hil_preference_fields(user.id, tool_overrides={})

        got = await repo.get(user.id)
        assert got is not None
        assert got.hil_preferences == {"mode": "auto", "tool_overrides": {}}

    async def test_supplying_nothing_writes_nothing(self, repo, make_user):
        user = await repo.create(make_user(hil_preferences={"mode": "auto"}))

        await repo.set_hil_preference_fields(user.id)

        got = await repo.get(user.id)
        assert got is not None
        assert got.hil_preferences == {"mode": "auto"}

    async def test_the_entity_cache_never_serves_a_pre_write_read(self, repo, make_user):
        # set_hil_tool_override bypasses _apply_raw_update (pipeline update), so its
        # manual evict+bump is what upholds the repository's freshness guarantee.
        user = await repo.create(make_user())
        assert await repo.get(user.id) is not None  # seed the entity cache

        await repo.set_hil_tool_override(user.id, "send", True)

        got = await repo.get(user.id)
        assert got is not None
        assert (got.hil_preferences or {})["tool_overrides"] == {"send": True}
