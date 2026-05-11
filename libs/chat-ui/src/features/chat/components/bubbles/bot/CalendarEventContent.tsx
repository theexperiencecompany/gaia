import type {
  CalendarDeleteOptions,
  CalendarEditOptions,
  CalendarEvent,
} from "@/types/features/calendarTypes";
import { isTimedEvent } from "@/utils/calendar/eventTypeGuards";
import { formatTimeRange } from "@/utils/date/calendarDateUtils";

type EventData = CalendarEvent | CalendarEditOptions | CalendarDeleteOptions;

interface EventContentProps {
  event: EventData;
  showOriginal?: boolean; // For edit events, show original vs updated
}

export const EventContent = ({
  event,
  showOriginal = false,
}: EventContentProps) => {
  // Determine what to display based on event type
  let summary: string | undefined;
  let description: string | undefined;
  let timeDisplay: string | undefined;

  if ("action" in event) {
    // Edit or Delete event
    if (event.action === "edit" && !showOriginal) {
      // Show updated values
      const editEvent = event as CalendarEditOptions;
      summary = editEvent.summary || editEvent.original_summary;
      description =
        editEvent.description !== undefined
          ? editEvent.description
          : editEvent.original_description;

      if (editEvent.start && editEvent.end) {
        timeDisplay = formatTimeRange(editEvent.start, editEvent.end);
      } else if (editEvent.is_all_day !== undefined && editEvent.is_all_day) {
        timeDisplay = "All day";
      } else if (
        editEvent.original_start?.dateTime &&
        editEvent.original_end?.dateTime
      ) {
        timeDisplay = formatTimeRange(
          editEvent.original_start.dateTime,
          editEvent.original_end.dateTime,
        );
      } else {
        timeDisplay = "All day";
      }
    } else if (event.action === "edit" && showOriginal) {
      // Show original values
      const editEvent = event as CalendarEditOptions;
      summary = editEvent.original_summary;
      description = editEvent.original_description;

      if (
        editEvent.original_start?.dateTime &&
        editEvent.original_end?.dateTime
      ) {
        timeDisplay = formatTimeRange(
          editEvent.original_start.dateTime,
          editEvent.original_end.dateTime,
        );
      } else {
        timeDisplay = "All day";
      }
    } else if (event.action === "delete") {
      // Delete event
      const deleteEvent = event as CalendarDeleteOptions;
      summary = deleteEvent.summary;
      description = deleteEvent.description;

      if (deleteEvent.start?.dateTime && deleteEvent.end?.dateTime) {
        timeDisplay = formatTimeRange(
          deleteEvent.start.dateTime,
          deleteEvent.end.dateTime,
        );
      } else {
        timeDisplay = "All day";
      }
    }
  } else {
    // Add event (CalendarEvent)
    const calEvent = event as CalendarEvent;
    summary = calEvent.summary;
    description = calEvent.description;

    const isAllDay = isTimedEvent(calEvent) && calEvent.is_all_day;

    if (isTimedEvent(calEvent)) {
      if (calEvent.start.includes("T") && calEvent.end) {
        timeDisplay = formatTimeRange(calEvent.start, calEvent.end);
      } else if (isAllDay) {
        timeDisplay = "All day";
      } else {
        timeDisplay = calEvent.start;
      }
    } else {
      timeDisplay = "All day";
    }
  }

  return (
    <>
      <div className="text-base leading-tight text-white">{summary}</div>
      {description && (
        <div className="mt-1 text-xs text-zinc-400">{description}</div>
      )}
      <div className="mt-1 flex items-center gap-2 text-xs text-zinc-400">
        <span>{timeDisplay}</span>
      </div>
    </>
  );
};
