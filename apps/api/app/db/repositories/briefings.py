"""Repository for the briefings collection.

User-scoped: every operation is keyed by ``user_id`` plus a date/kind or a
briefing id. Identity is the string business key ``id`` (persisted as Mongo's
``_id``, ``uses_object_id=False``) — the daily/weekly run mints it once on
insert and every subsequent write for that user/date/kind is a targeted
``$set``, never a replace.

No ``CachePolicy``: the dashboard's hot read (``get_latest``) is cheap and
infrequent relative to a per-request entity cache's upkeep, and several reads
(``list_recent``, ``get_before_date``) are list/range queries a single-id
entity cache can't serve anyway. Revisit only with evidence of a hot by-id
read path.
"""

from datetime import UTC, datetime
import uuid

from app.constants.briefing import BRIEFING_KIND_DAILY
from app.db.repositories.base import UserScopedRepository
from app.models.briefing_models import BriefingKind, BriefingModel, BriefingPayload, BriefingUpdate
from app.utils.errors import AppError


class BriefingsRepository(UserScopedRepository[BriefingModel, BriefingUpdate]):
    collection_name = "briefings"
    document_model = BriefingModel
    update_model = BriefingUpdate
    uses_object_id = False
    cache_policy = None

    # ------------------------------------------------------------------ reads

    async def get_latest(
        self, user_id: str, *, kind: BriefingKind = BRIEFING_KIND_DAILY
    ) -> BriefingModel | None:
        """The user's most recent briefing of ``kind`` — the dashboard read."""
        docs = await self._find(
            {"user_id": user_id, "kind": kind}, sort=[("created_at", -1)], limit=1
        )
        return docs[0] if docs else None

    async def get_before_date(
        self, user_id: str, *, kind: BriefingKind, before_date: str
    ) -> BriefingModel | None:
        """Latest briefing of ``kind`` strictly before ``before_date`` (``YYYY-MM-DD``,
        lexical ``$lt``) — the look-back comparison target, excluding a same-day
        rerun's own briefing."""
        docs = await self._find(
            {"user_id": user_id, "kind": kind, "date": {"$lt": before_date}},
            sort=[("date", -1)],
            limit=1,
        )
        return docs[0] if docs else None

    async def list_recent(
        self, user_id: str, *, limit: int, kind: BriefingKind | None = None
    ) -> list[BriefingModel]:
        """Newest-first briefings. The archive view reads every kind
        (``kind=None``); the winback lookback narrows to ``kind=daily`` so a
        weekly digest never breaks a daily unacknowledged-streak count."""
        query: dict[str, object] = {"user_id": user_id}
        if kind is not None:
            query["kind"] = kind
        return await self._find(query, sort=[("created_at", -1)], limit=limit)

    async def has_daily_briefing(self, user_id: str) -> bool:
        """Whether the user has ever received a daily briefing (first-briefing gate)."""
        return await self._count({"user_id": user_id, "kind": BRIEFING_KIND_DAILY}) > 0

    # ----------------------------------------------------------------- writes

    async def upsert_briefing(
        self, user_id: str, date: str, kind: BriefingKind, payload: BriefingPayload
    ) -> BriefingModel:
        """Store the payload (one per user/date/kind), preserving ``opened_at``
        and ``delivered_channels`` across a same-day rerun. Persisted BEFORE
        delivery so the dashboard never misses a brief that reached a channel."""
        doc = await self._apply_raw_update(
            {"user_id": user_id, "date": date, "kind": kind},
            {
                "$set": {"payload": payload.model_dump()},
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
            raise AppError(message="briefing upsert did not return a document")
        return doc

    async def set_delivered_channels(
        self, user_id: str, date: str, kind: BriefingKind, channels: list[str]
    ) -> None:
        await self._apply_raw_update_unfetched(
            {"user_id": user_id, "date": date, "kind": kind},
            {"$set": {"delivered_channels": channels}},
            scope=user_id,
        )

    async def mark_opened(self, user_id: str, briefing_id: str) -> BriefingModel | None:
        """Stamp ``opened_at`` once (idempotent). ``None`` when already opened or
        the briefing doesn't exist — the caller only cares whether it flipped."""
        return await self._apply_update(
            briefing_id,
            user_id,
            {"user_id": user_id, "opened_at": None},
            BriefingUpdate(opened_at=datetime.now(UTC)),
        )


briefing_repository = BriefingsRepository()
