"""Account erasure against real Mongo: the user's briefing_state row is inventoried, then deleted."""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import MongoClient
from pymongo.database import Database
import pytest

from app.db.repositories.briefing_state import briefing_state_repository
from app.models.brief_settings_models import BriefingSchedule
from app.models.briefing_state_models import BriefingStateUpdate
from app.scripts.delete_user_account import _delete_mongo_data, _Footprint, _mongo_inventory
from tests.helpers import worker_mongo_db_name

_EMAIL = "erased@example.com"


@pytest.fixture
def sync_db(mongodb_url: str) -> Iterator[Database]:
    """Open the erasure script's own synchronous handle on the database the repositories write to."""
    client: MongoClient = MongoClient(mongodb_url, serverSelectionTimeoutMS=5000)
    yield client[worker_mongo_db_name()]
    client.close()


def _footprint(db: Database, uid: str) -> _Footprint:
    return _Footprint(
        db=db,
        pg=MagicMock(),
        chroma=MagicMock(),
        redis_client=MagicMock(),
        composio=MagicMock(),
        workos=MagicMock(),
        uid=uid,
        email=_EMAIL,
        platform_links={},
        conversation_ids=[],
        composio_accounts=[],
        sandbox_ids=[],
        workos_users=[],
        chroma_counts={},
        redis_keys=[],
        jfs_path=Path("/nonexistent"),
        link_snapshots=[],
        edition_keys=[],
    )


async def test_erasure_counts_and_deletes_the_users_briefing_state(
    mongo_db: AsyncIOMotorDatabase, sync_db: Database
) -> None:
    uid, kept = str(ObjectId()), str(ObjectId())
    for user_id in (uid, kept):
        await briefing_state_repository.upsert(
            user_id, BriefingStateUpdate(schedule=BriefingSchedule(hour=6))
        )
    await briefing_state_repository.mark_day_zero_hello_sent(uid, "telegram")

    assert _mongo_inventory(sync_db, uid, _EMAIL)["briefing_state"] == 1
    _delete_mongo_data(_footprint(sync_db, uid))

    assert "briefing_state" not in _mongo_inventory(sync_db, uid, _EMAIL)
    assert await briefing_state_repository.get(uid) is None
    assert await briefing_state_repository.get(kept) is not None
    await mongo_db["briefing_state"].delete_many({"user_id": kept})
