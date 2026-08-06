"""
Service module for handling note operations.
"""

from fastapi import HTTPException, status
from langchain_core.documents import Document

from app.db.chroma.chromadb import ChromaClient
from app.db.repositories.notes import note_repository
from app.models.notes_models import NoteModel, NoteResponse, NoteUpdate
from app.utils.notes_utils import insert_note
from shared.py.wide_events import log


async def get_note(note_id: str, user_id: str) -> NoteResponse:
    """Retrieve a single note by its ID for the user."""
    log.set(service="notes_service", operation="get_note", note_id=note_id, user_id=user_id)
    note = await note_repository.get(note_id, user_id=user_id)
    if note is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    return NoteResponse.model_validate(note.model_dump())


async def get_all_notes(user_id: str) -> list[NoteResponse]:
    """Retrieve all notes for the user."""
    log.set(service="notes_service", operation="get_all_notes", user_id=user_id)
    notes = await note_repository.list_notes(user_id=user_id)
    return [NoteResponse.model_validate(note.model_dump()) for note in notes]


async def update_note(note_id: str, note: NoteModel, user_id: str) -> NoteResponse:
    """Update an existing note by its ID for the user."""
    log.set(service="notes_service", operation="update_note", note_id=note_id, user_id=user_id)

    updated = await note_repository.update(
        note_id,
        user_id=user_id,
        update=NoteUpdate(content=note.content, plaintext=note.plaintext),
    )
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")

    # Keep the vector index in sync; a ChromaDB hiccup must not fail the write.
    try:
        chroma_notes_collection = await ChromaClient.get_langchain_client(collection_name="notes")
        await chroma_notes_collection.update_document(  # type: ignore[func-returns-value,misc]
            document_id=note_id,
            document=Document(page_content=note.plaintext),
        )
        log.info(f"Note with id {note_id} updated in ChromaDB")
    except Exception as e:
        log.error(f"Failed to update note in ChromaDB: {e!s}")

    return NoteResponse.model_validate(updated.model_dump())


async def delete_note(note_id: str, user_id: str) -> None:
    """Delete a note by its ID for the user."""
    log.set(service="notes_service", operation="delete_note", note_id=note_id, user_id=user_id)

    deleted = await note_repository.delete(note_id, user_id=user_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")

    # Best-effort vector-index cleanup; a ChromaDB hiccup must not fail the delete.
    try:
        chroma_notes_collection = await ChromaClient.get_langchain_client(collection_name="notes")
        await chroma_notes_collection.adelete(ids=[note_id])
        log.info(f"Note with id {note_id} deleted from ChromaDB")
    except Exception as e:
        log.error(f"Failed to delete note from ChromaDB: {e!s}")


async def create_note_service(note: NoteModel, user_id: str) -> NoteResponse:
    """Create a new note for the authenticated user."""
    try:
        return await insert_note(note, user_id)
    except Exception as e:
        log.error(f"Failed to create note: {e!s}")
        raise HTTPException(status_code=500, detail="Failed to create note")
