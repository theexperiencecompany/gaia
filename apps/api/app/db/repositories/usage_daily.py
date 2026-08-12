"""Repository for the ``usage_daily`` collection — durable per-day usage rollups.

One document per user per UTC day (``{user_id, date: "YYYY-MM-DD", count, cost,
aux_cost, ...token counts}``), ``$inc``-upserted on every metered action. Backs
the activity heatmap, the percentile badge, and the durable cost history
(``cost``/``*_tokens`` mirror the charged Redis budget windows; ``aux_cost``/
``aux_*_tokens`` are un-charged background COGS — see
``app.services.usage_activity.record_cost``). The token counts ride alongside
their cost in the same write so a mispriced call can be re-derived from the
raw usage after the fact, instead of only the (possibly wrong) dollar amount
surviving.
"""

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict

from app.db.repositories.base import UserScopedDocument, UserScopedRepository


class UsageDailyDocument(UserScopedDocument):
    """One user's rollup row for one UTC day."""

    date: str
    count: int = 0
    cost: float = 0.0
    aux_cost: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0
    aux_input_tokens: int = 0
    aux_output_tokens: int = 0
    aux_cached_tokens: int = 0
    aux_reasoning_tokens: int = 0


class UsageDailyUpdate(BaseModel):
    """Typed ``$set`` fields for a rollup row. Rollups move via ``$inc``-only
    raw updates, so nothing is typed-settable."""

    model_config = ConfigDict(extra="forbid")


class UsageDailyRepository(UserScopedRepository[UsageDailyDocument, UsageDailyUpdate]):
    collection_name = "usage_daily"
    document_model = UsageDailyDocument
    update_model = UsageDailyUpdate
    uses_object_id = True
    cache_policy = None

    async def increment(
        self,
        user_id: str,
        day: str,
        *,
        count: int = 0,
        cost: float = 0.0,
        aux_cost: float = 0.0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cached_tokens: int = 0,
        reasoning_tokens: int = 0,
        aux_input_tokens: int = 0,
        aux_output_tokens: int = 0,
        aux_cached_tokens: int = 0,
        aux_reasoning_tokens: int = 0,
    ) -> None:
        """``$inc``-upsert the user's rollup row for ``day`` (``YYYY-MM-DD``)."""
        inc: dict[str, object] = {
            field: amount
            for field, amount in (
                ("count", count),
                ("cost", cost),
                ("aux_cost", aux_cost),
                ("input_tokens", input_tokens),
                ("output_tokens", output_tokens),
                ("cached_tokens", cached_tokens),
                ("reasoning_tokens", reasoning_tokens),
                ("aux_input_tokens", aux_input_tokens),
                ("aux_output_tokens", aux_output_tokens),
                ("aux_cached_tokens", aux_cached_tokens),
                ("aux_reasoning_tokens", aux_reasoning_tokens),
            )
            if amount
        }
        if not inc:
            return
        await self._apply_raw_update(
            {"user_id": user_id, "date": day},
            {"$inc": inc},
            scope=user_id,
            return_document=False,
            upsert=True,
        )

    async def counts_since(self, user_id: str, since_day: str) -> dict[str, int]:
        """The user's per-day action counts from ``since_day`` (inclusive) on."""
        rows = await self.rollups_since(user_id, since_day)
        return {row.date: row.count for row in rows}

    async def rollups_since(self, user_id: str, since_day: str) -> list[UsageDailyDocument]:
        """The user's full rollup rows from ``since_day`` (inclusive) on."""
        return await self._find({"user_id": user_id, "date": {"$gte": since_day}})

    async def rank_thresholds(
        self, window_start: str, rank_fractions: Mapping[str, float]
    ) -> dict[str, float]:
        """Cross-user activity thresholds at each top-X% RANK position.

        One server-side pass: sum each user's window total, sort descending,
        push the totals into a single Mongo-side array, then read the value at
        each top-X% rank position (0-based index ``ceil(fraction * n) - 1``,
        floored at 0). Rank-based (not value-quantile) so a single whale cannot
        stretch a threshold past every other user. The sorted array is bounded
        by the 16MB BSON doc limit (fine for realistic user counts) and never
        leaves Mongo; only the threshold scalars come back. Returns ``{}`` when
        the window has no rows at all.
        """
        threshold_at = {
            key: {
                "$arrayElemAt": [
                    "$totals",
                    {
                        "$toInt": {
                            "$max": [
                                0,
                                {"$subtract": [{"$ceil": {"$multiply": [frac, "$n"]}}, 1]},
                            ]
                        }
                    },
                ]
            }
            for key, frac in rank_fractions.items()
        }
        rows = [
            row
            async for row in self._raw_collection().aggregate(
                [
                    {"$match": {"date": {"$gte": window_start}}},
                    {"$group": {"_id": "$user_id", "total": {"$sum": "$count"}}},
                    {"$sort": {"total": -1}},
                    {"$group": {"_id": None, "totals": {"$push": "$total"}}},
                    {"$set": {"n": {"$size": "$totals"}}},
                    {"$project": {"_id": 0, **threshold_at}},
                ]
            )
        ]
        if not rows:
            return {}
        return {key: float(rows[0][key]) for key in rank_fractions}

    async def user_window_totals(self, window_start: str) -> list[tuple[str, int]]:
        """Every user's summed action count since ``window_start``, one pass."""
        return [
            (str(row["_id"]), int(row["total"]))
            async for row in self._raw_collection().aggregate(
                [
                    {"$match": {"date": {"$gte": window_start}}},
                    {"$group": {"_id": "$user_id", "total": {"$sum": "$count"}}},
                ]
            )
        ]


usage_daily_repository = UsageDailyRepository()
