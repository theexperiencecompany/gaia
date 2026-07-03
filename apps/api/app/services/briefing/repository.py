"""Persistence for briefings and awards.

Single access point for the ``briefings`` and ``awards`` collections so the
service, endpoints, and rollout share one set of queries. All reads/writes key
off the unique indexes (``user_id+date+kind``, ``user_id+key``).
"""

from datetime import UTC, datetime

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.constants.briefing import BRIEFING_KIND_DAILY
from app.db.mongodb.collections import awards_collection, briefings_collection
from app.models.briefing_models import BriefingKind, BriefingModel, BriefingPayload


def _to_model(doc: dict) -> BriefingModel:
    return BriefingModel.model_validate(doc)


async def upsert_briefing(
    user_id: str, date: str, kind: BriefingKind, payload: BriefingPayload
) -> BriefingModel:
    """Store the payload (one per user/date/kind), preserving ``opened_at``.

    Persisted BEFORE delivery so the dashboard never misses a brief that was
    sent to a channel. Returns the stored document.
    """
    model = BriefingModel(user_id=user_id, date=date, kind=kind, payload=payload)
    doc = await briefings_collection.find_one_and_update(
        {"user_id": user_id, "date": date, "kind": kind},
        {
            "$set": {"payload": payload.model_dump()},
            "$setOnInsert": {
                "_id": model.id,
                "id": model.id,
                "created_at": model.created_at,
                "delivered_channels": [],
                "opened_at": None,
            },
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return _to_model(doc)


async def set_delivered_channels(
    user_id: str, date: str, kind: BriefingKind, channels: list[str]
) -> None:
    await briefings_collection.update_one(
        {"user_id": user_id, "date": date, "kind": kind},
        {"$set": {"delivered_channels": channels}},
    )


async def get_latest_briefing(
    user_id: str, kind: BriefingKind = BRIEFING_KIND_DAILY
) -> BriefingModel | None:
    doc = await briefings_collection.find_one(
        {"user_id": user_id, "kind": kind}, sort=[("created_at", -1)]
    )
    return _to_model(doc) if doc else None


async def list_briefings(user_id: str, limit: int) -> list[BriefingModel]:
    cursor = briefings_collection.find({"user_id": user_id}).sort("created_at", -1).limit(limit)
    return [_to_model(doc) async for doc in cursor]


async def mark_opened(user_id: str, briefing_id: str) -> BriefingModel | None:
    """Stamp ``opened_at`` once (idempotent). Returns the briefing if it flipped."""
    doc = await briefings_collection.find_one_and_update(
        {"id": briefing_id, "user_id": user_id, "opened_at": None},
        {"$set": {"opened_at": datetime.now(UTC)}},
        return_document=ReturnDocument.AFTER,
    )
    return _to_model(doc) if doc else None


async def has_daily_briefing(user_id: str) -> bool:
    doc = await briefings_collection.find_one(
        {"user_id": user_id, "kind": BRIEFING_KIND_DAILY}, {"_id": 1}
    )
    return doc is not None


async def get_awarded_keys(user_id: str) -> set[str]:
    cursor = awards_collection.find({"user_id": user_id}, {"key": 1})
    return {doc["key"] async for doc in cursor}


async def award_badge(user_id: str, key: str) -> bool:
    """Insert a badge once. Returns True if newly earned, False if already held."""
    try:
        await awards_collection.insert_one(
            {"user_id": user_id, "key": key, "earned_at": datetime.now(UTC)}
        )
        return True
    except DuplicateKeyError:
        return False
