"""The briefing state expand and contract migrations over real Mongo: user-document fields read back from briefing_state."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
import uuid

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase
from pydantic import ValidationError
import pytest

from app.constants.briefing import BriefingBag, BriefingFrequency, EditionChoice
from app.db.mongodb import indexes
from app.db.repositories.briefing_state import briefing_state_repository
from app.models.brief_settings_models import BriefingSchedule
from app.models.briefing_state_models import (
    BriefingBootstrap,
    BriefingStateDocument,
    BriefingWindDown,
    DayZeroHello,
    ShuffleBag,
)
from scripts import migrate_briefing_state as migration

_SINCE = datetime(2026, 11, 1, 2, 30, tzinfo=UTC)
_ASKED = datetime(2026, 11, 10, 2, 30, tzinfo=UTC)
_FAMILY_BAG = {"order": ["memo", "swiss"], "index": 1}
_CITY_BAG = {"order": ["lisbon", "osaka"], "index": 0}


@dataclass
class _Store:
    users: AsyncIOMotorCollection
    states: AsyncIOMotorCollection


@pytest.fixture
async def store(
    mongo_db: AsyncIOMotorDatabase, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[_Store]:
    """Point the migration and the repository at fresh users and briefing_state collections."""
    suffix = uuid.uuid4().hex
    s = _Store(users=mongo_db[f"users_{suffix}"], states=mongo_db[f"briefing_state_{suffix}"])
    monkeypatch.setattr(migration, "users_collection", s.users)
    monkeypatch.setattr(migration, "briefing_state_collection", s.states)
    monkeypatch.setattr("app.db.repositories.base.get_async_collection", lambda _name: s.states)
    monkeypatch.setattr(indexes, "get_async_collection", lambda _name: s.states)
    await indexes.create_briefing_state_indexes()
    yield s
    await s.users.drop()
    await s.states.drop()


def _old_user(**fields: object) -> dict[str, object]:
    return {"_id": ObjectId(), "email": "ada@example.com", "timezone": "Asia/Kolkata", **fields}


_EVERY_FIELD: dict[str, object] = {
    "briefing_schedule": {"frequency": "weekdays", "hour": 7},
    "briefing_editions": {"menu": "off", "swiss": "favourite"},
    "briefing_bootstrap": {"pending": True, "since": _SINCE},
    "briefing_dormancy": {
        "idle_days": 2,
        "date": "2026-11-12",
        "dormant_since": _SINCE,
        "goal_asked_at": _ASKED,
    },
    "day_zero_hello": {"sent_at": _SINCE, "platform": "telegram"},
    "briefing_shuffle_bags": {"edition_family": _FAMILY_BAG, "stamp_city": _CITY_BAG},
}


async def test_a_dry_run_counts_the_users_and_writes_nothing(store: _Store) -> None:
    await store.users.insert_many([_old_user(**_EVERY_FIELD), _old_user()])

    assert await migration.migrate(apply=False) == 1

    assert await store.states.count_documents({}) == 0
    assert await store.users.count_documents({"briefing_schedule": {"$exists": True}}) == 1


async def test_every_field_is_copied_to_the_users_row_and_stays_on_the_user_document(
    store: _Store,
) -> None:
    user = _old_user(**_EVERY_FIELD)
    await store.users.insert_one(user)

    assert await migration.migrate(apply=True) == 1

    assert await briefing_state_repository.state_for(str(user["_id"])) == BriefingStateDocument(
        user_id=str(user["_id"]),
        schedule=BriefingSchedule(frequency=BriefingFrequency.WEEKDAYS, hour=7),
        editions={"menu": EditionChoice.OFF, "swiss": EditionChoice.FAVOURITE},
        bootstrap=BriefingBootstrap(pending=True, since=_SINCE),
        wind_down=BriefingWindDown(
            idle_days=2, date="2026-11-12", wound_down_since=_SINCE, goal_asked_at=_ASKED
        ),
        day_zero_hello=DayZeroHello(sent_at=_SINCE, platform="telegram"),
        shuffle_bags={
            BriefingBag.EDITION_FAMILY: ShuffleBag.model_validate(_FAMILY_BAG),
            BriefingBag.STAMP_CITY: ShuffleBag.model_validate(_CITY_BAG),
        },
    )
    assert await store.users.find_one({"_id": user["_id"]}) == user


async def test_a_second_apply_copies_nothing(store: _Store) -> None:
    user = _old_user(**_EVERY_FIELD)
    await store.users.insert_one(user)
    await migration.migrate(apply=True)
    moved = await store.states.find_one({"user_id": str(user["_id"])}, {"_id": 0})

    assert await migration.migrate(apply=True) == 0

    assert await store.states.count_documents({}) == 1
    assert await store.states.find_one({"user_id": str(user["_id"])}, {"_id": 0}) == moved


@pytest.mark.regression
async def test_what_the_new_code_already_wrote_wins_key_by_key(store: _Store) -> None:
    """The worker runs the step beside new code, which may have written the row first."""
    user = _old_user(**_EVERY_FIELD)
    user_id = str(user["_id"])
    await store.users.insert_one(user)
    fresh_bag = ShuffleBag(order=["postal"], index=0)
    await briefing_state_repository.set_bag(user_id, BriefingBag.EDITION_FAMILY, fresh_bag)
    await briefing_state_repository.set_idle_day(user_id, idle_days=0, date_str="2026-11-18")

    await migration.migrate(apply=True)

    state = await briefing_state_repository.state_for(user_id)
    assert state.shuffle_bags == {
        BriefingBag.EDITION_FAMILY: fresh_bag,
        BriefingBag.STAMP_CITY: ShuffleBag.model_validate(_CITY_BAG),
    }
    assert state.wind_down == BriefingWindDown(
        idle_days=0, date="2026-11-18", wound_down_since=_SINCE, goal_asked_at=_ASKED
    )
    assert state.schedule == BriefingSchedule(frequency=BriefingFrequency.WEEKDAYS, hour=7)


async def test_a_malformed_value_stops_the_run_before_it_writes(store: _Store) -> None:
    user = _old_user(briefing_shuffle_bags={"no_such_bag": _FAMILY_BAG})
    await store.users.insert_one(user)

    with pytest.raises(ValidationError):
        await migration.migrate(apply=True)

    assert await store.states.count_documents({}) == 0
    assert await store.users.count_documents({"briefing_shuffle_bags": {"$exists": True}}) == 1


async def test_contract_copies_what_the_previous_release_wrote_since_then_drops_the_old_fields(
    store: _Store,
) -> None:
    user = _old_user(briefing_schedule={"frequency": "weekdays", "hour": 7})
    user_id = str(user["_id"])
    await store.users.insert_one(user)
    await migration.migrate(apply=True)
    hello = {"sent_at": _SINCE, "platform": "telegram"}
    await store.users.update_one({"_id": user["_id"]}, {"$set": {"day_zero_hello": hello}})

    assert await migration.contract(apply=False) == 1
    assert await store.users.count_documents({"day_zero_hello": {"$exists": True}}) == 1

    assert await migration.contract(apply=True) == 1

    state = await briefing_state_repository.state_for(user_id)
    assert state.schedule == BriefingSchedule(frequency=BriefingFrequency.WEEKDAYS, hour=7)
    assert state.day_zero_hello == DayZeroHello(sent_at=_SINCE, platform="telegram")
    left = await store.users.find_one({"_id": user["_id"]})
    assert left is not None
    assert set(left) == {"_id", "email", "timezone"}
    assert await migration.contract(apply=True) == 0
