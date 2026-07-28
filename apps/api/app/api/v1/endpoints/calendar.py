import contextlib
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.v1.dependencies.google_scope_dependencies import require_integration_user_id
from app.decorators import tiered_rate_limit
from app.models.calendar_models import (
    BatchEventCreateFailure,
    BatchEventCreateRequest,
    BatchEventCreateResponse,
    BatchEventDeleteRequest,
    BatchEventDeleteResponse,
    BatchEventDeleteSuccess,
    BatchEventFailure,
    BatchEventUpdateRequest,
    BatchEventUpdateResponse,
    CalendarEventPageResponse,
    CalendarEventsQueryRequest,
    CalendarEventsResponse,
    CalendarListResponse,
    CalendarPreferencesResponse,
    CalendarPreferencesUpdateRequest,
    CalendarPreferencesUpdateResponse,
    EventCreateRequest,
    EventDeleteRequest,
    EventDeleteResponse,
    EventUpdateRequest,
    GoogleCalendarEventResource,
)
from app.services import calendar_service
from app.services.calendar_service import (
    delete_calendar_event,
    update_calendar_event,
)
from shared.py.wide_events import log

router = APIRouter()


@router.get("/calendar/list", summary="Get Calendar List")
async def get_calendar_list(
    user_id: str = Depends(require_integration_user_id("calendar")),
) -> CalendarListResponse:
    """Retrieve the list of calendars for the authenticated user."""
    try:
        log.set(user={"id": user_id}, calendar={"operation": "list_calendars"})

        # short=False (the default) always returns the calendarList envelope, not
        # the trimmed list branch of list_calendars' union return type.
        calendars = CalendarListResponse.model_validate(
            await calendar_service.list_calendars(user_id)
        )
        log.set(
            calendar={
                "operation": "list_calendars",
                "event_count": len(calendars.items),
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
    user_id: str = Depends(require_integration_user_id("calendar")),
) -> CalendarEventsResponse:
    """
    Query events from selected calendars using POST to avoid URL length limits.
    """
    try:
        time_min = None
        time_max = None
        if request.start_date:
            try:
                start_dt = datetime.strptime(request.start_date, "%Y-%m-%d").replace(tzinfo=UTC)
                time_min = start_dt.isoformat()
            except ValueError:
                raise HTTPException(
                    status_code=400, detail="Invalid start_date format. Use YYYY-MM-DD"
                )

        if request.end_date:
            try:
                end_dt = datetime.strptime(request.end_date, "%Y-%m-%d").replace(tzinfo=UTC)
                end_dt = end_dt + timedelta(days=1)
                time_max = end_dt.isoformat()
            except ValueError:
                raise HTTPException(
                    status_code=400, detail="Invalid end_date format. Use YYYY-MM-DD"
                )

        time_range_days = None
        if time_min and time_max:
            with contextlib.suppress(Exception):
                time_range_days = (
                    datetime.fromisoformat(time_max) - datetime.fromisoformat(time_min)
                ).days

        log.set(
            user={"id": user_id},
            calendar={
                "operation": "get_events",
                "calendar_id": None,
                "time_range_days": time_range_days,
            },
        )

        result = CalendarEventsResponse.model_validate(
            await calendar_service.get_calendar_events(
                user_id=user_id,
                page_token=None,
                selected_calendars=request.selected_calendars,
                time_min=time_min,
                time_max=time_max,
                max_results=request.max_results,
                fetch_all=request.fetch_all,
            )
        )
        log.set(
            calendar={
                "operation": "get_events",
                "event_count": len(result.events),
            }
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/calendar/events", summary="Get Calendar Events (Simple Queries)")
async def get_events(
    page_token: str | None = None,
    selected_calendars: list[str] | None = Query(None),
    start_date: str | None = None,
    end_date: str | None = None,
    max_results: int = Query(100, ge=1, le=250),
    fetch_all: bool = Query(False, description="Fetch ALL events in date range"),
    user_id: str = Depends(require_integration_user_id("calendar")),
) -> CalendarEventsResponse:
    """Get calendar events using GET — ideal for simple queries with few parameters."""
    try:
        time_min = None
        time_max = None

        if start_date:
            try:
                start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=UTC)
                time_min = start_dt.isoformat()
            except ValueError:
                raise HTTPException(
                    status_code=400, detail="Invalid start_date format. Use YYYY-MM-DD"
                )

        if end_date:
            try:
                end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=UTC)
                end_dt = end_dt + timedelta(days=1)
                time_max = end_dt.isoformat()
            except ValueError:
                raise HTTPException(
                    status_code=400, detail="Invalid end_date format. Use YYYY-MM-DD"
                )

        time_range_days = None
        if time_min and time_max:
            with contextlib.suppress(Exception):
                time_range_days = (
                    datetime.fromisoformat(time_max) - datetime.fromisoformat(time_min)
                ).days

        log.set(
            user={"id": user_id},
            calendar={
                "operation": "get_events",
                "calendar_id": None,
                "time_range_days": time_range_days,
            },
        )

        result = CalendarEventsResponse.model_validate(
            await calendar_service.get_calendar_events(
                user_id=user_id,
                page_token=page_token,
                selected_calendars=selected_calendars,
                time_min=time_min,
                time_max=time_max,
                max_results=max_results,
                fetch_all=fetch_all,
            )
        )
        log.set(
            calendar={
                "operation": "get_events",
                "event_count": len(result.events),
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
    start_date: str | None = None,
    end_date: str | None = None,
    page_token: str | None = None,
    user_id: str = Depends(require_integration_user_id("calendar")),
) -> CalendarEventPageResponse:
    """Fetch events for a specific calendar identified by its ID."""
    try:
        time_min = None
        time_max = None

        if start_date:
            try:
                start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=UTC)
                time_min = start_dt.isoformat()
            except ValueError:
                raise HTTPException(
                    status_code=400, detail="Invalid start_date format. Use YYYY-MM-DD"
                )

        if end_date:
            try:
                end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=UTC)
                end_dt = end_dt + timedelta(days=1)
                time_max = end_dt.isoformat()
            except ValueError:
                raise HTTPException(
                    status_code=400, detail="Invalid end_date format. Use YYYY-MM-DD"
                )

        time_range_days = None
        if time_min and time_max:
            with contextlib.suppress(Exception):
                time_range_days = (
                    datetime.fromisoformat(time_max) - datetime.fromisoformat(time_min)
                ).days

        log.set(
            user={"id": user_id},
            calendar={
                "operation": "get_events",
                "calendar_id": calendar_id,
                "time_range_days": time_range_days,
            },
        )

        result = await calendar_service.get_calendar_events_by_id(
            calendar_id=calendar_id,
            user_id=user_id,
            page_token=page_token,
            time_min=time_min,
            time_max=time_max,
        )
        log.set(
            calendar={
                "operation": "get_events",
                "event_count": len(result.events),
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
    user_id: str = Depends(require_integration_user_id("calendar")),
) -> GoogleCalendarEventResource:
    """Create a new calendar event."""
    try:
        log.set(
            user={"id": user_id},
            calendar={
                "operation": "create_event",
                "calendar_id": event.calendar_id,
            },
        )

        return GoogleCalendarEventResource.model_validate(
            await calendar_service.create_calendar_event(event, user_id)
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/calendar/preferences", summary="Get User Calendar Preferences")
async def get_calendar_preferences(
    user_id: str = Depends(require_integration_user_id("calendar")),
) -> CalendarPreferencesResponse:
    """Retrieve the user's selected calendar preferences from the database."""
    try:
        log.set(user={"id": user_id}, calendar={"operation": "get_preferences"})
        return await calendar_service.get_user_calendar_preferences(user_id)
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/calendar/preferences", summary="Update User Calendar Preferences")
@tiered_rate_limit("calendar_management")
async def update_calendar_preferences(
    preferences: CalendarPreferencesUpdateRequest,
    user_id: str = Depends(require_integration_user_id("calendar")),
) -> CalendarPreferencesUpdateResponse:
    """Update the user's selected calendar preferences in the database."""
    try:
        log.set(user={"id": user_id}, calendar={"operation": "update_preferences"})
        return await calendar_service.update_user_calendar_preferences(
            user_id, preferences.selected_calendars
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/calendar/event", summary="Delete a Calendar Event")
@tiered_rate_limit("calendar_management")
async def delete_event(
    event: EventDeleteRequest,
    user_id: str = Depends(require_integration_user_id("calendar")),
) -> EventDeleteResponse:
    """Delete a calendar event."""
    try:
        log.set(user={"id": user_id}, calendar={"operation": "delete_event"})

        return await delete_calendar_event(event, user_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/calendar/event", summary="Update a Calendar Event")
@tiered_rate_limit("calendar_management")
async def update_event(
    event: EventUpdateRequest,
    user_id: str = Depends(require_integration_user_id("calendar")),
) -> GoogleCalendarEventResource:
    """Update a calendar event."""
    try:
        log.set(user={"id": user_id}, calendar={"operation": "update_event"})

        return GoogleCalendarEventResource.model_validate(
            await update_calendar_event(event, user_id)
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/calendar/events/batch", summary="Create Multiple Calendar Events")
@tiered_rate_limit("calendar_management")
async def create_events_batch(
    batch_request: BatchEventCreateRequest,
    user_id: str = Depends(require_integration_user_id("calendar")),
) -> BatchEventCreateResponse:
    """Create multiple calendar events in a batch operation."""
    try:
        log.set(user={"id": user_id}, calendar={"operation": "batch_create"})

        successful: list[GoogleCalendarEventResource] = []
        failed: list[BatchEventCreateFailure] = []

        for event in batch_request.events:
            try:
                created_event = await calendar_service.create_calendar_event(event, user_id)
            except Exception as e:
                failed.append(BatchEventCreateFailure(event=event.summary, error=str(e)))
                continue
            # Validated outside the except above on purpose: the event already
            # exists in the user's calendar by now, so a response-shape surprise
            # must not be reported as a failure — the user would retry and end up
            # with a duplicate event.
            successful.append(GoogleCalendarEventResource.model_validate(created_event))

        return BatchEventCreateResponse(successful=successful, failed=failed)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/calendar/events/batch", summary="Update Multiple Calendar Events")
@tiered_rate_limit("calendar_management")
async def update_events_batch(
    batch_request: BatchEventUpdateRequest,
    user_id: str = Depends(require_integration_user_id("calendar")),
) -> BatchEventUpdateResponse:
    """Update multiple calendar events in a batch operation."""
    try:
        log.set(user={"id": user_id}, calendar={"operation": "batch_update"})

        successful: list[GoogleCalendarEventResource] = []
        failed: list[BatchEventFailure] = []

        for event in batch_request.events:
            try:
                updated_event = await update_calendar_event(event, user_id)
            except Exception as e:
                failed.append(BatchEventFailure(event_id=event.event_id, error=str(e)))
                continue
            # See batch-create above: the update already landed, so validation of
            # the echoed payload must not reclassify it as failed.
            successful.append(GoogleCalendarEventResource.model_validate(updated_event))

        return BatchEventUpdateResponse(successful=successful, failed=failed)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/calendar/events/batch", summary="Delete Multiple Calendar Events")
@tiered_rate_limit("calendar_management")
async def delete_events_batch(
    batch_request: BatchEventDeleteRequest,
    user_id: str = Depends(require_integration_user_id("calendar")),
) -> BatchEventDeleteResponse:
    """Delete multiple calendar events in a batch operation."""
    try:
        log.set(user={"id": user_id}, calendar={"operation": "batch_delete"})

        successful: list[BatchEventDeleteSuccess] = []
        failed: list[BatchEventFailure] = []

        for event in batch_request.events:
            try:
                await delete_calendar_event(event, user_id)
                successful.append(
                    BatchEventDeleteSuccess(event_id=event.event_id, calendar_id=event.calendar_id)
                )
            except Exception as e:
                failed.append(BatchEventFailure(event_id=event.event_id, error=str(e)))

        return BatchEventDeleteResponse(successful=successful, failed=failed)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
