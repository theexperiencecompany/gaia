from langchain_core.documents import Document

from app.config.loggers import notes_logger as logger
from app.db.chroma.chromadb import ChromaClient
from app.db.mongodb.collections import notes_collection
from app.db.redis import delete_cache, set_cache
from app.models.notes_models import NoteModel, NoteResponse


async def insert_note(
    note: NoteModel,
    user_id: str,
    auto_created=False,
) -> NoteResponse:
    logger.info(f"Creating new note for user: {user_id}")

    langchain_chroma_client = await ChromaClient.get_langchain_client(
        collection_name="notes"
    )

    note_data = note.model_dump()
    note_data["user_id"] = user_id
    note_data["auto_created"] = auto_created

    result = await notes_collection.insert_one(note_data)

    note_id = str(result.inserted_id)

    logger.info(f"Note created with ID: {note_id}")

    # Add note to ChromaDB for vector search
    await langchain_chroma_client.aadd_documents(
        documents=[
            Document(
                page_content=note_data.get("plaintext") or "",
                metadata={
                    "note_id": note_id,
                    "user_id": user_id,
                },
            )
        ],
        ids=[note_id],
    )
    logger.info(f"Note with id {note_id} indexed in ChromaDB")

    response_data = {
        "id": note_id,
        "content": note_data["content"],
        "plaintext": note_data["plaintext"],
        "user_id": user_id,
        "auto_created": note_data.get("auto_created", False),
        "title": note_data.get("title"),
        "description": note_data.get("description"),
    }

    await delete_cache(f"notes:{user_id}")

    await set_cache(f"note:{user_id}:{note_id}", response_data)
    logger.info(f"Note created with ID: {note_id} and cache updated")

    return NoteResponse(**response_data)
