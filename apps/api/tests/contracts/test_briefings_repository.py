"""Contract tests for BriefingsRepository.

User-scoped, business-key id persisted as _id, no cache policy: a bespoke suite, not
the inherited UserScopedRepositoryContract (same as test_conversations_repository.py).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import re

from pymongo.errors import DuplicateKeyError
import pytest

from app.constants.briefing import (
    BriefForm,
    BriefingKind,
)
from app.db.repositories.briefings import BriefingsRepository
from app.db.repositories.cache import CachePolicy
from app.models.brief_document_models import (
    BriefCardRecord,
    BriefDelivery,
    BriefingModel,
    DeliveryStep,
    EditionRender,
)
from app.models.brief_item_models import ItemState
from app.models.brief_payload_models import BriefingItem, BriefingPayload, BriefingSection
from tests.helpers import local_timezone


def _payload(**overrides: object) -> BriefingPayload:
    data: dict[str, object] = {
        "kicker": "THE MORNING BRIEF",
        "template_family": "swiss",
        "date": "2026-08-06",
        "headline": "All quiet",
        "lede": "Nothing urgent today.",
        "mood": "clear",
        "caption": "steady",
    }
    data.update(overrides)
    return BriefingPayload.model_validate(data)


_EDITION = EditionRender(key="edition-key")
_PLAN = BriefDelivery(push=True, notification_kind="briefing_daily", held_ids=["h1"])
_FRESH = timedelta(minutes=1)


def _is_now(stamp: datetime | None) -> bool:
    return stamp is not None and abs(datetime.now(UTC) - stamp) < _FRESH


async def _upsert(
    repo: BriefingsRepository,
    user_id: str,
    date: str,
    kind: BriefingKind,
    payload: BriefingPayload,
    *,
    edition: EditionRender | None,
) -> BriefingModel:
    """Store the brief the way store_brief does: under the id briefing_id_for gives."""
    return await repo.upsert_briefing(
        BriefingModel(
            id=await repo.briefing_id_for(user_id, date, kind),
            user_id=user_id,
            date=date,
            kind=kind,
            payload=payload,
            edition=edition,
            delivery=_PLAN,
        )
    )


async def _deliver(
    repo: BriefingsRepository, user_id: str, date: str, kind: BriefingKind, channels: list[str]
) -> None:
    """Record the brief's notification as reaching channels, then complete its delivery."""
    brief = await repo.find_for_date(user_id, date, kind)
    assert brief is not None
    await repo.record_step(user_id, brief.id, DeliveryStep.NOTIFICATION, channels)
    await repo.complete_delivery(user_id, brief.id)


@pytest.fixture
def repo(raw_collection) -> BriefingsRepository:
    return BriefingsRepository()


class TestBriefingsCore:
    async def test_upsert_then_get_roundtrips(self, repo):
        created = await _upsert(
            repo, "owner", "2026-08-06", BriefingKind.DAILY, _payload(), edition=_EDITION
        )
        fetched = await repo.get(created.id, user_id="owner")
        assert fetched == created

    async def test_get_is_scoped_to_user(self, repo):
        created = await _upsert(
            repo, "owner", "2026-08-06", BriefingKind.DAILY, _payload(), edition=_EDITION
        )
        assert await repo.get(created.id, user_id="attacker") is None
        assert await repo.get(created.id, user_id="owner") is not None

    async def test_delete(self, repo):
        created = await _upsert(
            repo, "owner", "2026-08-06", BriefingKind.DAILY, _payload(), edition=_EDITION
        )
        assert await repo.delete(created.id, user_id="owner") is True
        assert await repo.get(created.id, user_id="owner") is None


