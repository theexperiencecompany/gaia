"""Repository for the notes collection."""

from app.constants.cache import NOTE_CACHE_PREFIX
from app.db.repositories.base import UserScopedRepository, cached_query
from app.db.repositories.cache import CachePolicy
from app.models.notes_models import NoteDocument, NoteUpdate


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


note_repository = NotesRepository()
