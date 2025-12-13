"""
Usage tracking service for database operations.
"""

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from app.db.mongodb.collections import usage_snapshots_collection
from app.models.usage_models import UserUsageSnapshot


class UsageService:
    @staticmethod
    def _prepare_doc_for_model(doc: dict) -> dict:
        """Helper to prepare MongoDB document for Pydantic model."""
        doc["_id"] = str(doc["_id"])
        return doc

    @staticmethod
    async def save_usage_snapshot(snapshot: UserUsageSnapshot) -> str:
        """Save usage snapshot with smart aggregation to prevent document explosion."""
        snapshot_dict = snapshot.model_dump()

        # Use hourly aggregation to prevent too many documents
        current_hour = datetime.now(timezone.utc).replace(
            minute=0, second=0, microsecond=0
        )

        # Try to update existing document for this hour, or insert new one
        filter_query = {
            "user_id": snapshot.user_id,
            "snapshot_date": {
                "$gte": current_hour,
                "$lt": current_hour + timedelta(hours=1),
            },
        }

        existing_doc = await usage_snapshots_collection.find_one(filter_query)

        if existing_doc:
            # Update existing document by merging usage data
            update_query = {
                "$set": {
                    "plan_type": snapshot.plan_type,
                    "features": [f.model_dump() for f in snapshot.features],
                    "credits": [c.model_dump() for c in snapshot.credits],
                    "updated_at": datetime.now(timezone.utc),
                }
            }
            await usage_snapshots_collection.update_one(filter_query, update_query)
            return str(existing_doc["_id"])
        else:
            # Insert new document
            snapshot_dict["snapshot_date"] = current_hour
            result = await usage_snapshots_collection.insert_one(snapshot_dict)
            return str(result.inserted_id)

    @staticmethod
    async def get_latest_usage_snapshot(user_id: str) -> Optional[UserUsageSnapshot]:
        snapshot_doc = await usage_snapshots_collection.find_one(
            {"user_id": user_id}, sort=[("created_at", -1)]
        )
        if snapshot_doc:
            return UserUsageSnapshot(
                **UsageService._prepare_doc_for_model(snapshot_doc)
            )
        return None

    @staticmethod
    async def get_usage_history(
        user_id: str, feature_key: Optional[str] = None, days: int = 30
    ) -> List[UserUsageSnapshot]:
        query = {
            "user_id": user_id,
            "created_at": {
                "$gte": datetime.now(timezone.utc).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                - timedelta(days=days)
            },
        }

        snapshots = []
        async for doc in usage_snapshots_collection.find(query).sort("created_at", -1):
            snapshot = UserUsageSnapshot(**UsageService._prepare_doc_for_model(doc))

            if feature_key:
                # Filter to only include the requested feature (create new list, don't mutate)
                filtered_features = [
                    f for f in snapshot.features if f.feature_key == feature_key
                ]
                if filtered_features:
                    snapshot.features = filtered_features
                    snapshots.append(snapshot)
            else:
                snapshots.append(snapshot)

        return snapshots
