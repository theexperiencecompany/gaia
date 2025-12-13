import { create } from "zustand";
import { devtools, persist } from "zustand/middleware";

import type { CalendarItem } from "@/types/api/calendarApiTypes";
import type { GoogleCalendarEvent } from "@/types/features/calendarTypes";

interface CalendarState {
  calendars: CalendarItem[];
  selectedCalendars: string[];
  events: GoogleCalendarEvent[];
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
  selectedDate: Date;
  currentWeek: Date;
  daysToShow: number;
  visibleMonth: string;
  visibleYear: string;
  // Infinite scroll state
  loadedDateRanges: Array<{
    startDate: string; // YYYY-MM-DD
    endDate: string; // YYYY-MM-DD
    calendars: string[];
  }>;
  isLoadingPast: boolean;
  isLoadingFuture: boolean;
}

interface CalendarActions {
  setCalendars: (calendars: CalendarItem[]) => void;
  setSelectedCalendars: (calendarIds: string[]) => void;
  toggleCalendarSelection: (calendarId: string) => void;
  setEvents: (events: GoogleCalendarEvent[], reset?: boolean) => void;
  addEvent: (event: GoogleCalendarEvent) => void;
  updateEvent: (
    eventId: string,
    updatedEvent: Partial<GoogleCalendarEvent>,
  ) => void;
  removeEvent: (eventId: string) => void;
  setLoading: (type: "calendars" | "events", loading: boolean) => void;
  setError: (type: "calendars" | "events", error: string | null) => void;
  resetEvents: () => void;
  clearError: (type: "calendars" | "events") => void;
  setInitialized: (initialized: boolean) => void;
  autoSelectPrimaryCalendar: () => void;
  setCreateEventAction: (action: (() => void) | null) => void;
  setSelectedDate: (date: Date) => void;
  setCurrentWeek: (date: Date) => void;
  goToPreviousDay: () => void;
  goToNextDay: () => void;
  goToToday: () => void;
  handleDateChange: (date: Date) => void;
  setDaysToShow: (days: number) => void;
  setVisibleMonthYear: (month: string, year: string) => void;
  // Infinite scroll actions
  addLoadedRange: (start: string, end: string, calendars: string[]) => void;
  isDateRangeLoaded: (start: Date, end: Date, calendars: string[]) => boolean;
  setLoadingPast: (loading: boolean) => void;
  setLoadingFuture: (loading: boolean) => void;
  clearLoadedRanges: () => void;
}

type CalendarStore = CalendarState & CalendarActions;

const initialState: CalendarState = {
  calendars: [],
  selectedCalendars: [],
  events: [],
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
  selectedDate: new Date(),
  currentWeek: new Date(),
  daysToShow: 7,
  visibleMonth: new Date().toLocaleDateString("en-US", { month: "long" }),
  visibleYear: new Date().getFullYear().toString(),
  loadedDateRanges: [],
  isLoadingPast: false,
  isLoadingFuture: false,
};

