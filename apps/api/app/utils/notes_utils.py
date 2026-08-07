from langchain_core.documents import Document

from app.constants.log_tags import LogTag
from app.db.chroma.chromadb import ChromaClient
from app.db.repositories.notes import note_repository
from app.models.notes_models import NoteDocument, NoteModel, NoteResponse
from shared.py.wide_events import log


async def insert_note(
    note: NoteModel,
    user_id: str,
    auto_created: bool = False,
) -> NoteResponse:
    log.set(user_id=user_id, auto_created=auto_created, operation="insert_note")
    log.info(f"{LogTag.API} Creating new note for user: {user_id}")

    langchain_chroma_client = await ChromaClient.get_langchain_client(collection_name="notes")

    created = await note_repository.create(
        NoteDocument(
            user_id=user_id,
            content=note.content,
            plaintext=note.plaintext,
            auto_created=auto_created,
        )
    )
    note_id = created.id
    log.info(f"{LogTag.API} Note created with ID: {note_id}")

    # Index the note for vector search.
    await langchain_chroma_client.aadd_documents(
        documents=[
            Document(
                page_content=created.plaintext or "",
                metadata={"note_id": note_id, "user_id": user_id},
            )
        ],
        ids=[note_id],
    )
    log.info(f"{LogTag.API} Note with id {note_id} indexed in ChromaDB")

    return NoteResponse.model_validate(created.model_dump())
