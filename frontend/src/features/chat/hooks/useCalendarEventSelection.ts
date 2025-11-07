import {
  CalendarEventSelectionOptions,
  SelectedCalendarEventData,
  useCalendarEventSelectionStore,
} from "@/stores/calendarEventSelectionStore";

export { type CalendarEventSelectionOptions, type SelectedCalendarEventData };

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