class TestBriefingsUpsert:
    async def test_upsert_records_the_stored_edition_and_finds_its_owner_by_its_key(self, repo):
        stored = await _upsert(
            repo, "u-image", "2026-08-06", BriefingKind.DAILY, _payload(), edition=_EDITION
        )
        fetched = await repo.get(stored.id, user_id="u-image")
        assert fetched is not None and fetched.edition == _EDITION
        assert await repo.owner_of_edition("edition-key") == "u-image"
        assert await repo.owner_of_edition("another-key") is None

    async def test_upsert_records_where_the_edition_folds_and_where_its_paper_sits(self, repo):
        edition = EditionRender(key="fold-key", fold=0.4, paper=[0.1, 0.2, 0.9, 0.8])
        stored = await _upsert(
            repo, "u-fold", "2026-08-06", BriefingKind.DAILY, _payload(), edition=edition
        )

        fetched = await repo.get(stored.id, user_id="u-fold")

        assert fetched is not None
        assert fetched.edition == edition

    async def test_a_new_brief_is_minted_unopened_undelivered_and_stamped_now(
        self, repo, raw_collection
    ):
        with local_timezone("Asia/Kolkata"):
            stored = await _upsert(
                repo,
                "u-mint",
                "2026-08-06",
                BriefingKind.DAILY,
                _payload(),
                edition=_EDITION,
            )

        assert re.fullmatch(r"brief_[0-9a-f]{12}", stored.id)
        assert _is_now(stored.created_at)
        raw = await raw_collection.find_one({"_id": stored.id})
        assert raw is not None
        assert (raw["delivered_channels"], raw["opened_at"]) == ([], None)

    async def test_upsert_creates_then_updates_payload_in_place(self, repo, raw_collection):
        user_id = "u-upsert"
        first = await _upsert(
            repo, user_id, "2026-08-06", BriefingKind.DAILY, _payload(), edition=_EDITION
        )
        assert first.payload.headline == "All quiet"
        second = await _upsert(
            repo,
            user_id,
            "2026-08-06",
            BriefingKind.DAILY,
            _payload(headline="Busy day"),
            edition=_EDITION,
        )
        assert second.id == first.id  # same doc, not a duplicate
        assert second.payload.headline == "Busy day"
        assert await raw_collection.count_documents({"user_id": user_id}) == 1

    async def test_upsert_preserves_opened_at_across_rerun(self, repo):
        user_id = "u-preserve"
        briefing = await _upsert(
            repo, user_id, "2026-08-06", BriefingKind.DAILY, _payload(), edition=_EDITION
        )
        assert briefing.opened_at is None
        opened = await repo.mark_opened(user_id, briefing.id)
        assert opened is not None and opened.opened_at is not None

        rerun = await _upsert(
            repo,
            user_id,
            "2026-08-06",
            BriefingKind.DAILY,
            _payload(headline="rerun"),
            edition=_EDITION,
        )
        assert rerun.opened_at == opened.opened_at  # untouched by the rerun
        assert rerun.payload.headline == "rerun"

    async def test_a_rerun_is_given_the_id_the_brief_already_has(self, repo):
        stored = await _upsert(
            repo, "u-id", "2026-08-06", BriefingKind.DAILY, _payload(), edition=_EDITION
        )

        assert await repo.briefing_id_for("u-id", "2026-08-06", BriefingKind.DAILY) == stored.id
        assert await repo.briefing_id_for("u-id", "2026-08-07", BriefingKind.DAILY) != stored.id

    async def test_a_brief_stored_first_under_another_id_refuses_the_late_upsert(
        self, repo, raw_collection
    ):
        """The late run's edition encodes its own id's link, so it must not overwrite the stored brief."""
        await raw_collection.create_index([("user_id", 1), ("date", 1), ("kind", 1)], unique=True)
        stored = await _upsert(
            repo, "u-race", "2026-08-06", BriefingKind.DAILY, _payload(), edition=_EDITION
        )

        with pytest.raises(DuplicateKeyError):
            await repo.upsert_briefing(
                stored.model_copy(
                    update={"id": "brief_000000000000", "payload": _payload(headline="late")}
                )
            )
        assert await repo.get(stored.id, user_id="u-race") == stored

    async def test_upsert_distinguishes_by_date_and_kind(self, repo, raw_collection):
        user_id = "u-distinct"
        await _upsert(repo, user_id, "2026-08-06", BriefingKind.DAILY, _payload(), edition=_EDITION)
        await _upsert(repo, user_id, "2026-08-07", BriefingKind.DAILY, _payload(), edition=_EDITION)
        await _upsert(
            repo,
            user_id,
            "2026-08-06",
            BriefingKind.WEEKLY,
            _payload(mood="weekly"),
            edition=_EDITION,
        )
        assert await raw_collection.count_documents({"user_id": user_id}) == 3


