"""Repository for the mail collection (analyzed-email importance summaries)."""

from app.db.repositories.base import MongoRepository
from app.models.mail_models import MailDocument, MailUpdate


class MailRepository(MongoRepository[MailDocument, MailUpdate]):
    collection_name = "mail"
    document_model = MailDocument
    update_model = MailUpdate
    uses_object_id = True
    cache_policy = None

    async def list_for_user(
        self, user_id: str, *, important_only: bool = False, limit: int = 50
    ) -> list[MailDocument]:
        filter_: dict[str, object] = {"user_id": user_id}
        if important_only:
            filter_["is_important"] = True
        return await self._find(filter_, sort=[("analyzed_at", -1)], limit=limit)

    async def get_by_message(self, user_id: str, message_id: str) -> MailDocument | None:
        return await self._find_one({"user_id": user_id, "message_id": message_id})

    async def list_by_message_ids(self, user_id: str, message_ids: list[str]) -> list[MailDocument]:
        return await self._find({"user_id": user_id, "message_id": {"$in": message_ids}})


mail_repository = MailRepository()
