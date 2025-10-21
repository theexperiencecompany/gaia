import { create } from "zustand";
import { devtools, persist } from "zustand/middleware";

import { CalendarItem } from "@/types/api/calendarApiTypes";
import { GoogleCalendarEvent } from "@/types/features/calendarTypes";

interface CalendarState {
  calendars: CalendarItem[];
  selectedCalendars: string[];
  events: GoogleCalendarEvent[];
  nextPageToken: string | null;
  loading: {
    calendars: boolean;
    events: boolean;
  };
  error: {
    calendars: string | null;
    events: string | null;
  };
  isInitialized: boolean;
  createEventAction: (() => void) | null;
}

interface CalendarActions {
  setCalendars: (calendars: CalendarItem[]) => void;
  setSelectedCalendars: (calendarIds: string[]) => void;
  toggleCalendarSelection: (calendarId: string) => void;
  setEvents: (events: GoogleCalendarEvent[], reset?: boolean) => void;
  setNextPageToken: (token: string | null) => void;
  setLoading: (type: "calendars" | "events", loading: boolean) => void;
  setError: (type: "calendars" | "events", error: string | null) => void;
  resetEvents: () => void;
  clearError: (type: "calendars" | "events") => void;
  setInitialized: (initialized: boolean) => void;
  autoSelectPrimaryCalendar: () => void;
  setCreateEventAction: (action: (() => void) | null) => void;
}

type CalendarStore = CalendarState & CalendarActions;

const initialState: CalendarState = {
  calendars: [],
  selectedCalendars: [],
  events: [],
  nextPageToken: null,
  loading: {
    calendars: false,
    events: false,
  },
  error: {
    calendars: null,
    events: null,
  },
  isInitialized: false,
  createEventAction: null,
};

export const useCalendarStore = create<CalendarStore>()(
  devtools(
    persist(
      (set, get) => ({
        ...initialState,

        setCalendars: (calendars) => set({ calendars }, false, "setCalendars"),

        setSelectedCalendars: (selectedCalendars) =>
          set({ selectedCalendars }, false, "setSelectedCalendars"),

        toggleCalendarSelection: (calendarId) =>
          set(
            (state) => {
              const index = state.selectedCalendars.indexOf(calendarId);
              const newSelection =
                index === -1
                  ? [...state.selectedCalendars, calendarId]
                  : state.selectedCalendars.filter((id) => id !== calendarId);

              return { selectedCalendars: newSelection };
            },
            false,
            "toggleCalendarSelection",
          ),

        setEvents: (events, reset = false) =>
          set(
            (state) => {
              if (reset) {
                return { events };
              }

              // Deduplicate events by ID when appending
              const existingEventIds = new Set(state.events.map((e) => e.id));
              const newUniqueEvents = events.filter(
                (e) => e.id && !existingEventIds.has(e.id),
              );

              return {
                events: [...state.events, ...newUniqueEvents],
              };
            },
            false,
            "setEvents",
          ),

        setNextPageToken: (nextPageToken) =>
          set({ nextPageToken }, false, "setNextPageToken"),

        setLoading: (type, loading) =>
          set(
            (state) => ({
              loading: { ...state.loading, [type]: loading },
            }),
            false,
            "setLoading",
          ),

        setError: (type, error) =>
          set(
            (state) => ({
              error: { ...state.error, [type]: error },
            }),
            false,
            "setError",
          ),

        resetEvents: () =>
          set(
            {
              events: [],
              nextPageToken: null,
              error: { ...get().error, events: null },
            },
            false,
            "resetEvents",
          ),

        clearError: (type) =>
          set(
            (state) => ({
              error: { ...state.error, [type]: null },
            }),
            false,
            "clearError",
          ),

        setInitialized: (isInitialized) =>
          set({ isInitialized }, false, "setInitialized"),

        autoSelectPrimaryCalendar: () => {
          const { calendars, selectedCalendars } = get();
          if (selectedCalendars.length === 0 && calendars.length > 0) {
            const primaryCalendar = calendars.find((cal) => cal.primary);
            if (primaryCalendar) {
              set(
                { selectedCalendars: [primaryCalendar.id] },
                false,
                "autoSelectPrimaryCalendar",
              );
            }
          }
        },

        setCreateEventAction: (createEventAction) =>
          set({ createEventAction }, false, "setCreateEventAction"),
      }),
      {
        name: "calendar-storage",
        partialize: (state) => ({
          selectedCalendars: state.selectedCalendars,
        }),
      },
    ),
    { name: "calendar-store" },
  ),
);

// Selectors
export const useCalendars = () => useCalendarStore((state) => state.calendars);
export const useSelectedCalendars = () =>
  useCalendarStore((state) => state.selectedCalendars);
export const useCalendarEvents = () =>
  useCalendarStore((state) => state.events);
export const useCalendarLoading = () =>
  useCalendarStore((state) => state.loading);
export const useCalendarError = () => useCalendarStore((state) => state.error);
export const useCalendarNextPageToken = () =>
  useCalendarStore((state) => state.nextPageToken);
export const useCalendarInitialized = () =>
  useCalendarStore((state) => state.isInitialized);
export const useSetCreateEventAction = () =>
  useCalendarStore((state) => state.setCreateEventAction);
export const useCreateEventAction = () =>
  useCalendarStore((state) => state.createEventAction);
