import { useCallback } from "react";

import { useSelectedCalendarEvent } from "@/stores/composerStore";
import type { SelectedCalendarEventData } from "@/stores/composerStore.types";
import type { GoogleCalendarEvent } from "@/types/features/calendarTypes";

export type { SelectedCalendarEventData };

/** Narrow a Google Calendar event down to the fields the composer attaches. */
const toSelectedCalendarEventData = (
  event: GoogleCalendarEvent | SelectedCalendarEventData,
): SelectedCalendarEventData =>
  "kind" in event
    ? {
        id: event.id,
        summary: event.summary,
        description: event.description || "",
        start: {
          date: event.start.date,
          dateTime: event.start.dateTime,
          timeZone: event.start.timeZone,
        },
        end: {
          date: event.end.date,
          dateTime: event.end.dateTime,
          timeZone: event.end.timeZone,
        },
        calendarId: event.calendarId,
        calendarTitle: event.calendarTitle,
        backgroundColor: event.organizer?.email && event.backgroundColor,
        isAllDay: !!event.start.date,
      }
    : event;

export const useCalendarEventSelection = () => {
  const {
    selectedCalendarEvent,
    selectCalendarEvent: storeSelectCalendarEvent,
    clearSelectedCalendarEvent,
  } = useSelectedCalendarEvent();

  const selectCalendarEvent = useCallback(
    (event: GoogleCalendarEvent | SelectedCalendarEventData) => {
      storeSelectCalendarEvent(toSelectedCalendarEventData(event));
    },
    [storeSelectCalendarEvent],
  );

  return {
    selectedCalendarEvent,
    selectCalendarEvent,
    clearSelectedCalendarEvent,
  };
};
