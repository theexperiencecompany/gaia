import { create } from "zustand";
import { devtools, persist } from "zustand/middleware";

/** The calendar page's view state; calendars, events and the selection are server truth in React Query. */
interface CalendarState {
  createEventAction: (() => void) | null;
  selectedDate: Date;
  daysToShow: number;
  visibleMonth: string;
  visibleYear: string;
}

interface CalendarActions {
  setCreateEventAction: (action: (() => void) | null) => void;
  goToPreviousDay: () => void;
  goToNextDay: () => void;
  goToToday: () => void;
  setDaysToShow: (days: number) => void;
  setVisibleMonthYear: (month: string, year: string) => void;
}

type CalendarStore = CalendarState & CalendarActions;

// Time-dependent defaults (today's date, current month/year) are computed inside this factory,
// not at module evaluation, so each store instance gets a fresh value instead of one frozen
// value reused across every SSR request.
const createInitialState = (): CalendarState => {
  const now = new Date();
  return {
    createEventAction: null,
    selectedDate: now,
    daysToShow: 7,
    visibleMonth: now.toLocaleDateString("en-US", { month: "long" }),
    visibleYear: now.getFullYear().toString(),
  };
};

export const useCalendarStore = create<CalendarStore>()(
  devtools(
    persist(
      (set) => ({
        ...createInitialState(),

        setCreateEventAction: (createEventAction) =>
          set({ createEventAction }, false, "setCreateEventAction"),

        goToPreviousDay: () =>
          set(
            (state) => {
              const newDate = new Date(state.selectedDate);
              newDate.setDate(newDate.getDate() - 1);
              return { selectedDate: newDate };
            },
            false,
            "goToPreviousDay",
          ),

        goToNextDay: () =>
          set(
            (state) => {
              const newDate = new Date(state.selectedDate);
              newDate.setDate(newDate.getDate() + 1);
              return { selectedDate: newDate };
            },
            false,
            "goToNextDay",
          ),

        goToToday: () => {
          const today = new Date();
          set({ selectedDate: today }, false, "goToToday");
        },

        setDaysToShow: (daysToShow) =>
          set({ daysToShow }, false, "setDaysToShow"),

        setVisibleMonthYear: (visibleMonth, visibleYear) =>
          set({ visibleMonth, visibleYear }, false, "setVisibleMonthYear"),
      }),
      {
        name: "calendar-storage",
        partialize: (state) => ({
          daysToShow: state.daysToShow,
        }),
      },
    ),
    { name: "calendar-store" },
  ),
);

// Selectors
export const useSetCreateEventAction = () =>
  useCalendarStore((state) => state.setCreateEventAction);
export const useCreateEventAction = () =>
  useCalendarStore((state) => state.createEventAction);
export const useCalendarSelectedDate = () =>
  useCalendarStore((state) => state.selectedDate);
export const useDaysToShow = () =>
  useCalendarStore((state) => state.daysToShow);

// Individual action selectors for stable references
export const useGoToPreviousDay = () =>
  useCalendarStore((state) => state.goToPreviousDay);
export const useGoToNextDay = () =>
  useCalendarStore((state) => state.goToNextDay);
export const useGoToToday = () => useCalendarStore((state) => state.goToToday);
export const useSetDaysToShow = () =>
  useCalendarStore((state) => state.setDaysToShow);
export const useVisibleMonth = () =>
  useCalendarStore((state) => state.visibleMonth);
export const useVisibleYear = () =>
  useCalendarStore((state) => state.visibleYear);
export const useSetVisibleMonthYear = () =>
  useCalendarStore((state) => state.setVisibleMonthYear);
