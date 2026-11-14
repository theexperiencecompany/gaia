"""Repository for the waits collection: who to pick back up once the user does what GAIA asked.

Keyed by (user_id, condition, subject_id, waiter, waiter_id) under a unique index; a TTL
index on created_at drops an ask nobody answered within 7 days.
"""

from datetime import UTC, datetime, timedelta

from pymongo.errors import DuplicateKeyError

from app.constants.waits import RESUME_WAITER_LEASE, WAIT_TTL_SECONDS, WaitCondition
from app.db.repositories.base import UserScopedRepository
from app.models.wait_models import WaitDocument, WaitKey, WaitUpdate


class WaitsRepository(UserScopedRepository[WaitDocument, WaitUpdate]):
    collection_name = "waits"
    document_model = WaitDocument
    update_model = WaitUpdate
    uses_object_id = True
    cache_policy = None

    async def keep(self, key: WaitKey, update: WaitUpdate) -> None:
        """Keep the waiter on the condition; a repeat ask restarts its 7 days.

        Two first asks can both miss and insert; the unique index rejects the loser,
        and its retry overwrites the winner.
        """
        write = {
            "$set": {**update.model_dump(), "created_at": datetime.now(UTC)},
            # A fresh ask outlives the resume holding the old one: that job's settle won't match.
            "$unset": _LEASE_CLEARED,
        }
        try:
            await self._apply_raw_update(key.model_dump(), write, scope=None, upsert=True)
        except DuplicateKeyError:
            await self._apply_raw_update(key.model_dump(), write, scope=None, upsert=True)

    async def find_met(
        self, user_id: str, condition: WaitCondition, subject_id: str
    ) -> list[WaitDocument]:
        """Return the live waits on the subject without taking them; claim() hands each one out."""
        return await self._find(
            {
                "user_id": user_id,
                "condition": condition.value,
                "subject_id": subject_id,
                "created_at": {"$gte": _oldest_live()},
            }
        )

    async def claim(self, wait_id: str, *, user_id: str, job_id: str) -> WaitDocument | None:
        """Lease the live wait to the job; None when another job holds it or it expired.

        The wait stays on file until settle(), so a worker that dies mid-resume loses nothing:
        ARQ reruns the same job id, which takes the lease again. A lease past
        RESUME_WAITER_LEASE goes to whichever job asks next.
        """
        now = datetime.now(UTC)
        return await self._apply_raw_update(
            {
                **self._identity_filter(wait_id),
                "user_id": user_id,
                "created_at": {"$gte": _oldest_live()},
                "$or": [
                    {"claimed_by": None},
                    {"claimed_by": job_id},
                    {"claimed_at": {"$lt": now - RESUME_WAITER_LEASE}},
                ],
            },
            {"$set": {"claimed_by": job_id, "claimed_at": now}},
            scope=None,
        )

    async def settle(self, wait_id: str, *, job_id: str) -> None:
        """Drop the wait the job resumed; a newer ask on the same waiter cleared the lease and stays."""
        await self._raw_collection().delete_one(
            {**self._identity_filter(wait_id), "claimed_by": job_id}
        )

    async def release(self, wait_id: str, *, job_id: str) -> None:
        """Give up the job's lease, so the next report of the condition can resume the waiter."""
        await self._raw_collection().update_one(
            {**self._identity_filter(wait_id), "claimed_by": job_id},
            {"$unset": _LEASE_CLEARED},
        )


_LEASE_CLEARED: dict[str, object] = {"claimed_by": "", "claimed_at": ""}


def _oldest_live() -> datetime:
    # The TTL monitor sweeps about once a minute, so an expired wait can still be on disk.
    return datetime.now(UTC) - timedelta(seconds=WAIT_TTL_SECONDS)


wait_repository = WaitsRepository()