class TestBriefingsReads:
    async def test_get_before_date_excludes_same_day_and_orders_lexically(self, repo):
        user_id = "u-before"
        earlier = await _upsert(
            repo, user_id, "2026-08-04", BriefingKind.DAILY, _payload(), edition=_EDITION
        )
        await _upsert(repo, user_id, "2026-08-05", BriefingKind.DAILY, _payload(), edition=_EDITION)
        await _upsert(repo, user_id, "2026-08-06", BriefingKind.DAILY, _payload(), edition=_EDITION)
        result = await repo.get_before_date(
            user_id, kind=BriefingKind.DAILY, before_date="2026-08-05"
        )
        assert result is not None and result.id == earlier.id

    async def test_get_before_date_returns_the_latest_earlier_brief_of_that_kind(self, repo):
        user_id = "u-before-latest"
        await _upsert(repo, user_id, "2026-08-03", BriefingKind.DAILY, _payload(), edition=_EDITION)
        latest = await _upsert(
            repo, user_id, "2026-08-04", BriefingKind.DAILY, _payload(), edition=_EDITION
        )
        await _upsert(
            repo,
            user_id,
            "2026-08-04",
            BriefingKind.WEEKLY,
            _payload(mood="weekly"),
            edition=_EDITION,
        )

        result = await repo.get_before_date(
            user_id, kind=BriefingKind.DAILY, before_date="2026-08-06"
        )

        assert result is not None and result.id == latest.id
        assert (
            await repo.get_before_date(user_id, kind=BriefingKind.DAILY, before_date="2026-08-03")
            is None
        )

    async def test_list_recent_is_newest_first_and_scoped(self, repo):
        user_id = "u-recent"
        await _upsert(repo, user_id, "2026-08-05", BriefingKind.DAILY, _payload(), edition=_EDITION)
        newest = await _upsert(
            repo, user_id, "2026-08-06", BriefingKind.DAILY, _payload(), edition=_EDITION
        )
        await _upsert(
            repo,
            "other-user",
            "2026-08-06",
            BriefingKind.DAILY,
            _payload(),
            edition=_EDITION,
        )
        recent = await repo.list_recent(user_id, limit=10)
        assert [b.user_id for b in recent] == [user_id, user_id]
        assert recent[0].id == newest.id

    async def test_the_archive_lists_editions_and_leaves_quiet_notes_out(self, repo):
        """A quiet day's note has no edition to show: the archive is editions only."""
        user_id = "u-quiet"
        edition = await _upsert(
            repo, user_id, "2026-08-05", BriefingKind.DAILY, _payload(), edition=_EDITION
        )
        note = await _upsert(
            repo,
            user_id,
            "2026-08-06",
            BriefingKind.DAILY,
            _payload(form=BriefForm.QUIET_NOTE),
            edition=None,
        )

        assert [b.id for b in await repo.list_recent(user_id, limit=10, editions_only=True)] == [
            edition.id
        ]
        assert [b.id for b in await repo.list_cards(user_id, limit=10)] == [edition.id]
        assert [b.id for b in await repo.list_recent(user_id, limit=10)] == [note.id, edition.id]
        assert note.edition is None

    async def test_a_card_reads_the_fields_it_shows_off_the_stored_brief(self, repo):
        """The projection carries every field a card is built from, so it folds as the whole brief does."""
        user_id = "u-card"
        section = BriefingSection(
            numeral="I",
            title="Needs you",
            items=[BriefingItem(text="Sign", action="approve", kind=ItemState.YOU)],
        )
        stored = await _upsert(
            repo,
            user_id,
            "2026-08-06",
            BriefingKind.DAILY,
            _payload(template_family="postal", stamp_city="tokyo", sections=[section]),
            edition=EditionRender(key="k", fold=0.3, paper=[0.1, 0.1, 0.9, 0.9]),
        )
        whole = BriefCardRecord.model_validate(stored, from_attributes=True)

        assert await repo.list_cards(user_id, limit=10) == [whole]
        assert await repo.get_card(stored.id, user_id=user_id) == whole
        assert await repo.get_card(stored.id, user_id="attacker") is None

    async def test_list_recent_orders_by_brief_date_not_write_time(self, repo, raw_collection):
        """A backfilled brief is written after newer days but still lists by its own date."""
        user_id = "u-backfilled"
        later_day = await _upsert(
            repo, user_id, "2026-08-06", BriefingKind.DAILY, _payload(), edition=_EDITION
        )
        earlier_day = await _upsert(
            repo, user_id, "2026-08-05", BriefingKind.DAILY, _payload(), edition=_EDITION
        )
        weekly_same_day = await _upsert(
            repo, user_id, "2026-08-06", BriefingKind.WEEKLY, _payload(), edition=_EDITION
        )
        for hour, brief in enumerate([weekly_same_day, later_day, earlier_day]):
            await raw_collection.update_one(
                {"_id": brief.id}, {"$set": {"created_at": datetime(2026, 8, 7, hour, tzinfo=UTC)}}
            )

        recent = await repo.list_recent(user_id, limit=10)

        assert [b.id for b in recent] == [weekly_same_day.id, later_day.id, earlier_day.id]

    async def test_list_cards_before_a_brief_continues_the_listing_after_it(self, repo):
        """The archive's next page starts right after the last brief of the one before it."""
        user_id = "u-paged"
        older = await _upsert(
            repo, user_id, "2026-08-05", BriefingKind.DAILY, _payload(), edition=_EDITION
        )
        same_day = await _upsert(
            repo, user_id, "2026-08-06", BriefingKind.DAILY, _payload(), edition=_EDITION
        )
        weekly = await _upsert(
            repo, user_id, "2026-08-06", BriefingKind.WEEKLY, _payload(), edition=_EDITION
        )
        newest = await _upsert(
            repo, user_id, "2026-08-07", BriefingKind.DAILY, _payload(), edition=_EDITION
        )
        await _upsert(
            repo, "other-user", "2026-08-04", BriefingKind.DAILY, _payload(), edition=_EDITION
        )

        first = await repo.list_cards(user_id, limit=2)
        second = await repo.list_cards(user_id, limit=2, before=first[-1])
        last = await repo.list_cards(user_id, limit=2, before=second[-1])

        assert [b.id for b in first] == [newest.id, weekly.id]
        assert [b.id for b in second] == [same_day.id, older.id]
        assert last == []

    async def test_list_cards_puts_a_weekly_ahead_of_the_daily_on_its_day_whichever_was_stored_first(
        self, repo
    ):
        user_id = "u-weekly-first"
        stored: dict[tuple[str, BriefingKind], str] = {}
        for date, kinds in [
            ("2026-08-06", (BriefingKind.DAILY, BriefingKind.WEEKLY)),
            ("2026-08-05", (BriefingKind.WEEKLY, BriefingKind.DAILY)),
        ]:
            for kind in kinds:
                brief = await _upsert(repo, user_id, date, kind, _payload(), edition=_EDITION)
                stored[(date, kind)] = brief.id

        cards = await repo.list_cards(user_id, limit=10)

        assert [c.id for c in cards] == [
            stored[("2026-08-06", BriefingKind.WEEKLY)],
            stored[("2026-08-06", BriefingKind.DAILY)],
            stored[("2026-08-05", BriefingKind.WEEKLY)],
            stored[("2026-08-05", BriefingKind.DAILY)],
        ]

    async def test_list_stamped_orders_its_cities_by_the_day_each_arrived_not_by_city(self, repo):
        user_id = "u-stamped-order"
        # Stored newest first and against the cities' alphabetical order.
        cities = ["zurich", "oslo", "lima", "kyiv", "dakar", "accra"]
        for day, city in zip(range(9, 3, -1), cities, strict=True):
            date = f"2026-08-{day:02d}"
            await _upsert(
                repo,
                user_id,
                date,
                BriefingKind.DAILY,
                _payload(stamp_city=city),
                edition=_EDITION,
            )
            await _deliver(repo, user_id, date, BriefingKind.DAILY, ["inapp"])

        stamped = await repo.list_stamped(user_id)

        assert [s.payload.stamp_city for s in stamped] == list(reversed(cities))

    async def test_list_stamped_reads_each_citys_first_delivered_brief_of_the_users_oldest_first(
        self, repo
    ):
        user_id = "u-stamped"
        later = await _upsert(
            repo,
            user_id,
            "2026-08-07",
            BriefingKind.DAILY,
            _payload(stamp_city="lima"),
            edition=_EDITION,
        )
        await _upsert(repo, user_id, "2026-08-06", BriefingKind.DAILY, _payload(), edition=_EDITION)
        # Tokyo again, after it first arrived: the city counts once, on its first day.
        await _upsert(
            repo,
            user_id,
            "2026-08-09",
            BriefingKind.DAILY,
            _payload(stamp_city="tokyo"),
            edition=_EDITION,
        )
        earlier = await _upsert(
            repo,
            user_id,
            "2026-08-05",
            BriefingKind.DAILY,
            _payload(stamp_city="tokyo"),
            edition=_EDITION,
        )
        await _upsert(
            repo,
            "other-user",
            "2026-08-04",
            BriefingKind.DAILY,
            _payload(stamp_city="paris"),
            edition=_EDITION,
        )
        # Stamped but delivered nowhere: the user never received this city.
        await _upsert(
            repo,
            user_id,
            "2026-08-08",
            BriefingKind.DAILY,
            _payload(stamp_city="oslo"),
            edition=_EDITION,
        )
        for owner, date in [
            (user_id, "2026-08-05"),
            (user_id, "2026-08-06"),
            (user_id, "2026-08-07"),
            (user_id, "2026-08-09"),
            ("other-user", "2026-08-04"),
        ]:
            await _deliver(repo, owner, date, BriefingKind.DAILY, ["inapp"])

        stamped = await repo.list_stamped(user_id)

        assert [b.id for b in stamped] == [earlier.id, later.id]

    async def test_list_recent_honours_the_limit_and_the_kind(self, repo, raw_collection):
        user_id = "u-recent-kind"
        oldest = await _upsert(
            repo, user_id, "2026-08-05", BriefingKind.DAILY, _payload(), edition=_EDITION
        )
        newest_daily = await _upsert(
            repo, user_id, "2026-08-06", BriefingKind.DAILY, _payload(), edition=_EDITION
        )
        weekly = await _upsert(
            repo,
            user_id,
            "2026-08-07",
            BriefingKind.WEEKLY,
            _payload(mood="weekly"),
            edition=_EDITION,
        )
        # Writes inside one millisecond tie on created_at; pin a strict order.
        for hour, brief in enumerate([oldest, newest_daily, weekly]):
            await raw_collection.update_one(
                {"_id": brief.id}, {"$set": {"created_at": datetime(2026, 8, 7, hour, tzinfo=UTC)}}
            )

        assert [b.id for b in await repo.list_recent(user_id, limit=1)] == [weekly.id]
        dailies = await repo.list_recent(user_id, limit=1, kind=BriefingKind.DAILY)
        assert [b.id for b in dailies] == [newest_daily.id]

    async def test_has_daily_briefing(self, repo):
        user_id = "u-has-daily"
        assert await repo.has_daily_briefing(user_id) is False
        await _upsert(
            repo, user_id, "2026-08-06", BriefingKind.WEEKLY, _payload(), edition=_EDITION
        )
        assert await repo.has_daily_briefing(user_id) is False  # weekly doesn't count
        await _upsert(repo, user_id, "2026-08-06", BriefingKind.DAILY, _payload(), edition=_EDITION)
        assert await repo.has_daily_briefing(user_id) is True

    async def test_was_delivered_needs_its_delivery_completed_on_that_date_and_kind(self, repo):
        user_id = "u-delivered"
        assert await repo.was_delivered(user_id, "2026-08-06", BriefingKind.DAILY) is False
        stored = await _upsert(
            repo, user_id, "2026-08-06", BriefingKind.DAILY, _payload(), edition=_EDITION
        )
        # Stored, then delivered part-way: a retry still finishes it.
        assert await repo.was_delivered(user_id, "2026-08-06", BriefingKind.DAILY) is False
        await repo.record_step(user_id, stored.id, DeliveryStep.NOTIFICATION, ["inapp"])
        assert await repo.was_delivered(user_id, "2026-08-06", BriefingKind.DAILY) is False

        await repo.complete_delivery(user_id, stored.id)

        assert await repo.was_delivered(user_id, "2026-08-06", BriefingKind.DAILY) is True
        assert await repo.was_delivered(user_id, "2026-08-07", BriefingKind.DAILY) is False
        assert await repo.was_delivered(user_id, "2026-08-06", BriefingKind.WEEKLY) is False


