"""
Router module for note-related endpoints.

This module contains endpoints for creating, retrieving, updating, and deleting notes.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.constants.log_tags import LogTag
from app.decorators import tiered_rate_limit
from app.models.notes_models import NoteModel, NoteResponse
from app.models.user_models import AuthenticatedUser
from app.services.analytics_service import AnalyticsEvents, capture_context_event
from app.services.notes_service import (
    create_note_service,
    delete_note,
    get_all_notes,
    get_note,
    update_note,
)
from shared.py.wide_events import log

router = APIRouter()


@router.post("/notes", response_model=NoteResponse, status_code=status.HTTP_201_CREATED)
@tiered_rate_limit("notes")
async def create_note_endpoint(
    note: NoteModel,
    user: AuthenticatedUser = Depends(get_current_user),
) -> NoteResponse:
    """Create a new note for the authenticated user."""
    log.set(operation="create_note")
    try:
        result = await create_note_service(note, user["user_id"])
        capture_context_event(AnalyticsEvents.NOTE_CREATED)
        log.set(outcome="success")
        return result
    except HTTPException:
        raise  # let a deliberate 404/4xx from the service through, not masked as 500
    except Exception as e:
        log.error(
            f"{LogTag.API} Error creating note",
            user_id=user["user_id"],
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create note",
        ) from e


@router.get("/notes/{note_id}", response_model=NoteResponse)
async def get_note_endpoint(
    note_id: str, user: AuthenticatedUser = Depends(get_current_user)
) -> NoteResponse:
    """Retrieve a single note by its ID."""
    log.set(operation="get_note")
    try:
        result = await get_note(note_id, user["user_id"])
        log.set(note_id=note_id)
        log.set(outcome="success")
        return result
    except HTTPException:
        raise  # let a deliberate 404/4xx from the service through, not masked as 500
    except Exception as e:
        log.error(
            f"{LogTag.API} Error getting note",
            note_id=note_id,
            user_id=user["user_id"],
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve note",
        ) from e


@router.get("/notes", response_model=list[NoteResponse])
async def get_all_notes_endpoint(
    user: AuthenticatedUser = Depends(get_current_user),
) -> list[NoteResponse]:
    """Retrieve all notes for the authenticated user."""
    log.set(operation="list_notes")
    try:
        notes = await get_all_notes(user["user_id"])
        log.set(result_count=len(notes))
        log.set(outcome="success")
        return notes
    except HTTPException:
        raise  # let a deliberate 404/4xx from the service through, not masked as 500
    except Exception as e:
        log.error(
            f"{LogTag.API} Error listing notes",
            user_id=user["user_id"],
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve notes",
        ) from e


@router.put("/notes/{note_id}", response_model=NoteResponse)
@tiered_rate_limit("notes")
async def update_note_endpoint(
    note_id: str,
    note: NoteModel,
    user: AuthenticatedUser = Depends(get_current_user),
) -> NoteResponse:
    """Update an existing note by its ID."""
    log.set(operation="update_note")
    try:
        result = await update_note(note_id, note, user["user_id"])
        capture_context_event(AnalyticsEvents.NOTE_UPDATED)
        log.set(note_id=note_id)
        log.set(outcome="success")
        return result
    except HTTPException:
        raise  # let a deliberate 404/4xx from the service through, not masked as 500
    except Exception as e:
        log.error(
            f"{LogTag.API} Error updating note",
            note_id=note_id,
            user_id=user["user_id"],
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update note",
        ) from e


@router.delete("/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
@tiered_rate_limit("notes")
async def delete_note_endpoint(
    note_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
) -> None:
    """Delete a note by its ID."""
    log.set(operation="delete_note")
    try:
        await delete_note(note_id, user["user_id"])
        capture_context_event(AnalyticsEvents.NOTE_DELETED)
        log.set(note_id=note_id)
        log.set(outcome="success")
    except HTTPException:
        raise  # let a deliberate 404/4xx from the service through, not masked as 500
    except Exception as e:
        log.error(
            f"{LogTag.API} Error deleting note",
            note_id=note_id,
            user_id=user["user_id"],
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete note",
        ) from e
