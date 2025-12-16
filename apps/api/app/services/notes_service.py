"""
Service module for handling note operations.
"""

from typing import Any, Dict

from app.agents.prompts.convo_prompts import NOTES_PROMPT
from app.config.loggers import notes_logger as logger
from app.db.chromadb.chromadb import ChromaClient
from app.db.mongodb.collections import notes_collection
from app.db.redis import delete_cache, get_cache, set_cache
from app.db.utils import serialize_document
from app.models.notes_models import NoteModel, NoteResponse
from app.utils.embedding_utils import search_notes_by_similarity
from app.utils.notes_utils import insert_note
from bson import ObjectId
from fastapi import HTTPException, status
from langchain_core.documents import Document


async def get_note(note_id: str, user_id: str) -> NoteResponse:
    """
    Retrieve a single note by its ID for the specified user.

    Args:
        note_id (str): The note's ID.
        user_id (str): The ID of the authenticated user.

    Returns:
        NoteResponse: The retrieved note.

    Raises:
        HTTPException: If the note is not found.
    """
    logger.info(f"Retrieving note with id: {note_id} for user: {user_id}")
    cache_key = f"note:{user_id}:{note_id}"
    cached_note = await get_cache(cache_key)
    if cached_note:
        logger.info("Note found in cache.")
        return NoteResponse(**cached_note)

    note = await notes_collection.find_one(
        {"_id": ObjectId(note_id), "user_id": user_id}
    )
    if not note:
        logger.error("Note not found.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Note not found"
        )

    serialized_note = serialize_document(note)
    await set_cache(cache_key, serialized_note)
    logger.info("Note retrieved from DB and cached.")
    return NoteResponse(**serialized_note)


async def get_all_notes(user_id: str) -> list[NoteResponse]:
    """
    Retrieve all notes for the specified user.

    Args:
        user_id (str): The ID of the authenticated user.

    Returns:
        list[NoteResponse]: A list of the user's notes.
    """
    logger.info(f"Retrieving all notes for user: {user_id}")
    cache_key = f"notes:{user_id}"
    cached_notes = await get_cache(cache_key)
    if cached_notes and "notes" in cached_notes:
        cached_notes = cached_notes["notes"]
        logger.info("All notes found in cache.")
        return [NoteResponse(**note) for note in cached_notes]

    notes = await notes_collection.find({"user_id": user_id}).to_list(length=None)
    serialized_notes = [serialize_document(note) for note in notes]

    # Convert the list to a dictionary for caching
    notes_dict = {"notes": serialized_notes}
    await set_cache(cache_key, notes_dict)

    logger.info("Notes retrieved from DB and cached.")
    return [NoteResponse(**note) for note in serialized_notes]


async def update_note(note_id: str, note: NoteModel, user_id: str) -> NoteResponse:
    """
    Update an existing note by its ID for the specified user.

    Args:
        note_id (str): The ID of the note to update.
        note (NoteModel): The updated note data.
        user_id (str): The ID of the authenticated user.

    Returns:
        NoteResponse: The updated note.

    Raises:
        HTTPException: If the note is not found.
    """
    logger.info(f"Updating note with id: {note_id} for user: {user_id}")

    update_data = {k: v for k, v in note.model_dump().items() if v is not None}

    result = await notes_collection.update_one(
        {"_id": ObjectId(note_id), "user_id": user_id}, {"$set": update_data}
    )
    if result.matched_count == 0:
        logger.error("Note not found for update.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Note not found"
        )

    # Fetch the complete updated note
    updated_note = await notes_collection.find_one(
        {"_id": ObjectId(note_id), "user_id": user_id}
    )

    if not updated_note:
        raise ValueError(f"Note {note_id} not found after update")

    serialized_note = serialize_document(updated_note)

    # Update ChromaDB with the new content if client is provided
    if "plaintext" in update_data:
        try:
            chroma_notes_collection = await ChromaClient.get_langchain_client(
                collection_name="notes"
            )

            # Update the existing document in ChromaDB (no return value expected)
            await chroma_notes_collection.update_document(  # type: ignore[func-returns-value]
                document_id=note_id,
                document=Document(
                    page_content=update_data["plaintext"],
                ),
            )
            logger.info(f"Note with id {note_id} updated in ChromaDB")
        except Exception as e:
            # Log the error but don't fail the request if ChromaDB update fails
            logger.error(f"Failed to update note in ChromaDB: {str(e)}")

    # Invalidate caches for this note and for all notes of the user
    await delete_cache(f"note:{user_id}:{note_id}")
    await delete_cache(f"notes:{user_id}")

    # Update the cache with the new note data
    await set_cache(f"note:{user_id}:{note_id}", serialized_note)
    logger.info("Note updated and cache refreshed.")

    return NoteResponse(**serialized_note)


async def delete_note(note_id: str, user_id: str) -> None:
    """
    Delete a note by its ID for the specified user.

    Args:
        note_id (str): The ID of the note to delete.
        user_id (str): The ID of the authenticated user.

    Raises:
        HTTPException: If the note is not found.
    """
    logger.info(f"Deleting note with id: {note_id} for user: {user_id}")

    # Delete from MongoDB
    result = await notes_collection.delete_one(
        {"_id": ObjectId(note_id), "user_id": user_id}
    )
    if result.deleted_count == 0:
        logger.error("Note not found for deletion.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Note not found"
        )

    # Invalidate caches for this note and for all notes of the user
    await delete_cache(f"note:{user_id}:{note_id}")
    await delete_cache(f"notes:{user_id}")

    # Delete from ChromaDB if client is provided
    try:
        chroma_notes_collection = await ChromaClient.get_langchain_client(
            collection_name="notes"
        )
        await chroma_notes_collection.adelete(ids=[note_id])
        logger.info(f"Note with id {note_id} deleted from ChromaDB")
    except Exception as e:
        # Log the error but don't fail the request if ChromaDB deletion fails
        logger.error(f"Failed to delete note from ChromaDB: {str(e)}")

    logger.info("Note successfully deleted from MongoDB and cache invalidated.")


async def create_note_service(note: NoteModel, user_id: str) -> NoteResponse:
    """
    Create a new note for the authenticated user.

    Args:
        note (NoteModel): The note data.
        user_id (str): The ID of the authenticated user.

    Returns:
        NoteResponse: The created note.

    Raises:
        HTTPException: If note creation fails.
    """
    try:
        return await insert_note(note, user_id)
    except Exception as e:
        logger.error(f"Failed to create note: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to create note")


async def fetch_notes(context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Fetch similar notes and append their content to the last message.

    Args:
        context: The context containing message data.

    Returns:
        Updated context with notes data if found.
    """
    last_message = context["last_message"]
    query_text = context["query_text"]
    user = context["user"]

    notes = await search_notes_by_similarity(
        input_text=query_text,
        user_id=user.get("user_id"),
    )

    if notes:
        formatted_notes = []
        for note in notes:
            formatted_notes.append(
                f"- Title: {note.get('title', 'Untitled Note')}\n  Content: {note.get('content', '')}\n"
            )

        notes_text = "\n".join(formatted_notes)

        last_message["content"] = NOTES_PROMPT.format(
            message=last_message["content"], notes=notes_text
        )
        context["notes_added"] = True
    else:
        context["notes_added"] = False
    return context
