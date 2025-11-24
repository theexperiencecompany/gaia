import {
  type CalendarEventSelectionOptions,
  type SelectedCalendarEventData,
  useCalendarEventSelectionStore,
} from "@/stores/calendarEventSelectionStore";

export type { CalendarEventSelectionOptions, SelectedCalendarEventData };

export const useCalendarEventSelection = () => {
  const {
    selectedCalendarEvent,
    selectCalendarEvent,
    clearSelectedCalendarEvent,
    setSelectedCalendarEvent,
  } = useCalendarEventSelectionStore();

  return {
    selectedCalendarEvent,
    selectCalendarEvent,
    clearSelectedCalendarEvent,
    setSelectedCalendarEvent,
  };
};
