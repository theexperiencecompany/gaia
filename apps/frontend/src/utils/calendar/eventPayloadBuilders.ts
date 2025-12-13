import type {
  CalendarDeleteOptions,
  CalendarEditOptions,
  CalendarEvent,
} from "@/types/features/calendarTypes";

import { isTimedEvent } from "./eventTypeGuards";

export const buildAddEventPayload = (event: CalendarEvent) => {
  const userTimeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;

  if (isTimedEvent(event)) {
    return {
      ...event,
      timezone: userTimeZone,
      is_all_day: event.is_all_day || false,
    };
  }

  return {
    summary: event.summary,
    description: event.description,
    is_all_day: true,
    timezone: userTimeZone,
  };
};

export const buildEditEventPayload = (
  event: CalendarEditOptions,
): {
  event_id: string;
  calendar_id: string;
  summary?: string;
  description?: string;
  start?: string;
  end?: string;
  is_all_day?: boolean;
  timezone?: string;
  original_summary?: string;
} => {
  const payload: {
    event_id: string;
    calendar_id: string;
    summary?: string;
    description?: string;
    start?: string;
    end?: string;
    is_all_day?: boolean;
    timezone?: string;
    original_summary?: string;
  } = {
    event_id: event.event_id,
    calendar_id: event.calendar_id,
    original_summary: event.original_summary,
  };

  if (event.summary !== undefined) payload.summary = event.summary;
  if (event.description !== undefined) payload.description = event.description;
  if (event.start !== undefined) payload.start = event.start;
  if (event.end !== undefined) payload.end = event.end;
  if (event.is_all_day !== undefined) payload.is_all_day = event.is_all_day;
  if (event.timezone !== undefined) payload.timezone = event.timezone;

  return payload;
};

export const buildDeleteEventPayload = (event: CalendarDeleteOptions) => ({
  event_id: event.event_id,
  calendar_id: event.calendar_id,
  summary: event.summary,
});

export const buildBatchAddPayloads = (events: CalendarEvent[]) =>
  events.map(buildAddEventPayload);

export const buildBatchEditPayloads = (events: CalendarEditOptions[]) =>
  events.map(buildEditEventPayload);

export const buildBatchDeletePayloads = (events: CalendarDeleteOptions[]) =>
  events.map(buildDeleteEventPayload);
