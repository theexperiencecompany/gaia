"""Repository for the ``user_integrations`` collection.

User-scoped; one document per ``(user_id, integration_id)`` (unique index),
addressed by the business ``integration_id`` within a user. Tracks which
integrations a user has added and whether they are connected.
"""

from app.db.repositories.base import UserScopedRepository
from app.models.integration_models import (
    UserIntegrationDocument,
    UserIntegrationUpdate,
)


class UserIntegrationsRepository(
    UserScopedRepository[UserIntegrationDocument, UserIntegrationUpdate]
):
    collection_name = "user_integrations"
    document_model = UserIntegrationDocument
    update_model = UserIntegrationUpdate
    uses_object_id = True
    identity_field = "integration_id"
    cache_policy = None

    async def get_for_user(
        self, user_id: str, integration_id: str
    ) -> UserIntegrationDocument | None:
        return await self._find_one({"user_id": user_id, "integration_id": integration_id})

    async def exists(self, user_id: str, integration_id: str) -> bool:
        return await self.get_for_user(user_id, integration_id) is not None

    async def list_for_user_newest_first(self, user_id: str) -> list[UserIntegrationDocument]:
        return await self.list_for_user(user_id, sort=[("created_at", -1)])

    async def delete_for_user(self, user_id: str, integration_id: str) -> bool:
        return await self.delete(integration_id, user_id=user_id)


user_integration_repository = UserIntegrationsRepository()