class TestBriefingsMarkOpened:
    async def test_mark_opened_is_idempotent(self, repo):
        user_id = "u-opened"
        briefing = await _upsert(
            repo, user_id, "2026-08-06", BriefingKind.DAILY, _payload(), edition=_EDITION
        )
        with local_timezone("Asia/Kolkata"):
            first = await repo.mark_opened(user_id, briefing.id)
        assert first is not None and _is_now(first.opened_at)
        second = await repo.mark_opened(user_id, briefing.id)
        assert second is None  # already opened — no flip, no overwrite

    async def test_mark_opened_missing_or_wrong_user_returns_none(self, repo):
        user_id = "u-owner"
        briefing = await _upsert(
            repo, user_id, "2026-08-06", BriefingKind.DAILY, _payload(), edition=_EDITION
        )
        assert await repo.mark_opened("attacker", briefing.id) is None
        assert await repo.mark_opened(user_id, "brief_missing") is None


class TestBriefingsDeliverySteps:
    async def test_each_step_and_each_channel_it_reached_is_recorded_once(self, repo):
        user_id = "u-channels"
        stored = await _upsert(
            repo, user_id, "2026-08-06", BriefingKind.DAILY, _payload(), edition=_EDITION
        )
        await repo.record_step(user_id, stored.id, DeliveryStep.NOTIFICATION, ["inapp", "email"])
        await repo.record_step(user_id, stored.id, DeliveryStep.CHAT, ["telegram"])
        await repo.record_step(user_id, stored.id, DeliveryStep.CHAT, ["telegram"])
        await repo.record_step("attacker", stored.id, DeliveryStep.CONVERSATION, ["inapp"])

        fetched = await repo.get(stored.id, user_id=user_id)

        assert fetched is not None and fetched.delivery is not None
        assert fetched.delivered_channels == ["inapp", "email", "telegram"]
        assert fetched.delivery.done == [DeliveryStep.NOTIFICATION, DeliveryStep.CHAT]
        assert (fetched.delivery.held_ids, fetched.delivery.completed_at) == (["h1"], None)

    async def test_a_rerun_before_any_step_replans_its_delivery(self, repo):
        stored = await _upsert(
            repo, "u-replan", "2026-08-06", BriefingKind.DAILY, _payload(), edition=_EDITION
        )
        replanned = await repo.upsert_briefing(
            stored.model_copy(update={"delivery": _PLAN.model_copy(update={"held_ids": ["h2"]})})
        )

        assert replanned.delivery is not None and replanned.delivery.held_ids == ["h2"]


