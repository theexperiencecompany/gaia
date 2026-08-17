"""Repository for the ``usage_snapshots`` collection — user-scoped usage tracking.

Snapshots are hourly-aggregated: a write merges into the current hour's row for
the user (bounded ``$gte``/``$lt`` on ``snapshot_date``) or creates it, keeping the
document count from exploding. ``updated_at`` is stamped by the base on merge; a
90-day TTL on ``created_at`` reaps old rows (see indexes).
"""

from datetime import UTC, datetime, timedelta

from app.db.repositories.base import UserScopedRepository
from app.models.usage_models import UsageSnapshotUpdate, UserUsageSnapshot


class UsageSnapshotsRepository(UserScopedRepository[UserUsageSnapshot, UsageSnapshotUpdate]):
    collection_name = "usage_snapshots"
    document_model = UserUsageSnapshot
    update_model = UsageSnapshotUpdate
    uses_object_id = True
    cache_policy = None

    async def upsert_hourly(self, snapshot: UserUsageSnapshot) -> str:
        """Merge usage into the user's current-hour snapshot, or insert a new one.
        Returns the snapshot id."""
        current_hour = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        hour_filter: dict[str, object] = {
            "user_id": snapshot.user_id,
            "snapshot_date": {
                "$gte": current_hour,
                "$lt": current_hour + timedelta(hours=1),
            },
        }
        existing = await self._find_one(hour_filter)
        if existing is not None:
            await self._apply_raw_update(
                hour_filter,
                {
                    "$set": {
                        "plan_type": snapshot.plan_type,
                        "features": [feature.model_dump() for feature in snapshot.features],
                    }
                },
                scope=snapshot.user_id,
                return_document=False,
            )
            return existing.id

        snapshot.snapshot_date = current_hour
        created = await self.create(snapshot)
        return created.id

    async def history_for_user(self, user_id: str, *, since: datetime) -> list[UserUsageSnapshot]:
        """A user's snapshots created since ``since``, newest first."""
        return await self._find(
            {"user_id": user_id, "created_at": {"$gte": since}},
            sort=[("created_at", -1)],
        )


usage_snapshot_repository = UsageSnapshotsRepository()
