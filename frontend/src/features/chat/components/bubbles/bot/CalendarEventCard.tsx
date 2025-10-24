import {
  CalendarDeleteOptions,
  CalendarEditOptions,
  CalendarEvent,
} from "@/types/features/calendarTypes";
import { formatTimeRange } from "@/utils/date/calendarDateUtils";
import { isTimedEvent } from "@/utils/calendar/eventTypeGuards";

interface AddEventCardProps {
  actionType: "add";
  event: CalendarEvent;
}

interface EditEventCardProps {
  actionType: "edit";
  event: CalendarEditOptions;
}

interface DeleteEventCardProps {
  actionType: "delete";
  event: CalendarDeleteOptions;
}

type EventCardProps =
  | AddEventCardProps
  | EditEventCardProps
  | DeleteEventCardProps;

export const EventCard = ({ actionType, event }: EventCardProps) => {
  if (actionType === "add") {
    const calEvent = event as CalendarEvent;
    const isAllDay = isTimedEvent(calEvent) && calEvent.is_all_day;

    return (
      <>
        <div className="text-base leading-tight text-white">
          {calEvent.summary}
        </div>
        {calEvent.description && (
          <div className="mt-1 text-xs text-zinc-400">
            {calEvent.description}
          </div>
        )}
        <div className="mt-1 flex items-center gap-2 text-xs text-zinc-400">
          {isTimedEvent(calEvent) ? (
            <span>
              {calEvent.start.includes("T") && calEvent.end
                ? formatTimeRange(calEvent.start, calEvent.end)
                : isAllDay
                  ? "All day"
                  : calEvent.start}
            </span>
          ) : (
            <span>All day</span>
          )}
        </div>
      </>
    );
  }

  if (actionType === "edit") {
    const editEvent = event as CalendarEditOptions;
    const hasChanges =
      editEvent.summary !== undefined ||
      editEvent.description !== undefined ||
      editEvent.start !== undefined ||
      editEvent.end !== undefined ||
      editEvent.is_all_day !== undefined;

    return (
      <>
        <div className="text-base leading-tight text-white">
          {editEvent.summary || editEvent.original_summary}
        </div>
        <div className="mt-1 flex items-center gap-2 text-xs text-zinc-400">
          <span>
            {editEvent.original_start?.dateTime && editEvent.original_end?.dateTime
              ? formatTimeRange(
                  editEvent.original_start.dateTime,
                  editEvent.original_end.dateTime,
                )
              : "All day"}
          </span>
        </div>
        {hasChanges && (
          <div className="mt-2 rounded-md bg-primary/10 p-2 text-xs">
            <div className="font-medium text-primary">Changes:</div>
            <div className="mt-1 space-y-1 text-zinc-300">
              {editEvent.summary && <div>• Title: {editEvent.summary}</div>}
              {editEvent.description !== undefined && (
                <div>• Description: {editEvent.description}</div>
              )}
              {editEvent.start && <div>• New time: {editEvent.start}</div>}
              {editEvent.is_all_day !== undefined && (
                <div>• All-day: {editEvent.is_all_day ? "Yes" : "No"}</div>
              )}
            </div>
          </div>
        )}
      </>
    );
  }

  const deleteEvent = event as CalendarDeleteOptions;
  return (
    <>
      <div className="text-base leading-tight text-white">
        {deleteEvent.summary}
      </div>
      {deleteEvent.description && (
        <div className="mt-1 text-xs text-zinc-400">
          {deleteEvent.description}
        </div>
      )}
      <div className="mt-1 flex items-center gap-2 text-xs text-zinc-400">
        <span>
          {deleteEvent.start?.dateTime && deleteEvent.end?.dateTime
            ? formatTimeRange(
                deleteEvent.start.dateTime,
                deleteEvent.end.dateTime,
              )
            : "All day"}
        </span>
      </div>
    </>
  );
};
