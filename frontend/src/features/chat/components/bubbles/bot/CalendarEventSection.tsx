import {
  CalendarEvent,
  SingleTimeEvent,
  TimedEvent,
} from "@/types/features/calendarTypes";
import { CalendarOptions } from "@/types/features/convoTypes";

import { CalendarActionListCard } from "./CalendarActionListCard";

export default function CalendarEventSection({
  calendar_options,
}: {
  calendar_options: CalendarOptions[];
}) {
  // Validate that we have at least a summary for each event
  if (!calendar_options.every((option) => option.summary)) {
    return (
      <div className="p-3 text-red-500">
        Error: Could not add Calendar event. Please try again later.
      </div>
    );
  }

  const calendarEvents: CalendarEvent[] = calendar_options.map(
    (option): CalendarEvent => {
      // If we have both start and end times, create a TimedEvent
      if (option.start && option.end) {
        const timedEvent: TimedEvent = {
          summary: option.summary,
          description: option.description || "",
          start: option.start,
          end: option.end,
          is_all_day: option.is_all_day || false,
          recurrence: option.recurrence,
          calendar_id: option.calendar_id,
        };
        return timedEvent;
      }

      // If we have only a start time, use it as a single time event
      if (option.start) {
        const singleTimeEvent: SingleTimeEvent = {
          summary: option.summary,
          description: option.description || "",
          time: option.start,
          is_all_day: option.is_all_day || true, // Default to all-day for single time events
          recurrence: option.recurrence,
          calendar_id: option.calendar_id,
        };
        return singleTimeEvent;
      }

      // Fallback: create a single time event with "TBD" time
      const fallbackEvent: SingleTimeEvent = {
        summary: option.summary,
        description: option.description || "",
        time: "Time TBD",
        is_all_day: true,
        recurrence: option.recurrence,
        calendar_id: option.calendar_id,
      };
      return fallbackEvent;
    },
  );

  return (
    <CalendarActionListCard
      actionType="add"
      events={calendarEvents}
      isDummy={false}
    />
  );
}
