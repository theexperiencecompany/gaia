"""Calendar tools using Composio custom tool infrastructure.

These tools provide calendar functionality routed through Composio's proxy.
The proxy attaches the user's OAuth token server-side, so tools only need to
look up `user_id` from `auth_credentials`.

Note: Errors raised here propagate as exceptions; Composio wraps responses
in {successful, data, error} format automatically.
"""

import asyncio
from collections.abc import Coroutine
import concurrent.futures
from datetime import UTC, datetime, timedelta, tzinfo
from typing import TypeVar

from composio import Composio
from composio.types import ExecuteRequestFn
from langgraph.config import get_config, get_stream_writer
from langgraph.types import StreamWriter
from pydantic import TypeAdapter

from app.constants.calendar import DEFAULT_CALENDAR_COLOR, DEFAULT_EVENT_DURATION
from app.constants.log_tags import LogTag
from app.db.repositories.users import user_repository
from app.decorators import with_doc
from app.models.agent_models import read_agent_configurable
from app.models.calendar_models import (
    AddRecurrenceInput,
    CalendarEventDisplay,
    CalendarSummary,
    CreatedEventSummary,
    CreateEventInput,
    DeleteEventInput,
    EventDraftFailure,
    EventReference,
    EventToolFailure,
    FetchedEvent,
    FetchEventsInput,
    FindEventInput,
    GetDaySummaryInput,
    GetEventInput,
    GoogleCalendarAttendee,
    GoogleCalendarEventDateTime,
    GoogleCalendarEventResource,
    GoogleCalendarEventWrite,
    GoogleConferenceCreateRequest,
    GoogleConferenceData,
    GoogleConferenceSolutionKey,
    ListCalendarsInput,
    PatchEventInput,
    SingleEventInput,
)
from app.models.common_models import GatherContextInput
from app.models.integrations.composio import CustomToolAuthCredentials
from app.services import calendar_service
from app.services.composio.proxy_client import ProxyRequest, proxy_request_sync
from app.templates.docstrings.calendar_tool_docs import (
    CUSTOM_ADD_RECURRENCE as CUSTOM_ADD_RECURRENCE_DOC,
    CUSTOM_CREATE_EVENT as CUSTOM_CREATE_EVENT_DOC,
    CUSTOM_DELETE_EVENT as CUSTOM_DELETE_EVENT_DOC,
    CUSTOM_FETCH_EVENTS as CUSTOM_FETCH_EVENTS_DOC,
    CUSTOM_FIND_EVENT as CUSTOM_FIND_EVENT_DOC,
    CUSTOM_GET_DAY_SUMMARY as CUSTOM_GET_DAY_SUMMARY_DOC,
    CUSTOM_GET_EVENT as CUSTOM_GET_EVENT_DOC,
    CUSTOM_LIST_CALENDARS as CUSTOM_LIST_CALENDARS_DOC,
    CUSTOM_PATCH_EVENT as CUSTOM_PATCH_EVENT_DOC,
)
from app.utils.calendar_utils import calendar_events_endpoint
from app.utils.concurrency import run_on_captured_loop
from app.utils.context_utils import execute_tool
from app.utils.errors import AppError
from app.utils.timezone import Timezone, home_timezone_from_config
from shared.py.wide_events import log

CALENDAR_TOOLKIT = "GOOGLECALENDAR"

_T = TypeVar("_T")


def _optional_stream_writer() -> StreamWriter | None:
    """Return the graph stream writer, or None outside a graph run.

    get_stream_writer() raises outside a Pregel runtime (backend dispatch: ticket
    redeem, sandbox, workflows), so these tools treat the writer as a best-effort
    UI hint and skip when it returns None. The result travels in the tool's return
    value, not the writer.
    """
    try:
        writer: StreamWriter = get_stream_writer()
    except (KeyError, RuntimeError):
        return None
    return writer


