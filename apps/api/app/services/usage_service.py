"""
Usage tracking service — thin orchestration over the usage-snapshot repository.
"""

from datetime import UTC, datetime, timedelta

from app.db.repositories.usage_snapshots import usage_snapshot_repository
from app.models.usage_models import UserUsageSnapshot


class UsageService:
    @staticmethod
    async def save_usage_snapshot(snapshot: UserUsageSnapshot) -> str:
        """Save a usage snapshot, hourly-aggregated to prevent document explosion."""
        return await usage_snapshot_repository.upsert_hourly(snapshot)

    @staticmethod
    async def get_usage_history(
        user_id: str, feature_key: str | None = None, days: int = 30
    ) -> list[UserUsageSnapshot]:
        since = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
            days=days
        )
        snapshots = await usage_snapshot_repository.history_for_user(user_id, since=since)

        if not feature_key:
            return snapshots

        filtered = []
        for snapshot in snapshots:
            # Keep only the requested feature (new list, don't mutate the shared one).
            matching = [f for f in snapshot.features if f.feature_key == feature_key]
            if matching:
                snapshot.features = matching
                filtered.append(snapshot)
        return filtered
