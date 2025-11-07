import { create } from "zustand";
import { devtools, persist } from "zustand/middleware";

import { GoogleCalendarEvent } from "@/types/features/calendarTypes";

export interface SelectedCalendarEventData {
  id: string;
  summary: string;
  description: string;
  start: {
    date?: string;
    dateTime?: string;
    timeZone?: string;
  };
  end: {
    date?: string;
    dateTime?: string;
    timeZone?: string;
  };
  calendarId?: string;
  calendarTitle?: string;
  backgroundColor?: string;
  isAllDay?: boolean;
}

export interface CalendarEventSelectionOptions {
  // Reserved for future options if needed
}

interface CalendarEventSelectionState {
  selectedCalendarEvent: SelectedCalendarEventData | null;
}

interface CalendarEventSelectionActions {
  selectCalendarEvent: (
    event: GoogleCalendarEvent | SelectedCalendarEventData,
    options?: CalendarEventSelectionOptions,
  ) => void;
  clearSelectedCalendarEvent: () => void;
  setSelectedCalendarEvent: (event: SelectedCalendarEventData | null) => void;
}

type CalendarEventSelectionStore = CalendarEventSelectionState &
  CalendarEventSelectionActions;

const initialState: CalendarEventSelectionState = {
  selectedCalendarEvent: null,
};

export const useCalendarEventSelectionStore =
  create<CalendarEventSelectionStore>()(
    devtools(
      persist(
        (set) => ({
          ...initialState,

          selectCalendarEvent: (event, options) => {
            const eventData: SelectedCalendarEventData =
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
                    backgroundColor:
                      event.organizer?.email && (event as any).backgroundColor,
                    isAllDay: !!event.start.date,
                  }
                : event;

            set({
              selectedCalendarEvent: eventData,
            });
          },

          clearSelectedCalendarEvent: () => set(initialState),

          setSelectedCalendarEvent: (event) =>
            set({ selectedCalendarEvent: event }),
        }),
        {
          name: "calendar-event-selection-storage",
        },
      ),
    ),
  );
