"""Repository for the usage_daily collection — durable per-day usage rollups.

One document per user per UTC day ({user_id, date: "YYYY-MM-DD", count, cost,
aux_cost, ...token counts}), $inc-upserted on every metered action. Backs
the activity heatmap, the percentile badge, and the durable cost history
(cost/*_tokens mirror the charged Redis budget windows; aux_cost/
aux_*_tokens are un-charged background COGS — see
app.services.usage_activity.record_cost). The token counts ride alongside
their cost in the same write so a mispriced call can be re-derived from the
raw usage after the fact, instead of only the (possibly wrong) dollar amount
surviving.
"""

from collections.abc import Mapping
from datetime import datetime

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
    # What the provider actually billed, reconstructed by scripts/backfill_true_cost.py.
    # Absent (not 0.0) on any row the backfill hasn't reached yet — a missing
    # reconstruction is not "$0 spent".
    cost_actual: float | None = None
    aux_cost_actual: float | None = None
    cost_actual_coverage: float | None = None
    cost_actual_provider_mix: dict[str, float] | None = None
    cost_actual_at: datetime | None = None


class TrueCostActuals(BaseModel):
    """One user-day's reconstructed provider spend, as written by the backfill."""

    model_config = ConfigDict(extra="forbid")

    cost_actual: float
    aux_cost_actual: float
    coverage: float
    provider_mix: dict[str, float]
    at: datetime


class UsageDailyIncrement(BaseModel):
    """One metered action's contribution to a rollup row.

    The charged and auxiliary halves of the row hold the same six counters
    under different names, so they are one shape plus a flag at
    :meth:`UsageDailyRepository.increment` rather than twelve parallel
    arguments that have to be kept in step by hand.
    """

    model_config = ConfigDict(extra="forbid")

    count: int = 0
    cost: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0


class UsageDailyUpdate(BaseModel):
    """Typed ``$set`` fields for a rollup row; nothing is typed-settable since rollups move via ``$inc``."""

    model_config = ConfigDict(extra="forbid")


class UsageDailyRepository(UserScopedRepository[UsageDailyDocument, UsageDailyUpdate]):
    collection_name = "usage_daily"
    document_model = UsageDailyDocument
    update_model = UsageDailyUpdate
    uses_object_id = True
    cache_policy = None

    async def increment(
        self, user_id: str, day: str, delta: UsageDailyIncrement, *, charged: bool = True
    ) -> None:
        """$inc-upsert the user's rollup row for day (YYYY-MM-DD).

        charged=False books spend/tokens under the aux_* fields instead, so the
        charged fields stay an exact mirror of the Redis budget windows. The
        action count is never split — the heatmap counts actions, not dollars.
        """
        prefix = "" if charged else "aux_"
        inc: dict[str, object] = {
            field: amount
            for field, amount in (
                ("count", delta.count),
                (f"{prefix}cost", delta.cost),
                (f"{prefix}input_tokens", delta.input_tokens),
                (f"{prefix}output_tokens", delta.output_tokens),
                (f"{prefix}cached_tokens", delta.cached_tokens),
                (f"{prefix}reasoning_tokens", delta.reasoning_tokens),
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

    async def apply_true_cost(self, user_id: str, date: str, actuals: TrueCostActuals) -> bool:
        """Stamp the reconstructed provider spend onto an EXISTING rollup row.

        Never touches cost/aux_cost, since budget enforcement already acted on
        those; the actuals land in their own fields instead. No upsert — a
        user-day with no rollup row was never metered, and inventing one would
        fabricate usage history.
        """
        matched = await self._apply_raw_update_unfetched(
            {"user_id": user_id, "date": date},
            {
                "$set": {
                    "cost_actual": actuals.cost_actual,
                    "aux_cost_actual": actuals.aux_cost_actual,
                    "cost_actual_coverage": actuals.coverage,
                    "cost_actual_provider_mix": actuals.provider_mix,
                    "cost_actual_at": actuals.at,
                }
            },
            scope=user_id,
            upsert=False,
        )
        return matched > 0

    async def counts_since(self, user_id: str, since_day: str) -> dict[str, int]:
        """Return the user's per-day action counts from since_day (inclusive) on."""
        rows = await self.rollups_since(user_id, since_day)
        return {row.date: row.count for row in rows}

    async def rollups_since(self, user_id: str, since_day: str) -> list[UsageDailyDocument]:
        """Return the user's full rollup rows from since_day (inclusive) on."""
        return await self._find({"user_id": user_id, "date": {"$gte": since_day}})

    async def rank_thresholds(
        self, window_start: str, rank_fractions: Mapping[str, float]
    ) -> dict[str, float]:
        """Cross-user activity thresholds at each top-X% RANK position.

        One server-side pass: sum each user's window total, sort descending, and
        read the value at each rank position (index ceil(fraction * n) - 1, floored
        at 0) — rank-based, not value-quantile, so one whale can't skew it. Bounded
        by the 16MB BSON doc limit; returns {} when the window has no rows.
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
        """Every user's summed action count since window_start, one pass."""
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
