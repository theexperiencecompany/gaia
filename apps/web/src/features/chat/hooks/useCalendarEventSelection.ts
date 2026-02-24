import {
  type SelectedCalendarEventData,
  useCalendarEventSelectionStore,
} from "@/stores/calendarEventSelectionStore";


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
