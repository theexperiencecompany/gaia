"""
Router module for note-related endpoints.

This module contains endpoints for creating, retrieving, updating, and deleting notes.
"""

from fastapi import APIRouter, Depends, status

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.decorators import tiered_rate_limit
from app.models.notes_models import NoteModel, NoteResponse
from app.services.notes_service import (
    create_note_service,
    delete_note,
    get_all_notes,
    get_note,
    update_note,
)

router = APIRouter()


@router.post("/notes", response_model=NoteResponse, status_code=status.HTTP_201_CREATED)
@tiered_rate_limit("notes")
async def create_note_endpoint(
    note: NoteModel,
    user: dict = Depends(get_current_user),
):
    """
    Create a new note for the authenticated user.

    Args:
        note (NoteModel): The note data.
        user (dict): The authenticated user information.

    Returns:
        NoteResponse: The created note.
    """
    return await create_note_service(note, user["user_id"])


@router.get("/notes/{note_id}", response_model=NoteResponse)
async def get_note_endpoint(note_id: str, user: dict = Depends(get_current_user)):
    """
    Retrieve a single note by its ID.

    Args:
        note_id (str): The note's ID.
        user (dict): The authenticated user information.

    Returns:
        NoteResponse: The retrieved note.
    """
    return await get_note(note_id, user["user_id"])


@router.get("/notes", response_model=list[NoteResponse])
async def get_all_notes_endpoint(user: dict = Depends(get_current_user)):
    """
    Retrieve all notes for the authenticated user.

    Args:
        user (dict): The authenticated user information.

    Returns:
        list[NoteResponse]: A list of the user's notes.
    """
    return await get_all_notes(user["user_id"])


@router.put("/notes/{note_id}", response_model=NoteResponse)
@tiered_rate_limit("notes")
async def update_note_endpoint(
    note_id: str,
    note: NoteModel,
    user: dict = Depends(get_current_user),
):
    """
    Update an existing note by its ID.

    Args:
        note_id (str): The ID of the note to update.
        note (NoteModel): The updated note data.
        user (dict): The authenticated user information.

    Returns:
        NoteResponse: The updated note.
    """
    return await update_note(note_id, note, user["user_id"])


@router.delete("/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
@tiered_rate_limit("notes")
async def delete_note_endpoint(
    note_id: str,
    user: dict = Depends(get_current_user),
):
    """
    Delete a note by its ID.

    Args:
        note_id (str): The ID of the note to delete.
        user (dict): The authenticated user information.
    """
    await delete_note(note_id, user["user_id"])