export const useCalendarStore = create<CalendarStore>()(
  devtools(
    persist(
      (set, get) => ({
        ...initialState,

        setCalendars: (calendars) =>
          set(
            (state) => {
              // If no calendars are selected (initial load or new connection),
              // select all available calendars by default
              if (
                state.selectedCalendars.length === 0 &&
                calendars.length > 0
              ) {
                return {
                  calendars,
                  selectedCalendars: calendars.map((c) => c.id),
                };
              }
              return { calendars };
            },
            false,
            "setCalendars",
          ),

        setSelectedCalendars: (selectedCalendars) =>
          set(
            {
              selectedCalendars,
              // Clear loaded ranges when calendars are set
              loadedDateRanges: [],
              // Clear events when calendars are set
              events: [],
            },
            false,
            "setSelectedCalendars",
          ),

        toggleCalendarSelection: (calendarId) =>
          set(
            (state) => {
              const index = state.selectedCalendars.indexOf(calendarId);
              const newSelection =
                index === -1
                  ? [...state.selectedCalendars, calendarId]
                  : state.selectedCalendars.filter((id) => id !== calendarId);

              return {
                selectedCalendars: newSelection,
                // Clear loaded ranges when calendar selection changes
                loadedDateRanges: [],
                // Clear events when calendar selection changes
                events: [],
              };
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

              // Optimized deduplication using Set for O(1) lookup
              const existingEventIds = new Set(
                state.events.map((e) => e.id).filter(Boolean),
              );
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

        addEvent: (event) =>
          set(
            (state) => {
              // Optimized: Check if event already exists using Set for O(1) lookup
              if (!event.id) {
                return { events: [...state.events, event] };
              }

              const eventIds = new Set(state.events.map((e) => e.id));
              if (eventIds.has(event.id)) {
                return state;
              }

              return {
                events: [...state.events, event],
              };
            },
            false,
            "addEvent",
          ),

        updateEvent: (eventId, updatedEvent) =>
          set(
            (state) => ({
              events: state.events.map((event) =>
                event.id === eventId ? { ...event, ...updatedEvent } : event,
              ),
            }),
            false,
            "updateEvent",
          ),

        removeEvent: (eventId) =>
          set(
            (state) => ({
              events: state.events.filter((event) => event.id !== eventId),
            }),
            false,
            "removeEvent",
          ),

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

        setSelectedDate: (selectedDate) =>
          set({ selectedDate }, false, "setSelectedDate"),

        setCurrentWeek: (currentWeek) =>
          set({ currentWeek }, false, "setCurrentWeek"),

        goToPreviousDay: () =>
          set(
            (state) => {
              const newDate = new Date(state.selectedDate);
              newDate.setDate(newDate.getDate() - 1);
              return {
                selectedDate: newDate,
                currentWeek: newDate,
              };
            },
            false,
            "goToPreviousDay",
          ),

        goToNextDay: () =>
          set(
            (state) => {
              const newDate = new Date(state.selectedDate);
              newDate.setDate(newDate.getDate() + 1);
              return {
                selectedDate: newDate,
                currentWeek: newDate,
              };
            },
            false,
            "goToNextDay",
          ),

        goToToday: () => {
          const today = new Date();
          set(
            {
              selectedDate: today,
              currentWeek: today,
            },
            false,
            "goToToday",
          );
        },

        handleDateChange: (date) =>
          set(
            {
              selectedDate: date,
              currentWeek: date,
            },
            false,
            "handleDateChange",
          ),

        setDaysToShow: (daysToShow) =>
          set({ daysToShow }, false, "setDaysToShow"),

        // Infinite scroll actions
        addLoadedRange: (startDate, endDate, calendars) =>
          set(
            (state) => ({
              loadedDateRanges: [
                ...state.loadedDateRanges,
                { startDate, endDate, calendars },
              ],
            }),
            false,
            "addLoadedRange",
          ),

        isDateRangeLoaded: (start, end, calendars) => {
          const state = get();
          const startStr = start.toISOString().split("T")[0];
          const endStr = end.toISOString().split("T")[0];

          return state.loadedDateRanges.some((range) => {
            const rangeStart = new Date(range.startDate);
            const rangeEnd = new Date(range.endDate);
            const requestStart = new Date(startStr);
            const requestEnd = new Date(endStr);

            // Check if the requested range is covered by this loaded range
            const isCovered =
              rangeStart <= requestStart && rangeEnd >= requestEnd;

            // Check if calendars match
            const calendarsMatch =
              calendars.length === range.calendars.length &&
              calendars.every((cal) => range.calendars.includes(cal));

            return isCovered && calendarsMatch;
          });
        },

        setLoadingPast: (isLoadingPast) =>
          set({ isLoadingPast }, false, "setLoadingPast"),

        setLoadingFuture: (isLoadingFuture) =>
          set({ isLoadingFuture }, false, "setLoadingFuture"),

        clearLoadedRanges: () =>
          set({ loadedDateRanges: [] }, false, "clearLoadedRanges"),

        setVisibleMonthYear: (visibleMonth, visibleYear) =>
          set({ visibleMonth, visibleYear }, false, "setVisibleMonthYear"),
      }),
      {
        name: "calendar-storage",
        partialize: (state) => ({
          selectedCalendars: state.selectedCalendars,
          daysToShow: state.daysToShow,
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
export const useCalendarInitialized = () =>
  useCalendarStore((state) => state.isInitialized);
export const useSetCreateEventAction = () =>
  useCalendarStore((state) => state.setCreateEventAction);
export const useCreateEventAction = () =>
  useCalendarStore((state) => state.createEventAction);
export const useCalendarSelectedDate = () =>
  useCalendarStore((state) => state.selectedDate);
export const useCalendarCurrentWeek = () =>
  useCalendarStore((state) => state.currentWeek);
export const useDaysToShow = () =>
  useCalendarStore((state) => state.daysToShow);

// Individual action selectors for stable references
export const useSetSelectedDate = () =>
  useCalendarStore((state) => state.setSelectedDate);
export const useSetCurrentWeek = () =>
  useCalendarStore((state) => state.setCurrentWeek);
export const useGoToPreviousDay = () =>
  useCalendarStore((state) => state.goToPreviousDay);
export const useGoToNextDay = () =>
  useCalendarStore((state) => state.goToNextDay);
export const useGoToToday = () => useCalendarStore((state) => state.goToToday);
export const useHandleDateChange = () =>
  useCalendarStore((state) => state.handleDateChange);
export const useAddEvent = () => useCalendarStore((state) => state.addEvent);
export const useUpdateEvent = () =>
  useCalendarStore((state) => state.updateEvent);
export const useRemoveEvent = () =>
  useCalendarStore((state) => state.removeEvent);
export const useSetDaysToShow = () =>
  useCalendarStore((state) => state.setDaysToShow);
export const useVisibleMonth = () =>
  useCalendarStore((state) => state.visibleMonth);
export const useVisibleYear = () =>
  useCalendarStore((state) => state.visibleYear);
export const useSetVisibleMonthYear = () =>
  useCalendarStore((state) => state.setVisibleMonthYear);
