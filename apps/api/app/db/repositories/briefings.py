"""Repository for the briefings collection.

User-scoped: every operation is keyed by user_id plus a date/kind or a briefing id.
Identity is the string business key id (persisted as Mongo _id, uses_object_id=False);
every write after the first insert is a targeted $set, never a replace.

No CachePolicy: the hot read (get_latest) is cheap, and list/range queries cannot
be served by a single-id entity cache.
"""

from datetime import UTC, datetime
from typing import ClassVar

from pydantic import BaseModel, Field

from app.constants.briefing import (
    BriefForm,
    BriefingKind,
)
from app.db.repositories.base import UserScopedRepository
from app.db.repositories.cache import CachePolicy
from app.models.brief_document_models import (
    BriefCardRecord,
    BriefingModel,
    BriefingUpdate,
    DeliveryStep,
    new_briefing_id,
)
from app.utils.errors import AppError


class _BriefingOwner(BaseModel):
    user_id: str


class ExpiredBriefing(BaseModel):
    """A brief past its retention: whose it is, and the edition key its image is stored under."""

    id: str = Field(alias="_id")
    user_id: str
    edition_key: str | None = None


# A brief counts as delivered once every step of its delivery is done; one whose run died
# mid-delivery is finished by the next run, never regenerated or dropped.
_DELIVERED: dict[str, object] = {"delivery.completed_at": {"$ne": None}}
# The stored fields a BriefCardRecord reads, so a card never loads the whole payload.
_CARD_FIELDS: dict[str, object] = {
    "_id": 0,
    "id": "$_id",
    "date": 1,
    "kind": 1,
    "edition": 1,
    "payload.headline": 1,
    "payload.template_family": 1,
    "payload.stamp_city": 1,
    "payload.sections.items.kind": 1,
}


