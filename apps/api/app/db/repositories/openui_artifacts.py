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


openui_artifact_repository = OpenUIArtifactsRepository()