def _run_sync(coro: Coroutine[object, object, _T], *, timeout: float | None = None) -> _T:
    """Run an async service call from a synchronous Composio custom-tool body.

    The custom tools call async services (calendar_service, user_service) that
    drive the loop-bound Motor client. In production the tool runs on a worker
    thread with no running loop of its own, so the coroutine is dispatched onto
    the server loop the client was built on — ``asyncio.run`` there would spin a
    fresh loop and make Motor raise "attached to a different loop". When the tool
    is already inside a running loop (nested-loop test harnesses), that loop can't
    be blocked, so the coroutine is offloaded to a fresh thread + loop.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return run_on_captured_loop(coro, timeout=timeout)
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(lambda: asyncio.run(coro)).result(timeout=timeout)
    finally:
        # wait=False, so no `with` block: shutting the pool down with wait=True
        # joins the worker, which would make `timeout` a no-op — the caller would
        # still block for however long the coroutine takes.
        pool.shutdown(wait=False)


def _extract_datetime(dt: GoogleCalendarEventDateTime) -> str:
    """Return the timed dateTime of a Google start/end, else its all-day date."""
    return dt.dateTime or dt.date or ""


def _format_calendar_for_stream(cal: CalendarSummary) -> dict[str, str | None]:
    """Format a calendar entry into CalendarListFetchData schema for frontend streaming."""
    return {
        "name": cal.summary,
        "id": cal.id,
        "description": cal.description,
        "backgroundColor": cal.backgroundColor,
    }


def _get_user_timezone() -> tzinfo | None:
    """User's home timezone from the LangGraph RunnableConfig, or None if absent.

    None (not UTC) is deliberate: the caller leaves an event time naive when the
    config carries no zone, so Google interprets it in the calendar's own zone.
    """
    try:
        config = get_config()
        if read_agent_configurable(config).user_timezone:
            return home_timezone_from_config(config).tzinfo
    except Exception:
        log.error(f"{LogTag.TOOL} Error getting user timezone")
    return None


async def get_effective_timezone(user_id: str) -> tzinfo | None:
    """Home zone for naive datetimes: run config first, stored profile second.

    Backend dispatch (ticket redeem, sandbox) synthesizes a config carrying
    only the user id, so the config lookup alone wrongly reports "unknown"
    for users with a stored zone — and naive datetimes then fail after
    approval instead of stamping like they do in-graph.
    """
    tz = _get_user_timezone()
    if tz is not None:
        return tz
    try:
        user = await user_repository.get(user_id)
    except Exception as e:
        log.warning(
            f"{LogTag.TOOL} Could not load user for effective timezone",
            user_id=user_id,
            error_type=type(e).__name__,
        )
        return None
    raw = user.timezone if user else None
    if not raw:
        return None
    # try_parse, not parse: parse falls back to UTC, which would silently book
    # a naive time at UTC instead of rejecting it.
    parsed = Timezone.try_parse(raw)
    if parsed is None:
        log.warning(
            f"{LogTag.TOOL} Could not parse stored home timezone",
            error_type="unrecognized_timezone",
        )
        return None
    return parsed.tzinfo


def _parse_event_datetimes(event: SingleEventInput) -> tuple[datetime, datetime | None]:
    """ISO start/end datetimes; raises ValueError with a user-facing message on bad input."""
    try:
        start_dt = datetime.fromisoformat(event.start_datetime)
    except ValueError as e:
        raise ValueError(f"Invalid start_datetime format: {e}") from e

    end_dt: datetime | None = None
    if event.end_datetime:
        try:
            end_dt = datetime.fromisoformat(event.end_datetime)
        except ValueError as e:
            raise ValueError(f"Invalid end_datetime format: {e}") from e
    return start_dt, end_dt


def _all_day_bounds(
    start_dt: datetime, end_dt: datetime | None
) -> tuple[GoogleCalendarEventDateTime, GoogleCalendarEventDateTime]:
    """All-day Google start/end dates; the end date is exclusive, so the inclusive last day becomes the following date."""
    last_day = end_dt or start_dt
    return (
        GoogleCalendarEventDateTime(date=start_dt.strftime("%Y-%m-%d")),
        GoogleCalendarEventDateTime(date=(last_day + timedelta(days=1)).strftime("%Y-%m-%d")),
    )


def _stamp_user_timezone(
    start_dt: datetime, end_dt: datetime, user_id: str
) -> tuple[datetime, datetime]:
    """Stamp naive datetimes with the user's home zone; raises ValueError when no zone is known."""
    if start_dt.tzinfo is not None and end_dt.tzinfo is not None:
        return start_dt, end_dt
    user_tz = _run_sync(get_effective_timezone(user_id))
    if user_tz is None:
        # Google 400s a naked wall time, and that failure used to land after
        # the user approved. Fail fast so the model adds an explicit offset.
        raise ValueError(
            "start_datetime has no UTC offset and no home timezone is "
            "configured: pass an explicit offset (e.g. 2026-09-21T11:00:00+05:30)."
        )
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=user_tz)
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=user_tz)
    return start_dt, end_dt


