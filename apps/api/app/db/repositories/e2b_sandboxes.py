"""Repository for the ``e2b_sandboxes`` collection — one sandbox record per user.

Global, keyed by ``user_id``. ``record_acquisition`` is an atomic upsert that
stamps the live sandbox and increments the invocation counter; the state
transitions (pause/dead/touch) are fire-and-forget raw writes.
"""

from datetime import datetime

from app.constants.cache import REPO_GLOBAL_SCOPE
from app.db.repositories.base import MongoRepository
from app.models.sandbox_models import E2bSandboxDocument, E2bSandboxUpdate


class E2bSandboxesRepository(MongoRepository[E2bSandboxDocument, E2bSandboxUpdate]):
    collection_name = "e2b_sandboxes"
    document_model = E2bSandboxDocument
    update_model = E2bSandboxUpdate
    uses_object_id = True
    cache_policy = None

    async def get_for_user(self, user_id: str) -> E2bSandboxDocument | None:
        return await self._find_one({"user_id": user_id})

    async def record_acquisition(
        self,
        *,
        user_id: str,
        sandbox_id: str | None,
        template_id: str | None,
        shard_id: int,
        workspace_version: int,
        last_canary_ts: str,
        timestamp: datetime,
    ) -> None:
        """Upsert the user's active sandbox and bump ``total_invocations``.

        ``created_at`` is set only on insert; every acquire refreshes the rest."""
        await self._apply_raw_update(
            {"user_id": user_id},
            {
                "$set": {
                    "user_id": user_id,
                    "sandbox_id": sandbox_id,
                    "template_id": template_id,
                    "shard_id": shard_id,
                    "state": "active",
                    "workspace_version": workspace_version,
                    "last_used_at": timestamp,
                    "last_canary_ts": last_canary_ts,
                },
                "$setOnInsert": {"created_at": timestamp},
                "$inc": {"total_invocations": 1},
            },
            scope=REPO_GLOBAL_SCOPE,
            upsert=True,
        )

    async def mark_paused(self, user_id: str, *, timestamp: datetime) -> None:
        await self._apply_raw_update_unfetched(
            {"user_id": user_id},
            {"$set": {"state": "paused", "paused_at": timestamp}},
            scope=REPO_GLOBAL_SCOPE,
        )

    async def mark_dead(self, user_id: str, *, timestamp: datetime) -> None:
        await self._apply_raw_update_unfetched(
            {"user_id": user_id},
            {"$set": {"state": "dead", "last_used_at": timestamp}},
            scope=REPO_GLOBAL_SCOPE,
        )

    async def touch_last_used(self, user_id: str, *, timestamp: datetime) -> None:
        await self._apply_raw_update_unfetched(
            {"user_id": user_id},
            {"$set": {"last_used_at": timestamp}},
            scope=REPO_GLOBAL_SCOPE,
        )

    async def find_idle_user_ids(self, *, cutoff: datetime) -> list[str]:
        """User ids whose sandbox is idle past ``cutoff`` and not already dead."""
        return await self._distinct(
            "user_id", {"last_used_at": {"$lt": cutoff}, "state": {"$ne": "dead"}}
        )


e2b_sandbox_repository = E2bSandboxesRepository()