class BriefingsRepository(UserScopedRepository[BriefingModel, BriefingUpdate]):
    collection_name = "briefings"
    document_model = BriefingModel
    update_model = BriefingUpdate
    uses_object_id = False
    cache_policy: ClassVar[CachePolicy | None] = None

    # ------------------------------------------------------------------ reads

    async def get_before_date(
        self, user_id: str, *, kind: BriefingKind, before_date: str
    ) -> BriefingModel | None:
        """Return the latest briefing of kind strictly before before_date.

        before_date is YYYY-MM-DD, compared lexically with $lt.
        """
        return await self._find_one(
            {"user_id": user_id, "kind": kind, "date": {"$lt": before_date}},
            sort=[("date", -1)],
        )

    async def list_recent(
        self,
        user_id: str,
        *,
        limit: int,
        kind: BriefingKind | None = None,
        editions_only: bool = False,
    ) -> list[BriefingModel]:
        """Return briefings newest brief date first, a weekly ahead of the daily on its day.

        Ordered by date, not write time: a backfilled brief is written after newer days.
        kind=None reads every kind; the winback lookback passes kind=daily so a weekly
        digest never breaks a daily unacknowledged-streak count.
        """
        query: dict[str, object] = {"user_id": user_id}
        if kind is not None:
            query["kind"] = kind
        if editions_only:
            query["payload.form"] = {"$ne": BriefForm.QUIET_NOTE.value}
        return await self._find(query, sort=[("date", -1), ("kind", -1)], limit=limit)

    async def get_card(self, briefing_id: str, user_id: str) -> BriefCardRecord | None:
        """Return the user's brief read for its card alone, or None when they have no such brief."""
        return await self._find_one_projected(
            {"_id": briefing_id, "user_id": user_id}, _CARD_FIELDS, BriefCardRecord
        )

    async def list_cards(
        self, user_id: str, *, limit: int, before: BriefCardRecord | None = None
    ) -> list[BriefCardRecord]:
        """Return the user's editions as their cards, ordered as list_recent orders them.

        A quiet note has no edition, so it is never listed. before starts the list right
        after that brief, the archive's next page.
        """
        query: dict[str, object] = {
            "user_id": user_id,
            "payload.form": {"$ne": BriefForm.QUIET_NOTE.value},
        }
        if before is not None:
            # (date, kind) is unique per user, so this resumes the sort exactly after it
            query["$or"] = [
                {"date": {"$lt": before.date}},
                {"date": before.date, "kind": {"$lt": before.kind}},
            ]
        return await self._aggregate(
            [
                {"$match": query},
                {"$sort": {"date": -1, "kind": -1}},
                {"$limit": limit},
                {"$project": _CARD_FIELDS},
            ],
            BriefCardRecord,
        )

    async def list_stamped(self, user_id: str) -> list[BriefCardRecord]:
        """Return each Air Mail city's first delivered brief as its card's fields, oldest first.

        A city counts once, on the day its stamp first arrived.
        """
        return await self._aggregate(
            [
                {"$match": {"user_id": user_id, "payload.stamp_city": {"$ne": None}, **_DELIVERED}},
                {"$sort": {"date": 1}},
                {"$project": _CARD_FIELDS},
                {"$group": {"_id": "$payload.stamp_city", "first": {"$first": "$$ROOT"}}},
                {"$replaceRoot": {"newRoot": "$first"}},
                {"$sort": {"date": 1}},
            ],
            BriefCardRecord,
        )

    async def owner_of_edition(self, key: str) -> str | None:
        """Return who owns the brief an edition key belongs to, for a caller holding its signed URL."""
        owner = await self._find_one_projected(
            {"edition.key": key}, {"user_id": 1, "_id": 0}, _BriefingOwner
        )
        return owner.user_id if owner is not None else None

    async def list_expired(self, created_before: datetime, limit: int) -> list[ExpiredBriefing]:
        """Return up to limit briefs written before created_before, oldest first, for the retention sweep."""
        return await self._aggregate(
            [
                {"$match": {"created_at": {"$lt": created_before}}},
                {"$sort": {"created_at": 1}},
                {"$limit": limit},
                {"$project": {"user_id": 1, "edition_key": "$edition.key"}},
            ],
            ExpiredBriefing,
        )

    async def has_daily_briefing(self, user_id: str) -> bool:
        """Whether the user has ever received a daily briefing (first-briefing gate)."""
        return await self._count({"user_id": user_id, "kind": BriefingKind.DAILY}) > 0

    async def was_delivered(self, user_id: str, date: str, kind: BriefingKind) -> bool:
        """Whether the (user, date, kind) brief's delivery completed.

        A brief whose delivery never completed does not count, so a retry can still finish it.
        """
        return await self._count({"user_id": user_id, "date": date, "kind": kind, **_DELIVERED}) > 0

    async def find_for_date(
        self, user_id: str, date: str, kind: BriefingKind
    ) -> BriefingModel | None:
        """Return the (user, date, kind) brief, delivered or not."""
        return await self._find_one({"user_id": user_id, "date": date, "kind": kind})

    async def briefing_id_for(self, user_id: str, date: str, kind: BriefingKind) -> str:
        """Return the id the (user, date, kind) brief has, or the fresh one it will be stored under."""
        existing = await self.find_for_date(user_id, date, kind)
        return existing.id if existing else new_briefing_id()

    # ----------------------------------------------------------------- writes

    async def upsert_briefing(self, brief: BriefingModel) -> BriefingModel:
        """Store the brief's payload, link, edition and delivery plan (one per user/date/kind) under its id.

        Preserves opened_at and delivered_channels across a same-day rerun. Persisted
        BEFORE delivery so the dashboard never misses a brief that reached a channel.
        A racing run that stored the brief under another id first makes this a duplicate
        of the unique (user, date, kind) key, so the write fails instead of overwriting it.
        """
        doc = await self._apply_raw_update(
            {"_id": brief.id, "user_id": brief.user_id, "date": brief.date, "kind": brief.kind},
            {
                "$set": {
                    "payload": brief.payload.model_dump(),
                    "link": brief.link,
                    "edition": brief.edition.model_dump() if brief.edition else None,
                    "delivery": brief.delivery.model_dump() if brief.delivery else None,
                },
                "$setOnInsert": {
                    "created_at": datetime.now(UTC),
                    "delivered_channels": [],
                    "opened_at": None,
                },
            },
            scope=brief.user_id,
            upsert=True,
        )
        if doc is None:
            # pragma: no mutate below — unreachable, so its message cannot be observed:
            # find_one_and_update(upsert=True, AFTER) always yields a document.
            raise AppError(message="briefing upsert returned no document")  # pragma: no mutate
        return doc

    async def record_step(
        self, user_id: str, briefing_id: str, step: DeliveryStep, reached: list[str]
    ) -> None:
        """Record one delivery step done, and the channels it reached the user on."""
        await self._apply_raw_update(
            {"_id": briefing_id, "user_id": user_id},
            {
                "$addToSet": {
                    "delivery.done": step.value,
                    "delivered_channels": {"$each": reached},
                }
            },
            scope=user_id,
        )

    async def complete_delivery(self, user_id: str, briefing_id: str) -> None:
        """Mark the brief's delivery complete: every step is done and its held results consumed."""
        await self._apply_raw_update(
            {"_id": briefing_id, "user_id": user_id},
            {"$set": {"delivery.completed_at": datetime.now(UTC)}},
            scope=user_id,
        )

    async def mark_opened(self, user_id: str, briefing_id: str) -> BriefingModel | None:
        """Stamp opened_at once (idempotent).

        Return None when already opened or the briefing does not exist.
        """
        return await self._apply_update(
            briefing_id,
            user_id,
            {"user_id": user_id, "opened_at": None},
            BriefingUpdate(opened_at=datetime.now(UTC)),
        )


briefing_repository = BriefingsRepository()