class _CachedBriefingsRepository(BriefingsRepository):
    cache_policy = CachePolicy(prefix="contract:briefings")


class TestWritesUnderACachePolicy:
    """Every write names the owner's scope, so switching a cache policy on never serves a stale get()."""

    @pytest.fixture
    def cached_repo(self, raw_collection) -> _CachedBriefingsRepository:
        return _CachedBriefingsRepository()

    async def _cached_brief(self, cached_repo: _CachedBriefingsRepository, user_id: str):
        stored = await _upsert(
            cached_repo,
            user_id,
            "2026-08-06",
            BriefingKind.DAILY,
            _payload(),
            edition=_EDITION,
        )
        assert await cached_repo.get(stored.id, user_id=user_id) == stored
        return stored

    async def test_a_rerun_refreshes_the_cached_brief(self, cached_repo):
        stored = await self._cached_brief(cached_repo, "u-cache-rerun")

        await _upsert(
            cached_repo,
            "u-cache-rerun",
            "2026-08-06",
            BriefingKind.DAILY,
            _payload(headline="Busy day"),
            edition=_EDITION,
        )

        fetched = await cached_repo.get(stored.id, user_id="u-cache-rerun")
        assert fetched is not None and fetched.payload.headline == "Busy day"

    async def test_recording_delivery_refreshes_the_cached_brief(self, cached_repo):
        stored = await self._cached_brief(cached_repo, "u-cache-channels")

        await _deliver(cached_repo, "u-cache-channels", "2026-08-06", BriefingKind.DAILY, ["inapp"])

        fetched = await cached_repo.get(stored.id, user_id="u-cache-channels")
        assert fetched is not None and fetched.delivered_channels == ["inapp"]

    async def test_opening_refreshes_the_cached_brief(self, cached_repo):
        stored = await self._cached_brief(cached_repo, "u-cache-open")

        await cached_repo.mark_opened("u-cache-open", stored.id)

        fetched = await cached_repo.get(stored.id, user_id="u-cache-open")
        assert fetched is not None and fetched.opened_at is not None
