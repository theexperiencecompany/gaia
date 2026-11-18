"""The dormancy-to-wind_down rename over real Mongo: a row an earlier migration wrote reads back whole."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
import uuid

from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase
import pytest

from app.db.repositories.briefing_state import briefing_state_repository
from app.models.briefing_state_models import BriefingWindDown
from scripts import rename_brief_wind_down as migration
from tests.factories import make_user_id

_SINCE = datetime(2026, 11, 1, 2, 30, tzinfo=UTC)
_ASKED = datetime(2026, 11, 10, 2, 30, tzinfo=UTC)


@pytest.fixture
async def states(
    mongo_db: AsyncIOMotorDatabase, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncIOMotorCollection]:
    """Point the migration and the repository at a fresh briefing_state collection."""
    collection = mongo_db[f"briefing_state_{uuid.uuid4().hex}"]
    monkeypatch.setattr(migration, "briefing_state_collection", collection)
    monkeypatch.setattr("app.db.repositories.base.get_async_collection", lambda _name: collection)
    yield collection
    await collection.drop()


async def test_a_row_written_as_dormancy_reads_back_as_its_wind_down(
    states: AsyncIOMotorCollection,
) -> None:
    user_id = make_user_id()
    await states.insert_one(
        {
            "user_id": user_id,
            "dormancy": {
                "idle_days": 3,
                "date": "2026-11-01",
                "dormant_since": _SINCE,
                "goal_asked_at": _ASKED,
            },
        }
    )

    assert await migration.migrate(apply=True) == 1

    assert (await briefing_state_repository.state_for(user_id)).wind_down == BriefingWindDown(
        idle_days=3, date="2026-11-01", wound_down_since=_SINCE, goal_asked_at=_ASKED
    )
    assert await migration.migrate(apply=True) == 0


async def test_a_dry_run_renames_nothing(states: AsyncIOMotorCollection) -> None:
    await states.insert_one({"user_id": make_user_id(), "dormancy": {"idle_days": 1}})

    assert await migration.migrate(apply=False) == 1

    assert await states.count_documents({"dormancy": {"$exists": True}}) == 1
