"""Repository for the ``files`` collection — user-scoped uploaded-file metadata.

Every access is by the business ``file_id`` scoped to the owning user; the Mongo
``_id`` (ObjectId) is incidental but preserved as ``id`` because the update
endpoint still returns it.
"""

from app.db.repositories.base import UserScopedRepository
from app.models.files_models import FileDocument, FileUpdate


class FilesRepository(UserScopedRepository[FileDocument, FileUpdate]):
    collection_name = "files"
    document_model = FileDocument
    update_model = FileUpdate
    uses_object_id = True
    cache_policy = None

    async def get_by_file_id(self, file_id: str, user_id: str) -> FileDocument | None:
        return await self._find_one({"file_id": file_id, "user_id": user_id})

    async def find_by_ids_for_user(self, file_ids: list[str], user_id: str) -> list[FileDocument]:
        if not file_ids:
            return []
        return await self._find({"file_id": {"$in": file_ids}, "user_id": user_id})

    async def apply_metadata_update(
        self, file_id: str, *, user_id: str, update: FileUpdate
    ) -> FileDocument | None:
        """Patch a file's editable metadata, always stamping ``updated_at``.

        An empty patch still bumps ``updated_at`` (matching the pre-repository
        behaviour of a ``$set`` that only carried the timestamp)."""
        set_fields = update.model_dump(exclude_unset=True)
        ops: dict[str, dict[str, object]] = {"$set": set_fields} if set_fields else {}
        return await self._apply_raw_update(
            {"file_id": file_id, "user_id": user_id}, ops, scope=user_id
        )

    async def delete_by_file_id(self, file_id: str, user_id: str) -> bool:
        deleted = await self._delete_many({"file_id": file_id, "user_id": user_id}, scope=user_id)
        return deleted > 0


file_repository = FilesRepository()
