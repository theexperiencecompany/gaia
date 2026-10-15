"""Repository for the briefings collection.

User-scoped: every operation is keyed by user_id plus a date/kind or a briefing id.
Identity is the string business key id (persisted as Mongo _id, uses_object_id=False);
every write after the first insert is a targeted $set, never a replace.

No CachePolicy: the hot read (get_latest) is cheap, and list/range queries cannot
be served by a single-id entity cache.
"""

from datetime import UTC, datetime
import uuid

from app.constants.briefing import BRIEFING_KIND_DAILY
from app.db.repositories.base import UserScopedRepository
from app.models.briefing_models import BriefingKind, BriefingModel, BriefingPayload, BriefingUpdate
from app.utils.errors import AppError

# A brief counts as delivered once it reached at least one channel; one stored but
# delivered nowhere (its run failed mid-delivery) was never received.
_DELIVERED: dict[str, object] = {"delivered_channels.0": {"$exists": True}}


class BriefingsRepository(UserScopedRepository[BriefingModel, BriefingUpdate]):
    collection_name = "briefings"
    document_model = BriefingModel
    update_model = BriefingUpdate
    uses_object_id = False
    cache_policy = None

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
        self, user_id: str, *, limit: int, kind: BriefingKind | None = None
    ) -> list[BriefingModel]:
        """Return briefings newest first.

        kind=None reads every kind; the winback lookback passes kind=daily so a weekly
        digest never breaks a daily unacknowledged-streak count.
        """
        query: dict[str, object] = {"user_id": user_id}
        if kind is not None:
            query["kind"] = kind
        return await self._find(query, sort=[("created_at", -1)], limit=limit)

    async def list_stamped(self, user_id: str) -> list[BriefingModel]:
        """Return the delivered briefs that carried an Air Mail city stamp, oldest first."""
        return await self._find(
            {"user_id": user_id, "payload.stamp_city": {"$ne": None}, **_DELIVERED},
            sort=[("date", 1)],
        )

    async def has_daily_briefing(self, user_id: str) -> bool:
        """Whether the user has ever received a daily briefing (first-briefing gate)."""
        return await self._count({"user_id": user_id, "kind": BRIEFING_KIND_DAILY}) > 0

    async def was_delivered(self, user_id: str, date: str, kind: BriefingKind) -> bool:
        """Whether the (user, date, kind) brief already reached at least one channel.

        An undelivered brief does not count, so a retry can still send it.
        """
        return await self._count({"user_id": user_id, "date": date, "kind": kind, **_DELIVERED}) > 0

    # ----------------------------------------------------------------- writes

    async def upsert_briefing(
        self,
        user_id: str,
        date: str,
        kind: BriefingKind,
        payload: BriefingPayload,
        *,
        edition_image_url: str | None,
    ) -> BriefingModel:
        """Store the payload (one per user/date/kind).

        Preserves opened_at and delivered_channels across a same-day rerun. Persisted
        BEFORE delivery so the dashboard never misses a brief that reached a channel.
        """
        doc = await self._apply_raw_update(
            {"user_id": user_id, "date": date, "kind": kind},
            {
                "$set": {"payload": payload.model_dump(), "edition_image_url": edition_image_url},
                "$setOnInsert": {
                    "_id": f"brief_{uuid.uuid4().hex[:12]}",
                    "created_at": datetime.now(UTC),
                    "delivered_channels": [],
                    "opened_at": None,
                },
            },
            scope=user_id,
            upsert=True,
        )
        if doc is None:
            # pragma: no mutate below — unreachable, so its message cannot be observed:
            # find_one_and_update(upsert=True, AFTER) always yields a document.
            raise AppError(message="briefing upsert returned no document")  # pragma: no mutate
        return doc

    async def set_delivered_channels(
        self, user_id: str, date: str, kind: BriefingKind, channels: list[str]
    ) -> None:
        await self._apply_raw_update(
            {"user_id": user_id, "date": date, "kind": kind},
            {"$set": {"delivered_channels": channels}},
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
