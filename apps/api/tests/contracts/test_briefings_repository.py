"""Contract tests for BriefingsRepository (user-scoped, business-key ``id``
persisted as ``_id``, no cache policy — a bespoke suite, not the inherited
``UserScopedRepositoryContract``, matching ``test_conversations_repository.py``).
"""

from __future__ import annotations

import pytest

from app.constants.briefing import BRIEFING_KIND_DAILY, BRIEFING_KIND_WEEKLY
from app.db.repositories.briefings import BriefingsRepository
from app.models.briefing_models import BriefingPayload


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


@pytest.fixture
def repo(raw_collection) -> BriefingsRepository:
    return BriefingsRepository()


class TestBriefingsCore:
    async def test_upsert_then_get_roundtrips(self, repo):
        created = await repo.upsert_briefing("owner", "2026-08-06", BRIEFING_KIND_DAILY, _payload())
        fetched = await repo.get(created.id, user_id="owner")
        assert fetched == created

    async def test_get_is_scoped_to_user(self, repo):
        created = await repo.upsert_briefing("owner", "2026-08-06", BRIEFING_KIND_DAILY, _payload())
        assert await repo.get(created.id, user_id="attacker") is None
        assert await repo.get(created.id, user_id="owner") is not None

    async def test_delete(self, repo):
        created = await repo.upsert_briefing("owner", "2026-08-06", BRIEFING_KIND_DAILY, _payload())
        assert await repo.delete(created.id, user_id="owner") is True
        assert await repo.get(created.id, user_id="owner") is None


class TestBriefingsUpsert:
    async def test_upsert_creates_then_updates_payload_in_place(self, repo, raw_collection):
        user_id = "u-upsert"
        first = await repo.upsert_briefing(user_id, "2026-08-06", BRIEFING_KIND_DAILY, _payload())
        assert first.payload.headline == "All quiet"
        second = await repo.upsert_briefing(
            user_id, "2026-08-06", BRIEFING_KIND_DAILY, _payload(headline="Busy day")
        )
        assert second.id == first.id  # same doc, not a duplicate
        assert second.payload.headline == "Busy day"
        assert await raw_collection.count_documents({"user_id": user_id}) == 1

    async def test_upsert_preserves_opened_at_across_rerun(self, repo):
        user_id = "u-preserve"
        briefing = await repo.upsert_briefing(
            user_id, "2026-08-06", BRIEFING_KIND_DAILY, _payload()
        )
        assert briefing.opened_at is None
        opened = await repo.mark_opened(user_id, briefing.id)
        assert opened is not None and opened.opened_at is not None

        rerun = await repo.upsert_briefing(
            user_id, "2026-08-06", BRIEFING_KIND_DAILY, _payload(headline="rerun")
        )
        assert rerun.opened_at == opened.opened_at  # untouched by the rerun
        assert rerun.payload.headline == "rerun"

    async def test_upsert_distinguishes_by_date_and_kind(self, repo, raw_collection):
        user_id = "u-distinct"
        await repo.upsert_briefing(user_id, "2026-08-06", BRIEFING_KIND_DAILY, _payload())
        await repo.upsert_briefing(user_id, "2026-08-07", BRIEFING_KIND_DAILY, _payload())
        await repo.upsert_briefing(
            user_id, "2026-08-06", BRIEFING_KIND_WEEKLY, _payload(mood="weekly")
        )
        assert await raw_collection.count_documents({"user_id": user_id}) == 3


class TestBriefingsReads:
    async def test_get_latest_returns_most_recent_of_kind(self, repo):
        user_id = "u-latest"
        await repo.upsert_briefing(user_id, "2026-08-05", BRIEFING_KIND_DAILY, _payload())
        newest = await repo.upsert_briefing(user_id, "2026-08-06", BRIEFING_KIND_DAILY, _payload())
        await repo.upsert_briefing(user_id, "2026-08-06", BRIEFING_KIND_WEEKLY, _payload())
        latest = await repo.get_latest(user_id, kind=BRIEFING_KIND_DAILY)
        assert latest is not None and latest.id == newest.id

    async def test_get_latest_missing_returns_none(self, repo):
        assert await repo.get_latest("nobody") is None

    async def test_get_before_date_excludes_same_day_and_orders_lexically(self, repo):
        user_id = "u-before"
        earlier = await repo.upsert_briefing(user_id, "2026-08-04", BRIEFING_KIND_DAILY, _payload())
        await repo.upsert_briefing(user_id, "2026-08-05", BRIEFING_KIND_DAILY, _payload())
        await repo.upsert_briefing(user_id, "2026-08-06", BRIEFING_KIND_DAILY, _payload())
        result = await repo.get_before_date(
            user_id, kind=BRIEFING_KIND_DAILY, before_date="2026-08-05"
        )
        assert result is not None and result.id == earlier.id

    async def test_list_recent_is_newest_first_and_scoped(self, repo):
        user_id = "u-recent"
        await repo.upsert_briefing(user_id, "2026-08-05", BRIEFING_KIND_DAILY, _payload())
        newest = await repo.upsert_briefing(user_id, "2026-08-06", BRIEFING_KIND_DAILY, _payload())
        await repo.upsert_briefing("other-user", "2026-08-06", BRIEFING_KIND_DAILY, _payload())
        recent = await repo.list_recent(user_id, limit=10)
        assert [b.user_id for b in recent] == [user_id, user_id]
        assert recent[0].id == newest.id

    async def test_has_daily_briefing(self, repo):
        user_id = "u-has-daily"
        assert await repo.has_daily_briefing(user_id) is False
        await repo.upsert_briefing(user_id, "2026-08-06", BRIEFING_KIND_WEEKLY, _payload())
        assert await repo.has_daily_briefing(user_id) is False  # weekly doesn't count
        await repo.upsert_briefing(user_id, "2026-08-06", BRIEFING_KIND_DAILY, _payload())
        assert await repo.has_daily_briefing(user_id) is True


class TestBriefingsMarkOpened:
    async def test_mark_opened_is_idempotent(self, repo):
        user_id = "u-opened"
        briefing = await repo.upsert_briefing(
            user_id, "2026-08-06", BRIEFING_KIND_DAILY, _payload()
        )
        first = await repo.mark_opened(user_id, briefing.id)
        assert first is not None and first.opened_at is not None
        second = await repo.mark_opened(user_id, briefing.id)
        assert second is None  # already opened — no flip, no overwrite

    async def test_mark_opened_missing_or_wrong_user_returns_none(self, repo):
        user_id = "u-owner"
        briefing = await repo.upsert_briefing(
            user_id, "2026-08-06", BRIEFING_KIND_DAILY, _payload()
        )
        assert await repo.mark_opened("attacker", briefing.id) is None
        assert await repo.mark_opened(user_id, "brief_missing") is None


class TestBriefingsDeliveredChannels:
    async def test_set_delivered_channels(self, repo):
        user_id = "u-channels"
        await repo.upsert_briefing(user_id, "2026-08-06", BRIEFING_KIND_DAILY, _payload())
        await repo.set_delivered_channels(
            user_id, "2026-08-06", BRIEFING_KIND_DAILY, ["inapp", "telegram"]
        )
        latest = await repo.get_latest(user_id, kind=BRIEFING_KIND_DAILY)
        assert latest is not None
        assert latest.delivered_channels == ["inapp", "telegram"]
