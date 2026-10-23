"""Repository for the files collection — user-scoped uploaded-file metadata.

Every access is by the business file_id scoped to the owning user; the Mongo
_id (ObjectId) is incidental but preserved as id because the update
endpoint still returns it.
"""

from app.db.repositories.base import UserScopedRepository
from app.models.files_models import FileDocument, FileMimetypeRow, FileUpdate

_EXISTS = "$exists"

# The fields the mimetype migration reads; FileMimetypeRow ignores the rest.
_MIMETYPE_PROJECTION = {
    "file_id": 1,
    "filename": 1,
    "type": 1,
    "content_type": 1,
}  # pragma: no mutate — inclusion values are equivalent in Mongo


class FilesRepository(UserScopedRepository[FileDocument, FileUpdate]):
    """File metadata, scoped to the owning user and addressed by file_id."""

    collection_name = "files"
    document_model = FileDocument
    update_model = FileUpdate
    uses_object_id = True
    cache_policy = None

    async def get_by_file_id(self, file_id: str, user_id: str) -> FileDocument | None:
        """Return one file the user owns, or None."""
        return await self._find_one({"file_id": file_id, "user_id": user_id})

    async def find_by_ids_for_user(self, file_ids: list[str], user_id: str) -> list[FileDocument]:
        """Return the user's files among these ids, skipping unknown or foreign ids."""
        if not file_ids:
            return []
        return await self._find({"file_id": {"$in": file_ids}, "user_id": user_id})

    async def find_for_conversation(self, conversation_id: str, user_id: str) -> list[FileDocument]:
        """Return every file the user uploaded in this conversation."""
        return await self._find({"user_id": user_id, "conversation_id": conversation_id})

    async def find_ids_for_conversation(self, conversation_id: str, user_id: str) -> list[str]:
        """Return the user's file_ids visible in one conversation.

        Files uploaded before conversation scoping existed carry no
        conversation_id (the old web client never sent one, and only new
        conversations get backfilled), so they stay visible everywhere — do not
        "simplify" this to an exact conversation_id match.
        """
        documents = await self._find(
            {
                "user_id": user_id,
                "$or": [
                    {"conversation_id": conversation_id},
                    {"conversation_id": {_EXISTS: False}},
                    {"conversation_id": None},
                ],
            }
        )
        return [document.file_id for document in documents]

    async def apply_metadata_update(
        self, file_id: str, *, user_id: str, update: FileUpdate
    ) -> FileDocument | None:
        """Patch a file's editable metadata, always stamping updated_at.

        An empty patch still bumps updated_at (matching the pre-repository
        behaviour of a $set that only carried the timestamp)."""
        set_fields = update.model_dump(exclude_unset=True)
        ops: dict[str, dict[str, object]] = {"$set": set_fields} if set_fields else {}
        return await self._apply_raw_update(
            {"file_id": file_id, "user_id": user_id}, ops, scope=user_id
        )

    async def delete_by_file_id(self, file_id: str, user_id: str) -> bool:
        """Delete one file the user owns; False when nothing matched."""
        deleted = await self._delete_many({"file_id": file_id, "user_id": user_id}, scope=user_id)
        return deleted > 0

    async def find_mimetype_rows(self) -> list[FileMimetypeRow]:
        """Every file's mimetype fields, including rows FileDocument would reject."""
        cursor = self._raw_collection().find()
        return [FileMimetypeRow.model_validate(row) async for row in cursor]

    async def rename_legacy_mimetype(self, file_id: str, content_type: str) -> bool:
        """Move content_type to type on one row, only if it still looks as planned."""
        result = await self._raw_collection().update_one(
            {
                "file_id": file_id,
                "type": {_EXISTS: False},
                "content_type": content_type,
            },
            {"$set": {"type": content_type}, "$unset": {"content_type": ""}},  # pragma: no mutate
        )
        return result.modified_count == 1

    async def restore_legacy_mimetype(self, file_id: str, content_type: str) -> bool:
        """Reverse rename_legacy_mimetype for one row from a recorded backup."""
        result = await self._raw_collection().update_one(
            {
                "file_id": file_id,
                "type": content_type,
                "content_type": {_EXISTS: False},
            },
            {"$set": {"content_type": content_type}, "$unset": {"type": ""}},  # pragma: no mutate
        )
        return result.modified_count == 1


file_repository = FilesRepository()
