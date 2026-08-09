"""Repository for the notes collection."""

from app.constants.cache import NOTE_CACHE_PREFIX
from app.db.repositories.base import UserScopedRepository, cached_query
from app.db.repositories.cache import CachePolicy
from app.models.notes_models import NoteDocument, NoteSearchHit, NoteUpdate


class NotesRepository(UserScopedRepository[NoteDocument, NoteUpdate]):
    collection_name = "notes"
    document_model = NoteDocument
    update_model = NoteUpdate
    uses_object_id = True
    cache_policy = CachePolicy(prefix=NOTE_CACHE_PREFIX)

    @cached_query(list[NoteDocument])
    async def list_notes(self, *, user_id: str) -> list[NoteDocument]:
        """All of a user's notes — cached, orphaned automatically on any write."""
        return await self._find({"user_id": user_id})

    async def find_by_ids(self, user_id: str, note_ids: list[str]) -> list[NoteDocument]:
        """The user's notes whose ``_id`` is in ``note_ids`` (order not preserved)."""
        if not note_ids:
            return []
        return await self._find(
            {"_id": {"$in": [self._id_value(nid) for nid in note_ids]}, "user_id": user_id}
        )

    async def search_by_plaintext(self, user_id: str, *, pattern: str) -> list[NoteSearchHit]:
        """Notes whose plaintext matches a regex ``pattern`` (caller escapes it)."""
        return await self._aggregate(
            [
                {"$match": {"user_id": user_id, "plaintext": {"$regex": pattern, "$options": "i"}}},
                {"$project": {"_id": 0, "id": {"$toString": "$_id"}, "note_id": 1, "plaintext": 1}},
            ],
            NoteSearchHit,
        )


note_repository = NotesRepository()
