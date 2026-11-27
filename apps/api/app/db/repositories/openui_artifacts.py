"""Repository for the artifacts collection: OpenUI artifact programs, owner-scoped.

No CachePolicy: an artifact is read when its card or viewer opens, rarely twice in a row.
"""

from app.db.repositories.base import UserScopedRepository
from app.models.openui_artifact_models import OpenUIArtifact, OpenUIArtifactUpdate

ARTIFACT_USER_CREATED_INDEX = "user_created"


class OpenUIArtifactsRepository(UserScopedRepository[OpenUIArtifact, OpenUIArtifactUpdate]):
    collection_name = "artifacts"
    document_model = OpenUIArtifact
    update_model = OpenUIArtifactUpdate
    uses_object_id = True
    cache_policy = None

    async def ids_in_conversation(self, user_id: str, conversation_id: str) -> list[str]:
        """Return the ids of the artifacts one of the owner's conversations made."""
        found = await self._find({"user_id": user_id, "conversation_id": conversation_id})
        return [artifact.id for artifact in found]

    async def delete_for_conversation(self, user_id: str, conversation_id: str) -> int:
        """Delete every artifact one of the owner's conversations made."""
        owned = {"user_id": user_id, "conversation_id": conversation_id}
        return await self._delete_many(owned)


openui_artifact_repository = OpenUIArtifactsRepository()
