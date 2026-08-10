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

interface EventDisplay {
  summary?: string;
  description?: string;
  timeDisplay?: string;
}

function resolveEditUpdated(editEvent: CalendarEditOptions): EventDisplay {
  let timeDisplay: string;
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

  return {
    summary: editEvent.summary || editEvent.original_summary,
    description:
      editEvent.description !== undefined
        ? editEvent.description
        : editEvent.original_description,
    timeDisplay,
  };
}

function resolveEditOriginal(editEvent: CalendarEditOptions): EventDisplay {
  const timeDisplay =
    editEvent.original_start?.dateTime && editEvent.original_end?.dateTime
      ? formatTimeRange(
          editEvent.original_start.dateTime,
          editEvent.original_end.dateTime,
        )
      : "All day";

  return {
    summary: editEvent.original_summary,
    description: editEvent.original_description,
    timeDisplay,
  };
}

function resolveDelete(deleteEvent: CalendarDeleteOptions): EventDisplay {
  const timeDisplay =
    deleteEvent.start?.dateTime && deleteEvent.end?.dateTime
      ? formatTimeRange(deleteEvent.start.dateTime, deleteEvent.end.dateTime)
      : "All day";

  return {
    summary: deleteEvent.summary,
    description: deleteEvent.description,
    timeDisplay,
  };
}

function resolveAdd(calEvent: CalendarEvent): EventDisplay {
  let timeDisplay = "All day";

  if (isTimedEvent(calEvent)) {
    if (calEvent.start.includes("T") && calEvent.end) {
      timeDisplay = formatTimeRange(calEvent.start, calEvent.end);
    } else if (calEvent.is_all_day) {
      timeDisplay = "All day";
    } else {
      timeDisplay = calEvent.start;
    }
  }

  return {
    summary: calEvent.summary,
    description: calEvent.description,
    timeDisplay,
  };
}

function resolveEventDisplay(
  event: EventData,
  showOriginal: boolean,
): EventDisplay {
  if (!("action" in event)) {
    return resolveAdd(event as CalendarEvent);
  }
  if (event.action === "edit") {
    const editEvent = event as CalendarEditOptions;
    return showOriginal
      ? resolveEditOriginal(editEvent)
      : resolveEditUpdated(editEvent);
  }
  if (event.action === "delete") {
    return resolveDelete(event as CalendarDeleteOptions);
  }
  return {};
}

export const EventContent = ({
  event,
  showOriginal = false,
}: EventContentProps) => {
  // Determine what to display based on event type
  const { summary, description, timeDisplay } = resolveEventDisplay(
    event,
    showOriginal,
  );

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
