from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.api.v1.dependencies.google_scope_dependencies import require_integration
from app.decorators import tiered_rate_limit
from app.models.calendar_models import (
    BatchEventCreateRequest,
    BatchEventDeleteRequest,
    BatchEventUpdateRequest,
    CalendarEventsQueryRequest,
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
from fastapi import APIRouter, Depends, HTTPException, Query
from shared.py.wide_events import log

router = APIRouter()


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
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        log.set(user={"id": user_id}, calendar={"operation": "list_calendars"})

        calendars = calendar_service.list_calendars(str(user_id))
        log.set(
            calendar={
                "operation": "list_calendars",
                "event_count": len(calendars) if isinstance(calendars, list) else None,
            }
        )
        return calendars
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/calendar/events/query", summary="Query Events from Selected Calendars")
async def query_events(
    request: CalendarEventsQueryRequest,
    current_user: dict = Depends(require_integration("calendar")),
):
    """
    Query events from selected calendars using POST to avoid URL length limits.
    """
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

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
                end_dt = end_dt + timedelta(days=1)
                time_max = end_dt.isoformat()
            except ValueError:
                raise HTTPException(
                    status_code=400, detail="Invalid end_date format. Use YYYY-MM-DD"
                )

        time_range_days = None
        if time_min and time_max:
            try:
                time_range_days = (
                    datetime.fromisoformat(time_max) - datetime.fromisoformat(time_min)
                ).days
            except Exception:  # nosec B110
                pass

        log.set(
            user={"id": user_id},
            calendar={
                "operation": "get_events",
                "calendar_id": None,
                "time_range_days": time_range_days,
            },
        )

        result = calendar_service.get_calendar_events(
            user_id=str(user_id),
            page_token=None,
            selected_calendars=request.selected_calendars,
            time_min=time_min,
            time_max=time_max,
            max_results=request.max_results,
            fetch_all=request.fetch_all,
        )
        events = result.get("events", []) if isinstance(result, dict) else result
        log.set(
            calendar={
                "operation": "get_events",
                "event_count": len(events) if isinstance(events, list) else None,
            }
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/calendar/events", summary="Get Calendar Events (Simple Queries)")
async def get_events(
    page_token: Optional[str] = None,
    selected_calendars: Optional[List[str]] = Query(None),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    max_results: int = Query(100, ge=1, le=250),
    fetch_all: bool = Query(False, description="Fetch ALL events in date range"),
    current_user: dict = Depends(require_integration("calendar")),
):
    """Get calendar events using GET — ideal for simple queries with few parameters."""
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        time_min = None
        time_max = None

        if start_date:
            try:
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
                end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
                end_dt = end_dt + timedelta(days=1)
                time_max = end_dt.isoformat()
            except ValueError:
                raise HTTPException(
                    status_code=400, detail="Invalid end_date format. Use YYYY-MM-DD"
                )

        time_range_days = None
        if time_min and time_max:
            try:
                time_range_days = (
                    datetime.fromisoformat(time_max) - datetime.fromisoformat(time_min)
                ).days
            except Exception:  # nosec B110
                pass

        log.set(
            user={"id": user_id},
            calendar={
                "operation": "get_events",
                "calendar_id": None,
                "time_range_days": time_range_days,
            },
        )

        result = calendar_service.get_calendar_events(
            user_id=str(user_id),
            page_token=page_token,
            selected_calendars=selected_calendars,
            time_min=time_min,
            time_max=time_max,
            max_results=max_results,
            fetch_all=fetch_all,
        )
        events = result.get("events", []) if isinstance(result, dict) else result
        log.set(
            calendar={
                "operation": "get_events",
                "event_count": len(events) if isinstance(events, list) else None,
            }
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/calendar/{calendar_id}/events", summary="Get Events by Calendar ID")
async def get_events_by_calendar(
    calendar_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    page_token: Optional[str] = None,
    current_user: dict = Depends(require_integration("calendar")),
):
    """Fetch events for a specific calendar identified by its ID."""
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        time_min = None
        time_max = None

        if start_date:
            try:
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
                end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
                end_dt = end_dt + timedelta(days=1)
                time_max = end_dt.isoformat()
            except ValueError:
                raise HTTPException(
                    status_code=400, detail="Invalid end_date format. Use YYYY-MM-DD"
                )

        time_range_days = None
        if time_min and time_max:
            try:
                time_range_days = (
                    datetime.fromisoformat(time_max) - datetime.fromisoformat(time_min)
                ).days
            except Exception:  # nosec B110
                pass

        log.set(
            user={"id": user_id},
            calendar={
                "operation": "get_events",
                "calendar_id": calendar_id,
                "time_range_days": time_range_days,
            },
        )

        result = calendar_service.get_calendar_events_by_id(
            calendar_id=calendar_id,
            user_id=str(user_id),
            page_token=page_token,
            time_min=time_min,
            time_max=time_max,
        )
        events = result.get("events", []) if isinstance(result, dict) else result
        log.set(
            calendar={
                "operation": "get_events",
                "event_count": len(events) if isinstance(events, list) else None,
            }
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/calendar/event", summary="Create a Calendar Event")
@tiered_rate_limit("calendar_management")
async def create_event(
    event: EventCreateRequest,
    current_user: dict = Depends(require_integration("calendar")),
):
    """Create a new calendar event."""
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        log.set(
            user={"id": user_id},
            calendar={
                "operation": "create_event",
                "calendar_id": getattr(event, "calendar_id", None),
            },
        )

        return calendar_service.create_calendar_event(event, str(user_id))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/calendar/preferences", summary="Get User Calendar Preferences")
async def get_calendar_preferences(
    current_user: dict = Depends(require_integration("calendar")),
):
    """Retrieve the user's selected calendar preferences from the database."""
    try:
        user_id = current_user.get("user_id")
        log.set(user={"id": user_id}, calendar={"operation": "get_preferences"})
        return calendar_service.get_user_calendar_preferences(str(user_id or ""))
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
    """Update the user's selected calendar preferences in the database."""
    try:
        user_id = current_user.get("user_id")
        log.set(user={"id": user_id}, calendar={"operation": "update_preferences"})
        return calendar_service.update_user_calendar_preferences(
            str(user_id), preferences.selected_calendars
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/calendar/event", summary="Delete a Calendar Event")
@tiered_rate_limit("calendar_management")
async def delete_event(
    event: EventDeleteRequest,
    current_user: dict = Depends(require_integration("calendar")),
):
    """Delete a calendar event."""
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        log.set(user={"id": user_id}, calendar={"operation": "delete_event"})

        return delete_calendar_event(event, str(user_id))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/calendar/event", summary="Update a Calendar Event")
@tiered_rate_limit("calendar_management")
async def update_event(
    event: EventUpdateRequest,
    current_user: dict = Depends(require_integration("calendar")),
):
    """Update a calendar event."""
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        log.set(user={"id": user_id}, calendar={"operation": "update_event"})

        return update_calendar_event(event, str(user_id))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/calendar/events/batch", summary="Create Multiple Calendar Events")
@tiered_rate_limit("calendar_management")
async def create_events_batch(
    batch_request: BatchEventCreateRequest,
    current_user: dict = Depends(require_integration("calendar")),
):
    """Create multiple calendar events in a batch operation."""
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        log.set(user={"id": user_id}, calendar={"operation": "batch_create"})

        results: Dict[str, List[Any]] = {"successful": [], "failed": []}

        for event in batch_request.events:
            try:
                created_event = calendar_service.create_calendar_event(
                    event, str(user_id)
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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/calendar/events/batch", summary="Update Multiple Calendar Events")
@tiered_rate_limit("calendar_management")
async def update_events_batch(
    batch_request: BatchEventUpdateRequest,
    current_user: dict = Depends(require_integration("calendar")),
):
    """Update multiple calendar events in a batch operation."""
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        log.set(user={"id": user_id}, calendar={"operation": "batch_update"})

        results: dict[str, list] = {"successful": [], "failed": []}

        for event in batch_request.events:
            try:
                updated_event = update_calendar_event(event, str(user_id))
                results["successful"].append(updated_event)
            except Exception as e:
                results["failed"].append(
                    {
                        "event_id": event.event_id,
                        "error": str(e),
                    }
                )

        return results
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/calendar/events/batch", summary="Delete Multiple Calendar Events")
@tiered_rate_limit("calendar_management")
async def delete_events_batch(
    batch_request: BatchEventDeleteRequest,
    current_user: dict = Depends(require_integration("calendar")),
):
    """Delete multiple calendar events in a batch operation."""
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        log.set(user={"id": user_id}, calendar={"operation": "batch_delete"})

        results: dict[str, list] = {"successful": [], "failed": []}

        for event in batch_request.events:
            try:
                delete_calendar_event(event, str(user_id))
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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