def _resolve_event_bounds(
    event: SingleEventInput, user_id: str
) -> tuple[GoogleCalendarEventDateTime, GoogleCalendarEventDateTime]:
    """Google start/end for one event; raises ValueError with a user-facing message on bad input."""
    start_dt, end_dt = _parse_event_datetimes(event)

    # Google treats an all-day end.date as exclusive, so an inclusive last
    # day (or a missing end) becomes the following date.
    if event.is_all_day:
        return _all_day_bounds(start_dt, end_dt)

    if end_dt is None:
        end_dt = start_dt + DEFAULT_EVENT_DURATION
    start_dt, end_dt = _stamp_user_timezone(start_dt, end_dt, user_id)

    if end_dt <= start_dt:
        raise ValueError("end_datetime must be after start_datetime.")

    return (
        GoogleCalendarEventDateTime(dateTime=start_dt.isoformat()),
        GoogleCalendarEventDateTime(dateTime=end_dt.isoformat()),
    )


def register_calendar_custom_tools(composio: Composio) -> list[str]:
    """Register calendar tools as Composio custom tools."""

    @composio.tools.custom_tool(toolkit="GOOGLECALENDAR")
    @with_doc(CUSTOM_LIST_CALENDARS_DOC)
    def CUSTOM_LIST_CALENDARS(
        request: ListCalendarsInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        del execute_request  # unused: framework-mandated custom-tool signature
        log.set(tool={"integration": "google_calendar", "action": "list_calendars"})
        user_id = CustomToolAuthCredentials.parse(auth_credentials).user_id
        calendar_list = _run_sync(calendar_service.list_calendars(user_id))
        summaries = calendar_service.to_calendar_summaries(calendar_list)
        calendars = (
            [summary.model_dump() for summary in summaries]
            if request.short
            else [entry.model_dump() for entry in calendar_list.items]
        )

        writer = _optional_stream_writer()
        if writer is not None and summaries:
            writer(
                {
                    "calendar_list_fetch_data": [
                        _format_calendar_for_stream(summary) for summary in summaries
                    ]
                }
            )

        return {"calendars": calendars}

    @composio.tools.custom_tool(toolkit="GOOGLECALENDAR")
    @with_doc(CUSTOM_GET_DAY_SUMMARY_DOC)
    def CUSTOM_GET_DAY_SUMMARY(
        request: GetDaySummaryInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        del execute_request  # unused: framework-mandated custom-tool signature
        log.set(tool={"integration": "google_calendar", "action": "get_day_summary"})
        user_id = CustomToolAuthCredentials.parse(auth_credentials).user_id

        try:
            user = _run_sync(user_repository.get(user_id), timeout=5)
            user_timezone = user.timezone if user else None
        except Exception:
            user_timezone = None

        # Timezone.parse is offset-safe (a stored ±HH:MM home zone makes
        # zoneinfo.ZoneInfo raise) and normalizes None/blank to UTC.
        home_tz = Timezone.parse(user_timezone)
        tz = home_tz.tzinfo
        user_timezone = home_tz.value

        now = datetime.now(tz)
        if request.date:
            try:
                target_date = datetime.strptime(request.date, "%Y-%m-%d").replace(tzinfo=tz)
            except ValueError as e:
                raise ValueError(f"Invalid date format: {request.date}. Use YYYY-MM-DD.") from e
        else:
            target_date = now

        day_start = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

        result = _run_sync(
            calendar_service.get_calendar_events(
                user_id=user_id,
                selected_calendars=None,
                time_min=day_start.isoformat(),
                time_max=day_end.isoformat(),
                max_results=100,
            )
        )

        events = result.events

        try:
            color_map, name_map = _run_sync(calendar_service.get_calendar_metadata_map(user_id))
            formatted_events = [
                calendar_service.format_event_for_frontend(event, color_map, name_map).model_dump()
                for event in events
            ]
        except Exception:
            formatted_events = [event.model_dump() for event in events]

        busy_minutes: float = 0.0
        for event in events:
            start_time = event.start.dateTime if event.start else None
            end_time = event.end.dateTime if event.end else None
            if start_time and end_time:
                try:
                    start_dt = datetime.fromisoformat(start_time)
                    end_dt = datetime.fromisoformat(end_time)
                    duration = (end_dt - start_dt).total_seconds() / 60
                    busy_minutes += duration
                except (ValueError, TypeError) as e:
                    log.debug(
                        f"{LogTag.TOOL} Excluding event from busy-hours total, unparseable times",
                        start_time=start_time,
                        end_time=end_time,
                        error=str(e),
                        error_type=type(e).__name__,
                    )

        next_event: dict[str, object] | None = None
        if day_start.date() == now.date():
            for event in events:
                start_time = event.start.dateTime if event.start else None
                if start_time:
                    try:
                        event_start = datetime.fromisoformat(start_time)
                        if event_start > now:
                            next_event = event.model_dump()
                            break
                    except (ValueError, TypeError) as e:
                        log.debug(
                            f"{LogTag.TOOL} Skipping event when resolving next_event, "
                            "unparseable start time",
                            start_time=start_time,
                            error=str(e),
                            error_type=type(e).__name__,
                        )

        result_data = {
            "date": day_start.strftime("%Y-%m-%d"),
            "timezone": user_timezone,
            "events": formatted_events,
            "next_event": next_event,
            "busy_hours": round(busy_minutes / 60, 1),
        }

        writer = _optional_stream_writer()
        if writer is not None and formatted_events:
            writer({"calendar_fetch_data": formatted_events})

        return result_data

    @composio.tools.custom_tool(toolkit="GOOGLECALENDAR")
    @with_doc(CUSTOM_FETCH_EVENTS_DOC)
    def CUSTOM_FETCH_EVENTS(
        request: FetchEventsInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        del execute_request  # unused: framework-mandated custom-tool signature
        log.set(tool={"integration": "google_calendar", "action": "fetch_events"})
        user_id = CustomToolAuthCredentials.parse(auth_credentials).user_id

        time_min = request.time_min or datetime.now(UTC).isoformat()

        result = _run_sync(
            calendar_service.get_calendar_events(
                user_id=user_id,
                selected_calendars=request.calendar_ids or None,
                time_min=time_min,
                time_max=request.time_max,
                max_results=request.max_results,
            )
        )

        events = result.events

        try:
            color_map, name_map = _run_sync(calendar_service.get_calendar_metadata_map(user_id))
            calendar_fetch_data = [
                calendar_service.format_event_for_frontend(event, color_map, name_map).model_dump()
                for event in events
            ]
        except Exception:
            calendar_fetch_data = [event.model_dump() for event in events]

        writer = _optional_stream_writer()
        if writer is not None and calendar_fetch_data:
            writer({"calendar_fetch_data": calendar_fetch_data})

        return {
            "calendar_fetch_data": calendar_fetch_data,
            "has_more": result.has_more,
        }

    @composio.tools.custom_tool(toolkit="GOOGLECALENDAR")
    @with_doc(CUSTOM_FIND_EVENT_DOC)
    def CUSTOM_FIND_EVENT(
        request: FindEventInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        del execute_request  # unused: framework-mandated custom-tool signature
        log.set(tool={"integration": "google_calendar", "action": "find_event"})
        user_id = CustomToolAuthCredentials.parse(auth_credentials).user_id

        result = _run_sync(
            calendar_service.search_calendar_events_native(
                query=request.query,
                user_id=user_id,
                time_min=request.time_min,
                time_max=request.time_max,
            )
        )

        events = [event.model_dump() for event in result.matching_events]

        try:
            color_map, name_map = _run_sync(calendar_service.get_calendar_metadata_map(user_id))
            calendar_search_data = [
                calendar_service.format_event_for_frontend(event, color_map, name_map).model_dump()
                for event in result.matching_events
            ]
        except Exception:
            calendar_search_data = events

        writer = _optional_stream_writer()
        if writer is not None and calendar_search_data:
            writer({"calendar_fetch_data": calendar_search_data})

        return {
            "events": events,
            "calendar_search_data": calendar_search_data,
        }

    @composio.tools.custom_tool(toolkit="GOOGLECALENDAR")
    @with_doc(CUSTOM_GET_EVENT_DOC)
    def CUSTOM_GET_EVENT(
        request: GetEventInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        del execute_request  # unused: framework-mandated custom-tool signature
        log.set(tool={"integration": "google_calendar", "action": "get_event"})
        user_id = CustomToolAuthCredentials.parse(auth_credentials).user_id

        results: list[FetchedEvent] = []
        errors: list[EventToolFailure] = []

        for event_ref in request.events:
            try:
                event = GoogleCalendarEventResource.model_validate(
                    proxy_request_sync(
                        ProxyRequest(
                            user_id=user_id,
                            toolkit=CALENDAR_TOOLKIT,
                            endpoint=calendar_events_endpoint(
                                event_ref.calendar_id, event_ref.event_id
                            ),
                            method="GET",
                        )
                    )
                )
                results.append(
                    FetchedEvent(
                        event_id=event_ref.event_id,
                        calendar_id=event_ref.calendar_id,
                        event=event,
                    )
                )
            except AppError as e:
                log.error(
                    f"{LogTag.TOOL} Error getting event",
                    event_id=event_ref.event_id,
                    error_type=type(e).__name__,
                )
                errors.append(
                    EventToolFailure(
                        event_id=event_ref.event_id,
                        calendar_id=event_ref.calendar_id,
                        error=f"Event not found: {e.message}",
                    )
                )

        # JSON-native fields: python and json dumps are identical
        failures = [error.model_dump(mode="json") for error in errors]  # pragma: no mutate
        if errors and not results:
            raise RuntimeError(f"Failed to get events: {failures}")

        # `errors` must travel with the partial result — dropping it made the
        # agent report a batch where some events failed as a clean success.
        return {
            # JSON-native fields: python and json dumps are identical
            "events": [result.model_dump(mode="json") for result in results],  # pragma: no mutate
            "errors": failures,
        }

    @composio.tools.custom_tool(toolkit="GOOGLECALENDAR")
    @with_doc(CUSTOM_DELETE_EVENT_DOC)
    def CUSTOM_DELETE_EVENT(
        request: DeleteEventInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        del execute_request  # unused: framework-mandated custom-tool signature
        log.set(tool={"integration": "google_calendar", "action": "delete_event"})
        user_id = CustomToolAuthCredentials.parse(auth_credentials).user_id

        deleted: list[EventReference] = []
        errors: list[EventToolFailure] = []

        for event_ref in request.events:
            try:
                proxy_request_sync(
                    ProxyRequest(
                        user_id=user_id,
                        toolkit=CALENDAR_TOOLKIT,
                        endpoint=calendar_events_endpoint(
                            event_ref.calendar_id, event_ref.event_id
                        ),
                        method="DELETE",
                        query={"sendUpdates": request.send_updates},
                    )
                )
                deleted.append(event_ref)
            except AppError as e:
                log.error(
                    f"{LogTag.TOOL} Error deleting event",
                    event_id=event_ref.event_id,
                    error_type=type(e).__name__,
                )
                errors.append(
                    EventToolFailure(
                        event_id=event_ref.event_id,
                        calendar_id=event_ref.calendar_id,
                        error=f"Failed to delete: {e.message}",
                    )
                )

        # JSON-native fields: python and json dumps are identical
        failures = [error.model_dump(mode="json") for error in errors]  # pragma: no mutate
        if errors and not deleted:
            raise RuntimeError(f"Failed to delete events: {failures}")

        # JSON-native fields: python and json dumps are identical
        deleted_refs = [ref.model_dump(mode="json") for ref in deleted]  # pragma: no mutate
        return {
            "deleted": deleted_refs,
            "errors": failures,
        }

    @composio.tools.custom_tool(toolkit="GOOGLECALENDAR")
    @with_doc(CUSTOM_PATCH_EVENT_DOC)
    def CUSTOM_PATCH_EVENT(
        request: PatchEventInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        del execute_request  # unused: framework-mandated custom-tool signature
        log.set(tool={"integration": "google_calendar", "action": "patch_event"})
        user_id = CustomToolAuthCredentials.parse(auth_credentials).user_id

        body = GoogleCalendarEventWrite(
            summary=request.summary,
            description=request.description,
            location=request.location,
            start=(
                GoogleCalendarEventDateTime(dateTime=request.start_datetime)
                if request.start_datetime is not None
                else None
            ),
            end=(
                GoogleCalendarEventDateTime(dateTime=request.end_datetime)
                if request.end_datetime is not None
                else None
            ),
            attendees=(
                [GoogleCalendarAttendee(email=email) for email in request.attendees]
                if request.attendees is not None
                else None
            ),
        )

        event = GoogleCalendarEventResource.model_validate(
            proxy_request_sync(
                ProxyRequest(
                    user_id=user_id,
                    toolkit=CALENDAR_TOOLKIT,
                    endpoint=calendar_events_endpoint(request.calendar_id, request.event_id),
                    method="PATCH",
                    # JSON-native fields: python and json dumps are identical
                    body=body.model_dump(mode="json", exclude_none=True),  # pragma: no mutate
                    query={"sendUpdates": request.send_updates},
                )
            )
        )

        # JSON-native fields: python and json dumps are identical
        return {"event": event.model_dump(mode="json")}  # pragma: no mutate

    @composio.tools.custom_tool(toolkit="GOOGLECALENDAR")
    @with_doc(CUSTOM_ADD_RECURRENCE_DOC)
    def CUSTOM_ADD_RECURRENCE(
        request: AddRecurrenceInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        del execute_request  # unused: framework-mandated custom-tool signature
        log.set(tool={"integration": "google_calendar", "action": "add_recurrence"})
        user_id = CustomToolAuthCredentials.parse(auth_credentials).user_id
        endpoint = calendar_events_endpoint(request.calendar_id, request.event_id)

        event = GoogleCalendarEventResource.model_validate(
            proxy_request_sync(
                ProxyRequest(
                    user_id=user_id,
                    toolkit=CALENDAR_TOOLKIT,
                    endpoint=endpoint,
                    method="GET",
                )
            )
        )

        rrule_parts = [f"FREQ={request.frequency}"]
        if request.interval != 1:
            rrule_parts.append(f"INTERVAL={request.interval}")
        if request.count > 0:
            rrule_parts.append(f"COUNT={request.count}")
        if request.until_date:
            until_formatted = request.until_date.replace("-", "")
            rrule_parts.append(f"UNTIL={until_formatted}")
        if request.by_day:
            rrule_parts.append(f"BYDAY={','.join(request.by_day)}")

        rrule = "RRULE:" + ";".join(rrule_parts)
        event.recurrence = [rrule]

        updated = GoogleCalendarEventResource.model_validate(
            proxy_request_sync(
                ProxyRequest(
                    user_id=user_id,
                    toolkit=CALENDAR_TOOLKIT,
                    endpoint=endpoint,
                    method="PUT",
                    # JSON-native fields: python and json dumps are identical
                    body=event.model_dump(mode="json"),  # pragma: no mutate
                )
            )
        )

        return {
            # JSON-native fields: python and json dumps are identical
            "event": updated.model_dump(mode="json"),  # pragma: no mutate
            "recurrence_rule": rrule,
        }

    @composio.tools.custom_tool(toolkit="GOOGLECALENDAR")
    @with_doc(CUSTOM_CREATE_EVENT_DOC)
    def CUSTOM_CREATE_EVENT(
        request: CreateEventInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        del execute_request  # unused: framework-mandated custom-tool signature
        log.set(tool={"integration": "google_calendar", "action": "create_event"})
        user_id = CustomToolAuthCredentials.parse(auth_credentials).user_id

        try:
            color_map, name_map = _run_sync(calendar_service.get_calendar_metadata_map(user_id))
        except Exception:
            color_map, name_map = {}, {}

        created_events: list[CreatedEventSummary] = []
        errors: list[EventDraftFailure] = []

        for index, event in enumerate(request.events):
            try:
                start, end = _resolve_event_bounds(event, user_id)
            except ValueError as e:
                errors.append(EventDraftFailure(index=index, summary=event.summary, error=str(e)))
                continue

            body = GoogleCalendarEventWrite(
                summary=event.summary,
                start=start,
                end=end,
                description=event.description or None,
                location=event.location or None,
                attendees=(
                    [GoogleCalendarAttendee(email=email) for email in event.attendees]
                    if event.attendees
                    else None
                ),
                conferenceData=(
                    GoogleConferenceData(
                        createRequest=GoogleConferenceCreateRequest(
                            # naive local now() and UTC now() give the same epoch
                            requestId=f"meet_{index}_{int(datetime.now(UTC).timestamp())}",  # pragma: no mutate
                            conferenceSolutionKey=GoogleConferenceSolutionKey(type="hangoutsMeet"),
                        )
                    )
                    if event.create_meeting_room
                    else None
                ),
            )
            query: dict[str, str] = {"sendUpdates": "all"}
            if event.create_meeting_room:
                query["conferenceDataVersion"] = "1"

            # JSON-native fields: python and json dumps are identical
            event_body = body.model_dump(mode="json", exclude_none=True)  # pragma: no mutate
            created_event = GoogleCalendarEventResource.model_validate(
                proxy_request_sync(
                    ProxyRequest(
                        user_id=user_id,
                        toolkit=CALENDAR_TOOLKIT,
                        endpoint=calendar_events_endpoint(event.calendar_id),
                        method="POST",
                        body=event_body,
                        query=query,
                    )
                )
            )
            created_events.append(
                CreatedEventSummary(
                    index=index,
                    summary=event.summary,
                    event_id=created_event.id,
                    calendar_id=event.calendar_id,
                    link=created_event.htmlLink,
                    start=start,
                    end=end,
                )
            )

        # JSON-native fields: python and json dumps are identical
        failures = [error.model_dump(mode="json") for error in errors]  # pragma: no mutate
        if errors and not created_events:
            raise ValueError(f"All events failed validation: {failures}")

        writer = _optional_stream_writer()
        if writer is not None and created_events:
            displays = [
                CalendarEventDisplay(
                    summary=e.summary,
                    start_time=_extract_datetime(e.start),
                    end_time=_extract_datetime(e.end),
                    calendar_name=name_map.get(e.calendar_id, ""),
                    background_color=color_map.get(e.calendar_id, DEFAULT_CALENDAR_COLOR),
                )
                for e in created_events
            ]
            # JSON-native fields: python and json dumps are identical
            dumps = [d.model_dump(mode="json") for d in displays]  # pragma: no mutate
            writer({"calendar_fetch_data": dumps})

        # JSON-native fields: python and json dumps are identical
        created_dumps = [e.model_dump(mode="json") for e in created_events]  # pragma: no mutate
        return {
            "created": len(created_events) > 0,
            "created_events": created_dumps,
            "errors": failures,
        }

    @composio.tools.custom_tool(toolkit="GOOGLECALENDAR")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Get Google Calendar context snapshot: today's events, busy hours, free slots.

        Zero required parameters. Returns today's schedule for situational awareness.
        """
        del request, execute_request  # unused: framework-mandated custom-tool signature
        log.set(tool={"integration": "google_calendar", "action": "gather_context"})
        user_id = CustomToolAuthCredentials.parse(auth_credentials).user_id
        # No date: the day summary resolves "today" in the user's home timezone,
        # which this process cannot do (its own date may be a day off).
        return TypeAdapter(dict[str, object]).validate_python(
            execute_tool("GOOGLECALENDAR_CUSTOM_GET_DAY_SUMMARY", {}, user_id)
        )

    return [
        "GOOGLECALENDAR_CUSTOM_CREATE_EVENT",
        "GOOGLECALENDAR_CUSTOM_LIST_CALENDARS",
        "GOOGLECALENDAR_CUSTOM_GET_DAY_SUMMARY",
        "GOOGLECALENDAR_CUSTOM_FETCH_EVENTS",
        "GOOGLECALENDAR_CUSTOM_FIND_EVENT",
        "GOOGLECALENDAR_CUSTOM_GET_EVENT",
        "GOOGLECALENDAR_CUSTOM_DELETE_EVENT",
        "GOOGLECALENDAR_CUSTOM_PATCH_EVENT",
        "GOOGLECALENDAR_CUSTOM_ADD_RECURRENCE",
        "GOOGLECALENDAR_CUSTOM_GATHER_CONTEXT",
    ]
