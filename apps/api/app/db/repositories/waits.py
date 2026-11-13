"""Repository for the waits collection: who to pick back up once the user does what GAIA asked.

Keyed by (user_id, condition, subject_id, waiter, waiter_id) under a unique index; a TTL
index on created_at drops an ask nobody answered within 7 days.
"""

from datetime import UTC, datetime

from pymongo.errors import DuplicateKeyError

from app.constants.waits import WaitCondition
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
        write = {"$set": {**update.model_dump(mode="json"), "created_at": datetime.now(UTC)}}
        try:
            await self._apply_raw_update(
                key.model_dump(mode="json"), write, scope=None, upsert=True
            )
        except DuplicateKeyError:
            await self._apply_raw_update(
                key.model_dump(mode="json"), write, scope=None, upsert=True
            )

    async def take_met(
        self, user_id: str, condition: WaitCondition, subject_id: str
    ) -> list[WaitDocument]:
        """Remove and return every wait on the subject; each is handed to one caller only.

        A condition can be reported more than once (an MCP session reopening from stored
        tokens), so the delete is the claim: a second report finds nothing left.
        """
        collection = self._raw_collection()
        match = {"user_id": user_id, "condition": condition.value, "subject_id": subject_id}
        taken: list[WaitDocument] = []
        while (raw := await collection.find_one_and_delete(match)) is not None:
            taken.append(self._to_model(raw))
        return taken


wait_repository = WaitsRepository()
