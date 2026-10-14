"""Contract tests for BriefingsRepository.

User-scoped, business-key id persisted as _id, no cache policy: a bespoke suite, not
the inherited UserScopedRepositoryContract (same as test_conversations_repository.py).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import re

import pytest

from app.constants.briefing import BRIEFING_KIND_DAILY, BRIEFING_KIND_WEEKLY
from app.db.repositories.briefings import BriefingsRepository
from app.db.repositories.cache import CachePolicy
from app.models.briefing_models import BriefingPayload
from tests.helpers import local_timezone


def _payload(**overrides: object) -> BriefingPayload:
    data: dict[str, object] = {
        "kicker": "THE MORNING BRIEF",
        "date": "2026-08-06",
        "headline": "All quiet",
        "lede": "Nothing urgent today.",
        "mood": "clear",
        "caption": "steady",
    }
    data.update(overrides)
    return BriefingPayload.model_validate(data)


_IMAGE = "https://cdn.example/brief.png"
_FRESH = timedelta(minutes=1)


def _is_now(stamp: datetime | None) -> bool:
    return stamp is not None and abs(datetime.now(UTC) - stamp) < _FRESH


@pytest.fixture
def repo(raw_collection) -> BriefingsRepository:
    return BriefingsRepository()


class TestBriefingsCore:
    async def test_upsert_then_get_roundtrips(self, repo):
        created = await repo.upsert_briefing(
            "owner", "2026-08-06", BRIEFING_KIND_DAILY, _payload(), edition_image_url=_IMAGE
        )
        fetched = await repo.get(created.id, user_id="owner")
        assert fetched == created

    async def test_get_is_scoped_to_user(self, repo):
        created = await repo.upsert_briefing(
            "owner", "2026-08-06", BRIEFING_KIND_DAILY, _payload(), edition_image_url=_IMAGE
        )
        assert await repo.get(created.id, user_id="attacker") is None
        assert await repo.get(created.id, user_id="owner") is not None

    async def test_delete(self, repo):
        created = await repo.upsert_briefing(
            "owner", "2026-08-06", BRIEFING_KIND_DAILY, _payload(), edition_image_url=_IMAGE
        )
        assert await repo.delete(created.id, user_id="owner") is True
        assert await repo.get(created.id, user_id="owner") is None


class TestBriefingsUpsert:
    async def test_upsert_records_the_hosted_edition_render(self, repo):
        stored = await repo.upsert_briefing(
            "u-image", "2026-08-06", BRIEFING_KIND_DAILY, _payload(), edition_image_url=_IMAGE
        )
        fetched = await repo.get(stored.id, user_id="u-image")
        assert fetched is not None and fetched.edition_image_url == _IMAGE

    async def test_a_new_brief_is_minted_unopened_undelivered_and_stamped_now(
        self, repo, raw_collection
    ):
        with local_timezone("Asia/Kolkata"):
            stored = await repo.upsert_briefing(
                "u-mint", "2026-08-06", BRIEFING_KIND_DAILY, _payload(), edition_image_url=_IMAGE
            )

        assert re.fullmatch(r"brief_[0-9a-f]{12}", stored.id)
        assert _is_now(stored.created_at)
        raw = await raw_collection.find_one({"_id": stored.id})
        assert raw is not None
        assert (raw["delivered_channels"], raw["opened_at"]) == ([], None)

    async def test_upsert_creates_then_updates_payload_in_place(self, repo, raw_collection):
        user_id = "u-upsert"
        first = await repo.upsert_briefing(
            user_id, "2026-08-06", BRIEFING_KIND_DAILY, _payload(), edition_image_url=_IMAGE
        )
        assert first.payload.headline == "All quiet"
        second = await repo.upsert_briefing(
            user_id,
            "2026-08-06",
            BRIEFING_KIND_DAILY,
            _payload(headline="Busy day"),
            edition_image_url=_IMAGE,
        )
        assert second.id == first.id  # same doc, not a duplicate
        assert second.payload.headline == "Busy day"
        assert await raw_collection.count_documents({"user_id": user_id}) == 1

    async def test_upsert_preserves_opened_at_across_rerun(self, repo):
        user_id = "u-preserve"
        briefing = await repo.upsert_briefing(
            user_id, "2026-08-06", BRIEFING_KIND_DAILY, _payload(), edition_image_url=_IMAGE
        )
        assert briefing.opened_at is None
        opened = await repo.mark_opened(user_id, briefing.id)
        assert opened is not None and opened.opened_at is not None

        rerun = await repo.upsert_briefing(
            user_id,
            "2026-08-06",
            BRIEFING_KIND_DAILY,
            _payload(headline="rerun"),
            edition_image_url=_IMAGE,
        )
        assert rerun.opened_at == opened.opened_at  # untouched by the rerun
        assert rerun.payload.headline == "rerun"

    async def test_upsert_distinguishes_by_date_and_kind(self, repo, raw_collection):
        user_id = "u-distinct"
        await repo.upsert_briefing(
            user_id, "2026-08-06", BRIEFING_KIND_DAILY, _payload(), edition_image_url=_IMAGE
        )
        await repo.upsert_briefing(
            user_id, "2026-08-07", BRIEFING_KIND_DAILY, _payload(), edition_image_url=_IMAGE
        )
        await repo.upsert_briefing(
            user_id,
            "2026-08-06",
            BRIEFING_KIND_WEEKLY,
            _payload(mood="weekly"),
            edition_image_url=_IMAGE,
        )
        assert await raw_collection.count_documents({"user_id": user_id}) == 3


class TestBriefingsReads:
    async def test_get_before_date_excludes_same_day_and_orders_lexically(self, repo):
        user_id = "u-before"
        earlier = await repo.upsert_briefing(
            user_id, "2026-08-04", BRIEFING_KIND_DAILY, _payload(), edition_image_url=_IMAGE
        )
        await repo.upsert_briefing(
            user_id, "2026-08-05", BRIEFING_KIND_DAILY, _payload(), edition_image_url=_IMAGE
        )
        await repo.upsert_briefing(
            user_id, "2026-08-06", BRIEFING_KIND_DAILY, _payload(), edition_image_url=_IMAGE
        )
        result = await repo.get_before_date(
            user_id, kind=BRIEFING_KIND_DAILY, before_date="2026-08-05"
        )
        assert result is not None and result.id == earlier.id

    async def test_get_before_date_returns_the_latest_earlier_brief_of_that_kind(self, repo):
        user_id = "u-before-latest"
        await repo.upsert_briefing(
            user_id, "2026-08-03", BRIEFING_KIND_DAILY, _payload(), edition_image_url=_IMAGE
        )
        latest = await repo.upsert_briefing(
            user_id, "2026-08-04", BRIEFING_KIND_DAILY, _payload(), edition_image_url=_IMAGE
        )
        await repo.upsert_briefing(
            user_id,
            "2026-08-04",
            BRIEFING_KIND_WEEKLY,
            _payload(mood="weekly"),
            edition_image_url=_IMAGE,
        )

        result = await repo.get_before_date(
            user_id, kind=BRIEFING_KIND_DAILY, before_date="2026-08-06"
        )

        assert result is not None and result.id == latest.id
        assert (
            await repo.get_before_date(user_id, kind=BRIEFING_KIND_DAILY, before_date="2026-08-03")
            is None
        )

    async def test_list_recent_is_newest_first_and_scoped(self, repo):
        user_id = "u-recent"
        await repo.upsert_briefing(
            user_id, "2026-08-05", BRIEFING_KIND_DAILY, _payload(), edition_image_url=_IMAGE
        )
        newest = await repo.upsert_briefing(
            user_id, "2026-08-06", BRIEFING_KIND_DAILY, _payload(), edition_image_url=_IMAGE
        )
        await repo.upsert_briefing(
            "other-user", "2026-08-06", BRIEFING_KIND_DAILY, _payload(), edition_image_url=_IMAGE
        )
        recent = await repo.list_recent(user_id, limit=10)
        assert [b.user_id for b in recent] == [user_id, user_id]
        assert recent[0].id == newest.id

    async def test_list_recent_honours_the_limit_and_the_kind(self, repo, raw_collection):
        user_id = "u-recent-kind"
        oldest = await repo.upsert_briefing(
            user_id, "2026-08-05", BRIEFING_KIND_DAILY, _payload(), edition_image_url=_IMAGE
        )
        newest_daily = await repo.upsert_briefing(
            user_id, "2026-08-06", BRIEFING_KIND_DAILY, _payload(), edition_image_url=_IMAGE
        )
        weekly = await repo.upsert_briefing(
            user_id,
            "2026-08-07",
            BRIEFING_KIND_WEEKLY,
            _payload(mood="weekly"),
            edition_image_url=_IMAGE,
        )
        # Writes inside one millisecond tie on created_at; pin a strict order.
        for hour, brief in enumerate([oldest, newest_daily, weekly]):
            await raw_collection.update_one(
                {"_id": brief.id}, {"$set": {"created_at": datetime(2026, 8, 7, hour, tzinfo=UTC)}}
            )

        assert [b.id for b in await repo.list_recent(user_id, limit=1)] == [weekly.id]
        dailies = await repo.list_recent(user_id, limit=1, kind=BRIEFING_KIND_DAILY)
        assert [b.id for b in dailies] == [newest_daily.id]

    async def test_has_daily_briefing(self, repo):
        user_id = "u-has-daily"
        assert await repo.has_daily_briefing(user_id) is False
        await repo.upsert_briefing(
            user_id, "2026-08-06", BRIEFING_KIND_WEEKLY, _payload(), edition_image_url=_IMAGE
        )
        assert await repo.has_daily_briefing(user_id) is False  # weekly doesn't count
        await repo.upsert_briefing(
            user_id, "2026-08-06", BRIEFING_KIND_DAILY, _payload(), edition_image_url=_IMAGE
        )
        assert await repo.has_daily_briefing(user_id) is True

    async def test_was_delivered_needs_a_channel_on_that_date_and_kind(self, repo):
        user_id = "u-delivered"
        assert await repo.was_delivered(user_id, "2026-08-06", BRIEFING_KIND_DAILY) is False
        await repo.upsert_briefing(
            user_id, "2026-08-06", BRIEFING_KIND_DAILY, _payload(), edition_image_url=_IMAGE
        )
        # Stored but delivered nowhere: a retry may still send it.
        assert await repo.was_delivered(user_id, "2026-08-06", BRIEFING_KIND_DAILY) is False

        await repo.set_delivered_channels(user_id, "2026-08-06", BRIEFING_KIND_DAILY, ["inapp"])

        assert await repo.was_delivered(user_id, "2026-08-06", BRIEFING_KIND_DAILY) is True
        assert await repo.was_delivered(user_id, "2026-08-07", BRIEFING_KIND_DAILY) is False
        assert await repo.was_delivered(user_id, "2026-08-06", BRIEFING_KIND_WEEKLY) is False


class TestBriefingsMarkOpened:
    async def test_mark_opened_is_idempotent(self, repo):
        user_id = "u-opened"
        briefing = await repo.upsert_briefing(
            user_id, "2026-08-06", BRIEFING_KIND_DAILY, _payload(), edition_image_url=_IMAGE
        )
        with local_timezone("Asia/Kolkata"):
            first = await repo.mark_opened(user_id, briefing.id)
        assert first is not None and _is_now(first.opened_at)
        second = await repo.mark_opened(user_id, briefing.id)
        assert second is None  # already opened — no flip, no overwrite

    async def test_mark_opened_missing_or_wrong_user_returns_none(self, repo):
        user_id = "u-owner"
        briefing = await repo.upsert_briefing(
            user_id, "2026-08-06", BRIEFING_KIND_DAILY, _payload(), edition_image_url=_IMAGE
        )
        assert await repo.mark_opened("attacker", briefing.id) is None
        assert await repo.mark_opened(user_id, "brief_missing") is None


class TestBriefingsDeliveredChannels:
    async def test_set_delivered_channels(self, repo):
        user_id = "u-channels"
        stored = await repo.upsert_briefing(
            user_id, "2026-08-06", BRIEFING_KIND_DAILY, _payload(), edition_image_url=_IMAGE
        )
        await repo.set_delivered_channels(
            user_id, "2026-08-06", BRIEFING_KIND_DAILY, ["inapp", "telegram"]
        )
        fetched = await repo.get(stored.id, user_id=user_id)
        assert fetched is not None
        assert fetched.delivered_channels == ["inapp", "telegram"]


class _CachedBriefingsRepository(BriefingsRepository):
    cache_policy = CachePolicy(prefix="contract:briefings")


class TestWritesUnderACachePolicy:
    """Every write names the owner's scope, so switching a cache policy on never serves a stale get()."""

    @pytest.fixture
    def cached_repo(self, raw_collection) -> _CachedBriefingsRepository:
        return _CachedBriefingsRepository()

    async def _cached_brief(self, cached_repo: _CachedBriefingsRepository, user_id: str):
        stored = await cached_repo.upsert_briefing(
            user_id, "2026-08-06", BRIEFING_KIND_DAILY, _payload(), edition_image_url=_IMAGE
        )
        assert await cached_repo.get(stored.id, user_id=user_id) == stored
        return stored

    async def test_a_rerun_refreshes_the_cached_brief(self, cached_repo):
        stored = await self._cached_brief(cached_repo, "u-cache-rerun")

        await cached_repo.upsert_briefing(
            "u-cache-rerun",
            "2026-08-06",
            BRIEFING_KIND_DAILY,
            _payload(headline="Busy day"),
            edition_image_url=_IMAGE,
        )

        fetched = await cached_repo.get(stored.id, user_id="u-cache-rerun")
        assert fetched is not None and fetched.payload.headline == "Busy day"

    async def test_recording_delivery_refreshes_the_cached_brief(self, cached_repo):
        stored = await self._cached_brief(cached_repo, "u-cache-channels")

        await cached_repo.set_delivered_channels(
            "u-cache-channels", "2026-08-06", BRIEFING_KIND_DAILY, ["inapp"]
        )

        fetched = await cached_repo.get(stored.id, user_id="u-cache-channels")
        assert fetched is not None and fetched.delivered_channels == ["inapp"]

    async def test_opening_refreshes_the_cached_brief(self, cached_repo):
        stored = await self._cached_brief(cached_repo, "u-cache-open")

        await cached_repo.mark_opened("u-cache-open", stored.id)

        fetched = await cached_repo.get(stored.id, user_id="u-cache-open")
        assert fetched is not None and fetched.opened_at is not None
