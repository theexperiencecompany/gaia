"""Repository for the waits collection: who to pick back up once the user does what GAIA asked.

Keyed by (user_id, condition, subject_id, waiter, waiter_id) under a unique index; a TTL
index on created_at drops an ask nobody answered within 7 days.
"""

from datetime import UTC, datetime, timedelta

from pymongo.errors import DuplicateKeyError

from app.constants.waits import WAIT_TTL_SECONDS, WaitCondition
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
        write = {"$set": {**update.model_dump(), "created_at": datetime.now(UTC)}}
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

    async def claim(self, wait_id: str, *, user_id: str) -> WaitDocument | None:
        """Remove and return the wait if it is still live; None when another job already took it.

        A condition can be reported more than once (an MCP session reopening from stored
        tokens), so the delete is the claim: only one resume picks the waiter up.
        """
        raw = await self._raw_collection().find_one_and_delete(
            {
                **self._identity_filter(wait_id),
                "user_id": user_id,
                "created_at": {"$gte": _oldest_live()},
            }
        )
        return None if raw is None else self._to_model(raw)

    async def restore(self, wait: WaitDocument) -> None:
        """Put back a claimed wait whose resume failed; a newer ask on the same waiter is kept instead."""
        key = WaitKey(
            user_id=wait.user_id,
            condition=wait.condition,
            subject_id=wait.subject_id,
            waiter=wait.waiter,
            waiter_id=wait.waiter_id,
        )
        on_insert = {
            **WaitUpdate(subject_name=wait.subject_name, stream_id=wait.stream_id).model_dump(),
            "created_at": wait.created_at,
        }
        await self._apply_raw_update(
            key.model_dump(), {"$setOnInsert": on_insert}, scope=None, upsert=True
        )


def _oldest_live() -> datetime:
    # The TTL monitor sweeps about once a minute, so an expired wait can still be on disk.
    return datetime.now(UTC) - timedelta(seconds=WAIT_TTL_SECONDS)


wait_repository = WaitsRepository()
