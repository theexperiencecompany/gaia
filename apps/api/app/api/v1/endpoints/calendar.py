from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.api.v1.dependencies.google_scope_dependencies import require_integration
from app.decorators import tiered_rate_limit
from app.models.calendar_models import (
    BatchEventCreateRequest,
    BatchEventDeleteRequest,
    BatchEventUpdateRequest,
    CalendarPreferencesUpdateRequest,
    EventCreateRequest,
    EventDeleteRequest,
    EventUpdateRequest,
)
from app.services import calendar_service
from app.services.calendar_service import (
    delete_calendar_event,
    update_calendar_event,
)
from app.utils.composio_token_utils import get_google_calendar_token
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter()


class CalendarEventsQueryRequest(BaseModel):
    """Request model for querying calendar events via POST to avoid URL length limits."""

    selected_calendars: List[str] = Field(
        ..., description="List of calendar IDs to fetch events from"
    )
    start_date: Optional[str] = Field(
        None, description="Start date in YYYY-MM-DD format"
    )
    end_date: Optional[str] = Field(None, description="End date in YYYY-MM-DD format")
    fetch_all: bool = Field(
        True,
        description="Fetch ALL events in range (true) or limit per calendar (false)",
    )
    max_results: Optional[int] = Field(
        None,
        ge=1,
        le=250,
        description="Max events per calendar (only used if fetch_all=false)",
    )


@router.get("/calendar/list", summary="Get Calendar List")
async def get_calendar_list(
    current_user: dict = Depends(require_integration("calendar")),
):
    """
    Retrieve the list of calendars for the authenticated user.

    Returns:
        A list of calendars for the user.

    Raises:
        HTTPException: If an error occurs during calendar retrieval.
    """
    try:
        # Get user_id from the authenticated user object
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        # Get token from Composio
        access_token = get_google_calendar_token(str(user_id))

        return calendar_service.list_calendars(access_token)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/calendar/events/query", summary="Query Events from Selected Calendars")
