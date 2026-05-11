/**
 * Stub for chat-ui — real impl in apps/web. Replace at integration time.
 */
import type { GoogleCalendarEvent } from "@/types/features/calendarTypes";

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

export type CalendarEventSelectionOptions = {};

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

const noop = () => {};

const frozenState: CalendarEventSelectionStore = Object.freeze({
  selectedCalendarEvent: null,
  selectCalendarEvent: noop,
  clearSelectedCalendarEvent: noop,
  setSelectedCalendarEvent: noop,
});

type Selector<U> = (state: CalendarEventSelectionStore) => U;

interface UseStoreFn {
  <U>(selector: Selector<U>): U;
  (): CalendarEventSelectionStore;
  getState: () => CalendarEventSelectionStore;
  setState: (partial: Partial<CalendarEventSelectionStore>) => void;
  subscribe: (
    listener: (state: CalendarEventSelectionStore) => void,
  ) => () => void;
}

export const useCalendarEventSelectionStore: UseStoreFn = (<U,>(
  selector?: Selector<U>,
) => {
  if (selector) return selector(frozenState);
  return frozenState;
}) as UseStoreFn;
useCalendarEventSelectionStore.getState = () => frozenState;
useCalendarEventSelectionStore.setState = noop;
useCalendarEventSelectionStore.subscribe = () => noop;
