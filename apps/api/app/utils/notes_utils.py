from langchain_core.documents import Document

from app.constants.chroma import CHROMA_NOTES_COLLECTION
from app.constants.log_tags import LogTag
from app.db.chroma.chromadb import ChromaClient
from app.db.repositories.notes import note_repository
from app.models.notes_models import NoteDocument, NoteModel, NoteResponse, NoteUpdate
from shared.py.wide_events import log


async def insert_note(
    note: NoteModel,
    user_id: str,
    auto_created: bool = False,
) -> NoteResponse:
    log.set(user_id=user_id, auto_created=auto_created, operation="insert_note")
    log.info(f"{LogTag.API} Creating new note for user", user_id=user_id)

    created = await note_repository.create(
        NoteDocument(
            user_id=user_id,
            content=note.content,
            plaintext=note.plaintext,
            auto_created=auto_created,
        )
    )
    note_id = created.id
    log.info(f"{LogTag.API} Note created with ID", note_id=note_id)

    # The note is already committed, so a vector-store failure must not fail the
    # request — telling the user their note was lost would be a lie. But an
    # unindexed note is invisible to search, so flag it for repair rather than
    # letting it degrade silently.
    try:
        await index_note(note_id, user_id, created.plaintext or "")
    except Exception as e:
        log.error(
            f"{LogTag.API} Note persisted but vector indexing failed; flagged for reindex",
            exc_info=True,
            error_type=type(e).__name__,
            error=str(e),
            note_id=note_id,
            user_id=user_id,
        )
        await note_repository.update(
            note_id, user_id=user_id, update=NoteUpdate(needs_reindex=True)
        )
        created.needs_reindex = True

    return NoteResponse.model_validate(created.model_dump())


async def index_note(note_id: str, user_id: str, plaintext: str) -> None:
    """Index one note's plaintext into the ``notes`` vector collection."""
    collection = await ChromaClient.get_langchain_client(collection_name=CHROMA_NOTES_COLLECTION)
    await collection.aadd_documents(
        documents=[
            Document(page_content=plaintext, metadata={"note_id": note_id, "user_id": user_id})
        ],
        ids=[note_id],
    )
    log.info(f"{LogTag.API} Note with id indexed in ChromaDB", note_id=note_id)


async def reindex_note(note_id: str, user_id: str, plaintext: str) -> None:
    """Re-index a note whose first indexing attempt failed, clearing the flag.

    Mirrors ``reindex_file`` in app/services/files/store.py — the repair entry
    point for notes flagged by ``insert_note``. Failures propagate so a caller
    repairing a batch sees which notes are still broken.
    """
    await index_note(note_id, user_id, plaintext)
    await note_repository.update(note_id, user_id=user_id, update=NoteUpdate(needs_reindex=False))