async def query_events(
    request: CalendarEventsQueryRequest,
    current_user: dict = Depends(require_integration("calendar")),
):
    """
    Query events from selected calendars using POST to avoid URL length limits.

    Uses date-based pagination:
    - Specify start_date and end_date to define the time window
    - Set fetch_all=True to get ALL events in that window (default, recommended for calendar page)
    - Or set fetch_all=False and specify max_results to limit events per calendar

    The response includes:
    - events: List of all events in the range
    - has_more: Boolean indicating if any calendar was truncated
    - calendars_truncated: List of calendar IDs that hit the safety limit

    Returns:
        Events from selected calendars, deduplicated and sorted by start time.

    Raises:
        HTTPException: If event retrieval fails.
    """
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        # Convert start_date and end_date to time_min and time_max for Google Calendar API
        time_min = None
        time_max = None
        if request.start_date:
            try:
                start_dt = datetime.strptime(request.start_date, "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
                time_min = start_dt.isoformat()
            except ValueError:
                raise HTTPException(
                    status_code=400, detail="Invalid start_date format. Use YYYY-MM-DD"
                )

        if request.end_date:
            try:
                end_dt = datetime.strptime(request.end_date, "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
                # Add 24 hours to include the entire end day
                end_dt = end_dt + timedelta(days=1)
                time_max = end_dt.isoformat()
            except ValueError:
                raise HTTPException(
                    status_code=400, detail="Invalid end_date format. Use YYYY-MM-DD"
                )

        # Get token from Composio
        access_token = get_google_calendar_token(str(user_id))

        return calendar_service.get_calendar_events(
            user_id=user_id,
            access_token=access_token,
            page_token=None,
            selected_calendars=request.selected_calendars,
            time_min=time_min,
            time_max=time_max,
            max_results=request.max_results,
            fetch_all=request.fetch_all,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/calendar/events", summary="Get Calendar Events (Simple Queries)")
async def get_events(
    page_token: Optional[str] = None,
    selected_calendars: Optional[List[str]] = Query(None),
    start_date: Optional[str] = None,  # YYYY-MM-DD format
    end_date: Optional[str] = None,  # YYYY-MM-DD format
    max_results: int = Query(100, ge=1, le=250),
    fetch_all: bool = Query(False, description="Fetch ALL events in date range"),
    current_user: dict = Depends(require_integration("calendar")),
):
    """
    Get calendar events using GET - ideal for simple queries with few parameters.

    Use Cases:
    - Dashboard widgets (upcoming events)
    - Small date ranges with few calendars
    - Simple API integrations

    For complex queries with many calendars, use POST /calendar/events/query to avoid
    URL length limits (2000 char limit).

    Returns:
        Events from selected calendars, deduplicated and sorted by start time.

    Raises:
        HTTPException: If event retrieval fails.
    """
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        # Convert start_date and end_date to time_min and time_max for Google Calendar API
        time_min = None
        time_max = None

        if start_date:
            try:
                # Convert YYYY-MM-DD to start of day in UTC
                start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
                time_min = start_dt.isoformat()
            except ValueError:
                raise HTTPException(
                    status_code=400, detail="Invalid start_date format. Use YYYY-MM-DD"
                )

        if end_date:
            try:
                # Convert YYYY-MM-DD to end of day in UTC
                end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
                # Add 24 hours to include the entire end day
                end_dt = end_dt + timedelta(days=1)
                time_max = end_dt.isoformat()
            except ValueError:
                raise HTTPException(
                    status_code=400, detail="Invalid end_date format. Use YYYY-MM-DD"
                )

        # Get token from Composio
        access_token = get_google_calendar_token(str(user_id))

        return calendar_service.get_calendar_events(
            user_id=user_id,
            access_token=access_token,
            page_token=page_token,
            selected_calendars=selected_calendars,
            time_min=time_min,
            time_max=time_max,
            max_results=max_results,
            fetch_all=fetch_all,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/calendar/{calendar_id}/events", summary="Get Events by Calendar ID")
async def get_events_by_calendar(
    calendar_id: str,
    start_date: Optional[str] = None,  # YYYY-MM-DD format
    end_date: Optional[str] = None,  # YYYY-MM-DD format
    page_token: Optional[str] = None,
    current_user: dict = Depends(require_integration("calendar")),
):
    """
    Fetch events for a specific calendar identified by its ID.

    Args:
        calendar_id (str): The unique calendar identifier.
        time_min (Optional[str]): Lower bound of event start time.
        time_max (Optional[str]): Upper bound of event end time.
        page_token (Optional[str]): Pagination token for fetching further events.

    Returns:
        A list of events for the specified calendar.

    Raises:
        HTTPException: If the event retrieval process encounters an error.
    """
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        # Convert start_date and end_date to time_min and time_max for Google Calendar API
        time_min = None
        time_max = None

        if start_date:
            try:
                # Convert YYYY-MM-DD to start of day in UTC
                start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
                time_min = start_dt.isoformat()
            except ValueError:
                raise HTTPException(
                    status_code=400, detail="Invalid start_date format. Use YYYY-MM-DD"
                )

        if end_date:
            try:
                # Convert YYYY-MM-DD to end of day in UTC
                end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
                # Add 24 hours to include the entire end day
                end_dt = end_dt + timedelta(days=1)
                time_max = end_dt.isoformat()
            except ValueError:
                raise HTTPException(
                    status_code=400, detail="Invalid end_date format. Use YYYY-MM-DD"
                )

        # Get token from Composio
        access_token = get_google_calendar_token(str(user_id))

        return calendar_service.get_calendar_events_by_id(
            calendar_id=calendar_id,
            access_token=access_token,
            page_token=page_token,
            time_min=time_min,
            time_max=time_max,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/calendar/event", summary="Create a Calendar Event")
@tiered_rate_limit("calendar_management")
async def create_event(
    event: EventCreateRequest,
    current_user: dict = Depends(require_integration("calendar")),
):
    """
    Create a new calendar event. This endpoint accepts non-canonical timezone names
    which are normalized in the service.

    Args:
        event (EventCreateRequest): The event creation request details.

    Returns:
        The details of the created event.

    Raises:
        HTTPException: If event creation fails.
    """
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        # Get token from Composio
        access_token = get_google_calendar_token(str(user_id))

        return calendar_service.create_calendar_event(event, access_token, user_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/calendar/preferences", summary="Get User Calendar Preferences")
async def get_calendar_preferences(
    current_user: dict = Depends(require_integration("calendar")),
):
    """
    Retrieve the user's selected calendar preferences from the database.

    Returns:
        A dictionary with the user's selected calendar IDs.

    Raises:
        HTTPException: If the user is not authenticated or preferences are not found.
    """
    try:
        return calendar_service.get_user_calendar_preferences(
            str(current_user.get("user_id", ""))
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/calendar/preferences", summary="Update User Calendar Preferences")
@tiered_rate_limit("calendar_management")
async def update_calendar_preferences(
    preferences: CalendarPreferencesUpdateRequest,
    current_user: dict = Depends(require_integration("calendar")),
):
    """
    Update the user's selected calendar preferences in the database.

    Args:
        preferences (CalendarPreferencesUpdateRequest): The selected calendar IDs to update.

    Returns:
        A message indicating the result of the update operation.

    Raises:
        HTTPException: If the user is not authenticated.
    """
    try:
        return calendar_service.update_user_calendar_preferences(
            current_user["user_id"], preferences.selected_calendars
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/calendar/event", summary="Delete a Calendar Event")
@tiered_rate_limit("calendar_management")
async def delete_event(
    event: EventDeleteRequest,
    current_user: dict = Depends(require_integration("calendar")),
):
    """
    Delete a calendar event. This endpoint requires the event ID and optionally the calendar ID.

    Args:
        event (EventDeleteRequest): The event deletion request details.

    Returns:
        A confirmation message indicating successful deletion.

    Raises:
        HTTPException: If event deletion fails.
    """
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        # Get token from Composio
        access_token = get_google_calendar_token(str(user_id))

        return delete_calendar_event(event, access_token, user_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/calendar/event", summary="Update a Calendar Event")
@tiered_rate_limit("calendar_management")
async def update_event(
    event: EventUpdateRequest,
    current_user: dict = Depends(require_integration("calendar")),
):
    """
    Update a calendar event. This endpoint allows partial updates of event fields.
    Only provided fields will be updated, preserving existing values for omitted fields.

    Args:
        event (EventUpdateRequest): The event update request details.

    Returns:
        The details of the updated event.

    Raises:
        HTTPException: If event update fails.
    """
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        # Get token from Composio
        access_token = get_google_calendar_token(str(user_id))

        return update_calendar_event(event, access_token, user_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/calendar/events/batch", summary="Create Multiple Calendar Events")
@tiered_rate_limit("calendar_management")
async def create_events_batch(
    batch_request: BatchEventCreateRequest,
    current_user: dict = Depends(require_integration("calendar")),
):
    """
    Create multiple calendar events in a batch operation.

    Args:
        batch_request (BatchEventCreateRequest): The batch event creation request.

    Returns:
        A dict with successful and failed event creations.

    Raises:
        HTTPException: If batch creation fails.
    """
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        # Get token from Composio
        access_token = get_google_calendar_token(str(user_id))

        results: Dict[str, List[Any]] = {"successful": [], "failed": []}

        for event in batch_request.events:
            try:
                created_event = calendar_service.create_calendar_event(
                    event, access_token, user_id
                )
                results["successful"].append(created_event)
            except Exception as e:
                results["failed"].append(
                    {
                        "event": event.summary,
                        "error": str(e),
                    }
                )

        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/calendar/events/batch", summary="Update Multiple Calendar Events")
@tiered_rate_limit("calendar_management")
async def update_events_batch(
    batch_request: BatchEventUpdateRequest,
    current_user: dict = Depends(require_integration("calendar")),
):
    """
    Update multiple calendar events in a batch operation.

    Args:
        batch_request (BatchEventUpdateRequest): The batch event update request.

    Returns:
        A dict with successful and failed event updates.

    Raises:
        HTTPException: If batch update fails.
    """
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        # Get token from Composio
        access_token = get_google_calendar_token(str(user_id))

        results: dict[str, list] = {"successful": [], "failed": []}

        for event in batch_request.events:
            try:
                updated_event = update_calendar_event(event, access_token, user_id)
                results["successful"].append(updated_event)
            except Exception as e:
                results["failed"].append(
                    {
                        "event_id": event.event_id,
                        "error": str(e),
                    }
                )

        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/calendar/events/batch", summary="Delete Multiple Calendar Events")
@tiered_rate_limit("calendar_management")
async def delete_events_batch(
    batch_request: BatchEventDeleteRequest,
    current_user: dict = Depends(require_integration("calendar")),
):
    """
    Delete multiple calendar events in a batch operation.

    Args:
        batch_request (BatchEventDeleteRequest): The batch event deletion request.

    Returns:
        A dict with successful and failed event deletions.

    Raises:
        HTTPException: If batch deletion fails.
    """
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        # Get token from Composio
        access_token = get_google_calendar_token(str(user_id))

        results: dict[str, list] = {"successful": [], "failed": []}

        for event in batch_request.events:
            try:
                delete_calendar_event(event, access_token, user_id)
                results["successful"].append(
                    {
                        "event_id": event.event_id,
                        "calendar_id": event.calendar_id,
                    }
                )
            except Exception as e:
                results["failed"].append(
                    {
                        "event_id": event.event_id,
                        "error": str(e),
                    }
                )

        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
