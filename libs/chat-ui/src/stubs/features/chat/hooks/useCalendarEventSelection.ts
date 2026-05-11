/**
 * Stub for chat-ui — real impl in apps/web. Replace at integration time.
 */
import type {
  CalendarEventSelectionOptions,
  SelectedCalendarEventData,
} from "@/stores/calendarEventSelectionStore";

export type { CalendarEventSelectionOptions, SelectedCalendarEventData };

const noop = () => {};

export const useCalendarEventSelection = () => ({
  selectedCalendarEvent: null as SelectedCalendarEventData | null,
  selectCalendarEvent: noop as (
    event: SelectedCalendarEventData,
    options?: CalendarEventSelectionOptions,
  ) => void,
  clearSelectedCalendarEvent: noop as () => void,
  setSelectedCalendarEvent: noop as (
    event: SelectedCalendarEventData | null,
  ) => void,
});
