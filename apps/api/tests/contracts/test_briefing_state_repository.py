"""Contract tests for BriefingStateRepository against real Mongo: one row per user, every write an upsert."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo.errors import DuplicateKeyError
import pytest

from app.constants.briefing import BriefingBag, BriefingFrequency, EditionChoice
from app.db.mongodb import indexes
from app.db.repositories.briefing_state import BriefingStateRepository
from app.models.brief_settings_models import BriefingSchedule
from app.models.briefing_state_models import (
    BriefingStateDocument,
    BriefingStateUpdate,
    BriefingWindDown,
    ShuffleBag,
)

USER = "64f1c0ffee0000000000aaa1"
OTHER = "64f1c0ffee0000000000aaa2"


@pytest.fixture
async def repo(
    raw_collection: AsyncIOMotorCollection, monkeypatch: pytest.MonkeyPatch
) -> BriefingStateRepository:
    """Return the repository over a collection carrying the unique user_id index production builds."""
    monkeypatch.setattr(indexes, "get_async_collection", lambda _name: raw_collection)
    await indexes.create_briefing_state_indexes()
    return BriefingStateRepository()


def _stamped_now(stamp: datetime | None, before: datetime) -> bool:
    return stamp is not None and before <= stamp <= datetime.now(UTC)


def _just_before() -> datetime:
    return datetime.now(UTC) - timedelta(milliseconds=1)  # BSON stores milliseconds


class TestAUserWithNoRow:
    async def test_reads_as_every_default_and_writes_nothing(
        self, repo: BriefingStateRepository, raw_collection: AsyncIOMotorCollection
    ) -> None:
        assert await repo.get(USER) is None
        assert await repo.state_for(USER) == BriefingStateDocument(user_id=USER)
        assert await raw_collection.count_documents({}) == 0

    async def test_clearing_what_was_never_set_creates_no_row(
        self, repo: BriefingStateRepository, raw_collection: AsyncIOMotorCollection
    ) -> None:
        await repo.clear_wind_down(USER)

        assert await raw_collection.count_documents({}) == 0


class TestOneRowPerUser:
    async def test_every_write_lands_on_the_users_one_row(
        self, repo: BriefingStateRepository, raw_collection: AsyncIOMotorCollection
    ) -> None:
        schedule = BriefingSchedule(frequency=BriefingFrequency.WEEKDAYS, hour=7)
        bag = ShuffleBag(order=["memo", "swiss"], index=1)

        await repo.upsert(USER, BriefingStateUpdate(schedule=schedule))
        await repo.upsert(USER, BriefingStateUpdate(editions={"menu": EditionChoice.OFF}))
        await repo.set_bag(USER, BriefingBag.EDITION_FAMILY, bag)
        await repo.set_idle_day(USER, idle_days=1, date_str="2026-11-18")
        await repo.mark_day_zero_hello_sent(USER, "telegram")
        await repo.upsert(OTHER, BriefingStateUpdate(schedule=BriefingSchedule(hour=9)))

        assert await raw_collection.count_documents({"user_id": USER}) == 1
        assert await raw_collection.count_documents({}) == 2
        stored = await repo.state_for(USER)
        assert (stored.schedule, stored.editions, stored.shuffle_bags) == (
            schedule,
            {"menu": EditionChoice.OFF},
            {BriefingBag.EDITION_FAMILY: bag},
        )
        assert stored.wind_down == BriefingWindDown(idle_days=1, date="2026-11-18")
        assert stored.day_zero_hello is not None
        assert (await repo.state_for(OTHER)).schedule == BriefingSchedule(hour=9)

    async def test_a_second_row_for_a_user_is_refused_by_the_index(
        self, repo: BriefingStateRepository, raw_collection: AsyncIOMotorCollection
    ) -> None:
        await repo.upsert(USER, BriefingStateUpdate(schedule=BriefingSchedule()))

        with pytest.raises(DuplicateKeyError):
            await raw_collection.insert_one({"user_id": USER})


class TestSettings:
    async def test_edition_choices_replace_the_stored_ones_whole(
        self, repo: BriefingStateRepository
    ) -> None:
        await repo.upsert(USER, BriefingStateUpdate(editions={"menu": EditionChoice.OFF}))
        await repo.upsert(USER, BriefingStateUpdate(editions={"swiss": EditionChoice.FAVOURITE}))

        assert (await repo.state_for(USER)).editions == {"swiss": EditionChoice.FAVOURITE}

    async def test_a_new_schedule_leaves_the_editions_alone(
        self, repo: BriefingStateRepository
    ) -> None:
        await repo.upsert(USER, BriefingStateUpdate(editions={"menu": EditionChoice.OFF}))

        await repo.upsert(
            USER, BriefingStateUpdate(schedule=BriefingSchedule(frequency=BriefingFrequency.OFF))
        )

        stored = await repo.state_for(USER)
        assert stored.schedule.frequency is BriefingFrequency.OFF
        assert stored.editions == {"menu": EditionChoice.OFF}


class TestShuffleBags:
    async def test_each_bag_is_stored_and_read_on_its_own(
        self, repo: BriefingStateRepository
    ) -> None:
        family = ShuffleBag(order=["gaia", "explorer"], index=1)
        city = ShuffleBag(order=["Lisbon"], index=0)

        await repo.set_bag(USER, BriefingBag.EDITION_FAMILY, family)
        assert (await repo.state_for(USER)).shuffle_bags == {BriefingBag.EDITION_FAMILY: family}
        await repo.set_bag(USER, BriefingBag.STAMP_CITY, city)

        assert (await repo.state_for(USER)).shuffle_bags == {
            BriefingBag.EDITION_FAMILY: family,
            BriefingBag.STAMP_CITY: city,
        }


class TestTheIdleLadder:
    async def test_it_counts_goes_dormant_in_utc_and_clears_keeping_the_goal_question(
        self, repo: BriefingStateRepository, local_time_offset_from_utc: None
    ) -> None:
        await repo.set_idle_day(USER, idle_days=3, date_str="2026-10-14")
        counted = (await repo.state_for(USER)).wind_down
        assert counted == BriefingWindDown(idle_days=3, date="2026-10-14")

        before = _just_before()
        await repo.record_goal_question(USER)
        asked = (await repo.state_for(USER)).wind_down
        assert asked is not None and (asked.idle_days, asked.date) == (3, "2026-10-14")
        assert _stamped_now(asked.goal_asked_at, before)

        await repo.enter_wind_down(USER)
        dormant = (await repo.state_for(USER)).wind_down
        assert dormant is not None and (dormant.idle_days, dormant.date) == (3, "2026-10-14")
        assert _stamped_now(dormant.wound_down_since, before)

        await repo.clear_wind_down(USER)
        assert (await repo.state_for(USER)).wind_down == BriefingWindDown(
            goal_asked_at=asked.goal_asked_at
        )


class TestTheDayZeroHello:
    async def test_it_records_when_and_where_in_utc(
        self, repo: BriefingStateRepository, local_time_offset_from_utc: None
    ) -> None:
        before = _just_before()

        await repo.mark_day_zero_hello_sent(USER, "telegram")

        hello = (await repo.state_for(USER)).day_zero_hello
        assert hello is not None and hello.platform == "telegram"
        assert _stamped_now(hello.sent_at, before)
