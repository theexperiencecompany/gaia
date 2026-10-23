"""Repository for the user_instructions collection.

One document per (user_id, scope) (unique index). Writes carry an optional
expected revision so two editors cannot silently overwrite each other.
"""

from pymongo.errors import DuplicateKeyError

from app.db.repositories.base import UserScopedRepository
from app.models.user_instructions_models import (
    InstructionsEditor,
    UserInstructionsDocument,
    UserInstructionsUpdate,
)


class UserInstructionsRepository(
    UserScopedRepository[UserInstructionsDocument, UserInstructionsUpdate]
):
    collection_name = "user_instructions"
    document_model = UserInstructionsDocument
    update_model = UserInstructionsUpdate
    uses_object_id = True
    cache_policy = None

    async def get_record(self, user_id: str, scope: str) -> UserInstructionsDocument | None:
        return await self._find_one({"user_id": user_id, "scope": scope})

    async def all_nonempty(self, user_id: str) -> list[UserInstructionsDocument]:
        return await self._find({"user_id": user_id, "content": {"$ne": ""}})

    async def write(
        self,
        user_id: str,
        scope: str,
        *,
        content: str,
        updated_by: InstructionsEditor,
        expected_revision: int | None,
    ) -> UserInstructionsDocument | None:
        """Replace a scope's content and bump its revision; None when expected_revision is stale.

        expected_revision None writes unconditionally. 0 claims the scope is unwritten:
        the upsert then collides on the unique index if another writer created it first.
        """
        filter_: dict[str, object] = {"user_id": user_id, "scope": scope}
        if expected_revision is not None:
            filter_["revision"] = expected_revision
        try:
            return await self._apply_raw_update(
                filter_,
                {
                    "$set": {"content": content, "updated_by": updated_by.value},
                    "$inc": {"revision": 1},
                },
                scope=user_id,  # pragma: no mutate — cache_policy is None, so no cache reads the scope
                upsert=expected_revision is None or expected_revision == 0,
            )
        except DuplicateKeyError:
            return None


user_instructions_repository = UserInstructionsRepository()
